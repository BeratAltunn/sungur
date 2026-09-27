"""Chat tools: read-only queries over SentinelService, returned as compact Turkish JSON.

Same data-minimisation rule as the analyst: no absolute coordinates leave this module. Positions are
given relative to the base (distance, compass direction, zone) and report coordinates are masked.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sentinel.agent.masking import class_name, mask_packet
from sentinel.domain.models import LABEL_TR, RiskLevel, Verdict, hhmm, to_min
from sentinel.geo.geodesy import compass8
from sentinel.geo.zones import zone_display
from sentinel.reports.parser import COORD_RE, normalize

if TYPE_CHECKING:
    from sentinel.service import SentinelService


class ToolError(ValueError):
    pass


def _r(x: float | None, nd: int = 1) -> float | None:
    return None if x is None else round(float(x), nd)


def _fn(name: str, description: str, props: dict[str, Any], required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": props, "required": required or []},
        },
    }


_ZONE = {"type": "string", "description": "Bölge adı, örn. 'Doğu Yolu'"}
_TIME = {"type": "string", "description": "Saat, 'HH:MM'"}

TOOL_SPECS: list[dict] = [
    _fn(
        "list_frames",
        "Drone karelerini risk sırasıyla listeler (kare kimliği, bölge, saat, seviye, üsse mesafe, manşet).",
        {"zone": _ZONE, "level": {"type": "string", "enum": [lv.value for lv in RiskLevel]}},
    ),
    _fn(
        "analyze_image",
        "Bir karenin kanıt paketi: araçlar ve kinematikleri, risk faktörleri, taban kuralları, rapor kararları.",
        {"image_id": {"type": "string", "description": "örn. img_000860"}},
        ["image_id"],
    ),
    _fn(
        "get_track",
        "Bir aracın (track) 2 saatlik zaman çizelgesi: her 5 dakikada üsse mesafe, yön ve bölge; "
        "hız, yaklaşma, duraklamalar, ETA ve göründüğü kare.",
        {"track_id": {"type": "string", "description": "örn. T0122"}, "time": _TIME},
        ["track_id"],
    ),
    _fn(
        "find_reports",
        "Saha raporlarını zaman-duyarlı doğrulama kararlarıyla getirir. Bölge, saat aralığı, karar ya da kare ile süzülebilir.",
        {
            "zone": _ZONE,
            "t_from": _TIME,
            "t_to": _TIME,
            "verdict": {"type": "string", "enum": [v.value for v in Verdict]},
            "source": {
                "type": "string",
                "enum": ["official", "third_party"],
                "description": "resmî / 3. taraf",
            },
            "image_id": {"type": "string", "description": "Verilirse o kareyle ilgili raporlar"},
        },
    ),
    _fn(
        "zone_summary",
        "Bir bölgenin gün özeti: kareler ve seviyeleri, sınıflara göre araç sayıları, ağır araçlar, rapor kararları.",
        {"zone": _ZONE},
        ["zone"],
    ),
]


class ChatTools:
    def __init__(self, svc: SentinelService):
        self.svc = svc
        self.repo = svc.repo
        self._handlers: dict[str, Callable[..., Any]] = {
            "list_frames": self.list_frames,
            "analyze_image": self.analyze_image,
            "get_track": self.get_track,
            "find_reports": self.find_reports,
            "zone_summary": self.zone_summary,
        }

    def call(self, name: str, arguments: str | dict) -> Any:
        if name not in self._handlers:
            raise ToolError(f"bilinmeyen araç: {name}")
        args = json.loads(arguments or "{}") if isinstance(arguments, str) else dict(arguments)
        args = {k: v for k, v in args.items() if v not in (None, "")}
        return self._handlers[name](**args)

    # ------------------------------------------------------------------ helpers
    def _zone(self, name: str | None) -> str | None:
        if not name:
            return None
        n = normalize(name).replace(" bolgesi", "").strip()
        for z in self.repo.zone_index.names():
            if normalize(z) == n or normalize(z).startswith(n):
                return z
        raise ToolError(
            f"bilinmeyen bölge: {name} (geçerli: {', '.join(zone_display(z) for z in self.repo.zone_index.names())})"
        )

    def _where(self, lat: float, lon: float) -> dict:
        rel = self.repo.zone_index.relation(lat, lon)
        return {
            "uste_km": _r(rel.d_m / 1000),
            "yon": rel.direction,
            "bolge": zone_display(self.repo.zone_index.zone_of(lat, lon)),
        }

    def _mask_text(self, text: str) -> str:
        def repl(m: re.Match) -> str:
            w = self._where(float(m.group(1)), float(m.group(2)))
            return f"[konum: üsten {w['uste_km']} km {w['yon']}, {w['bolge']}]"

        return COORD_RE.sub(repl, text)

    def _check_frame(self, image_id: str) -> None:
        if image_id not in self.repo.meta:
            raise ToolError(f"bilinmeyen kare: {image_id}")

    # ------------------------------------------------------------------ tools
    def list_frames(self, zone: str | None = None, level: str | None = None) -> list[dict]:
        rows = self.svc.triage(self._zone(zone), RiskLevel(level) if level else None)
        return [
            {
                "kare": r.image_id,
                "bolge": zone_display(r.zone),
                "saat": r.capture_time,
                "seviye": r.level.value,
                "skor": r.score,
                "uste_km": _r(r.d_base_m / 1000),
                "arac": r.n_vehicles,
                "celisen_rapor": r.reports_contradicted,
                "manset": r.headline,
            }
            for r in rows
        ]

    def analyze_image(self, image_id: str) -> dict:
        self._check_frame(image_id)
        m = mask_packet(self.svc.packet(image_id))
        for v in m["araclar"]:  # keep the tool answer small
            for k in (
                "pencere_basi_uste_km",
                "hiza_cos",
                "hiz_maks_mps",
                "gecilen_bolgeler",
                "eslesme_marji_m",
            ):
                v.pop(k, None)
        m.pop("sabitler", None)
        return m

    def get_track(self, track_id: str, time: str | None = None) -> dict:
        if track_id not in self.repo.tracks:
            raise ToolError(f"bilinmeyen track: {track_id}")
        view = self.svc.get_track(track_id, time)
        tr, k = view.track, view.kinematics
        frames = [
            m.image_id
            for m in self.repo.meta.values()
            if m.capture_min == tr.t_end
            and any(v.track_id == track_id for v in self.svc.packet(m.image_id).vehicles)
        ]
        return {
            "track": track_id,
            "kapsam": f"{hhmm(tr.t_start)}–{hhmm(tr.t_end)}",
            "goruldugu_kare": frames[0] if frames else None,
            "sinif": next(
                (
                    class_name(v)
                    for f in frames
                    for v in self.svc.packet(f).vehicles
                    if v.track_id == track_id
                ),
                "bilinmiyor",
            ),
            "zaman_cizelgesi": [{"saat": hhmm(p.t_min), **self._where(p.lat, p.lon)} for p in tr.points],
            "ozet_saat": k.t_now,
            "uste_km": _r(k.d_now_m / 1000),
            "yaklasma_mps": _r(k.closing_mps),
            "yaklasiyor": k.approaching,
            "uzaklasiyor": k.leaving,
            "eta_dk": _r(k.eta_min),
            "hiz_simdi_mps": _r(k.speed_now_mps),
            "yol_2s_km": _r(k.path_m / 1000),
            "rota_yonu": compass8(k.heading_deg) if k.heading_deg is not None else None,
            "duraklamalar": [{"bas": s.start, "bit": s.end, "dk": s.minutes} for s in k.stops],
        }

    def find_reports(
        self,
        zone: str | None = None,
        t_from: str | None = None,
        t_to: str | None = None,
        verdict: str | None = None,
        source: str | None = None,
        image_id: str | None = None,
        limit: int = 25,
    ) -> dict:
        if image_id:
            self._check_frame(image_id)
            reps = self.svc.packet(image_id).reports
            lo, hi = to_min(t_from or "00:00"), to_min(t_to or "23:59")
            reps = [r for r in reps if lo <= to_min(r.time) <= hi]
        else:
            reps = self.svc.find_reports(
                zone=self._zone(zone), t_from=t_from or "00:00", t_to=t_to or "23:59"
            )
        if verdict:
            reps = [r for r in reps if r.verdict.value == verdict]
        if source:
            reps = [r for r in reps if r.source == source]
        # counts are given so the LLM never has to count
        return {
            "toplam": len(reps),
            "kararlar": dict(Counter(r.verdict.value for r in reps)),
            "kaynaklara_gore": dict(Counter(r.source for r in reps)),
            "gosterilen": min(len(reps), limit),
            "raporlar": [
                {
                    "id": r.report_id,
                    "saat": r.time,
                    "kaynak": r.source,
                    "metin": self._mask_text(r.text),
                    "karar": r.verdict.value,
                    "gerekce": r.reason,
                    "kimlik_iddiasi": r.identity_claim,
                }
                for r in reps[:limit]
            ],
        }

    def zone_summary(self, zone: str) -> dict:
        z = self._zone(zone)
        frames, classes, heavy = [], Counter(), []
        for meta in self.repo.frames(z):
            p = self.svc.packet(meta.image_id)
            frames.append(
                {
                    "kare": p.image_id,
                    "saat": p.frame.capture_time,
                    "seviye": p.risk.level.value,
                    "arac": len(p.vehicles),
                }
            )
            for v in p.vehicles:  # confirmed classes only (conf ≥ τ_op); the rest counted as "araç"
                classes[LABEL_TR[v.class_label]] += 1
                if v.class_label in ("truck", "bus"):
                    heavy.append(
                        {
                            "kare": p.image_id,
                            "arac": v.ref,
                            "track": v.track_id,
                            "sinif": LABEL_TR[v.class_label],
                        }
                    )
        reps = self.svc.find_reports(zone=z)
        return {
            "bolge": zone_display(z),
            "kareler": frames,
            "toplam_tespit": sum(classes.values()),
            "siniflara_gore": dict(classes),
            "agir_arac_sayisi": len(heavy),
            "agir_araclar": heavy,
            "rapor_sayisi": len(reps),
            "rapor_kararlari": dict(Counter(r.verdict.value for r in reps)),
            "not": "Sayımlar karelerdeki tespitlerdir; aynı araç birden çok karede görünebilir.",
        }
