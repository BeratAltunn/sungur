"""Main map vehicle view (GET /api/vehicles) and the operator's LLM switch (POST /api/llm)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sentinel.agent.llm import MockLLM
from sentinel.domain.models import RiskLevel, to_min
from sentinel.interfaces import api
from sentinel.service import SentinelService


def test_every_track_and_detection_appears_once_with_backend_identity(service):
    day = service.vehicles()
    vs = day["vehicles"]
    tracked = [v for v in vs if v["track_id"]]
    assert sorted(v["track_id"] for v in tracked) == sorted(service.repo.tracks)  # each track exactly once
    for v in tracked:
        assert v["points"] == [[p.t_min, p.lat, p.lon] for p in service.repo.track(v["track_id"]).points]
    # identity and level are the packet's own (a track seen in two frames keeps its highest level)
    for meta in service.repo.frames():
        for pv in service.packet(meta.image_id).vehicles:
            key = pv.track_id or f"{meta.image_id}/{pv.ref}"
            v = next(x for x in vs if x["id"] == key)
            assert v["label"] == pv.label and RiskLevel(v["level"]).rank >= pv.level.rank
            if pv.track_id is None:  # no track: one point at capture time, where the detector put it
                assert v["points"] == [[meta.capture_min, pv.lat, pv.lon]]
    # tracks no frame detected carry no identity (the map draws them as grey dots)
    for v in vs:
        if v["image_id"] is None:
            assert v["label"] is v["level"] is v["score"] is None
    assert day["window"]["start"] <= min(v["points"][0][0] for v in vs)
    assert day["window"]["end"] >= max(v["points"][-1][0] for v in vs)


@pytest.fixture
def mock_client(settings, tmp_path):
    # Own runs dir: the app's background warm-up may still write traces after this test, and other tests read theirs.
    s = settings.model_copy(deep=True)
    s.observability.runs_dir = tmp_path
    llm = MockLLM()
    api.service_factory = lambda: SentinelService(s, llm=llm)
    with TestClient(api.app) as c:
        yield c, llm
    api.service_factory = SentinelService


def test_llm_switch_off_sends_nothing_to_the_model(mock_client):
    client, llm = mock_client
    assert client.get("/api/health").json()["llm"]["enabled"] is True
    assert client.post("/api/llm", json={"enabled": False}).json() == {"enabled": False}
    assert client.get("/api/health").json()["llm"]["enabled"] is False
    before = len(llm.calls)
    chat = client.post("/api/chat", json={"question": "Üsse en yakın araç hangisi?"}).json()
    assert chat["note"] == "llm_kapali" and chat["llm_calls"] == 0
    res = client.post("/api/frames/img_000860/evaluate").json()
    assert res["result"]["brief_source"] != "llm"  # LLM cache or template, never a fresh call
    assert len(llm.calls) == before
    assert client.post("/api/llm", json={"enabled": True}).json() == {"enabled": True}
    client.post("/api/chat", json={"question": "Üsse en yakın araç hangisi?"})
    assert len(llm.calls) > before  # back on: the chat reaches the model again


def test_threat_timeline_ends_at_the_packet_score_and_is_real_time(service):
    """Each detected vehicle's score over time ends at its frame's own score; the demo truck T0122 is ORTA while it
    idles and becomes KRİTİK only with its last 5-minute dash to the base (the reason for real-time levels)."""
    vs = {v["id"]: v for v in service.vehicles()["vehicles"]}
    for meta in service.repo.frames():
        for pv in service.packet(meta.image_id).vehicles:
            v = vs[pv.track_id or f"{meta.image_id}/{pv.ref}"]
            if v["image_id"] != meta.image_id:
                continue  # a track seen in two frames keeps its higher-scoring detection
            t, score, level = v["timeline"][-1]
            assert (t, score, level) == (meta.capture_min, pv.score, pv.level.value)
            assert all(lv in {x.value for x in RiskLevel} for _, _, lv in v["timeline"])
            assert [e[0] for e in v["timeline"]] == sorted(e[0] for e in v["timeline"])
    truck = {t: lv for t, _, lv in vs["T0122"]["timeline"]}
    assert truck[845] != "KRİTİK" and truck[850] == "KRİTİK"  # 14:05 vs 14:10 (capture)


def test_a_report_counts_only_from_its_own_time(service):
    from sentinel.risk.timeline import score_timeline

    pkt = service.packet("img_000860")
    v = next(x for x in pkt.vehicles if x.track_id == "T0122")
    args = (service.repo.track("T0122"), 850, service.repo.geo, service.repo.zone_index, service.s)
    with_reports = score_timeline(v, args[0], pkt.reports, *args[1:])
    without = score_timeline(v, args[0], [], *args[1:])
    first_report = min(to_min(r.time) for r in pkt.reports)
    for (t, a, la), (_, b, lb) in zip(with_reports[:-1], without[:-1], strict=True):
        if t < first_report:
            assert (a, la) == (b, lb), t  # nothing had been reported yet
