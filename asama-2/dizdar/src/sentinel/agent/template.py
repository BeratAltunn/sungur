"""Rule-based brief (graceful degradation): used when the LLM is off, fails, or fails grounding.

Every number is formatted straight from the EvidencePacket.
"""

from __future__ import annotations

from sentinel.agent.masking import class_name, first_arrival
from sentinel.domain.models import (
    EvidencePacket,
    KeyFinding,
    ReportAssessment,
    RiskBrief,
    RiskLevel,
    VehicleEvidence,
    Verdict,
)
from sentinel.fmt import dec, km
from sentinel.geo.zones import zone_display

ACTIONS = {
    RiskLevel.DUSUK: "Rutin: bölgenin bir sonraki turunda yeniden bakılsın.",
    RiskLevel.ORTA: "İzlemeye alınsın; bölgenin sonraki karesinde yeniden değerlendirilsin ve saha birimine teyit sorusu gönderilsin.",
    RiskLevel.YUKSEK: "Nöbetçi amirine bildirilsin; bölgeye drone veya devriye yönlendirilmesi önerilir.",
    RiskLevel.KRITIK: "Anında eskalasyon: nöbetçi amirine ETA ile bildirilsin, kapı kontrolü sıkılaştırılsın ve QRF hazırlansın.",
}


def _vehicle_line(v: VehicleEvidence) -> str:
    name = class_name(v)
    head = f"{v.ref} ({name}{', ' + v.track_id if v.track_id else ''})"
    k = v.kinematics
    if k is None:
        return f"{head}: hareket kaydı yok (kayıtsız araç), üsse {km(v.d_base_m)} {v.direction}."
    parts = [f"2 saatte {km(k.path_m)} yol aldı"]
    if k.approaching:
        stops = f"{len(k.stops)} duraklamadan sonra " if k.stops else ""
        parts.append(f"{stops}son 10 dk'da üsse {dec(k.closing_mps)} m/s ile yaklaşıyor")
        parts.append(
            f"üsse {km(k.d_now_m)}, ETA ~{dec(k.eta_min)} dk"
            if k.eta_min is not None
            else f"üsse {km(k.d_now_m)}"
        )
    elif k.leaving:
        parts.append(f"üsten {dec(abs(k.closing_mps))} m/s ile uzaklaşıyor, şu an {km(k.d_now_m)}")
    else:
        stop = f", {k.stop_total_min} dk duraklama" if k.stops else ""
        parts.append(f"üsse belirgin yaklaşma yok{stop}; üsse {km(k.d_now_m)}")
    return f"{head}: " + "; ".join(parts) + "."


_INTENT_WORDS = {
    "approaching": "üsse yaklaşıyor",
    "identity_contradicted": "kimlik iddiası kanıtla çelişiyor",
    "identity_contradicted_frame": "kare çevresinde çelişen kimlik iddiası",
    "untracked": "hareket kaydı yok",
    "leaving": "üsten uzaklaşıyor",
    "identity_confirmed": "dost kimliği kanıtla tutarlı",
}


def _threat_line(v: VehicleEvidence) -> str | None:
    """One sentence per vehicle: what it is, where it is, what it does (Capability–Opportunity–Intent)."""
    t = v.threat
    if t is None:
        return None
    codes = [f.code for f in v.factors]
    what = class_name(v) if class_name(v) != "araç" else "sınıf bilinmiyor"
    if "convoy" in codes:
        what += ", konvoy"
    does = ", ".join(w for c, w in _INTENT_WORDS.items() if c in codes) or "gösterge yok"
    return (
        f"{v.ref} tehdit profili: yetenek {t.capability.band.value} ({what}), "
        f"fırsat {t.opportunity.band.value} (üsse {km(v.d_base_m)}), "
        f"niyet göstergeleri {t.intent.band.value} ({does})."
    )


def template_brief(p: EvidencePacket) -> RiskBrief:
    level = p.risk.level
    zone = zone_display(p.frame.zone)
    appr = [v for v in p.vehicles if v.kinematics and v.kinematics.approaching]
    contradicted = [r for r in p.reports if r.verdict == Verdict.CELISIYOR]

    # headline: one fact, <= ~80 chars, same pattern as the LLM prompt (analyst_v4)
    first = first_arrival(p)
    if first:
        cls = class_name(first)
        eta = dec(first.kinematics.eta_min)  # type: ignore[union-attr]
        headline = (
            f"{zone} bölgesinde {cls} yaklaşıyor, ETA ~{eta} dk"
            if len(appr) == 1
            else f"{zone} bölgesinde {len(appr)} araç yaklaşıyor, ilk varış {cls} ~{eta} dk"
        )
    elif appr:
        headline = f"{zone} bölgesinde {len(appr)} araç üsse yaklaşıyor"
    elif p.vehicles:
        headline = f"{zone} bölgesinde {len(p.vehicles)} araç, üsse yaklaşan yok"
        if contradicted:
            headline += f", {len(contradicted)} rapor çelişiyor"
    else:
        headline = f"{zone} bölgesinde araç tespit edilmedi"

    # findings: riskiest vehicles first, then reports
    findings = [
        KeyFinding(
            vehicle_ref=v.ref, statement=_vehicle_line(v), evidence_refs=[x for x in (v.ref, v.track_id) if x]
        )
        for v in sorted(p.vehicles, key=lambda v: (-v.level.rank, -v.score))[:3]
    ]
    top = next((v for v in p.vehicles if v.ref == p.risk.top_vehicle), None)
    line = _threat_line(top) if top else None
    if line:
        findings.insert(0, KeyFinding(vehicle_ref=top.ref, statement=line, evidence_refs=[top.ref]))
    for r in contradicted[:3]:
        kind = "kimlik iddiası" if r.identity_claim else "raporu"
        findings.append(
            KeyFinding(
                statement=f"{r.time} {r.source} {kind} {r.report_id} ✗ ÇELİŞİYOR: {r.reason}.",
                evidence_refs=[r.report_id],
            )
        )

    unc = list(p.uncertainties)
    conf = "orta-yüksek"
    if p.detector == "oracle" or any("eşlemesi belirsiz" in u for u in unc):
        conf = "orta"
    if not any(v.track_id for v in p.vehicles):
        conf = "düşük"

    return RiskBrief(
        image_id=p.image_id,
        risk_level=level,
        risk_score=p.risk.score,
        headline=headline,
        key_findings=findings,
        report_assessment=[
            ReportAssessment(report_id=r.report_id, verdict=r.verdict, reason=r.reason)
            for r in p.reports
            if r.verdict != Verdict.ILGISIZ
        ],
        recommended_action=ACTIONS[level],
        confidence=conf,
        uncertainties=unc,
    )
