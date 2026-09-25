"""Deterministic field-report parser: free text → structured Claim.

Regex first; an LLM batch pass can fill in reports that end up UNKNOWN (cached, one-shot).
"""

from __future__ import annotations

import re

from sentinel.domain.models import Claim as ClaimModel
from sentinel.domain.models import ClaimType, FieldReport

_TR_MAP = str.maketrans("çğıöşüâîûÇĞİIÖŞÜ", "cgiosuaiucgiiosu")


def normalize(text: str) -> str:
    return text.translate(_TR_MAP).lower()


COORD_RE = re.compile(r"(\d{1,2}\.\d+)\s*N\s+(\d{1,3}\.\d+)\s*E", re.IGNORECASE)

# (normalized word pattern, labels); order matters: longest / most specific first
VEHICLE_VOCAB: list[tuple[str, list[str], str]] = [
    (r"kamyon\s*/\s*otobus", ["truck", "bus"], "ağır araç"),
    (r"agir\s+(?:bir\s+)?arac", ["truck", "bus"], "ağır araç"),
    (r"kamyon", ["truck"], "kamyon"),
    (r"otobus", ["bus"], "otobüs"),
    (r"panelvan|minibus|van\b", ["van"], "panelvan"),
    (r"otomobil|binek", ["car"], "otomobil"),
    (r"arac", [], "araç"),
]
COLORS = ("mavi", "kirmizi", "sari", "beyaz", "siyah", "gri", "yesil")
NUM_WORDS = {"bir": 1, "iki": 2, "uc": 3, "dort": 4, "bes": 5, "alti": 6, "yedi": 7, "sekiz": 8}

NOISE_PATTERNS = [
    r"telsiz baglantisi",
    r"hava acik|gorus mesafesi",
    r"ihbar incelendi, dogrulanamadi",
    r"dogrulanmamis bir ihbar",
    r"olagandisi bir durum bildirmedi",
    r"lojistik konvoyu",
    r"planli tatbikat",
]
TYPE_PATTERNS: list[tuple[ClaimType, str]] = [
    (ClaimType.FRIENDLY_ID, r"dost devriye|bize bagli|planli ikmal|kimlik teyidi|teyitlidir"),
    (ClaimType.MOVING_TO_BASE, r"usse dogru ilerleyen|usse gelen|usse yaklas"),
    (ClaimType.LEAVING, r"uzaklasiyor|bolgeden ayriliyor"),
    (ClaimType.TRANSIT, r"transit|konvoyu ilerliyor"),
    (ClaimType.STATIONARY, r"hareketsiz|yerinden ayrilmadi|park halinde|beklemede|bekliyor|durdugu"),
    (ClaimType.ZONE_NO_HEAVY, r"agir arac hareketi yok"),
    (ClaimType.ZONE_NORMAL, r"trafik akisi normal|kayda deger bir hareketlilik bulunmuyor"),
    (ClaimType.DENSITY, r"yogun"),
    (ClaimType.NORMAL_BEHAVIOR, r"hareketleri olagan"),
]
COUNT_RE = re.compile(
    r"\b(\d+|"
    + "|".join(NUM_WORDS)
    + r")\s+(?:araclik\s+bir\s+)?(kamyon|otomobil|panelvan|otobus|agir arac|arac)"
)
USUAL_RE = re.compile(r"(\d+)\s+arac\s+civari")


class ReportParser:
    def __init__(self, zone_names: list[str]):
        self._zones = [(normalize(z), z) for z in zone_names]

    def parse(self, report: FieldReport) -> ClaimModel:
        raw = report.text
        text = normalize(raw)
        claim = ClaimModel(report_id=report.report_id, types=[])

        if m := COORD_RE.search(raw):
            claim.lat, claim.lon = float(m.group(1)), float(m.group(2))
        for zn, z in self._zones:
            if zn in text:
                claim.zone = z
                break

        if any(re.search(p, text) for p in NOISE_PATTERNS):
            claim.types = [ClaimType.NOISE]
            return claim

        for ctype, pat in TYPE_PATTERNS:
            if re.search(pat, text):
                claim.types.append(ctype)

        for pat, labels, word in VEHICLE_VOCAB:
            if re.search(pat, text):
                claim.vehicle_labels, claim.vehicle_word = labels, word
                break
        claim.color = next((c for c in COLORS if re.search(rf"\b{c}\b", text)), None)

        if m := USUAL_RE.search(text):
            claim.usual_count = int(m.group(1))  # "olağan trafik 4 araç civarı" is a baseline, not a count
        elif m := COUNT_RE.search(text):
            n = m.group(1)
            claim.count = int(n) if n.isdigit() else NUM_WORDS[n]
            if claim.count > 1 or re.search(r"konvoy|bulundugu|goruldu", text):
                claim.types.append(ClaimType.COUNT)

        if ClaimType.STATIONARY in claim.types:
            long_wait = re.search(r"uzun suredir|bir saatten uzun|saatlerdir", text)
            claim.stationary_min = 60 if long_wait else 10

        if not claim.types and claim.has_point and claim.vehicle_word:
            claim.types.append(ClaimType.PRESENCE)
        if not claim.types:
            claim.types.append(ClaimType.UNKNOWN)
        return claim

    def parse_all(self, reports: list[FieldReport]) -> dict[str, ClaimModel]:
        return {r.report_id: self.parse(r) for r in reports}
