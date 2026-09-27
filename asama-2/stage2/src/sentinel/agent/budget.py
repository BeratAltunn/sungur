"""Budget guard: hard stop at `stop_usd` (15 $ credit − 3 $ demo reserve)."""

from __future__ import annotations

import json
import threading
from pathlib import Path


class BudgetExceeded(RuntimeError):
    pass


class BudgetGuard:
    def __init__(self, ledger: Path, stop_usd: float):
        self.ledger = Path(ledger)
        self.stop_usd = stop_usd
        self._lock = threading.Lock()

    @property
    def spent(self) -> float:
        if not self.ledger.exists():
            return 0.0
        return float(json.loads(self.ledger.read_text(encoding="utf-8")).get("spent_usd", 0.0))

    def check(self) -> None:
        if self.spent >= self.stop_usd:
            raise BudgetExceeded(f"LLM bütçesi doldu: {self.spent:.2f} $ ≥ {self.stop_usd:.2f} $")

    def add(self, cost_usd: float, calls: int = 1) -> None:
        with self._lock:
            data = {"spent_usd": 0.0, "calls": 0}
            if self.ledger.exists():
                data.update(json.loads(self.ledger.read_text(encoding="utf-8")))
            data["spent_usd"] = round(data["spent_usd"] + cost_usd, 6)
            data["calls"] = int(data["calls"]) + calls
            self.ledger.parent.mkdir(parents=True, exist_ok=True)
            self.ledger.write_text(json.dumps(data), encoding="utf-8")

    def status(self) -> dict:
        s = self.spent
        return {
            "spent_usd": round(s, 4),
            "stop_usd": self.stop_usd,
            "ratio": round(s / self.stop_usd, 3) if self.stop_usd else 0,
        }
