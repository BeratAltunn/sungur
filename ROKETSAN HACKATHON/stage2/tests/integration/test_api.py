"""REST layer smoke test (mock LLM, oracle detector)."""

import pytest
from fastapi.testclient import TestClient

from sentinel.agent.llm import MockLLM
from sentinel.interfaces import api
from sentinel.service import SentinelService


@pytest.fixture(scope="module")
def client(settings):
    api.service_factory = lambda: SentinelService(settings, llm=MockLLM())
    with TestClient(api.app) as c:
        yield c
    api.service_factory = SentinelService


def test_read_endpoints(client):
    assert client.get("/api/health").json()["data"]["frames"] == 40
    assert len(client.get("/api/triage").json()) == 40
    m = client.get("/api/map").json()
    assert len(m["frames"]) == 40 and len(m["rings"]) == 2 and len(m["frames"][0]["corners"]) == 4
    f = client.get("/api/frames/img_000860").json()
    assert f["result"]["brief"]["risk_level"] == "KRİTİK"
    assert client.get("/api/frames/img_000860/packet").json()["risk"]["level"] == "KRİTİK"
    tr = client.get("/api/frames/img_000860/tracks").json()
    assert "T0122" in {t["track_id"] for t in tr["tracks"]} and tr["report_pins"]
    assert client.get("/api/frames/img_000860/image").headers["content-type"] == "image/jpeg"
    steps = [s["step"] for s in client.get(f"/api/runs/{f['result']['run_id']}/trace").json()]
    assert steps[0] == "1_tespit"


def test_errors_and_decisions(client):
    assert client.get("/api/frames/yok").status_code == 404
    run_id = client.get("/api/frames/img_000860").json()["result"]["run_id"]
    bad = {"run_id": run_id, "action": "override", "level": "YÜKSEK"}
    assert client.post("/api/frames/img_000860/decisions", json=bad).status_code == 422
    ok = client.post("/api/frames/img_000860/decisions", json={**bad, "reason": "dost konvoy teyitli"})
    assert ok.json()["decision"]["action"] == "override"


def test_chat_endpoint(client):
    assert client.post("/api/chat", json={"question": "  "}).status_code == 422
    r = client.post("/api/chat", json={"question": "Durum?", "image_id": "img_000860", "history": []})
    assert r.status_code == 200
    body = r.json()
    assert {"answer", "tool_calls", "grounded", "run_id"} <= body.keys()


def test_blind_labelling_endpoints(client, settings):
    prog = client.get("/api/gold/tester").json()
    assert prog["total"] == 40 and "level" not in str(prog).lower().replace("labeler", "")
    r = client.post("/api/frames/img_000860/gold", json={"labeler": "tester", "level": "YÜKSEK"})
    assert r.status_code == 200 and r.json()["level"] == "YÜKSEK"
    assert client.get("/api/gold/tester").json()["done"]["img_000860"] == "YÜKSEK"
    assert (
        client.post("/api/frames/img_000860/gold", json={"labeler": "  ", "level": "ORTA"}).status_code == 422
    )
