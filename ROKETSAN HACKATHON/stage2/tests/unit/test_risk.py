from sentinel.config import RiskCfg
from sentinel.domain.models import RiskLevel
from sentinel.risk.features import dimension_score
from sentinel.risk.scoring import band, matrix_level, opportunity_band

D, M, Y, K = RiskLevel.DUSUK, RiskLevel.ORTA, RiskLevel.YUKSEK, RiskLevel.KRITIK


def test_matrix_needs_all_three_elements():
    assert matrix_level(Y, Y, Y) == K
    assert matrix_level(Y, Y, M) == matrix_level(M, Y, Y) == matrix_level(Y, M, Y) == Y
    assert matrix_level(M, M, M) == matrix_level(Y, M, M) == M
    # one element missing: the threat cannot materialise, at most ORTA
    assert matrix_level(D, Y, Y) == matrix_level(Y, D, Y) == matrix_level(Y, Y, D) == M
    assert matrix_level(D, M, M) == D
    assert matrix_level(D, D, Y) == matrix_level(D, D, D) == D


def test_bands():
    cfg = RiskCfg()
    assert [band(s, cfg.capability_bands) for s in (20, 50, 80)] == [D, M, Y]
    assert [band(s, cfg.intent_bands) for s in (20, 45, 70, 95)] == [D, M, Y, Y]
    assert [opportunity_band(m, cfg) for m in (1600, 2700, 5400)] == [Y, M, D]


def _vehicle(label="car", conf=0.9, d_m=1600, eta=None, codes=(), bands=(M, Y, M)):
    from sentinel.domain.models import Kinematics, RiskFactor, ThreatDimension, ThreatProfile, VehicleEvidence

    k = None
    if eta is not None:
        k = Kinematics(
            track_id="T1", t_now="12:00", d_now_m=d_m, d_start_m=d_m + 3000, d_change_m=3000, closing_mps=5,
            align_cos=1, speed_now_mps=5, speed_mean_mps=5, speed_max_mps=5, path_m=3000, heading_deg=0,
            heading_dir="K", stops=[], stop_total_min=0, stop_and_go=False, approaching=True, leaving=False,
            eta_min=eta, zones_passed=[], window=("10:00", "12:00"), d_series=[],
        )  # fmt: skip
    v = VehicleEvidence(
        ref="V1", det_id="d", label=label, conf=conf, bbox=(0, 0, 1, 1), lat=0, lon=0, d_base_m=d_m,
        direction="K", track_id="T1" if k else None, kinematics=k, class_label=label if conf >= 0.4 else "unknown",
        factors=[RiskFactor(code=c, label=c, points=0) for c in codes],
    )  # fmt: skip
    t = ThreatProfile(
        capability=ThreatDimension(score=0, band=bands[0]),
        opportunity=ThreatDimension(score=0, band=bands[1]),
        intent=ThreatDimension(score=0, band=bands[2]),
        matrix_level=matrix_level(*bands),
    )
    return v, t


def test_critical_floor_needs_a_heavy_vehicle_or_intent_not_just_a_convoy():
    from sentinel.risk.floors import floor_level

    cfg = RiskCfg()
    car_convoy = _vehicle("car", eta=5, codes=("convoy", "approaching"), bands=(Y, Y, M))
    assert floor_level(*car_convoy, [], cfg)[0] == Y  # potential threat, not KRİTİK
    truck = _vehicle("truck", eta=5, codes=("approaching",), bands=(Y, Y, M))
    lv, why = floor_level(*truck, [], cfg)
    assert lv == K and "ağır araç" in why[0]
    weak_truck = _vehicle("truck", conf=0.14, eta=5, codes=("approaching",), bands=(M, Y, M))
    assert floor_level(*weak_truck, [], cfg)[0] is None  # class not confirmed
    deceiving_car = _vehicle("car", eta=5, codes=("approaching", "identity_contradicted"), bands=(D, Y, Y))
    assert floor_level(*deceiving_car, ["çelişen kimlik iddiası"], cfg)[0] == K
    assert floor_level(*_vehicle("truck", eta=12, bands=(Y, Y, M)), [], cfg)[0] == Y  # ETA too long


