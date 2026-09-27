"""Decision log: undo semantics and the measured handling time (frame opened → decision)."""

from sentinel.domain.models import OperatorDecision
from sentinel.observability.decisions import DecisionLog, decision_seconds, median_or_none


def _d(img: str, at: str, action: str = "approve") -> OperatorDecision:
    return OperatorDecision(decision_id="x", run_id="r", image_id=img, action=action, at=at)  # type: ignore[arg-type]


def test_undo_cancels_only_the_last_decision(tmp_path):
    log = DecisionLog(tmp_path)
    log.record("r", "img_1", "approve")
    log.record("r", "img_1", "escalate")
    log.record("r", "img_1", "undo")
    log.record("r", "img_2", "approve")
    log.record("r", "img_2", "undo")
    cur = log.current_all()
    assert cur["img_1"].action == "approve" and "img_2" not in cur
    assert log.current("img_1").action == "approve"


def test_handling_time_uses_last_opening_before_the_decision():
    decisions = {
        "img_1": _d("img_1", "2026-09-26T10:02:30+03:00"),
        "img_2": _d("img_2", "2026-09-26T10:10:00+03:00"),
        "img_3": _d("img_3", "2026-09-26T10:20:00+03:00"),  # decided without a logged opening
    }
    views = [
        ("img_1", "2026-09-26T09:00:00+03:00"),  # an older visit does not count
        ("img_1", "2026-09-26T10:01:00+03:00"),
        ("img_1", "2026-09-26T10:05:00+03:00"),  # after the decision: ignored
        ("img_2", "2026-09-26T10:09:15+03:00"),
    ]
    secs = decision_seconds(decisions, views)
    assert sorted(secs) == [45.0, 90.0]
    # Older decision lines were written without a UTC offset; they must still compare (read as local time).
    naive = {"img_9": _d("img_9", "2026-09-25T22:29:00")}
    assert decision_seconds(naive, [("img_9", "2026-09-26T01:00:00+03:00")]) == []  # opened later: ignored
    assert median_or_none(secs) == 67.5 and median_or_none([]) is None
