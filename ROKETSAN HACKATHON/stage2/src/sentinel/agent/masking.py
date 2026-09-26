"""EvidencePacket → the only thing the LLM ever sees.

Data minimisation: no image, no raw report pool, no absolute coordinates (replaced with distance and
direction relative to the base). Counts are precomputed so the LLM never has to count.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sentinel.domain.models import LABEL_TR, EvidencePacket, VehicleEvidence, Verdict
from sentinel.geo.zones import zone_display
from sentinel.reports.parser import COORD_RE


def _r(x: float | None, nd: int = 1) -> float | None:
    return None if x is None else round(float(x), nd)


def first_arrival(p: EvidencePacket) -> VehicleEvidence | None:
    """The approaching vehicle with the shortest ETA: headlines lead with it (chosen in code, not by the LLM)."""
    etas = [
        v
        for v in p.vehicles
        if v.kinematics and v.kinematics.approaching and v.kinematics.eta_min is not None
    ]
    return min(etas, key=lambda v: v.kinematics.eta_min) if etas else None  # type: ignore[union-attr]


def mask_packet(p: EvidencePacket, constants: dict[str, Any] | None = None) -> dict[str, Any]:
    vehicles = []
    for v in p.vehicles:
        k = v.kinematics
        item: dict[str, Any] = {
            "ref": v.ref,
            "sinif": LABEL_TR.get(v.label, v.label),
            "guven": _r(v.conf, 2),
            "track": v.track_id,
            "uste_km": _r(v.d_base_m / 1000),
            "yon": v.direction,
            "skor": v.score,
        }
        if v.track_id:
            item["eslesme_m"] = _r(v.match_m)
            item["eslesme_marji_m"] = _r(v.margin_m, 0)
        if v.promoted:
            item["dusuk_guvenden_terfi"] = True
        if k:
            item.update(
                {
                    "yaklasma_mps": _r(k.closing_mps),
                    "hiza_cos": _r(k.align_cos, 2),
                    "yaklasiyor": k.approaching,
                    "uzaklasiyor": k.leaving,
                    "eta_dk": _r(k.eta_min),
                    "hiz_simdi_mps": _r(k.speed_now_mps),
                    "hiz_maks_mps": _r(k.speed_max_mps),
                    "yol_2s_km": _r(k.path_m / 1000),
                    "pencere_basi_uste_km": _r(k.d_start_m / 1000),
                    "mesafe_degisimi_km": _r(k.d_change_m / 1000),
                    "rota_yonu": k.heading_dir,
                    "duraklamalar": [{"bas": s.start, "bit": s.end, "dk": s.minutes} for s in k.stops],
                    "duraklama_toplam_dk": k.stop_total_min,
                    "dur_kalk": k.stop_and_go,
                    "gecilen_bolgeler": [zone_display(z) for z in k.zones_passed],
                }
            )
        item["faktorler"] = [{"etiket": f.label, "puan": f.points} for f in v.factors]
        vehicles.append(item)

    reports = [
        {
            "id": r.report_id,
            "saat": r.time,
            "kaynak": r.source,
            "karar": r.verdict.value,
            "gerekce": r.reason,
            "kimlik_iddiasi": r.identity_claim,
        }
        for r in p.reports
        if r.verdict != Verdict.ILGISIZ
    ]
    n_by = {vd: sum(r.verdict == vd for r in p.reports) for vd in Verdict}
    first = first_arrival(p)
    f = p.frame
    return {
        "kare": {
            "id": p.image_id,
            "saat": f.capture_time,
            "bolge": zone_display(f.zone),
            "uste_km": _r(f.d_base_m / 1000),
            "yon": f.direction,
            "genislik_m": _r(f.width_m, 0),
        },
        "detektor": p.detector,
        "sayimlar": {
            "arac": len(p.vehicles),
            "yaklasan_arac": sum(1 for v in p.vehicles if v.kinematics and v.kinematics.approaching),
            "trackli_arac": sum(1 for v in p.vehicles if v.track_id),
            "tracksiz_tespit": len(p.untracked),
            "tespitsiz_track": len(p.undetected_tracks),
            "celisen_rapor": n_by[Verdict.CELISIYOR],
            "dogrulanan_rapor": n_by[Verdict.DOGRULANDI],
            "dogrulanamayan_rapor": n_by[Verdict.DOGRULANAMAZ],
            "ilgisiz_rapor": n_by[Verdict.ILGISIZ],
        },
        "risk": {
            "skor": p.risk.score,
            "kural_seviyesi": p.risk.level.value,
            "skor_seviyesi": p.risk.score_level.value,
            "taban_seviyesi": p.risk.floor_level.value if p.risk.floor_level else None,
            "taban_gerekceleri": p.risk.floor_reasons,
            "kare_faktorleri": [{"etiket": x.label, "puan": x.points} for x in p.risk.factors],
            "en_riskli_arac": p.risk.top_vehicle,
            "en_kisa_eta": (
                {
                    "ref": first.ref,
                    "sinif": LABEL_TR.get(first.label, first.label),
                    "eta_dk": _r(first.kinematics.eta_min),
                }  # type: ignore[union-attr]
                if first
                else None
            ),
        },
        "araclar": vehicles,
        "raporlar": reports,
        "tespitsiz_trackler": p.undetected_tracks,
        "belirsizlikler": p.uncertainties,
        "sabitler": constants or {},
    }


def mask_report_text(text: str, dist_to_frame_m: float | None) -> str:
    repl = f"[konum: kareye {dist_to_frame_m:.0f} m]" if dist_to_frame_m is not None else "[konum]"
    return COORD_RE.sub(repl, text)


def render_user_message(p: EvidencePacket, masked: dict[str, Any]) -> str:
    """Evidence as JSON + raw report texts wrapped in <rapor> tags (data, never instructions)."""
    rep_lines = [
        f'<rapor id="{r.report_id}" saat="{r.time}" kaynak="{r.source}" karar="{r.verdict.value}">'
        f"{_escape(mask_report_text(r.text, r.dist_to_frame_m))}</rapor>"
        for r in p.reports
        if r.verdict != Verdict.ILGISIZ
    ]
    return (
        "<kanit_paketi>\n"
        + json.dumps(masked, ensure_ascii=False, indent=1)
        + "\n</kanit_paketi>\n\n<rapor_metinleri>\n"
        + ("\n".join(rep_lines) or "(ilgili rapor yok)")
        + "\n</rapor_metinleri>\n\nBu kare için RiskBrief JSON nesnesini üret."
    )


def _escape(s: str) -> str:
    return re.sub(r"</?\s*(rapor|kanit_paketi|rapor_metinleri)[^>]*>", "", s, flags=re.IGNORECASE)
