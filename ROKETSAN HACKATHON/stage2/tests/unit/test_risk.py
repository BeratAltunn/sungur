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


# ---------------------------------------------------------------- calibration
def test_kappa_and_consensus_and_compare(tmp_path):
    from sentinel.risk.calibration import LabelStore, cohen_kappa, compare, consensus

    D, M, Y, K = RiskLevel.DUSUK, RiskLevel.ORTA, RiskLevel.YUKSEK, RiskLevel.KRITIK
    assert cohen_kappa([D, M, Y, K], [D, M, Y, K]) == 1.0
    assert cohen_kappa([D, D, K, K], [K, K, D, D]) < 0

    store = LabelStore(tmp_path)
    store.add("a", "Ayşe", M)
    store.add("a", "ayse", Y)  # same labeler (normalised), latest wins
    store.add("a", "mehmet", K)
    store.add("b", "mehmet", D)
    labels = store.latest()
    assert labels["ayse"]["a"].level == Y
    assert consensus(labels) == {"a": K, "b": D}  # disagreement → higher level

    m = compare({"a": D, "b": Y}, {"a": K, "b": D})
    assert m.missed_threats == ["a"] and m.false_alarms == ["b"]
    assert m.high_recall == 0.0 and m.false_alarm_rate == 1.0


def test_sensitivity_rescoring_does_not_mutate_packets(pipeline, repo):
    from sentinel.config import RiskCfg
    from sentinel.risk.calibration import levels_for, sensitivity

    packets = [pipeline.evaluate(i) for i in list(repo.meta)[:6]]
    before = [v.score for p in packets for v in p.vehicles]
    cfg = RiskCfg()
    assert levels_for(packets, cfg) == {p.image_id: p.risk.level for p in packets}
    rows = sensitivity(packets, cfg)
    assert {r["weight"] for r in rows} == set(cfg.weights.model_dump())
    assert [v.score for p in packets for v in p.vehicles] == before
