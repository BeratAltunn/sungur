"""Shift simulation for the impact view and the triage replay (PROJECT_DESIGN §1.2, §1.4).

One operator works through the day's frames as they arrive (capture time), one at a time:
  * by hand, first come first served, `manual_min` per frame;
  * with NÖBETÇİ, in the product's risk order, `system_min` per frame.
For every frame it records when the operator would start and decide, and compares the decision with the
projected arrival of the frame's closest approaching vehicle (capture + ETA). This is a model of operator
time, not evidence: it never feeds the risk score, the brief or grounding. Handling times come from
measurements when there are enough (stopwatch, opening→decision log), otherwise from config assumptions.
"""

from __future__ import annotations

import csv
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from sentinel.domain.models import to_min


class HandlingTime(BaseModel):
    minutes: float
    source: Literal["ölçüm", "kronometre", "varsayım"]
    n: int = 0  # measurements behind it (0 for an assumption)


class SimFrame(BaseModel):
    image_id: str
    level: str
    zone: str
    capture_time: str
    capture_min: float
    eta_min: float | None  # closest approaching vehicle at capture (from the packet)
    arrival_min: float | None  # capture + ETA: projected arrival at the base
    manual_start: float
    manual_done: float
    system_start: float
    system_done: float
    manual_before: bool | None  # decided before the projected arrival (None: nothing approaching)
    system_before: bool | None


class ArrivalOutcome(BaseModel):
    """Frames of one level with an approaching vehicle, and how many were decided before its arrival."""

    with_eta: int
    manual_before: int
    system_before: int


class ImpactSummary(BaseModel):
    by_level: dict[str, ArrivalOutcome]  # KRİTİK, YÜKSEK
    manual_median_delay_min: float | None  # capture → decision, YÜKSEK/KRİTİK
    system_median_delay_min: float | None


class ImpactReport(BaseModel):
    manual: HandlingTime
    system: HandlingTime
    frames: list[SimFrame]  # capture order
    summary: ImpactSummary
    assumptions: list[str]


def simulate(arrivals: Sequence[tuple[str, float]], service_min: float, priority: dict[str, int] | None):
    """Single server, non-preemptive. `priority` (lower first) picks among waiting frames; None = FIFO.
    Returns {image_id: (start_min, done_min)}."""
    pending = sorted(arrivals, key=lambda a: (a[1], a[0]))
    waiting: list[tuple[str, float]] = []
    t = pending[0][1] if pending else 0.0
    out: dict[str, tuple[float, float]] = {}
    while pending or waiting:
        while pending and pending[0][1] <= t:
            waiting.append(pending.pop(0))
        if not waiting:
            t = pending[0][1]
            continue
        if priority is None:
            waiting.sort(key=lambda a: (a[1], a[0]))
        else:
            waiting.sort(key=lambda a: (priority[a[0]], a[1]))
        img, _ = waiting.pop(0)
        out[img] = (t, t + service_min)
        t += service_min
    return out


def stopwatch_minutes(path: Path, mode: str) -> list[float]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [
            float(r["seconds"]) / 60 for r in csv.DictReader(fh) if r.get("mode") == mode and r.get("seconds")
        ]


def pick_handling_time(
    measured: list[float], stopwatch: list[float], assumed: float, min_n: int
) -> HandlingTime:
    if len(measured) >= min_n:
        return HandlingTime(minutes=statistics.median(measured), source="ölçüm", n=len(measured))
    if len(stopwatch) >= min_n:
        return HandlingTime(minutes=statistics.median(stopwatch), source="kronometre", n=len(stopwatch))
    return HandlingTime(minutes=assumed, source="varsayım")


def build_report(rows: Sequence, manual: HandlingTime, system: HandlingTime) -> ImpactReport:
    """rows: the triage queue (risk order, TriageRow-like: image_id, level, zone, capture_time, min_eta_min)."""
    cap = {r.image_id: float(to_min(r.capture_time)) for r in rows}
    arrivals = list(cap.items())
    fifo = simulate(arrivals, manual.minutes, None)
    risk = simulate(arrivals, system.minutes, {r.image_id: i for i, r in enumerate(rows)})
    frames = []
    for r in sorted(rows, key=lambda r: (cap[r.image_id], r.image_id)):
        c = cap[r.image_id]
        eta = r.min_eta_min
        arrival = c + eta if eta is not None else None
        frames.append(
            SimFrame(
                image_id=r.image_id,
                level=str(r.level.value if hasattr(r.level, "value") else r.level),
                zone=r.zone,
                capture_time=r.capture_time,
                capture_min=c,
                eta_min=eta,
                arrival_min=arrival,
                manual_start=fifo[r.image_id][0],
                manual_done=fifo[r.image_id][1],
                system_start=risk[r.image_id][0],
                system_done=risk[r.image_id][1],
                manual_before=None if arrival is None else fifo[r.image_id][1] <= arrival,
                system_before=None if arrival is None else risk[r.image_id][1] <= arrival,
            )
        )
    high = [f for f in frames if f.level in ("YÜKSEK", "KRİTİK")]

    def outcome(level: str) -> ArrivalOutcome:
        timed = [f for f in frames if f.level == level and f.arrival_min is not None]
        return ArrivalOutcome(
            with_eta=len(timed),
            manual_before=sum(bool(f.manual_before) for f in timed),
            system_before=sum(bool(f.system_before) for f in timed),
        )

    def med(xs: list[float]) -> float | None:
        return float(statistics.median(xs)) if xs else None

    summary = ImpactSummary(
        by_level={lv: outcome(lv) for lv in ("KRİTİK", "YÜKSEK")},
        manual_median_delay_min=med([f.manual_done - f.capture_min for f in high]),
        system_median_delay_min=med([f.system_done - f.capture_min for f in high]),
    )
    assumptions = [
        "Tek operatör, kareleri tek tek işliyor; telsiz ve rapor yükü hesaba katılmadı (elle akış için iyimser).",
        "Elle akış kareleri geliş sırasıyla (FIFO), NÖBETÇİ ürünün risk sırasıyla işler.",
        "Varış = çekim anı + o andaki yaklaşma hızına göre ETA (en yakın yaklaşan araç); hız değişirse varış da değişir.",
    ]
    return ImpactReport(manual=manual, system=system, frames=frames, summary=summary, assumptions=assumptions)
