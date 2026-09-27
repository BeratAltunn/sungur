"""Shift simulation: queue discipline, measured-vs-assumed handling time, decision vs projected arrival."""

from types import SimpleNamespace

from sentinel.impact import HandlingTime, build_report, pick_handling_time, simulate


def test_fifo_vs_priority_single_operator():
    arrivals = [("a", 0.0), ("b", 1.0), ("c", 2.0)]
    fifo = simulate(arrivals, 5.0, None)
    assert fifo == {"a": (0.0, 5.0), "b": (5.0, 10.0), "c": (10.0, 15.0)}
    # c is the most urgent: it jumps b once the operator is free (non-preemptive).
    prio = simulate(arrivals, 5.0, {"c": 0, "b": 1, "a": 2})
    assert prio["a"] == (0.0, 5.0) and prio["c"] == (5.0, 10.0) and prio["b"] == (10.0, 15.0)
    # Idle operator waits for the next arrival.
    assert simulate([("x", 10.0)], 1.0, None) == {"x": (10.0, 11.0)}


def test_measurements_win_over_assumptions():
    assert pick_handling_time([], [], 6.0, 3) == HandlingTime(minutes=6.0, source="varsayım")
    assert pick_handling_time([], [4.0, 5.0, 9.0], 6.0, 3).source == "kronometre"
    ht = pick_handling_time([0.5, 1.5, 1.0], [4.0, 5.0, 9.0], 6.0, 3)
    assert ht.source == "ölçüm" and ht.minutes == 1.0 and ht.n == 3


def test_decision_compared_with_projected_arrival():
    def row(i, lv, t, eta):
        return SimpleNamespace(image_id=i, level=lv, zone="Z", capture_time=t, min_eta_min=eta)

    rows = [row("k", "KRİTİK", "14:10", 4.5), row("o", "ORTA", "14:00", None)]  # queue (risk) order
    r = build_report(
        rows, HandlingTime(minutes=6.0, source="varsayım"), HandlingTime(minutes=1.0, source="varsayım")
    )
    k = next(f for f in r.frames if f.image_id == "k")
    assert k.arrival_min == 14 * 60 + 10 + 4.5
    assert k.manual_done == 14 * 60 + 16 and k.system_done == 14 * 60 + 11  # FIFO: o first (14:00–14:06)
    assert (k.manual_before, k.system_before) == (False, True)
    assert next(f for f in r.frames if f.image_id == "o").manual_before is None  # nothing approaching
    assert r.summary.by_level["KRİTİK"].model_dump() == {
        "with_eta": 1,
        "manual_before": 0,
        "system_before": 1,
    }
    assert [f.image_id for f in r.frames] == ["o", "k"]  # capture order for the replay
