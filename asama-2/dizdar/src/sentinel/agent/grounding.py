"""Grounding check: every number, time and id in a brief must come from the evidence.

- numbers: matched against a bank built from the masked packet (values + numbers inside its strings),
  with tolerance and unit variants (m↔km, m/s→km/h);
- times (HH:MM) and ids (V1, T0122, R069, img_…) must exist in the packet;
- report verdicts are deterministic: the brief may not change them;
- level: at most `max_dev` steps from the rule level and never below the floor.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from sentinel.domain.models import EvidencePacket, GroundingResult, RiskBrief, RiskLevel, Verdict

ID_RE = re.compile(r"\b(?:img_\d+|[TVRD]\d+)\b")
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
NUM_RE = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?")


def _numbers_in(text: str) -> list[float]:
    text = TIME_RE.sub(" ", ID_RE.sub(" ", text))
    return [float(n.replace(",", ".")) for n in NUM_RE.findall(text)]


def _walk(obj: Any, key: str = "") -> Iterable[tuple[str, Any]]:
    """Leaves with the name of the field they sit under (used to pick unit variants)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, str(k))
    elif isinstance(obj, list | tuple):
        for v in obj:
            yield from _walk(v, key)
    else:
        yield key, obj


def _unit_variants(key: str, v: float) -> set[float]:
    """Only conversions that make sense for the field: m↔km, m/s→km/h."""
    if key.endswith("_mps"):
        return {v * 3.6}
    if key.endswith("_km"):
        return {v * 1000}
    if key.endswith("_m"):
        return {v / 1000}
    return set()


class EvidenceBank:
    """Numbers / times / ids a text may use. Built from structured evidence plus free texts."""

    def __init__(self, masked: dict[str, Any], packet: EvidencePacket):
        # report raw texts may be quoted (masked coordinates excluded)
        raw = [re.sub(r"\d+\.\d+N\s+\d+\.\d+E", " ", r.text) + " " + r.time for r in packet.reports]
        self._collect([masked], raw)
        self.times.add(packet.frame.capture_time)
        self.ids |= {packet.image_id} | {v.ref for v in packet.vehicles} | {v.det_id for v in packet.vehicles}
        self.ids |= {v.track_id for v in packet.vehicles if v.track_id}
        self.ids |= {r.report_id for r in packet.reports} | set(packet.undetected_tracks)

    @classmethod
    def from_sources(cls, objects: list[Any], texts: list[str]) -> EvidenceBank:
        """Bank for chat answers: tool outputs (objects) + the conversation so far (texts)."""
        bank = cls.__new__(cls)
        bank._collect(objects, texts)
        return bank

    def _collect(self, objects: list[Any], extra_texts: list[str]) -> None:
        nums: set[float] = set()
        texts: list[str] = list(extra_texts)
        for key, x in _walk(objects):
            if isinstance(x, bool) or x is None:
                continue
            if isinstance(x, int | float):
                nums.add(float(x))
                nums.update(_unit_variants(key, float(x)))
            elif isinstance(x, str):
                texts.append(x)
        for t in texts:
            nums.update(_numbers_in(t))
        # ids inside identifiers ("img_000860") must not count as numbers, but ids themselves are known
        joined = " ".join(texts)
        self.numbers = nums
        self.times = set(TIME_RE.findall(joined))
        self.ids = set(ID_RE.findall(joined))

    def has_number(self, x: float) -> bool:
        for v in self.numbers:
            if abs(x - v) <= max(0.051, 0.02 * abs(v)):
                return True
            if float(x).is_integer() and round(v) == x and abs(v) >= 1:  # "~4 dk" for 4.46
                return True
        return False


def _brief_texts(b: RiskBrief) -> list[str]:
    out = [b.headline, b.recommended_action, b.level_rationale or ""]
    out += [f.statement for f in b.key_findings]
    out += [r.reason for r in b.report_assessment]
    out += list(b.uncertainties)
    return out


