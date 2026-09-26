"""SentinelService: the only entry point for UI and CLI (a FastAPI layer can wrap it 1:1).

evaluate(image_id)      POST /frames/{id}/evaluate
triage(zone, level)     GET  /triage
shift_summary()         GET  /summary
shift_handover()        GET  /handover
impact()                GET  /impact
get_track(id)           GET  /tracks/{id}
tracks_near(...)        GET  /tracks?near=…
find_reports(...)       GET  /reports
record_decision(...)    POST /frames/{id}/decisions
health()                GET  /health
map_context()           GET  /map
frame_tracks(id)        GET  /frames/{id}/tracks
chat(question, …)       POST /chat
"""

from __future__ import annotations

import logging
import os
import time
from functools import cached_property

from pydantic import BaseModel

from sentinel.agent.analyst import Analyst
from sentinel.agent.budget import BudgetGuard
from sentinel.agent.llm import LLMClient, LLMError, build_llm
from sentinel.config import PROJECT_ROOT, Settings, load_settings
from sentinel.data.repository import Repository
from sentinel.domain.models import (
    HEAVY_LABELS,
    EvaluationResult,
    EvidencePacket,
    Kinematics,
    OperatorDecision,
    ReportVerification,
    RiskLevel,
    Track,
    TrackSnapshot,
    TriageRow,
    Verdict,
    to_min,
)
from sentinel.observability.decisions import DecisionLog, ViewLog, decision_seconds, median_or_none
from sentinel.observability.trace import TraceListener, Tracer, new_run_id
from sentinel.perception.factory import build_detector
from sentinel.pipeline import Pipeline
from sentinel.tracking.kinematics import compute_kinematics

log = logging.getLogger(__name__)


class TrackView(BaseModel):
    track: Track
    kinematics: Kinematics


class ShiftSummary(BaseModel):
    frames: int
    reports: int
    by_level: dict[str, int]
    most_urgent: TriageRow | None
    contradicted_reports: int
    decided: int = 0
    awaiting_high: int = 0  # YÜKSEK/KRİTİK frames without an operator decision yet
    # Measured, not assumed: frame opened → operator decision (median over decided frames with a logged opening)
    decision_median_s: float | None = None
    decision_timed: int = 0
    # False-alarm signal (§1.6): YÜKSEK/KRİTİK frames the operator lowered, out of those decided
    high_decided: int = 0
    high_downgraded: int = 0
    # Facility threat posture for the status bar: the highest level still waiting for a decision (informative
    # only; the system never changes its own behaviour or takes an action because of it).
    posture_level: RiskLevel | None = None
    posture_pending: int = 0


class HandoverReport(BaseModel):
    """An official report the evidence contradicts, with the frames in whose context it was checked."""

    report_id: str
    time: str
    text: str
    identity_claim: bool
    reason: str
    frames: list[str]


class ShiftHandover(BaseModel):
    """Shift handover for the duty officer: deterministic, no LLM (every item comes from the queue,
    the packets and the decision log)."""

    generated_at: str
    summary: ShiftSummary
    escalated: list[TriageRow]
    overridden: list[TriageRow]
    approved: list[TriageRow]
    awaiting: list[TriageRow]  # YÜKSEK/KRİTİK without a decision, risk order
    contradicted_official: list[HandoverReport]
    contradicted_third_party: int


