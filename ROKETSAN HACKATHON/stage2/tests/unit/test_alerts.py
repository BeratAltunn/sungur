"""Critical cards: pending KRİTİK frames only, facts straight from the packet, no numbers in the questions."""

import re

from sentinel.agent.alerts import critical_cards
from sentinel.domain.models import OperatorDecision, RiskLevel

IDS = re.compile(r"\b(?:img_\d+|[VTR]\d{1,4})\b")


def test_demo_frame_card_has_the_reasons(service):
    # decisions recorded by other tests share the log: judge the card, not the decision state
    rows = [r.model_copy(update={"decision": None}) for r in service.triage()]
    cards = critical_cards(rows, service.packet)
    c = next(c for c in cards if c.image_id == "img_000860")
    facts = " ".join(c.facts)
    assert "R119" in facts and "R125" in facts and "konvoy" in facts
    assert c.eta_min is not None and "T0122" in (c.eta_vehicle or "")  # the truck arrives first
    assert 1 <= len(c.questions) <= 3 and len(c.facts) <= 3
    for q in c.questions:
        assert not re.search(r"\d", IDS.sub("", q.text)), q.text


def test_only_pending_kritik_frames_in_queue_order(service):
    rows = [r.model_copy(update={"decision": None}) for r in service.triage()]
    kritik = [r.image_id for r in rows if r.level == RiskLevel.KRITIK and r.decision is None]
    assert [c.image_id for c in critical_cards(rows, service.packet)] == kritik
    # a decision takes the frame off the cards
    d = OperatorDecision(
        decision_id="d1", run_id="r1", image_id=kritik[0], action="approve", at="2026-09-26T12:00:00"
    )
    decided = [r.model_copy(update={"decision": d}) if r.image_id == kritik[0] else r for r in rows]
    assert kritik[0] not in [c.image_id for c in critical_cards(decided, service.packet)]
