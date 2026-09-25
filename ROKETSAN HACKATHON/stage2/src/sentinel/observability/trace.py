"""Step trace → runs/trace.jsonl. The UI's "Ajan izi" tab is drawn from these records."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any


def new_run_id() -> str:
    return f"{datetime.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


# listener(kind, payload): kind is "start" ({"step": name}) or "step" (the finished record).
TraceListener = Callable[[str, dict[str, Any]], None]


class Tracer:
    def __init__(
        self,
        runs_dir: Path | None,
        run_id: str,
        image_id: str | None = None,
        listener: TraceListener | None = None,
    ):
        self.run_id = run_id
        self.image_id = image_id
        self.path = Path(runs_dir) / "trace.jsonl" if runs_dir else None
        self.steps: list[dict[str, Any]] = []
        self.listener = listener  # live progress (the UI's step-by-step run); never affects the result

    @contextmanager
    def step(self, name: str, input_summary: Any = None) -> Iterator[dict[str, Any]]:
        rec: dict[str, Any] = {
            "run_id": self.run_id,
            "image_id": self.image_id,
            "step": name,
            "input_summary": input_summary,
            "output_summary": None,
            "cache_hit": None,
            "error": None,
        }
        t0 = time.perf_counter()
        if self.listener:
            self.listener("start", {"step": name})
        try:
            yield rec
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
            raise
        finally:
            rec["duration_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            rec["at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            self.steps.append(rec)
            self._write(rec)
            if self.listener:
                self.listener("step", rec)

    def _write(self, rec: dict[str, Any]) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def read_trace(runs_dir: Path, run_id: str) -> list[dict[str, Any]]:
    path = Path(runs_dir) / "trace.jsonl"
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec.get("run_id") == run_id:
                out.append(rec)
    return out