def test_high_floors():
    from sentinel.risk.floors import floor_level

    cfg = RiskCfg()
    # deception close by, whatever the class (the matrix alone gives ORTA)
    v, t = _vehicle("car", codes=("identity_contradicted",), bands=(D, Y, Y))
    assert t.matrix_level == M and floor_level(v, t, ["çelişen kimlik iddiası"], cfg)[0] == Y
    # potential threat: unknown intent is not absent intent, but leaving is exculpatory
    assert floor_level(*_vehicle("truck", bands=(Y, Y, D)), [], cfg)[0] == Y
    assert floor_level(*_vehicle("truck", conf=0.5, codes=("leaving",), bands=(Y, Y, D)), [], cfg)[0] is None
    # confident untracked vehicle close to the base
    assert floor_level(*_vehicle("car", conf=0.7, bands=(D, Y, M)), [], cfg)[0] == Y
    assert floor_level(*_vehicle("car", conf=0.5, bands=(D, Y, M)), [], cfg)[0] is None


def test_demo_frame_is_critical_with_floor_and_convoy(packet_860):
    r = packet_860.risk
    assert r.level == K
    assert r.floor_level == K
    convoy = {v.track_id for v in packet_860.vehicles if any(f.code == "convoy" for f in v.factors)}
    assert {"T0122", "T0032", "T0192", "T0092"} <= convoy
    t = next(v for v in packet_860.vehicles if v.track_id == "T0122").threat
    assert (t.capability.band, t.opportunity.band, t.intent.band) == (Y, Y, Y)


def test_factors_explain_every_dimension(packet_860):
    for v in packet_860.vehicles:
        t = v.threat
        assert t is not None and all(f.label and f.dimension for f in v.factors)
        assert t.capability.score == dimension_score(v.factors, "yetenek")
        assert t.opportunity.score == dimension_score(v.factors, "firsat")
        assert t.intent.score == dimension_score(v.factors, "niyet")
        assert v.level.rank >= t.matrix_level.rank
        assert v.level.rank == max(t.matrix_level.rank, t.floor_level.rank if t.floor_level else 0)


def test_approach_is_intent_not_opportunity_and_stop_and_go_is_not_scored(pipeline, repo):
    for image_id in repo.meta:
        for v in pipeline.evaluate(image_id).vehicles:
            dims = {f.code: f.dimension for f in v.factors}
            assert dims.get("approaching", "niyet") == "niyet"
            assert "stop_and_go" not in dims and "eta_short" not in dims and "eta_mid" not in dims


def test_leaving_vehicle_gets_negative_factor(pipeline, repo):
    found = False
    for image_id in repo.meta:
        for v in pipeline.evaluate(image_id).vehicles:
            if v.kinematics and v.kinematics.leaving:
                assert any(f.code == "leaving" and f.points < 0 and f.dimension == "niyet" for f in v.factors)
                found = True
    assert found


def test_frame_level_is_the_highest_vehicle_level(pipeline, repo):
    for image_id in list(repo.meta)[:10]:
        p = pipeline.evaluate(image_id)
        assert p.risk.level == max((v.level for v in p.vehicles), key=lambda lv: lv.rank, default=D)


def test_not_every_frame_alarms(pipeline, repo):
    levels = [pipeline.evaluate(i).risk.level for i in repo.meta]
    assert D in levels and M in levels
    assert sum(lv == K for lv in levels) < len(levels) / 3


# ---------------------------------------------------------------- calibration
def test_kappa_and_consensus_and_compare(tmp_path):
    from sentinel.risk.calibration import LabelStore, cohen_kappa, compare, consensus

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
