"""Deterministic core: evaluate_image(image_id) -> EvidencePacket (steps 1–5, no LLM).

Every number the brief may mention is produced here.
"""

from __future__ import annotations

import numpy as np

from sentinel.config import Settings
from sentinel.data.repository import Repository
from sentinel.domain.models import (
    Detection,
    EvidencePacket,
    FrameInfo,
    GeoDetection,
    ReportVerification,
    VehicleEvidence,
    Verdict,
)
from sentinel.geo.georef import GeoReferencer
from sentinel.observability.trace import Tracer
from sentinel.perception.base import Detector
from sentinel.perception.cache import CachedDetector
from sentinel.reports.parser import ReportParser
from sentinel.reports.relevance import FrameContext, select_relevant
from sentinel.reports.verifier import ReportVerifier
from sentinel.risk.scoring import assess
from sentinel.tracking.kinematics import compute_kinematics
from sentinel.tracking.matcher import TrackMatcher


class Pipeline:
    def __init__(self, settings: Settings, repo: Repository, detector: Detector):
        self.s = settings
        self.repo = repo
        self.detector = detector
        self.matcher = TrackMatcher(settings.tracking.gate_m)
        self.parser = ReportParser(repo.zone_index.names())
        self.claims = self.parser.parse_all(repo.reports)
        self.verifier = ReportVerifier(repo, settings.reports, settings.tracking)
        self._frame_labels_memo: dict[str, dict[str, tuple[str, float]]] = {}

    # ================================================================ entry point
    def evaluate(
        self, image_id: str, tracer: Tracer | None = None, refresh_detections: bool = False
    ) -> EvidencePacket:
        tracer = tracer or Tracer(None, "adhoc", image_id)
        if image_id not in self.repo.meta:
            raise KeyError(f"Bilinmeyen kare: {image_id}")
        meta = self.repo.meta[image_id]
        georef = GeoReferencer(meta)

        # [1] Perception
        with tracer.step("1_tespit", {"image": image_id, "detector": self.detector.name}) as st:
            dets, scale = self._detect(image_id, refresh_detections)
            st["cache_hit"] = getattr(self.detector, "last_hit", None)
            if scale:
                st["ölçek"] = scale
            tau = self.s.detector.tau_op
            strong = [d for d in dets if d.conf >= tau]
            weak = [d for d in dets if d.conf < tau]
            st["output_summary"] = {
                "n": len(dets),
                f"conf>={tau}": len(strong),
                "düşük_güven": len(weak),
                "sınıflar": _count_labels(strong),
            }

        # [2] Geo
        with tracer.step("2_koordinat", {"n": len(dets), "georef": "bilineer (4 köşe)"}) as st:
            implausible = [d for d in strong + weak if not self._plausible(d, georef)]
            geo_strong = [self._georef(d, georef) for d in strong if d not in implausible]
            geo_weak = [self._georef(d, georef) for d in weak if d not in implausible]
            c_lat, c_lon = georef.center()
            rel = self.repo.zone_index.relation(c_lat, c_lon)
            zone = self.repo.zone_index.zone_of(c_lat, c_lon)
            w_m, h_m = georef.size_m()
            frame = FrameInfo(
                image_id=image_id,
                capture_time=meta.capture_time,
                zone=zone,
                center_lat=c_lat,
                center_lon=c_lon,
                d_base_m=rel.d_m,
                direction=rel.direction,
                width_m=w_m,
                height_m=h_m,
                width_px=meta.width_px,
                height_px=meta.height_px,
                corners=meta.corner_coordinates,
            )
            st["output_summary"] = {
                "kare_merkezi": [round(c_lat, 5), round(c_lon, 5)],
                "üsse_m": round(rel.d_m),
                "yön": rel.direction,
                "bölge": zone,
                "tespitler": [
                    {
                        "id": g.detection.det_id,
                        "lat": round(g.lat, 5),
                        "lon": round(g.lon, 5),
                        "üsse_m": round(g.d_base_m),
                    }
                    for g in geo_strong
                ],
            }

        # [3] Tracking + kinematics
        with tracer.step(
            "3_eşleme_kinematik", {"t": meta.capture_time, "kapı_m": self.s.tracking.gate_m}
        ) as st:
            vehicles, undetected, low_conf, match_notes = self._match(
                meta.capture_min, geo_strong, geo_weak, georef
            )
            known = self._known_classes(image_id, vehicles)
            for v in vehicles:
                v.class_label = self._class_of(v, known)  # type: ignore[assignment]
            st["output_summary"] = {
                "eşleşen": {
                    v.ref: {"track": v.track_id, "m": _r(v.match_m, 2), "marj_m": _r(v.margin_m, 1)}
                    for v in vehicles
                    if v.track_id
                },
                "track'siz_tespit": [v.ref for v in vehicles if not v.track_id],
                "tespitsiz_track": undetected,
                "terfi": [v.ref for v in vehicles if v.promoted],
                "kinematik": {
                    v.ref: {
                        "üsse_m": round(v.kinematics.d_now_m),
                        "yaklaşma_mps": round(v.kinematics.closing_mps, 2),
                        "eta_dk": _r(v.kinematics.eta_min, 1),
                        "yol_m": round(v.kinematics.path_m),
                        "duraklama": len(v.kinematics.stops),
                    }
                    for v in vehicles
                    if v.kinematics
                },
            }

        # [4] Reports
        with tracer.step(
            "4_raporlar", {"pencere_dk": self.s.reports.window_min, "yarıçap_m": self.s.reports.radius_m}
        ) as st:
            ctx = FrameContext(
                image_id=image_id,
                capture_min=meta.capture_min,
                zone=zone,
                center=(c_lat, c_lon),
                half_diag_m=georef.half_diagonal_m(),
                matched_tracks=[v.track_id for v in vehicles if v.track_id],
                labels_by_track={tid: lab for tid, (lab, _c) in known.items()},
                approaching_tracks={
                    v.track_id for v in vehicles if v.track_id and v.kinematics and v.kinematics.approaching
                },
                leaving_tracks={
                    v.track_id for v in vehicles if v.track_id and v.kinematics and v.kinematics.leaving
                },
            )
            reports = self._reports(ctx)
            st["output_summary"] = {
                "ilgili": len(reports),
                "kararlar": {vd.value: sum(r.verdict == vd for r in reports) for vd in Verdict},
                "çelişen": [r.report_id for r in reports if r.verdict == Verdict.CELISIYOR],
            }

        # [5] Risk
        with tracer.step("5_risk", {"araç": len(vehicles), "rapor": len(reports)}) as st:
            risk = assess(vehicles, reports, self.s.risk)
            st["output_summary"] = {
                "skor": risk.score,
                "skor_seviyesi": risk.score_level.value,
                "taban": risk.floor_level.value if risk.floor_level else None,
                "seviye": risk.level.value,
                "taban_gerekçe": risk.floor_reasons,
            }

        if implausible:
            match_notes.append(f"{len(implausible)} kutu araç boyutunda değil, elendi")
        return EvidencePacket(
            image_id=image_id,
            frame=frame,
            detector=self.detector.name,
            vehicles=vehicles,
            untracked=[v.ref for v in vehicles if not v.track_id],
            undetected_tracks=undetected,
            low_conf=low_conf + implausible,
            reports=reports,
            risk=risk,
            uncertainties=self._uncertainties(vehicles, undetected, reports, match_notes),
        )

    # ================================================================ steps
    def _detect(self, image_id: str, refresh: bool = False):
        """Detections in image_meta pixel space (+ the rescale note, if any)."""
        meta = self.repo.meta[image_id]
        path = self.repo.image_path(image_id)
        if isinstance(self.detector, CachedDetector):
            dets = self.detector.detect(path, refresh=refresh)
        else:
            dets = self.detector.detect(path)
        if self.detector.name == "oracle":
            return dets, None
        return _to_meta_space(dets, path, meta.width_px, meta.height_px)

    def _confident_classes(self, vehicles: list[VehicleEvidence]) -> dict[str, tuple[str, float]]:
        """{track: (label, conf)} from matched detections whose class can be trusted (conf ≥ τ_op)."""
        tau = self.s.detector.tau_op
        out: dict[str, tuple[str, float]] = {}
        for v in vehicles:
            confident = v.track_id and v.label != "unknown" and v.conf >= tau
            if confident and (v.track_id not in out or v.conf > out[v.track_id][1]):
                out[v.track_id] = (v.label, v.conf)
        return out

    def _frame_classes(self, image_id: str) -> dict[str, tuple[str, float]]:
        """Confident classes of another frame's matched vehicles (steps 1–3 only, memoised)."""
        if image_id not in self._frame_labels_memo:
            meta = self.repo.meta[image_id]
            georef = GeoReferencer(meta)
            dets, _ = self._detect(image_id)
            tau = self.s.detector.tau_op
            geo_s = [self._georef(d, georef) for d in dets if d.conf >= tau]
            geo_w = [self._georef(d, georef) for d in dets if d.conf < tau]
            vehicles = self._match(meta.capture_min, geo_s, geo_w, georef)[0]
            self._frame_labels_memo[image_id] = self._confident_classes(vehicles)
        return self._frame_labels_memo[image_id]

    def _known_classes(self, image_id: str, vehicles: list[VehicleEvidence]) -> dict[str, tuple[str, float]]:
        """Track classes known at this frame's capture time: this frame and every frame captured before it
        (never a later one: an operator at 13:00 cannot know the 15:00 frame). Highest confidence wins."""
        t = self.repo.meta[image_id].capture_min
        self._frame_labels_memo[image_id] = own = self._confident_classes(vehicles)  # fresh after a live run
        known: dict[str, tuple[str, float]] = {}
        sources = [
            self._frame_classes(m.image_id)
            for m in self.repo.frames()
            if m.image_id != image_id and m.capture_min <= t
        ]
        for src in [*sources, own]:
            for tid, (lab, conf) in src.items():
                if tid not in known or conf > known[tid][1]:
                    known[tid] = (lab, conf)
        return known

    def _class_of(self, v: VehicleEvidence, known: dict[str, tuple[str, float]]) -> str:
        if v.track_id and v.track_id in known:
            return known[v.track_id][0]
        return v.label if v.conf >= self.s.detector.tau_op else "unknown"

    def _georef(self, d: Detection, georef: GeoReferencer) -> GeoDetection:
        lat, lon = georef.pixel_to_latlon(d.cx, d.cy)
        rel = self.repo.zone_index.relation(lat, lon)
        return GeoDetection(
            detection=d,
            lat=lat,
            lon=lon,
            d_base_m=rel.d_m,
            bearing_deg=rel.bearing_deg,
            direction=rel.direction,
            zone=self.repo.zone_index.zone_of(lat, lon),
        )

    def _plausible(self, d: Detection, georef: GeoReferencer) -> bool:
        if self.s.detector.plausible_size_m is None:
            return True
        lo, hi = self.s.detector.plausible_size_m
        side = max(d.w, d.h) * georef.m_per_px()
        return lo <= side <= hi

    def _match(self, t: int, strong: list[GeoDetection], weak: list[GeoDetection], georef: GeoReferencer):
        geo = self.repo.geo
        tids, tpos = self.repo.tracks_at(t)
        # a vehicle can only be seen if its position is inside the frame; this rules out the trap tracks
        margin_px = self.s.tracking.frame_margin_m / georef.m_per_px()
        keep = [
            j for j in range(len(tids)) if georef.contains(float(tpos[j, 0]), float(tpos[j, 1]), margin_px)
        ]
        tids, tpos = [tids[j] for j in keep], tpos[keep]
        if tids:
            tx, ty = geo.to_local(tpos[:, 0], tpos[:, 1])
            txy = np.column_stack([tx, ty])
        else:
            txy = np.zeros((0, 2))

        def xy(gs: list[GeoDetection]) -> np.ndarray:
            if not gs:
                return np.zeros((0, 2))
            x, y = geo.to_local([g.lat for g in gs], [g.lon for g in gs])
            return np.column_stack([x, y])

        mpp = georef.m_per_px()
        k, cap = self.s.tracking.box_gate_factor, self.s.tracking.gate_max_m

        def gates(gs: list[GeoDetection]) -> np.ndarray:
            return np.array([min(cap, k * np.hypot(g.detection.w, g.detection.h) / 2 * mpp) for g in gs])

        res = self.matcher.match(xy(strong), txy, gates(strong))
        notes: list[str] = []
        vehicles: list[VehicleEvidence] = []
        by_det = {p.det_idx: p for p in res.pairs}
        for i, g in enumerate(strong):
            p = by_det.get(i)
            vehicles.append(self._vehicle(len(vehicles) + 1, g, t, tids, p, promoted=False))
            if p and p.margin_m is not None and p.margin_m < self.s.tracking.gate_m:
                notes.append(
                    f"V{len(vehicles)} eşlemesi belirsiz: 2. aday yalnızca {p.margin_m:.0f} m farkla"
                )

        # low-confidence boxes: promoted only if a remaining track confirms them
        low_conf: list[Detection] = []
        remaining = res.unmatched_tracks
        if weak and remaining:
            res_w = self.matcher.match(xy(weak), txy[remaining], gates(weak))
            by_w = {p.det_idx: p for p in res_w.pairs}
            used = set()
            for i, g in enumerate(weak):
                p = by_w.get(i)
                if p is None:
                    low_conf.append(g.detection)
                    continue
                p.track_idx = remaining[p.track_idx]
                p.second_idx = None
                used.add(p.track_idx)
                vehicles.append(self._vehicle(len(vehicles) + 1, g, t, tids, p, promoted=True))
            remaining = [j for j in remaining if j not in used]
        else:
            low_conf = [g.detection for g in weak]

        undetected = sorted(
            tids[j] for j in remaining if georef.contains(float(tpos[j, 0]), float(tpos[j, 1]))
        )
        return vehicles, undetected, low_conf, notes

    def _vehicle(
        self, n: int, g: GeoDetection, t: int, tids: list[str], p, promoted: bool
    ) -> VehicleEvidence:
        d = g.detection
        v = VehicleEvidence(
            ref=f"V{n}",
            det_id=d.det_id,
            label=d.label,
            conf=d.conf,
            bbox=(d.x, d.y, d.w, d.h),
            lat=g.lat,
            lon=g.lon,
            d_base_m=g.d_base_m,
            direction=g.direction,
            promoted=promoted,
        )
        if p is not None:
            tid = tids[p.track_idx]
            v.track_id = tid
            v.match_m = p.dist_m
            v.margin_m = p.margin_m
            v.second_track_id = tids[p.second_idx] if p.second_idx is not None else None
            v.kinematics = compute_kinematics(
                self.repo.track(tid), t, self.repo.geo, self.repo.zone_index, self.s.tracking
            )
        return v

    def _reports(self, ctx: FrameContext) -> list[ReportVerification]:
        rel = select_relevant(self.repo, self.claims, ctx, self.s.reports, self.s.tracking.window_min)
        out = [
            self.verifier.verify(
                r.report, r.claim, ctx, relevance=r.relevance, dist_to_frame_m=r.dist_to_frame_m
            )
            for r in rel
        ]
        order = {Verdict.CELISIYOR: 0, Verdict.DOGRULANDI: 1, Verdict.DOGRULANAMAZ: 2, Verdict.ILGISIZ: 3}
        return sorted(out, key=lambda r: (order[r.verdict], r.time))

    def _uncertainties(self, vehicles, undetected, reports, notes) -> list[str]:
        out: list[str] = []
        name = self.detector.name
        if name == "oracle":
            out.append("Test detektörü (oracle): araç sınıfı bilinmiyor, ağır araç faktörü hesaplanamadı")
        elif getattr(getattr(self.detector, "inner", self.detector), "has_van", True) is False:
            out.append("Geçici modelde 'van' sınıfı yok")
        if getattr(self.detector, "cache_only", False):
            out.append("Tespit modeli yüklenemedi; önceden hesaplanmış (önbellek) tespitler kullanıldı")
        if undetected:
            out.append(
                f"{len(undetected)} track karede olduğu hâlde tespit edilemedi ({', '.join(undetected)})"
            )
        unsure = [v.ref for v in vehicles if v.class_label == "unknown" and v.label != "unknown"]
        if unsure:
            out.append(
                f"{', '.join(unsure)} sınıfı teyit edilemedi (düşük güvenli tespit); yetenek 'bilinmiyor' sayıldı"
            )
        untracked = [v.ref for v in vehicles if not v.track_id]
        if untracked:
            out.append(
                f"{len(untracked)} tespit hareket kaydıyla eşleşmedi: {', '.join(untracked)} (kayıtsız araç)"
            )
        if vehicles and not any(v.track_id for v in vehicles):
            out.append("Bu karede kayıtlı hareket verisi yok; risk yalnızca konum ve tespite dayanıyor")
        if not vehicles:
            out.append("Karede araç tespit edilmedi")
        out.extend(notes)
        if not [r for r in reports if r.verdict != Verdict.ILGISIZ]:
            out.append("Son 2 saatte bu kare için doğrulanabilir rapor yok (risk düşürücü sayılmadı)")
        return out


def _to_meta_space(dets: list[Detection], path, width_px: int, height_px: int):
    """Detectors return boxes in the image file's pixel space; georef uses image_meta's width/height.
    If they differ (e.g. official 960×540 metadata vs a resized file), rescale the boxes."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
    except (OSError, ImportError):
        return dets, None
    if (w, h) == (width_px, height_px):
        return dets, None
    sx, sy = width_px / w, height_px / h
    scaled = [d.model_copy(update={"x": d.x * sx, "y": d.y * sy, "w": d.w * sx, "h": d.h * sy}) for d in dets]
    return scaled, f"{w}x{h} → {width_px}x{height_px}"


def _count_labels(dets: list[Detection]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in dets:
        out[d.label] = out.get(d.label, 0) + 1
    return out


def _r(x: float | None, nd: int) -> float | None:
    return None if x is None else round(x, nd)
