"""Oracle detector + MockLLM: every frame runs cleanly through the service facade."""

import json

import pytest

from sentinel.domain.models import RiskLevel
from sentinel.interfaces.cli import main as cli_main


def test_all_40_frames_evaluate_with_grounded_briefs(service):
    for meta in service.repo.frames():
        res = service.evaluate(meta.image_id)
        assert res.grounding.passed, (meta.image_id, res.grounding)
        assert res.brief.risk_level.rank >= res.packet.risk.level.rank - 1
        if res.packet.risk.floor_level:
            assert res.brief.risk_level.rank >= res.packet.risk.floor_level.rank


def test_trace_has_all_steps(service):
    res = service.evaluate("img_000860")
    steps = [r["step"] for r in service.trace(res.run_id)]
    assert steps[:5] == ["1_tespit", "2_koordinat", "3_eşleme_kinematik", "4_raporlar", "5_risk"]
    assert steps[5].startswith("6_")


def test_triage_puts_demo_frame_first(service):
    rows = service.triage()
    assert len(rows) == 40
    assert rows[0].image_id == "img_000860"
    assert [r.level.rank for r in rows] == sorted((r.level.rank for r in rows), reverse=True)


def test_decisions_are_append_only_with_undo(service):
    res = service.evaluate("img_000860")
    service.record_decision(res.run_id, "img_000860", "approve")
    with pytest.raises(ValueError):
        service.record_decision(res.run_id, "img_000860", "override", RiskLevel.YUKSEK, "")
    service.record_decision(res.run_id, "img_000860", "override", RiskLevel.YUKSEK, "konvoy dost birlik")
    assert service.decisions.current("img_000860").action == "override"
    service.record_decision(res.run_id, "img_000860", "undo")
    assert service.decisions.current("img_000860").action == "approve"
    assert len([d for d in service.decisions.all() if d.image_id == "img_000860"]) >= 3


def test_service_lookups(service):
    tv = service.get_track("T0122")
    assert tv.kinematics.t_now == "14:10"
    near = service.tracks_near(39.9253, 32.8718, "14:10", 200)
    assert "T0122" in {s.track_id for s in near}
    assert service.find_reports(zone="Dogu Yolu")
    assert service.health()["data"]["frames"] == 40


def test_cli_evaluate_json(capsys, monkeypatch, settings):
    monkeypatch.setenv("SENTINEL_LLM", "mock")
    monkeypatch.setenv("SENTINEL_DETECTOR", "oracle")
    assert cli_main(["evaluate", "img_000860", "--json", "--no-llm"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["brief"]["risk_level"] == "KRİTİK"
