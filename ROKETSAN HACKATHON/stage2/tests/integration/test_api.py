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
    # Map/box colours come from config thresholds on the backend, not from constants in the UI.
    pkt = client.get("/api/frames/img_000860/packet").json()
    assert set(tr["vehicle_levels"]) == {v["ref"] for v in pkt["vehicles"]}
    # Projection vectors carry the packet's own ETA for every approaching vehicle (nothing recomputed).
    etas = {
        v["ref"]: v["kinematics"]["eta_min"]
        for v in pkt["vehicles"]
        if v["kinematics"] and v["kinematics"]["approaching"]
    }
    assert {p["vehicle_ref"]: p["eta_min"] for p in tr["projections"]} == {
        k: e for k, e in etas.items() if e is not None
    }
    assert all(
        t["level"] == tr["vehicle_levels"][t["vehicle_ref"]] for t in tr["tracks"] if t["role"] == "vehicle"
    )
    assert [p["eta_min"] for p in tr["projections"]] == sorted(p["eta_min"] for p in tr["projections"])
    # Queue row carries the decisive numbers straight from the packet.
    row = next(r for r in client.get("/api/triage").json() if r["image_id"] == "img_000860")
    etas = [
        v["kinematics"]["eta_min"]
        for v in pkt["vehicles"]
        if v["kinematics"] and v["kinematics"]["approaching"] and v["kinematics"]["eta_min"] is not None
    ]
    assert row["min_eta_min"] == min(etas) and row["n_approaching"] >= len(etas) >= 1
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

    def row():
        return next(r for r in client.get("/api/triage").json() if r["image_id"] == "img_000860")

    assert row()["decision"]["level"] == "YÜKSEK"
    s = client.get("/api/summary").json()
    assert s["decided"] >= 1
    # Posture = highest level still waiting; img_000860 is decided now, the other KRİTİK frames are not.
    open_crit = sum(
        r["level"] == "KRİTİK" and r["decision"] is None for r in client.get("/api/triage").json()
    )
    assert (s["posture_level"], s["posture_pending"]) == ("KRİTİK", open_crit)
    client.post("/api/frames/img_000860/decisions", json={"run_id": run_id, "action": "undo"})
    assert row()["decision"] is None  # undo is visible in the queue too


def test_chat_endpoint(client):
    assert client.post("/api/chat", json={"question": "  "}).status_code == 422
    r = client.post("/api/chat", json={"question": "Durum?", "image_id": "img_000860", "history": []})
    assert r.status_code == 200
    body = r.json()
    assert {"answer", "tool_calls", "grounded", "run_id", "followups"} <= body.keys()


def test_chat_suggestions_endpoint(client):
    frame = client.get("/api/chat/suggestions", params={"image_id": "img_000860"}).json()["suggestions"]
    assert frame and {"text", "reason", "refs"} <= frame[0].keys()
    queue = client.get("/api/chat/suggestions").json()["suggestions"]
    assert queue and queue != frame
    two = client.post(
        "/api/chat/suggestions",
        json={
            "context": [
                {"kind": "frame", "image_id": "img_000860"},
                {"kind": "frame", "image_id": "img_006673"},
            ]
        },
    ).json()["suggestions"]
    assert any("img_000860" in x["text"] and "img_006673" in x["text"] for x in two)
    bad = client.post("/api/chat/suggestions", json={"context": [{"kind": "zone", "image_id": "x"}]})
    assert bad.status_code == 422


def test_chat_vocab_endpoint(client):
    v = client.get("/api/chat/vocab").json()
    assert len(v["frames"]) == 40 and len(v["reports"]) == 137 and len(v["zones"]) == 8
    assert any(t["id"] == "T0122" and t["frame"] == "img_000860" for t in v["tracks"])
    r119 = next(r for r in v["reports"] if r["id"] == "R119")
    assert r119["verdicts"]["img_000860"] == "ÇELİŞİYOR"  # verdicts are per frame
    assert "Doğu Yolu" in v["zones"] and "12:25" in v["times"]