def check(
    brief: RiskBrief, packet: EvidencePacket, masked: dict[str, Any], max_dev: int = 1
) -> GroundingResult:
    bank = EvidenceBank(masked, packet)
    res = GroundingResult()

    for text in _brief_texts(brief):
        for t in TIME_RE.findall(text):
            res.checked += 1
            if t not in bank.times:
                res.failed.append(f"saat {t}")
        for i in ID_RE.findall(text):
            if i not in bank.ids:
                res.unknown_refs.append(i)
        for n in _numbers_in(text):
            res.checked += 1
            if not bank.has_number(n):
                res.failed.append(f"{n:g} («{_ctx(text, n)}»)")

    refs = [f.vehicle_ref for f in brief.key_findings if f.vehicle_ref]
    refs += [e.split("@")[0] for f in brief.key_findings for e in f.evidence_refs]
    res.unknown_refs += [r for r in refs if r not in bank.ids]

    det = {r.report_id: r.verdict for r in packet.reports}
    for ra in brief.report_assessment:
        if ra.report_id not in det:
            res.unknown_refs.append(ra.report_id)
        elif ra.verdict != det[ra.report_id]:
            res.failed.append(
                f"{ra.report_id} kararı değiştirilmiş ({ra.verdict.value} ≠ {det[ra.report_id].value})"
            )

    # a free-text sentence may not restate a report with a different verdict ("R069 doğrulandı" when it is ÇELİŞİYOR)
    free = [brief.headline, brief.recommended_action, brief.level_rationale or ""]
    free += [f.statement for f in brief.key_findings] + list(brief.uncertainties)
    for text in free:
        res.failed += _verdict_mismatches(text, det)

    if brief.risk_score != packet.risk.score:
        res.failed.append(f"risk_score {brief.risk_score} ≠ {packet.risk.score}")

    rule, floor = packet.risk.level, packet.risk.floor_level
    dev = brief.risk_level.rank - rule.rank
    if abs(dev) > max_dev:
        res.level_ok, res.level_issue = False, f"seviye kural seviyesinden {abs(dev)} kademe sapıyor"
    elif floor is not None and brief.risk_level.rank < floor.rank:
        res.level_ok, res.level_issue = False, f"seviye tabanın ({floor.value}) altında"
    elif dev != 0 and not (brief.level_rationale or "").strip():
        res.level_ok, res.level_issue = False, "seviye farklı ama gerekçe (level_rationale) yok"
    res.unknown_refs = sorted(set(res.unknown_refs))
    return res


_REPORT_ID_RE = re.compile(r"\bR\d{3}\b")
# checked in this order: "doğrulanamadı" contains "doğrulan"
_VERDICT_WORDS: list[tuple[Verdict, re.Pattern]] = [
    (Verdict.CELISIYOR, re.compile(r"çeliş", re.IGNORECASE)),
    (Verdict.DOGRULANAMAZ, re.compile(r"doğrulanama|teyit edileme", re.IGNORECASE)),
    (
        Verdict.DOGRULANDI,
        re.compile(r"doğrulandı|doğruluyor|doğrulanıyor|doğrulanmış|teyit edildi", re.IGNORECASE),
    ),
]


def _verdict_mismatches(text: str, det: dict[str, Verdict]) -> list[str]:
    """Per clause with exactly one report id: the verdict word used must match the deterministic verdict."""
    out = []
    for clause in re.split(r"[.;]\s", text):
        ids = [i for i in set(_REPORT_ID_RE.findall(clause)) if i in det]
        if len(ids) != 1:
            continue
        said = [v for v, pat in _VERDICT_WORDS if pat.search(clause)]
        if not said:
            continue
        said = said[:1] if said[0] != Verdict.DOGRULANAMAZ else [Verdict.DOGRULANAMAZ]
        if said[0] != det[ids[0]]:
            out.append(f"{ids[0]} metinde '{said[0].value}' deniyor, karar {det[ids[0]].value}")
    return out


def clamp_level(level: RiskLevel, packet: EvidencePacket, max_dev: int = 1) -> RiskLevel:
    rule, floor = packet.risk.level, packet.risk.floor_level
    rank = max(rule.rank - max_dev, min(rule.rank + max_dev, level.rank))
    if floor is not None:
        rank = max(rank, floor.rank)
    return RiskLevel.from_rank(rank)


def _ctx(text: str, n: float) -> str:
    s = f"{n:g}"
    for cand in (s, s.replace(".", ",")):
        i = text.find(cand)
        if i >= 0:
            return text[max(0, i - 25) : i + len(cand) + 15].strip()
    return text[:40]


def check_text(text: str, bank: EvidenceBank) -> GroundingResult:
    """Grounding for free text (chat answers): every number, time and id must come from the bank."""
    res = GroundingResult()
    for t in TIME_RE.findall(text):
        res.checked += 1
        if t not in bank.times:
            res.failed.append(f"saat {t}")
    res.unknown_refs = sorted({i for i in ID_RE.findall(text) if i not in bank.ids})
    for n in _numbers_in(text):
        res.checked += 1
        if not bank.has_number(n):
            res.failed.append(f"{n:g} («{_ctx(text, n)}»)")
    return res
