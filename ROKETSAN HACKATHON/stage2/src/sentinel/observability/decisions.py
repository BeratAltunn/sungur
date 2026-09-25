"""Operator decisions, append-only (runs/decisions.jsonl). "Undo" is a new record, never a delete."""

from __future__ import annotations

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
            at=datetime.now().isoformat(timespec="seconds"),
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
        stack: list[OperatorDecision] = []
        for d in self.all():
            if d.image_id != image_id:
                continue
            if d.action == "undo":
                if stack:
                    stack.pop()
            else:
                stack.append(d)
        return stack[-1] if stack else None
