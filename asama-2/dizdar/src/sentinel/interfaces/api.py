"""REST layer over SentinelService (thin: no business logic here) + the built web UI.

    uvicorn sentinel.interfaces.api:app --port 8000        (or: make app)

The React app in web/ is built to web/dist and served from "/"; in development Vite proxies /api here.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, Response, StreamingResponse
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
    _warm["done"], _warm["total"] = 0, len(frames)  # a restarted app (tests) counts from zero
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


@app.get("/api/handover")
def handover():
    """Deterministic shift handover (no LLM): decisions, open high-risk frames, contradicted official reports."""
    return svc().shift_handover()


@app.get("/api/impact")
def impact():
    """Shift simulation for the impact view and the triage replay (a model of operator time, not evidence)."""
    return svc().impact()


@app.get("/api/triage")
def triage(zone: str | None = None, level: RiskLevel | None = None):
    return svc().triage(zone, level)


@app.get("/api/map")
def map_context() -> dict:
    return svc().map_context()


@app.get("/api/vehicles")
def vehicles() -> dict:
    """Every vehicle's path over the day, with its detected class and level where a frame matched it."""
    return svc().vehicles()


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


@app.get("/api/frames/{image_id}/vehicles/{vehicle_ref}/crop")
def vehicle_crop(image_id: str, vehicle_ref: str):
    """One vehicle cut out of its frame, around its detection box (the map's vehicle card)."""
    _check_frame(image_id)
    if not svc().repo.image_path(image_id).exists():
        raise HTTPException(404, "görüntü dosyası yok")
    try:
        return Response(svc().vehicle_crop(image_id, vehicle_ref), media_type="image/jpeg")
    except KeyError:
        raise HTTPException(404, f"{image_id} karesinde {vehicle_ref} yok") from None


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


@app.post("/api/frames/{image_id}/evaluate/stream")
def evaluate_stream(image_id: str, live: bool = False):
    """Same run as /evaluate, streamed as NDJSON: {"type": "start"|"step"|"packet"|"result"|"error", ...}.
    The UI shows the six steps as they finish and the evidence before the brief arrives."""
    _check_frame(image_id)
    events: queue.Queue = queue.Queue()
    done = object()

    def emit(kind: str, payload: dict) -> None:
        events.put({"type": kind, **payload})

    def run() -> None:
        try:
            with _frame_lock(image_id):
                res = svc().evaluate(image_id, live=live, on_event=emit)
            emit("result", {"result": res, "decision": svc().decisions.current(image_id)})
        except Exception as e:  # the stream reports it; the UI keeps the cached evaluation
            log.exception("canlı değerlendirme başarısız: %s", image_id)
            emit("error", {"detail": f"{type(e).__name__}: {e}"})
        finally:
            events.put(done)

    threading.Thread(target=run, daemon=True).start()

    def lines():
        while (ev := events.get()) is not done:
            yield json.dumps(jsonable_encoder(ev), ensure_ascii=False) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


class ContextIn(BaseModel):
    kind: Literal["vehicle", "frame"]
    image_id: str
    ref: str | None = None  # vehicle ref within image_id (V7)


class ChatIn(BaseModel):
    question: str
    history: list[dict] = []
    image_id: str | None = None
    vehicle_ref: str | None = None  # older single-vehicle form: a vehicle of image_id
    context: list[ContextIn] = []  # what the operator put in the chat (≤ 4, extra items dropped)


@app.post("/api/chat")
def chat(body: ChatIn) -> dict:
    """One chat turn: the LLM calls read-only tools (≤ 6 steps); numbers in the answer are grounded."""
    q = body.question.strip()
    if not q:
        raise HTTPException(422, "soru boş")
    ctx = [c.model_dump() for c in body.context]
    turn, run_id = svc().chat(q[:2000], body.history[-8:], body.image_id, body.vehicle_ref, ctx)
    return {**turn.model_dump(), "run_id": run_id}


@app.get("/api/chat/suggestions")
def chat_suggestions(image_id: str | None = None, vehicle_ref: str | None = None) -> dict:
    """Questions for the current situation (rule-based, no LLM call)."""
    return {"suggestions": [s.model_dump() for s in svc().chat_suggestions(image_id, vehicle_ref)]}


@app.get("/api/chat/vocab")
def chat_vocab() -> dict:
    """What the chat box can complete (ids, zones, times); loaded once by the UI, never per key press."""
    return svc().chat_vocab()


class SuggestIn(BaseModel):
    image_id: str | None = None
    context: list[ContextIn] = []


@app.post("/api/chat/suggestions")
def chat_suggestions_for(body: SuggestIn) -> dict:
    """Questions for what the operator put together in the chat (several vehicles and frames)."""
    ctx = [c.model_dump() for c in body.context]
    return {"suggestions": [s.model_dump() for s in svc().chat_suggestions(body.image_id, context=ctx)]}


class LlmSwitchIn(BaseModel):
    enabled: bool


@app.post("/api/llm")
def llm_switch(body: LlmSwitchIn) -> dict:
    """Operator switch: off → no LLM request is sent (briefs from the LLM cache or the template, chat says off)."""
    return {"enabled": svc().set_llm_enabled(body.enabled)}


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


@app.post("/api/frames/{image_id}/viewed")
def frame_viewed(image_id: str) -> dict:
    """Logged when the operator opens a frame: opening → decision is the measured handling time."""
    _check_frame(image_id)
    return {"at": svc().record_view(image_id)}


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