class SentinelService:
    def __init__(self, settings: Settings | None = None, llm: LLMClient | None = None, use_llm: bool = True):
        _load_dotenv()
        self.s = settings or load_settings()
        self.repo = Repository(self.s.data_path, self.s.images_subdir)
        self.detector = build_detector(self.s, self.repo)
        self.pipeline = Pipeline(self.s, self.repo, self.detector)
        self.runs_dir = self.s.path(self.s.observability.runs_dir)
        self.budget = BudgetGuard(self.runs_dir / "budget.json", self.s.llm.budget_stop_usd)
        self.llm_error: str | None = None
        if llm is None and use_llm:
            try:
                llm = build_llm(self.s.llm, self.s.path(self.s.llm.cache_dir), self.budget)
            except LLMError as e:  # missing key → template briefs, product keeps working
                self.llm_error = str(e)
                log.warning("LLM devre dışı: %s", e)
        self.llm = llm
        self.analyst = Analyst(llm, self.s)
        from sentinel.agent.analyst import load_prompt
        from sentinel.agent.chat import PROMPT_FILE, ChatAgent
        from sentinel.agent.tools import ChatTools

        self.chat_agent = ChatAgent(llm, ChatTools(self), load_prompt(PROMPT_FILE))
        self.decisions = DecisionLog(self.runs_dir)
        self.views = ViewLog(self.runs_dir)
        from sentinel.risk.calibration import LabelStore

        self.labels = LabelStore(self.s.path(self.s.observability.labels_dir))
        self._packets: dict[str, EvidencePacket] = {}
        self._results: dict[str, EvaluationResult] = {}

    # ================================================================ evaluate
    def evaluate(
        self,
        image_id: str,
        live: bool = False,
        use_llm: bool = True,
        llm_cache_only: bool = False,
        on_event: TraceListener | None = None,
    ) -> EvaluationResult:
        """Steps 1–5 deterministic, then one analyst call. `live` re-runs detection bypassing its cache;
        `llm_cache_only` never calls the LLM (uses its cache or the template) for fast previews.
        `on_event(kind, payload)` receives step start/end and the packet as soon as steps 1–5 are done,
        so a UI can show progress and the evidence before the brief."""
        run_id = new_run_id()
        tracer = Tracer(self.runs_dir, run_id, image_id, listener=on_event)
        t0 = time.perf_counter()
        packet = self.pipeline.evaluate(image_id, tracer, refresh_detections=live)
        if on_event:
            on_event("packet", {"run_id": run_id, "packet": packet})
        t1 = time.perf_counter()
        out = self.analyst.brief(packet, tracer, use_llm=use_llm, cache_only=llm_cache_only)
        t2 = time.perf_counter()
        res = EvaluationResult(
            run_id=run_id,
            packet=packet,
            brief=out.brief,
            brief_source=out.source,  # type: ignore[arg-type]
            grounding=out.grounding,
            llm_note=out.note,
            timings_ms={"core": round((t1 - t0) * 1000, 1), "brief": round((t2 - t1) * 1000, 1)},
        )
        self._packets[image_id] = packet
        self._results[image_id] = res
        return res

    def result(self, image_id: str) -> EvaluationResult:
        """Last evaluation of a frame. A preview that fell back to the template only because the LLM
        answer was not cached yet is upgraded with a real LLM call here."""
        from sentinel.agent.analyst import CACHE_MISS_NOTE

        res = self._results.get(image_id)
        if res is None or (res.llm_note == CACHE_MISS_NOTE and self.llm is not None):
            return self.evaluate(image_id)
        return res

    def preview(self, image_id: str) -> EvaluationResult:
        """Fast evaluation without network calls (triage warm-up)."""
        if image_id not in self._results:
            return self.evaluate(image_id, llm_cache_only=True)
        return self._results[image_id]

    def packet(self, image_id: str) -> EvidencePacket:
        if image_id not in self._packets:
            self._packets[image_id] = self.pipeline.evaluate(image_id)
        return self._packets[image_id]

    def trace(self, run_id: str) -> list[dict]:
        from sentinel.observability.trace import read_trace

        return read_trace(self.runs_dir, run_id)

    # ================================================================ triage
    def triage(self, zone: str | None = None, level: RiskLevel | None = None) -> list[TriageRow]:
        from sentinel.agent.template import template_brief

        decisions = self.decisions.current_all()
        rows = []
        for meta in self.repo.frames(zone):
            p = self.packet(meta.image_id)
            if level is not None and p.risk.level != level:
                continue
            res = self._results.get(meta.image_id)
            headline = res.brief.headline if res else template_brief(p).headline
            etas = [
                v.kinematics.eta_min
                for v in p.vehicles
                if v.kinematics and v.kinematics.approaching and v.kinematics.eta_min is not None
            ]
            rows.append(
                TriageRow(
                    image_id=p.image_id,
                    zone=p.frame.zone,
                    capture_time=p.frame.capture_time,
                    level=p.risk.level,
                    score=p.risk.score,
                    d_base_m=p.frame.d_base_m,
                    headline=headline,
                    n_vehicles=len(p.vehicles),
                    reports_contradicted=sum(r.verdict == Verdict.CELISIYOR for r in p.reports),
                    reports_confirmed=sum(r.verdict == Verdict.DOGRULANDI for r in p.reports),
                    min_eta_min=min(etas) if etas else None,
                    n_approaching=sum(bool(v.kinematics and v.kinematics.approaching) for v in p.vehicles),
                    n_heavy=sum(v.label in HEAVY_LABELS for v in p.vehicles),
                    decision=decisions.get(p.image_id),
                )
            )
        return sorted(rows, key=lambda r: (-r.level.rank, -r.score, r.d_base_m))

    def shift_summary(self) -> ShiftSummary:
        rows = self.triage()
        by = {lv.value: sum(r.level == lv for r in rows) for lv in reversed(list(RiskLevel))}
        secs = decision_seconds({r.image_id: r.decision for r in rows if r.decision}, self.views.all())
        high = [r for r in rows if r.decision and r.level in (RiskLevel.YUKSEK, RiskLevel.KRITIK)]
        open_rows = [r for r in rows if r.decision is None]
        posture = max((r.level for r in open_rows), key=lambda lv: lv.rank, default=None)
        return ShiftSummary(
            frames=len(rows),
            reports=len(self.repo.reports),
            by_level=by,
            most_urgent=rows[0] if rows else None,
            contradicted_reports=len({rid for r in rows for rid in self._contradicted_ids(r.image_id)}),
            decided=sum(r.decision is not None for r in rows),
            awaiting_high=sum(
                r.decision is None and r.level in (RiskLevel.YUKSEK, RiskLevel.KRITIK) for r in rows
            ),
            decision_median_s=median_or_none(secs),
            decision_timed=len(secs),
            high_decided=len(high),
            high_downgraded=sum(
                r.decision.action == "override"
                and r.decision.level is not None
                and r.decision.level.rank < r.level.rank
                for r in high
            ),
            posture_level=posture,
            posture_pending=sum(r.level == posture for r in open_rows) if posture else 0,
        )

    def shift_handover(self) -> ShiftHandover:
        from datetime import datetime

        rows = self.triage()

        def by_action(action: str) -> list[TriageRow]:
            return [r for r in rows if r.decision and r.decision.action == action]

        official: dict[str, HandoverReport] = {}
        third_party: set[str] = set()
        for r in rows:
            for rep in self.packet(r.image_id).reports:
                if rep.verdict != Verdict.CELISIYOR:
                    continue
                if rep.source != "official":
                    third_party.add(rep.report_id)
                    continue
                h = official.setdefault(
                    rep.report_id,
                    HandoverReport(
                        report_id=rep.report_id,
                        time=rep.time,
                        text=rep.text,
                        identity_claim=rep.identity_claim,
                        reason=rep.reason,
                        frames=[],
                    ),
                )
                h.frames.append(r.image_id)
        return ShiftHandover(
            generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            summary=self.shift_summary(),
            escalated=by_action("escalate"),
            overridden=by_action("override"),
            approved=by_action("approve"),
            awaiting=[
                r for r in rows if r.decision is None and r.level in (RiskLevel.YUKSEK, RiskLevel.KRITIK)
            ],
            contradicted_official=sorted(official.values(), key=lambda h: h.time),
            contradicted_third_party=len(third_party),
        )

    def impact(self):
        """Shift simulation: hand FIFO vs NÖBETÇİ risk order, decision time vs vehicles' projected arrival."""
        from sentinel.impact import build_report, pick_handling_time, stopwatch_minutes

        cfg = self.s.impact
        rows = self.triage()
        sw = self.s.path(cfg.stopwatch_file)
        measured = decision_seconds({r.image_id: r.decision for r in rows if r.decision}, self.views.all())
        manual = pick_handling_time(
            [], stopwatch_minutes(sw, "manual"), cfg.manual_min_assumed, cfg.min_measurements
        )
        system = pick_handling_time(
            [s / 60 for s in measured],
            stopwatch_minutes(sw, "system"),
            cfg.system_min_assumed,
            cfg.min_measurements,
        )
        return build_report(rows, manual, system)

    def _contradicted_ids(self, image_id: str) -> list[str]:
        return [r.report_id for r in self.packet(image_id).reports if r.verdict == Verdict.CELISIYOR]

    # ================================================================ lookups (chat tools, map)
    def get_track(self, track_id: str, t_now: str | None = None) -> TrackView:
        tr = self.repo.track(track_id)
        t = to_min(t_now) if t_now else tr.t_end
        k = compute_kinematics(tr, t, self.repo.geo, self.repo.zone_index, self.s.tracking)
        return TrackView(track=tr, kinematics=k)

    def tracks_near(
        self, lat: float, lon: float, time_hhmm: str, radius_m: float = 200.0
    ) -> list[TrackSnapshot]:
        return self.repo.tracks_near(lat, lon, to_min(time_hhmm), radius_m)

    def find_reports(
        self,
        zone: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: float | None = None,
        t_from: str = "00:00",
        t_to: str = "23:59",
    ) -> list[ReportVerification]:
        """Reports verified without frame context (time-aware)."""
        out = []
        radius = radius_m or self.s.reports.radius_m
        for rep in self.repo.reports_between(to_min(t_from), to_min(t_to)):
            claim = self.pipeline.claims[rep.report_id]
            in_zone = (
                zone is None
                or claim.zone == zone
                or (claim.has_point and self.repo.zone_index.zone_of(claim.lat, claim.lon) == zone)
            )
            near = (
                lat is None
                or lon is None
                or (
                    claim.has_point
                    and float(self.repo.geo.distance_m(lat, lon, claim.lat, claim.lon)) <= radius
                )
            )
            if in_zone and near:
                out.append(self.pipeline.verifier.verify(rep, claim))
        return out

    # ================================================================ map geometry (display only)
    def map_context(self) -> dict:
        """Base, zones, proximity rings and every frame's footprint with its current level."""
        import math

        geo, base, r = self.repo.geo, self.repo.base, self.s.risk

        def ring(radius_m: float, n: int = 96) -> list[list[float]]:
            pts = []
            for i in range(n + 1):
                a = 2 * math.pi * i / n
                lat, lon = geo.to_latlon(radius_m * math.sin(a), radius_m * math.cos(a))
                pts.append([float(lon), float(lat)])
            return pts

        frames = []
        for meta in self.repo.frames():
            p = self.packet(meta.image_id)
            c = meta.corner_coordinates
            frames.append(
                {
                    "image_id": meta.image_id,
                    "capture_time": meta.capture_time,
                    "zone": p.frame.zone,
                    "level": p.risk.level.value,
                    "score": p.risk.score,
                    "d_base_m": p.frame.d_base_m,
                    "center": [p.frame.center_lon, p.frame.center_lat],
                    "corners": [
                        [pt[1], pt[0]] for pt in (c.top_left, c.top_right, c.bottom_right, c.bottom_left)
                    ],
                }
            )
        from sentinel.geo.zones import zone_display

        # Build true-scale road corridors connecting base through the frame centers
        roads_by_zone: dict[str, list[dict]] = {}
        for f in frames:
            roads_by_zone.setdefault(f["zone"], []).append(f)

        zones_out = []
        for z in self.repo.zones:
            zone_frames = sorted(
                roads_by_zone.get(z.name, []),
                key=lambda item: item.get("d_base_m", 0),
            )
            road_path = [[base.lon, base.lat]] + [f["center"] for f in zone_frames]
            real_center = zone_frames[2]["center"] if len(zone_frames) >= 3 else [z.center[1], z.center[0]]
            zones_out.append(
                {
                    "name": z.name,
                    "label": zone_display(z.name),
                    "center": real_center,
                    "theoretical_center": [z.center[1], z.center[0]],
                    "path": road_path,
                }
            )

        return {
            "base": {"name": base.name, "center": [base.lon, base.lat]},
            "zones": zones_out,
            "rings": [
                {"km": r.near_km, "ring": ring(r.near_km * 1000)},
                {"km": r.mid_km, "ring": ring(r.mid_km * 1000)},
            ],
            "frames": frames,
        }

    def frame_tracks(self, image_id: str, max_report_tracks: int = 8) -> dict:
        """2-hour paths for the frame's vehicles, undetected tracks and the tracks reports point at,
        plus report pins. Raw points only: the UI interpolates positions for the time slider.
        Vehicle levels use config thresholds (risk.levels), so map/box colours follow calibration."""
        from sentinel.risk.scoring import level_for

        p = self.packet(image_id)
        vehicle_levels = {v.ref: level_for(v.score, self.s.risk).value for v in p.vehicles}
        t1 = self.repo.meta[image_id].capture_min
        t0 = t1 - self.s.tracking.window_min
        roles: dict[str, dict] = {}
        for v in p.vehicles:
            if v.track_id:
                roles[v.track_id] = {
                    "role": "vehicle",
                    "vehicle_ref": v.ref,
                    "label": v.label,
                    "score": v.score,
                    "level": vehicle_levels[v.ref],
                }
        for tid in p.undetected_tracks:
            roles.setdefault(tid, {"role": "undetected"})
        extra = [tid for r in p.reports for tid in r.related_tracks if tid not in roles]
        for tid in list(dict.fromkeys(extra))[:max_report_tracks]:
            roles[tid] = {"role": "report"}
        tracks = []
        for tid, meta in roles.items():
            pts = [[pt.t_min, pt.lat, pt.lon] for pt in self.repo.track(tid).points if t0 <= pt.t_min <= t1]
            if pts:
                tracks.append({"track_id": tid, **meta, "points": pts})
        pins = [
            {
                "report_id": r.report_id,
                "t_min": to_min(r.time),
                "time": r.time,
                "lat": r.claim.lat,
                "lon": r.claim.lon,
                "verdict": r.verdict.value,
                "related_tracks": r.related_tracks,
            }
            for r in p.reports
            if r.claim.has_point
        ]
        return {
            "window": {"start": t0, "end": t1},
            "radius_m": self.s.reports.radius_m,
            "tracks": tracks,
            "report_pins": pins,
            "vehicle_levels": vehicle_levels,
            # Projection (Endsley level 3): approaching vehicles at capture time and their ETA to the base,
            # straight from the packet, soonest first; the map draws a vector from each vehicle to the base.
            "projections": sorted(
                [
                    {
                        "vehicle_ref": v.ref,
                        "track_id": v.track_id,
                        "lat": v.lat,
                        "lon": v.lon,
                        "eta_min": v.kinematics.eta_min,
                        "level": vehicle_levels[v.ref],
                    }
                    for v in p.vehicles
                    if v.kinematics and v.kinematics.approaching and v.kinematics.eta_min is not None
                ],
                key=lambda pr: pr["eta_min"],
            ),
        }

    # ================================================================ chat
    def chat(self, question: str, history: list | None = None, image_id: str | None = None):
        """One chat turn (tool-calling loop). history: [{role, content}] of the visible conversation."""
        from sentinel.agent.chat import ChatMessage

        run_id = new_run_id()
        msgs = [m if isinstance(m, ChatMessage) else ChatMessage.model_validate(m) for m in history or []]
        if image_id is not None and image_id not in self.repo.meta:
            image_id = None
        turn = self.chat_agent.ask(question, msgs, image_id, Tracer(self.runs_dir, run_id, image_id))
        return turn, run_id

    # ================================================================ blind gold-set labelling
    def record_gold(self, image_id: str, labeler: str, level: RiskLevel, note: str = "") -> dict:
        if image_id not in self.repo.meta:
            raise KeyError(image_id)
        lab = self.labels.add(image_id, labeler, level, note)
        return {"image_id": lab.image_id, "labeler": lab.labeler, "level": lab.level.value, "at": lab.at}

    def gold_progress(self, labeler: str) -> dict:
        done = self.labels.progress(labeler)
        order = [
            m.image_id for m in self.repo.frames()
        ]  # capture-time order: no hint of the system's ranking
        return {"labeler": labeler, "done": done, "order": order, "total": len(order)}

    # ================================================================ decisions / health
    def record_view(self, image_id: str) -> str:
        """The operator opened a frame (start of the handling-time measurement)."""
        if image_id not in self.repo.meta:
            raise KeyError(image_id)
        return self.views.record(image_id)

    def record_decision(
        self, run_id: str, image_id: str, action: str, level: RiskLevel | None = None, reason: str = ""
    ) -> OperatorDecision:
        return self.decisions.record(run_id, image_id, action, level, reason)

    @cached_property
    def _llm_name(self) -> str:
        return getattr(self.llm, "model", "yok") if self.llm else "yok"

    def health(self) -> dict:
        return {
            "detector": self.detector.name,
            "detector_fallback": getattr(self.detector, "load_error", None),
            "llm": {"provider": self.s.llm.provider, "model": self._llm_name, "error": self.llm_error},
            "budget": self.budget.status(),
            "data": {
                "frames": len(self.repo.meta),
                "tracks": len(self.repo.tracks),
                "reports": len(self.repo.reports),
            },
            "demo_mode": os.environ.get("SENTINEL_DEMO") == "1",
        }


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # optional
        return
    load_dotenv(PROJECT_ROOT / ".env")
