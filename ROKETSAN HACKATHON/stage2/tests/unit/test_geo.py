"""Golden numbers from the organizer's worked example + georef properties."""

import random

import pytest

from sentinel.geo.geodesy import compass8
from sentinel.geo.georef import GeoReferencer


def test_pixel_to_latlon_matches_organizer_example(repo):
    # The organizer's (756, 301) is in the official 960×540 frame of img_000860.
    g = GeoReferencer(repo.meta["img_000860"], width_px=960, height_px=540)
    lat, lon = g.pixel_to_latlon(756, 301)
    assert round(lat, 5) == 39.92531
    assert round(lon, 5) == 32.87183


@pytest.mark.parametrize("image_id", ["img_000860", "img_003839", "img_004530"])
def test_roundtrip_below_half_pixel(repo, image_id):
    g = GeoReferencer(repo.meta[image_id])
    rnd = random.Random(0)
    for _ in range(50):
        px, py = rnd.uniform(0, g.W), rnd.uniform(0, g.H)
        qx, qy = g.latlon_to_pixel(*g.pixel_to_latlon(px, py))
        assert abs(qx - px) < 0.5 and abs(qy - py) < 0.5


def test_frames_are_on_rings_and_sized_as_documented(repo):
    for meta in repo.meta.values():
        g = GeoReferencer(meta)
        w, _ = g.size_m()
        assert 100 < w < 400
        d = repo.zone_index.relation(*g.center()).d_m
        assert 1400 < d < 5600


def test_eight_zones_five_frames_each(repo):
    counts = {z: len(repo.frames(z)) for z in repo.zone_index.names()}
    assert len(counts) == 8 and set(counts.values()) == {5}


def test_compass8():
    assert [compass8(b) for b in (0, 20, 46, 90, 180, 270, 315, 359)] == [
        "K",
        "K",
        "KD",
        "D",
        "G",
        "B",
        "KB",
        "K",
    ]
