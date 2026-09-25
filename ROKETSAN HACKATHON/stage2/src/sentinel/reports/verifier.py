"""Time-aware report verification.

A claim is compared with the track state *at the report's own time*, not at capture time.
Principle: absence of evidence is not contradiction. ÇELİŞİYOR needs positive counter-evidence,
e.g. the track that passes this point was provably elsewhere at report time, a class mismatch,
or a behaviour mismatch. Source trust (official > third_party) is only a prior; evidence wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sentinel.config import ReportsCfg, TrackingCfg
from sentinel.data.repository import Repository
from sentinel.domain.models import (
    LABEL_TR,
    Claim,
    ClaimType,
    FieldReport,
    ReportVerification,
    TrackSnapshot,
    Verdict,
    hhmm,
)
from sentinel.fmt import dec, km
from sentinel.geo.zones import zone_display
from sentinel.reports.relevance import FrameContext
from sentinel.tracking.kinematics import closing_at, is_stationary

_POINT_TYPES = {
    ClaimType.COUNT,
    ClaimType.PRESENCE,
    ClaimType.STATIONARY,
    ClaimType.MOVING_TO_BASE,
    ClaimType.LEAVING,
    ClaimType.TRANSIT,
    ClaimType.NORMAL_BEHAVIOR,
    ClaimType.FRIENDLY_ID,
    ClaimType.DENSITY,
}


@dataclass
class _Check:
    verdict: Verdict
    reason: str
    refs: list[str] = field(default_factory=list)  # counter-evidence that is not the claim's subject


class ReportVerifier:
    def __init__(self, repo: Repository, cfg: ReportsCfg, tcfg: TrackingCfg):
        self.repo = repo
        self.cfg = cfg
        self.tcfg = tcfg

    # ================================================================ public
    def verify(
        self,
        report: FieldReport,
        claim: Claim,
        ctx: FrameContext | None = None,
        relevance: str = "",
        dist_to_frame_m: float | None = None,
        time_aware: bool | None = None,
    ) -> ReportVerification:
        time_aware = self.cfg.time_aware if time_aware is None else time_aware
        refs: list[str] = [f"{report.report_id}@{report.time}"]
        related: list[str] = []

        if claim.is_noise:
            check = _Check(Verdict.ILGISIZ, "Bağlam bilgisi; araç/konum hakkında doğrulanabilir iddia yok")
        elif claim.has_point:
            if time_aware:
                check, related = self._verify_point(report, claim, ctx)
            else:
                check, related = self._verify_location_only(claim)
        elif claim.zone is not None:
            check, related = self._verify_zone(report, claim, ctx)
        else:
            check = _Check(Verdict.DOGRULANAMAZ, "Konum veya bölge belirtilmemiş")

        refs += [r for r in related + check.refs if r not in refs]
        return ReportVerification(
            report_id=report.report_id,
            time=report.time,
            source=report.source,
            text=report.text,
            claim=claim,
            verdict=check.verdict,
            reason=check.reason,
            relevance=relevance,
            evidence_refs=refs,
            related_tracks=related,
            identity_claim=ClaimType.FRIENDLY_ID in claim.types,
            dist_to_frame_m=dist_to_frame_m,
        )

    # ================================================================ point claims
    def _verify_point(self, report: FieldReport, claim: Claim, ctx: FrameContext | None):
        t = report.t_min
        R = self.cfg.radius_m
        present = self.repo.tracks_near(claim.lat, claim.lon, t, R)
        if not present:
            return self._absent(claim, t, ctx)

        related = [s.track_id for s in present]
        checks: list[_Check] = []
        type_check = self._type_check(claim, present, ctx)
        if type_check:
            checks.append(type_check)
        for ctype in claim.types:
            if ctype not in _POINT_TYPES:
                continue
            if ctype == ClaimType.FRIENDLY_ID and type_check and type_check.verdict == Verdict.DOGRULANDI:
                checks.append(_Check(Verdict.DOGRULANDI, "kimlik iddiası tip, konum ve zamanla tutarlı"))
                continue
            fn = getattr(self, f"_chk_{ctype.value.lower()}", None)
            if fn is not None:
                checks.append(fn(claim, present, t))
        return _combine(checks, present, t, R), related

    def _absent(self, claim: Claim, t: int, ctx: FrameContext | None):
        """Nobody registered at the point at report time. Contradiction only if a track that does pass
        this point was covered at t and provably elsewhere."""
        R = self.cfg.radius_m
        passes = self.repo.passes_near(claim.lat, claim.lon, R)
        elsewhere: list[tuple[str, float, int]] = []
        arrivals: set[str] = set()  # reach the point *after* the report: the vehicle the report pre-announces
        for tid, times in passes.items():
            pos = self.repo.position(tid, t)
            if pos is None:
                continue
            d = float(self.repo.geo.distance_m(claim.lat, claim.lon, *pos))
            if d > R:
                t_pass = min(times, key=lambda tt: abs(tt - t))
                elsewhere.append((tid, d, t_pass))
                if any(tt > t for tt in times):
                    arrivals.add(tid)
        if not elsewhere:
            return (
                _Check(
                    Verdict.DOGRULANAMAZ,
                    f"{hhmm(t)}'te noktanın {R:.0f} m içinde kayıtlı araç yok ve buradan geçen hiçbir "
                    "track o saati kapsamıyor (karşı-kanıt yok)",
                ),
                [],
            )
        head = f"{hhmm(t)}'te noktanın {R:.0f} m içinde kayıtlı araç yok"
        in_frame = [e for e in elsewhere if ctx and e[0] in ctx.matched_tracks]
        if in_frame:
            # the frame's own vehicles: type-compatible ones first, then the nearest
            labels = ctx.labels_by_track
            in_frame.sort(key=lambda e: (labels.get(e[0]) not in claim.vehicle_labels, e[1]))
            shown = ", ".join(f"{tid} {km(d)}" for tid, d, _ in in_frame[:3])
            more = f" +{len(in_frame) - 3} araç" if len(in_frame) > 3 else ""
            reason = f"{head}; bu karedeki araçlar o saatte uzaktaydı ({shown}{more})"
            ordered = [e[0] for e in in_frame] + [e[0] for e in elsewhere if e not in in_frame]
            related = [tid for tid in ordered if tid in arrivals]
            return _Check(Verdict.CELISIYOR, reason, [x for x in ordered if x not in related]), related
        elsewhere.sort(key=lambda e: abs(e[2] - t))
        tid, d, t_pass = elsewhere[0]
        when = (
            f"bu noktaya {hhmm(t_pass)}'te geliyor"
            if t_pass > t
            else f"bu noktadan {hhmm(t_pass)}'te geçmişti"
        )
        extra = f" (+{len(elsewhere) - 1} track daha)" if len(elsewhere) > 1 else ""
        related = [e[0] for e in elsewhere if e[0] in arrivals]
        others = [e[0] for e in elsewhere if e[0] not in arrivals]
        return _Check(
            Verdict.CELISIYOR, f"{head}; {tid} o saatte {km(d)} uzakta, {when}{extra}", others
        ), related

    def _type_check(
        self, claim: Claim, present: list[TrackSnapshot], ctx: FrameContext | None
    ) -> _Check | None:
        if not claim.vehicle_labels or ctx is None:
            return None
        known = {
            s.track_id: ctx.labels_by_track[s.track_id] for s in present if s.track_id in ctx.labels_by_track
        }
        if not known:
            return None
        if any(lab in claim.vehicle_labels for lab in known.values()):
            return _Check(Verdict.DOGRULANDI, "araç tipi tespitle uyumlu")
        tid, lab = next(iter(known.items()))
        return _Check(
            Verdict.CELISIYOR,
            f"rapor '{claim.vehicle_word}' diyor, {tid} bizim tespitimizde {LABEL_TR.get(lab, lab)}",
        )

    # --- per-type checks (present is non-empty) -------------------------------------------
    def _chk_count(self, claim: Claim, present: list[TrackSnapshot], t: int) -> _Check:
        k, n = len(present), claim.count or 1
        if k >= n:
            return _Check(Verdict.DOGRULANDI, f"{hhmm(t)}'te noktada {k} kayıtlı araç (iddia {n})")
        return _Check(Verdict.DOGRULANAMAZ, f"kısmi: iddia {n} araç, {hhmm(t)}'te kayıtlı {k}")

    def _chk_presence(self, claim: Claim, present: list[TrackSnapshot], t: int) -> _Check:
        return _Check(Verdict.DOGRULANDI, f"{hhmm(t)}'te noktada kayıtlı araç var ({present[0].track_id})")

    def _chk_density(self, claim: Claim, present: list[TrackSnapshot], t: int) -> _Check:
        k, usual = len(present), claim.usual_count
        if usual is not None and k > usual:
            return _Check(Verdict.DOGRULANDI, f"{hhmm(t)}'te {k} kayıtlı araç, olağan {usual}")
        return _Check(Verdict.DOGRULANAMAZ, f"{hhmm(t)}'te {k} kayıtlı araç; yoğunluk iddiası için yetersiz")

    def _chk_stationary(self, claim: Claim, present: list[TrackSnapshot], t: int) -> _Check:
        need = claim.stationary_min or self.cfg.stationary_default_min
        min_cov = min(need, self.cfg.stationary_min_coverage_min)
        moving: list[tuple[str, float, float]] = []
        for s in present:
            ok, disp, cov = is_stationary(
                self.repo.track(s.track_id), t - need, t, self.repo.geo, self.cfg.stationary_max_disp_m
            )
            if cov < min_cov:
                continue
            if ok:
                return _Check(
                    Verdict.DOGRULANDI,
                    f"{s.track_id} {hhmm(t - cov)}–{hhmm(t)} arasında hareketsiz (en fazla {disp:.0f} m yer değiştirme)",
                )
            moving.append((s.track_id, disp, cov))
        if moving:
            tid, disp, cov = moving[0]
            return _Check(
                Verdict.CELISIYOR,
                f"'hareketsiz' deniyor ama {tid} son {cov:.0f} dk'da {disp:.0f} m yer değiştirdi",
            )
        return _Check(Verdict.DOGRULANAMAZ, "hareketsizlik süresini kapsayan kayıt yok")

    def _motion(self, present: list[TrackSnapshot], t: int) -> list[tuple[str, float, float]]:
        out = []
        for s in present:
            m = closing_at(self.repo.track(s.track_id), t, self.repo.geo, self.tcfg.closing_window_min)
            if m is not None:
                out.append((s.track_id, *m))
        return out

    def _chk_moving_to_base(self, claim: Claim, present: list[TrackSnapshot], t: int) -> _Check:
        mot = self._motion(present, t)
        if not mot:
            return _Check(Verdict.DOGRULANAMAZ, "hareket yönünü gösterecek kayıt yok")
        for tid, closing, _speed in mot:
            if closing > 0.5:
                return _Check(
                    Verdict.DOGRULANDI, f"{tid} {hhmm(t)}'te üsse {dec(closing)} m/s ile yaklaşıyor"
                )
        tid, closing, speed = mot[0]
        if speed < self.tcfg.stop_speed_mps:
            return _Check(Verdict.CELISIYOR, f"'üsse ilerliyor' deniyor ama {tid} {hhmm(t)}'te duruyor")
        return _Check(
            Verdict.CELISIYOR,
            f"'üsse ilerliyor' deniyor ama {tid} üsten {dec(abs(closing))} m/s ile uzaklaşıyor",
        )

    def _chk_leaving(self, claim: Claim, present: list[TrackSnapshot], t: int) -> _Check:
        mot = self._motion(present, t)
        if not mot:
            return _Check(Verdict.DOGRULANAMAZ, "hareket yönünü gösterecek kayıt yok")
        for tid, closing, _ in mot:
            if closing < -0.5:
                return _Check(
                    Verdict.DOGRULANDI, f"{tid} {hhmm(t)}'te üsten {dec(abs(closing))} m/s ile uzaklaşıyor"
                )
        tid, closing, _ = mot[0]
        if closing > 0.5:
            return _Check(
                Verdict.CELISIYOR, f"'uzaklaşıyor' deniyor ama {tid} üsse {dec(closing)} m/s ile yaklaşıyor"
            )
        return _Check(Verdict.CELISIYOR, f"'uzaklaşıyor' deniyor ama {tid} {hhmm(t)}'te yerinde")

    def _chk_transit(self, claim: Claim, present: list[TrackSnapshot], t: int) -> _Check:
        mot = self._motion(present, t)
        if not mot:
            return _Check(Verdict.DOGRULANAMAZ, "hareketi gösterecek kayıt yok")
        tid, _, speed = max(mot, key=lambda m: m[2])
        if speed >= self.tcfg.moving_speed_mps:
            return _Check(Verdict.DOGRULANDI, f"{tid} {hhmm(t)}'te {dec(speed)} m/s ile hareket halinde")
        return _Check(Verdict.CELISIYOR, f"'transit geçiyor' deniyor ama {tid} {hhmm(t)}'te duruyor")

    def _chk_normal_behavior(self, claim: Claim, present: list[TrackSnapshot], t: int) -> _Check:
        for tid, closing, _ in self._motion(present, t):
            if closing > self.tcfg.approach_closing_mps:
                return _Check(
                    Verdict.CELISIYOR,
                    f"'hareketleri olağan' deniyor ama {tid} üsse {dec(closing)} m/s ile yaklaşıyor",
                )
        return _Check(Verdict.DOGRULANDI, f"{hhmm(t)}'te noktadaki araç(lar)da olağandışı hareket yok")

    def _chk_friendly_id(self, claim: Claim, present: list[TrackSnapshot], t: int) -> _Check:
        # Identity itself cannot be observed; without a class match we refuse to confirm (recall first).
        return _Check(Verdict.DOGRULANAMAZ, "konum ve zaman tutarlı; kimlik/tip tespitle teyit edilemedi")

    # ================================================================ location-only (regression)
    def _verify_location_only(self, claim: Claim):
        passes = self.repo.passes_near(claim.lat, claim.lon, self.cfg.radius_m)
        if passes:
            return _Check(Verdict.DOGRULANDI, "konum uyumlu (gün içinde bu noktadan araç geçti)"), sorted(
                passes
            )
        return _Check(Verdict.DOGRULANAMAZ, "bu noktadan geçen kayıtlı araç yok"), []

    # ================================================================ zone claims
    def _verify_zone(self, report: FieldReport, claim: Claim, ctx: FrameContext | None):
        t = report.t_min
        if ClaimType.ZONE_NO_HEAVY in claim.types:
            heavy = {
                tid: lab
                for tid, lab in (ctx.labels_by_track if ctx else {}).items()
                if lab in ("truck", "bus")
            }
            for tid, lab in heavy.items():
                pos = self.repo.position(tid, t)
                if pos and self.repo.zone_index.zone_of(*pos) == claim.zone:
                    return (
                        _Check(
                            Verdict.CELISIYOR,
                            f"'ağır araç yok' deniyor ama {tid} ({LABEL_TR[lab]}) {hhmm(t)}'te "
                            f"{zone_display(claim.zone)} bölgesinde",
                        ),
                        [tid],
                    )
            return _Check(
                Verdict.DOGRULANAMAZ, "bölge geneli iddia; bu karenin ağır araçlarıyla çelişki yok"
            ), []
        return _Check(Verdict.DOGRULANAMAZ, "bölge geneli, ölçülebilir olmayan ifade"), []


def _combine(checks: list[_Check], present: list[TrackSnapshot], t: int, R: float) -> _Check:
    if not checks:
        return _Check(
            Verdict.DOGRULANAMAZ, f"{hhmm(t)}'te noktada {len(present)} kayıtlı araç; iddia ölçülemiyor"
        )
    bad = [c for c in checks if c.verdict == Verdict.CELISIYOR]
    if bad:
        return _Check(Verdict.CELISIYOR, "; ".join(c.reason for c in bad))
    if all(c.verdict == Verdict.DOGRULANDI for c in checks):
        return _Check(Verdict.DOGRULANDI, "; ".join(c.reason for c in checks))
    return _Check(Verdict.DOGRULANAMAZ, "; ".join(c.reason for c in checks))
