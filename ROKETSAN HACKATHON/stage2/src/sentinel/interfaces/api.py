"""REST layer over SentinelService (thin: no business logic here) + the built web UI.

    uvicorn sentinel.interfaces.api:app --port 8000        (or: make app)

The React app in web/ is built to web/dist and served from "/"; in development Vite proxies /api here.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sentinel.config import PROJECT_ROOT
from sentinel.domain.models import RiskLevel
from sentinel.service import SentinelService

log = logging.getLogger(__name__)
WEB_DIST = PROJECT_ROOT / "web" / "dist"

_svc: SentinelService | None = None
service_factory: Callable[[], SentinelService] = SentinelService  # tests inject a mock-LLM service
_warm = {"done": 0, "total": 0}
# One lock per frame: an LLM call for one frame never blocks the other screens.
_frame_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()
_decision_lock = threading.Lock()


def _frame_lock(image_id: str) -> threading.Lock:
    with _registry_lock:
        return _frame_locks.setdefault(image_id, threading.Lock())


def svc() -> SentinelService:
    if _svc is None:  # pragma: no cover - lifespan sets it
        raise HTTPException(503, "servis başlatılıyor")
    return _svc


def _warmup() -> None:
    """Evaluate every frame once without network calls, so triage shows cached LLM headlines."""
    s = svc()
    frames = s.repo.frames()
    _warm["total"] = len(frames)
    for m in frames:
        try:
            with _frame_lock(m.image_id):
                s.preview(m.image_id)
        except Exception:  # one bad frame must not stop the others
            log.exception("ön-değerlendirme başarısız: %s", m.image_id)
        _warm["done"] += 1


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _svc
    _svc = service_factory()
    threading.Thread(target=_warmup, daemon=True).start()
    yield


app = FastAPI(title="NÖBETÇİ API", lifespan=lifespan)


def _check_frame(image_id: str) -> None:
    if image_id not in svc().repo.meta:
        raise HTTPException(404, f"Bilinmeyen kare: {image_id}")


# ------------------------------------------------------------------ read
@app.get("/api/health")
def health() -> dict:
    return {**svc().health(), "warmup": _warm}


@app.get("/api/summary")
def summary():
    return svc().shift_summary()


@app.get("/api/triage")
def triage(zone: str | None = None, level: RiskLevel | None = None):
    return svc().triage(zone, level)


@app.get("/api/map")
def map_context() -> dict:
    return svc().map_context()


@app.get("/api/frames/{image_id}")
def frame(image_id: str):
    _check_frame(image_id)
    with _frame_lock(image_id):
        res = svc().result(image_id)
    return {"result": res, "decision": svc().decisions.current(image_id)}


@app.get("/api/frames/{image_id}/packet")
def frame_packet(image_id: str):
    """Deterministic evidence only (fast): the UI renders it while the brief is still being written."""
    _check_frame(image_id)
    return svc().packet(image_id)


@app.get("/api/frames/{image_id}/tracks")
def frame_tracks(image_id: str) -> dict:
    _check_frame(image_id)
    return svc().frame_tracks(image_id)


@app.get("/api/frames/{image_id}/image")
def frame_image(image_id: str):
    _check_frame(image_id)
    path = svc().repo.image_path(image_id)
    if not path.exists():
        raise HTTPException(404, "görüntü dosyası yok")
    return FileResponse(path)


@app.get("/api/runs/{run_id}/trace")
def trace(run_id: str) -> list[dict]:
    return svc().trace(run_id)


# ------------------------------------------------------------------ write
@app.post("/api/frames/{image_id}/evaluate")
def evaluate(image_id: str, live: bool = False):
    """Re-run the pipeline; live=true bypasses the detection cache (the demo's live run)."""
    _check_frame(image_id)
    with _frame_lock(image_id):
        res = svc().evaluate(image_id, live=live)
    return {"result": res, "decision": svc().decisions.current(image_id)}


class ChatIn(BaseModel):
    question: str
    history: list[dict] = []
    image_id: str | None = None


@app.post("/api/chat")
def chat(body: ChatIn) -> dict:
    """One chat turn: the LLM calls read-only tools (≤ 6 steps); numbers in the answer are grounded."""
    q = body.question.strip()
    if not q:
        raise HTTPException(422, "soru boş")
    turn, run_id = svc().chat(q[:2000], body.history[-8:], body.image_id)
    return {**turn.model_dump(), "run_id": run_id}


class GoldIn(BaseModel):
    labeler: str
    level: RiskLevel
    note: str = ""


@app.get("/api/gold/{labeler}")
def gold_progress(labeler: str) -> dict:
    """Blind labelling progress. Returns no system output (level/score) on purpose."""
    try:
        return svc().gold_progress(labeler)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.post("/api/frames/{image_id}/gold")
def gold_label(image_id: str, body: GoldIn) -> dict:
    _check_frame(image_id)
    try:
        with _decision_lock:
            return svc().record_gold(image_id, body.labeler, body.level, body.note)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class DecisionIn(BaseModel):
    run_id: str
    action: str
    level: RiskLevel | None = None
    reason: str = ""


@app.post("/api/frames/{image_id}/decisions")
def decide(image_id: str, body: DecisionIn):
    _check_frame(image_id)
    if body.action not in {"approve", "override", "escalate", "undo"}:
        raise HTTPException(422, "geçersiz eylem")
    try:
        with _decision_lock:
            svc().record_decision(body.run_id, image_id, body.action, body.level, body.reason)
            return {"decision": svc().decisions.current(image_id)}
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


# ------------------------------------------------------------------ web UI
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = WEB_DIST / path
        if path and f.is_file() and Path(WEB_DIST) in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")