def test_blind_labelling_endpoints(client, settings):
    prog = client.get("/api/gold/tester").json()
    assert prog["total"] == 40 and "level" not in str(prog).lower().replace("labeler", "")
    r = client.post("/api/frames/img_000860/gold", json={"labeler": "tester", "level": "YÜKSEK"})
    assert r.status_code == 200 and r.json()["level"] == "YÜKSEK"
    assert client.get("/api/gold/tester").json()["done"]["img_000860"] == "YÜKSEK"
    assert (
        client.post("/api/frames/img_000860/gold", json={"labeler": "  ", "level": "ORTA"}).status_code == 422
    )


def test_live_evaluation_streams_steps_then_result(client):
    """The live run streams the six steps as they finish; the packet comes before the brief step."""
    import json

    with client.stream("POST", "/api/frames/img_000860/evaluate/stream?live=true") as r:
        assert r.status_code == 200
        events = [json.loads(line) for line in r.iter_lines() if line]
    kinds = [e["type"] for e in events]
    assert kinds[-1] == "result" and "error" not in kinds
    done = [e["step"] for e in events if e["type"] == "step"]
    assert done[:5] == ["1_tespit", "2_koordinat", "3_eşleme_kinematik", "4_raporlar", "5_risk"]
    assert done[5].startswith("6_")
    assert kinds.index("packet") < max(i for i, e in enumerate(events) if e["type"] == "step")
    assert [e["step"] for e in events if e["type"] == "start"][0] == "1_tespit"
    res = events[-1]["result"]
    assert (
        res["packet"]["risk"]["level"] == "KRİTİK"
        and res["run_id"] == events[kinds.index("packet")]["run_id"]
    )
    assert client.post("/api/frames/yok/evaluate/stream").status_code == 404


def test_shift_handover_is_deterministic_and_tracks_decisions(client):
    run_id = client.get("/api/frames/img_000860").json()["result"]["run_id"]
    client.post("/api/frames/img_000860/decisions", json={"run_id": run_id, "action": "escalate"})
    h = client.get("/api/handover").json()
    assert [r["image_id"] for r in h["escalated"]] == ["img_000860"]
    assert "img_000860" not in {r["image_id"] for r in h["awaiting"]}
    assert all(r["level"] in ("YÜKSEK", "KRİTİK") and r["decision"] is None for r in h["awaiting"])
    # The aha reports: official, contradicted in img_000860's context.
    official = {r["report_id"]: r for r in h["contradicted_official"]}
    assert {"R119", "R125"} <= official.keys() and "img_000860" in official["R125"]["frames"]
    assert official["R119"]["identity_claim"] is True
    client.post("/api/frames/img_000860/decisions", json={"run_id": run_id, "action": "undo"})
    assert client.get("/api/handover").json()["escalated"] == []


def test_handling_time_and_downgrade_are_measured(client):
    run_id = client.get("/api/frames/img_006673").json()["result"]["run_id"]
    assert client.post("/api/frames/img_006673/viewed").status_code == 200
    assert client.post("/api/frames/yok/viewed").status_code == 404
    body = {"run_id": run_id, "action": "override", "level": "ORTA", "reason": "dost konvoy teyitli"}
    client.post("/api/frames/img_006673/decisions", json=body)
    s = client.get("/api/summary").json()
    assert s["decision_timed"] >= 1 and s["decision_median_s"] is not None and s["decision_median_s"] >= 0
    assert s["high_downgraded"] >= 1 and s["high_decided"] >= s["high_downgraded"]
    client.post("/api/frames/img_006673/decisions", json={"run_id": run_id, "action": "undo"})


def test_impact_simulation_endpoint(client):
    r = client.get("/api/impact").json()
    assert len(r["frames"]) == 40 and r["manual"]["source"] in ("varsayım", "kronometre")
    crit = r["summary"]["by_level"]["KRİTİK"]
    assert crit["with_eta"] >= 1 and crit["system_before"] >= crit["manual_before"]
    f = next(x for x in r["frames"] if x["image_id"] == "img_000860")
    assert f["arrival_min"] is not None and f["system_done"] <= f["manual_done"]
