"""Operator decisions, append-only (runs/decisions.jsonl). "Undo" is a new record, never a delete.

Frame openings go to runs/views.jsonl, so the time from opening a frame to deciding on it
(the operator's per-frame handling time, PROJECT_DESIGN §1.4/§1.7) is measured, not assumed."""

from __future__ import annotations

import json
import statistics
import uuid
from datetime import datetime
from pathlib import Path

from sentinel.domain.models import OperatorDecision, RiskLevel


class DecisionLog:
    def __init__(self, runs_dir: Path):
        self.path = Path(runs_dir) / "decisions.jsonl"

    def record(
        self, run_id: str, image_id: str, action: str, level: RiskLevel | None = None, reason: str = ""
    ) -> OperatorDecision:
        if action == "override" and not reason.strip():
            raise ValueError("Seviye değişikliği için gerekçe zorunlu")
        dec = OperatorDecision(
            decision_id=uuid.uuid4().hex[:10],
            run_id=run_id,
            image_id=image_id,
            action=action,  # type: ignore[arg-type]
            level=level,
            reason=reason,
            at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(dec.model_dump_json() + "\n")
        return dec

    def all(self) -> list[OperatorDecision]:
        if not self.path.exists():
            return []
        return [
            OperatorDecision.model_validate_json(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def current(self, image_id: str) -> OperatorDecision | None:
        """Latest effective decision for a frame (an 'undo' cancels the one before it)."""
        return self.current_all().get(image_id)

    def current_all(self) -> dict[str, OperatorDecision]:
        """Effective decision per frame in one pass over the log (the triage queue needs all of them)."""
        stacks: dict[str, list[OperatorDecision]] = {}
        for d in self.all():
            stack = stacks.setdefault(d.image_id, [])
            if d.action == "undo":
                if stack:
                    stack.pop()
            else:
                stack.append(d)
        return {img: stack[-1] for img, stack in stacks.items() if stack}


class ViewLog:
    """When the operator opened a frame (append-only; the blind-labelling screen does not log)."""

    def __init__(self, runs_dir: Path):
        self.path = Path(runs_dir) / "views.jsonl"

    def record(self, image_id: str) -> str:
        at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"image_id": image_id, "at": at}) + "\n")
        return at

    def all(self) -> list[tuple[str, str]]:
        if not self.path.exists():
            return []
        rows = (json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line)
        return [(r["image_id"], r["at"]) for r in rows]


def decision_seconds(decisions: dict[str, OperatorDecision], views: list[tuple[str, str]]) -> list[float]:
    """Seconds from the last opening of a frame before its effective decision to that decision.
    Frames decided without a logged opening (e.g. via the API) are left out."""
    out = []
    for image_id, d in decisions.items():
        t_dec = _aware(d.at)
        opened = [_aware(at) for img, at in views if img == image_id]
        opened = [t for t in opened if t <= t_dec]
        if opened:
            out.append((t_dec - max(opened)).total_seconds())
    return out


def _aware(iso: str) -> datetime:
    """Older log lines have no UTC offset: read them as local time so they compare with newer ones."""
    t = datetime.fromisoformat(iso)
    return t if t.tzinfo else t.astimezone()


def median_or_none(xs: list[float]) -> float | None:
    return float(statistics.median(xs)) if xs else None
