"""Report-verification rules that feed the intent dimension: class check, low-confidence classes, identity
tie and absence-based contradictions."""

from __future__ import annotations

from sentinel.domain.models import VehicleEvidence, Verdict
from sentinel.reports.relevance import FrameContext


def _ctx(repo, image_id: str, **kw) -> FrameContext:
    m = repo.meta[image_id]
    return FrameContext(
        image_id=image_id,
        capture_min=m.capture_min,
        zone="",
        center=(0.0, 0.0),
        half_diag_m=0.0,
        **kw,
    )


def _verify(pipeline, repo, rid: str, ctx: FrameContext):
    return pipeline.verifier.verify(repo.report(rid), pipeline.claims[rid], ctx)


def test_class_mismatch_needs_every_vehicle_at_the_point_classified(pipeline, repo):
    # R042 (13:40, "yüklü kamyon park halinde"): T0126, T0122 and T0206 are at the point
    near = {"T0126", "T0122", "T0206"}
    assert near <= {s.track_id for s in repo.tracks_near(39.95238, 32.90158, 13 * 60 + 40, 200)}
    partial = _ctx(repo, "img_001733", labels_by_track={"T0126": "car", "T0206": "car"})
    r = _verify(pipeline, repo, "R042", partial)  # T0122 may be the truck: neither contradicted nor confirmed
    assert r.verdict == Verdict.DOGRULANAMAZ and "teyit edilemedi" in r.reason
    all_cars = _ctx(repo, "img_001733", labels_by_track=dict.fromkeys(near, "car"))
    r = _verify(pipeline, repo, "R042", all_cars)
    assert r.verdict == Verdict.CELISIYOR and "T0122 otomobil" in r.reason
    truck = _ctx(repo, "img_001733", labels_by_track={"T0126": "car", "T0122": "truck"})
    assert _verify(pipeline, repo, "R042", truck).verdict == Verdict.DOGRULANDI


def test_low_confidence_box_does_not_decide_the_class(pipeline):
    def v(label: str, conf: float) -> VehicleEvidence:
        return VehicleEvidence(
            ref="V1",
            det_id="d",
            label=label,
            conf=conf,
            bbox=(0, 0, 1, 1),
            lat=0,
            lon=0,
            d_base_m=0,
            direction="K",
        )

    tau = pipeline.s.detector.tau_op
    assert pipeline._class_of(v("truck", tau - 0.01), {}) == "unknown"
    assert pipeline._class_of(v("truck", tau), {}) == "truck"
    weak = v("car", 0.1).model_copy(update={"track_id": "T1"})
    assert pipeline._class_of(weak, {"T1": ("truck", 0.9)}) == "truck"  # known from an earlier frame


def test_classes_never_come_from_a_later_frame(pipeline, repo, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(pipeline, "_frame_classes", lambda i: seen.append(i) or {})
    t = repo.meta["img_000860"].capture_min
    pipeline._known_classes("img_000860", [])
    assert seen and all(repo.meta[i].capture_min <= t for i in seen)
    assert len(seen) == sum(m.capture_min <= t for m in repo.frames()) - 1


def test_friendly_arrival_claim_only_marks_approaching_vehicles(packet_860):
    r = next(r for r in packet_860.reports if r.report_id == "R119")
    assert r.verdict == Verdict.CELISIYOR
    approaching = {v.track_id for v in packet_860.vehicles if v.kinematics and v.kinematics.approaching}
    in_frame = {v.track_id for v in packet_860.vehicles if v.track_id}
    assert "T0122" in r.related_tracks
    assert set(r.related_tracks) & in_frame <= approaching  # "üsse gelen": parked or leaving ones are not it
    for v in packet_860.vehicles:
        if any(f.code == "identity_contradicted" for f in v.factors):
            assert v.track_id in approaching


def test_empty_point_is_not_a_contradiction_without_a_subject_in_the_frame(pipeline, repo):
    # R075 (09:35, "3 kamyon"): nobody at the point; in a frame whose vehicles never go there it stays open
    r = _verify(pipeline, repo, "R075", _ctx(repo, "img_008333"))
    assert r.verdict == Verdict.DOGRULANAMAZ and "karşı-kanıt yok" in r.reason
    # the organiser's 12:35 case keeps its subject: T0122 is in img_000860 and reaches the point later
    p = pipeline.evaluate("img_000860")
    r1235 = next(r for r in p.reports if r.report_id == "R125")
    assert r1235.verdict == Verdict.CELISIYOR and "T0122" in r1235.reason


def test_no_report_is_confirmed_in_one_frame_and_contradicted_in_another(pipeline, repo):
    verdicts: dict[str, set[Verdict]] = {}
    for image_id in repo.meta:
        for r in pipeline.evaluate(image_id).reports:
            verdicts.setdefault(r.report_id, set()).add(r.verdict)
    assert not [rid for rid, v in verdicts.items() if {Verdict.DOGRULANDI, Verdict.CELISIYOR} <= v]
