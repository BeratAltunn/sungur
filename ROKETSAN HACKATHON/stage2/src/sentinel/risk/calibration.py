"""Calibration against a blind gold set: agreement, confusion, recall-first metrics, weight sensitivity.

Gold labels are written by the UI's blind labelling mode to calibration/labels/<labeler>.jsonl
(append-only; the latest label per labeler and frame wins).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sentinel.config import RiskCfg
from sentinel.domain.models import EvidencePacket, RiskLevel
from sentinel.reports.parser import normalize
from sentinel.risk.scoring import assess

LEVELS = [RiskLevel.DUSUK, RiskLevel.ORTA, RiskLevel.YUKSEK, RiskLevel.KRITIK]
HIGH = {RiskLevel.YUKSEK, RiskLevel.KRITIK}


# ============================================================================ labels
@dataclass
class GoldLabel:
    image_id: str
    labeler: str
    level: RiskLevel
    note: str = ""
    at: str = ""


class LabelStore:
    def __init__(self, directory: Path):
        self.dir = Path(directory)

    @staticmethod
    def _safe(name: str) -> str:
        name = "".join(c for c in normalize(name.strip()) if c.isascii() and (c.isalnum() or c in "-_"))
        if not name:
            raise ValueError("etiketleyici adı boş olamaz")
        return name[:32]

    def add(self, image_id: str, labeler: str, level: RiskLevel, note: str = "") -> GoldLabel:
        lab = GoldLabel(
            image_id,
            self._safe(labeler),
            RiskLevel(level),
            note.strip(),
            datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / f"{lab.labeler}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({**lab.__dict__, "level": lab.level.value}, ensure_ascii=False) + "\n")
        return lab

    def latest(self) -> dict[str, dict[str, GoldLabel]]:
        """{labeler: {image_id: latest label}}"""
        out: dict[str, dict[str, GoldLabel]] = {}
        if not self.dir.exists():
            return out
        for f in sorted(self.dir.glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                d = json.loads(line)
                lab = GoldLabel(
                    d["image_id"], d["labeler"], RiskLevel(d["level"]), d.get("note", ""), d.get("at", "")
                )
                out.setdefault(lab.labeler, {})[lab.image_id] = lab
        return out

    def progress(self, labeler: str) -> dict[str, str]:
        return {k: v.level.value for k, v in self.latest().get(self._safe(labeler), {}).items()}


# ============================================================================ agreement
def cohen_kappa(a: list[RiskLevel], b: list[RiskLevel], weighted: bool = True) -> float | None:
    """Linearly weighted Cohen's kappa over the 4 ordinal levels (None if undefined)."""
    n = len(a)
    if n == 0 or n != len(b):
        return None
    k = len(LEVELS)
    idx = {lv: i for i, lv in enumerate(LEVELS)}

    def w(i: int, j: int) -> float:
        return abs(i - j) / (k - 1) if weighted else float(i != j)

    obs = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b, strict=True):
        obs[idx[x]][idx[y]] += 1
    ra = [sum(row) for row in obs]
    cb = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = sum(w(i, j) * obs[i][j] for i in range(k) for j in range(k))
    den = sum(w(i, j) * ra[i] * cb[j] / n for i in range(k) for j in range(k))
    return None if den == 0 else 1 - num / den


def consensus(labels: dict[str, dict[str, GoldLabel]]) -> dict[str, RiskLevel]:
    """Per frame: the agreed level; on disagreement the higher one (recall first)."""
    out: dict[str, RiskLevel] = {}
    for per_frame in labels.values():
        for img, lab in per_frame.items():
            cur = out.get(img)
            out[img] = lab.level if cur is None or lab.level.rank > cur.rank else cur
    return out


# ============================================================================ system vs gold
@dataclass
class Metrics:
    n: int
    confusion: list[list[int]]  # rows = gold, cols = system, order LEVELS
    missed_threats: list[str] = field(default_factory=list)  # gold ≥ YÜKSEK, system < ORTA
    under_called: list[str] = field(default_factory=list)  # gold ≥ YÜKSEK, system < YÜKSEK
    false_alarms: list[str] = field(default_factory=list)  # system ≥ YÜKSEK, gold < system
    exact: int = 0
    within_one: int = 0

    @property
    def high_recall(self) -> float | None:
        pos = sum(self.confusion[g][s] for g in (2, 3) for s in range(4))
        hit = sum(self.confusion[g][s] for g in (2, 3) for s in (2, 3))
        return hit / pos if pos else None

    @property
    def false_alarm_rate(self) -> float | None:
        flagged = sum(self.confusion[g][s] for g in range(4) for s in (2, 3))
        return len(self.false_alarms) / flagged if flagged else None


def compare(system: dict[str, RiskLevel], gold: dict[str, RiskLevel]) -> Metrics:
    idx = {lv: i for i, lv in enumerate(LEVELS)}
    common = sorted(set(system) & set(gold))
    m = Metrics(n=len(common), confusion=[[0] * 4 for _ in range(4)])
    for img in common:
        g, s = gold[img], system[img]
        m.confusion[idx[g]][idx[s]] += 1
        m.exact += g == s
        m.within_one += abs(g.rank - s.rank) <= 1
        if g in HIGH and s.rank < RiskLevel.ORTA.rank:
            m.missed_threats.append(img)
        if g in HIGH and s not in HIGH:
            m.under_called.append(img)
        if s in HIGH and s.rank > g.rank:
            m.false_alarms.append(img)
    return m


# ============================================================================ sensitivity
def levels_for(packets: Iterable[EvidencePacket], cfg: RiskCfg) -> dict[str, RiskLevel]:
    """Re-score packets with another risk config (evidence unchanged; vehicles are copied)."""
    out = {}
    for p in packets:
        vehicles = copy.deepcopy(p.vehicles)
        out[p.image_id] = assess(vehicles, p.reports, cfg).level
    return out


def sensitivity(packets: list[EvidencePacket], cfg: RiskCfg, delta: float = 0.2) -> list[dict]:
    """For each weight: how many frames change level when it is scaled by (1 ± delta)."""
    base = levels_for(packets, cfg)
    rows = []
    for name, value in cfg.weights.model_dump().items():
        row = {"weight": name, "value": value}
        for sign, key in ((-1, "down"), (1, "up")):
            c = cfg.model_copy(deep=True)
            setattr(c.weights, name, int(round(value * (1 + sign * delta))))
            lv = levels_for(packets, c)
            row[key] = sum(lv[i] != base[i] for i in base)
            row[f"{key}_frames"] = sorted(i for i in base if lv[i] != base[i])
        rows.append(row)
    return sorted(rows, key=lambda r: -(r["down"] + r["up"]))
