from sentinel.config import RiskCfg
from sentinel.domain.models import RiskLevel
from sentinel.risk.scoring import level_for


def test_level_thresholds():
    cfg = RiskCfg()
    assert [level_for(s, cfg) for s in (0, 24, 25, 49, 50, 74, 75, 100)] == [
        RiskLevel.DUSUK,
        RiskLevel.DUSUK,
        RiskLevel.ORTA,
        RiskLevel.ORTA,
        RiskLevel.YUKSEK,
        RiskLevel.YUKSEK,
        RiskLevel.KRITIK,
        RiskLevel.KRITIK,
    ]


def test_demo_frame_is_critical_with_floor_and_convoy(packet_860):
    r = packet_860.risk
    assert r.level == RiskLevel.KRITIK
    assert r.floor_level == RiskLevel.KRITIK
    convoy = {v.track_id for v in packet_860.vehicles if any(f.code == "convoy" for f in v.factors)}
    assert {"T0122", "T0032", "T0192", "T0092"} <= convoy


def test_factors_explain_the_score(packet_860):
    for v in packet_860.vehicles:
        assert v.score == max(0, min(100, sum(f.points for f in v.factors)))
        assert all(f.label for f in v.factors)


def test_leaving_vehicle_gets_negative_factor(pipeline, repo):
    found = False
    for image_id in repo.meta:
        for v in pipeline.evaluate(image_id).vehicles:
            if v.kinematics and v.kinematics.leaving:
                assert any(f.code == "leaving" and f.points < 0 for f in v.factors)
                found = True
    assert found


def test_not_every_frame_alarms(pipeline, repo):
    levels = [pipeline.evaluate(i).risk.level for i in repo.meta]
    assert RiskLevel.DUSUK in levels and RiskLevel.ORTA in levels
    assert sum(lv == RiskLevel.KRITIK for lv in levels) < len(levels) / 3
