"""Matching + kinematics golden numbers (T0122 in img_000860) and the trap tracks."""

import pytest

from sentinel.domain.models import to_min
from sentinel.geo.georef import GeoReferencer
from sentinel.tracking.kinematics import compute_kinematics


def test_every_track_has_25_points(repo):
    assert len(repo.tracks) == 226
    assert {len(t.points) for t in repo.tracks.values()} == {25}


def test_t0122_matched_below_1m_second_candidate_t0032_about_41m(packet_860):
    v = next(v for v in packet_860.vehicles if v.track_id == "T0122")
    assert v.match_m < 1.0
    assert v.second_track_id == "T0032"
    assert v.margin_m == pytest.approx(41, abs=1.5)


def test_t0122_kinematics(repo, settings):
    tr = repo.track("T0122")
    t_now = to_min("14:10")
    k = compute_kinematics(tr, t_now, repo.geo, repo.zone_index, settings.tracking)
    d_1315 = dict(k.d_series)["13:15"]
    assert d_1315 / 1000 == pytest.approx(5.5, abs=0.05)
    assert k.d_now_m / 1000 == pytest.approx(1.6, abs=0.05)
    assert k.path_m / 1000 == pytest.approx(10.5, abs=0.05)
    assert k.closing_mps == pytest.approx(6.2, abs=0.1)
    assert k.eta_min == pytest.approx(4.4, abs=0.1)
    assert k.approaching and k.stop_and_go
    assert len(k.stops) == 3


def test_t0122_was_far_from_the_report_point_at_1235(repo):
    pos = repo.position("T0122", to_min("12:35"))
    d = float(repo.geo.distance_m(39.9253, 32.8718, *pos))
    assert d / 1000 == pytest.approx(5.6, abs=0.1)


def _trap_tracks(repo):
    """Tracks whose last point is 7–26 m outside the frame captured at that time."""
    traps = []
    for tid, tr in repo.tracks.items():
        last = tr.points[-1]
        frames = [m for m in repo.meta.values() if m.capture_min == last.t_min]
        g = min(
            (GeoReferencer(m) for m in frames),
            key=lambda g: float(repo.geo.distance_m(last.lat, last.lon, *g.center())),
        )
        if not g.contains(last.lat, last.lon):
            traps.append(tid)
    return traps


def test_every_track_ends_at_a_capture_time_and_20_are_traps(repo):
    captures = {m.capture_min for m in repo.meta.values()}
    assert all(t.t_end in captures for t in repo.tracks.values())
    assert len(_trap_tracks(repo)) == 20


def test_trap_tracks_are_never_matched(repo, pipeline):
    traps = set(_trap_tracks(repo))
    matched = set()
    for image_id in repo.meta:
        p = pipeline.evaluate(image_id)
        matched |= {v.track_id for v in p.vehicles if v.track_id}
        assert not (set(p.undetected_tracks) & traps), "tuzak track 'tespitsiz' sayılmamalı"
    assert not (matched & traps)
    assert len(matched) == 206
