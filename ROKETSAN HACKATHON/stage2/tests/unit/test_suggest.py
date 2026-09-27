"""Chat suggestions follow the evidence packet: different anomalies, the dragged vehicle, no numbers."""

import re

from sentinel.agent import suggest

IDS = re.compile(r"\b(?:img_\d+|[VTR]\d{1,4})\b")


def test_frame_suggestions_cover_different_anomalies(packet_860):
    s = suggest.frame_suggestions(packet_860)
    assert 1 <= len(s) <= suggest.LIMIT
    assert len({x.reason for x in s}) == len(s)  # one question per kind of anomaly
    text = " ".join(x.text for x in s)
    assert "R119" in text and "R125" in text  # both contradicted reports of the demo frame
    assert "T0122" in text  # the soonest-arriving vehicle (the truck in the demo)


def test_questions_carry_ids_but_no_numbers(packet_860):
    # a number in the question would enter the grounding bank and could be quoted back as "evidence"
    for x in suggest.frame_suggestions(packet_860, limit=20):
        assert not re.search(r"\d", IDS.sub("", x.text)), x.text


def test_focus_limits_questions_to_the_dragged_vehicle(packet_860):
    v = next(v for v in packet_860.vehicles if v.track_id == "T0122")
    s = suggest.frame_suggestions(packet_860, focus_ref=v.ref)
    assert s and all(v.ref in x.refs for x in s)
    assert len(s) > 1  # every anomaly of that vehicle, not just one


def test_followups_skip_asked_and_prefer_ids_in_the_answer(packet_860):
    base = suggest.frame_suggestions(packet_860, limit=8)
    asked = [base[0].text]
    out = suggest.followups(base, "R125 12:35'te bu noktada araç yoktu.", asked)
    assert base[0].text not in [x.text for x in out]
    assert "R125" in out[0].refs


def test_general_suggestions_start_with_the_most_urgent_frame(service):
    rows = service.triage()
    top = next(r for r in rows if not r.decision and r.level.value in ("KRİTİK", "YÜKSEK"))
    s = suggest.general_suggestions(rows)
    assert top.image_id in s[0].text


def test_followups_skip_a_question_asked_in_other_words(packet_860):
    v = next(v for v in packet_860.vehicles if v.track_id == "T0122")
    base = suggest.frame_suggestions(packet_860, focus_ref=v.ref, limit=8)
    eta_q = next(x.text for x in base if x.reason == "kısa ETA")
    out = suggest.followups(base, "", ["Bu araç üsse ne zaman ulaşır, hangi yönden geliyor?"], v.ref)
    assert eta_q not in [x.text for x in out]
    # the same words about a different report are a different question
    assert not suggest._same_question(
        "R119 raporu neden kanıtla çelişiyor?", "R125 raporu neden kanıtla çelişiyor?"
    )


def test_two_vehicles_get_questions_that_connect_them(packet_860):
    a, b = [suggest.CtxVehicle(packet_860, v) for v in packet_860.vehicles if v.track_id][:2]
    s = suggest.context_suggestions([a, b])
    assert s and "birlikte hareket" in {x.reason for x in s}
    assert all({a.name, b.name, a.v.ref, b.v.ref} & set(IDS.findall(x.text)) for x in s)  # about these two
    for x in s:
        assert not re.search(r"\d", IDS.sub("", x.text)), x.text


def test_two_frames_of_one_zone_ask_what_changed(service):
    p = service.packet("img_000860")
    other = next(
        m.image_id
        for m in service.repo.frames()
        if m.image_id != p.image_id and service.packet(m.image_id).frame.zone == p.frame.zone
    )
    s = suggest.context_suggestions([suggest.CtxFrame(p), suggest.CtxFrame(service.packet(other))])
    reasons = {x.reason for x in s}
    assert {"karşılaştırma", "aynı bölge"} <= reasons


def test_vehicle_that_drove_through_another_frames_zone(service):
    # a question is offered only when the vehicle's own track passed that frame's zone
    for m in service.repo.frames():
        for v in service.packet(m.image_id).vehicles:
            passed = set(v.kinematics.zones_passed) if v.kinematics else set()
            other = next(
                (
                    f.image_id
                    for f in service.repo.frames()
                    if f.image_id != m.image_id and service.packet(f.image_id).frame.zone in passed
                ),
                None,
            )
            if other:
                items = [
                    suggest.CtxVehicle(service.packet(m.image_id), v),
                    suggest.CtxFrame(service.packet(other)),
                ]
                assert "bölgeden geçti" in {x.reason for x in suggest.context_suggestions(items)}
                return
    raise AssertionError("veride başka karenin bölgesinden geçen araç bulunamadı")
