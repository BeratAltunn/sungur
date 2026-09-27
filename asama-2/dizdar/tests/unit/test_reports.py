"""Parser coverage + time-aware verification (the product's differentiator)."""

import pytest

from sentinel.domain.models import ClaimType, Verdict
from sentinel.reports.parser import ReportParser


@pytest.fixture(scope="module")
def claims(repo):
    return ReportParser(repo.zone_index.names()).parse_all(repo.reports)


def test_every_report_gets_a_claim_type(claims):
    assert len(claims) == 137
    assert not [c for c in claims.values() if ClaimType.UNKNOWN in c.types]


def test_coordinate_regex_catches_72(claims):
    assert sum(c.has_point for c in claims.values()) == 72


@pytest.mark.parametrize(
    "text, types, labels, count",
    [
        (
            "39.9253N 32.8718E cevresinde 1 agir arac bulunuyor, hareketleri olagan.",
            {ClaimType.NORMAL_BEHAVIOR},
            ["truck", "bus"],
            1,
        ),
        (
            "39.9307N 32.8380E yakininda 5 kamyonun durdugu bildirildi.",
            {ClaimType.STATIONARY, ClaimType.COUNT},
            ["truck"],
            5,
        ),
        (
            "39.92538N 32.87130E civarindan usse gelen otomobil bize bagli unsurdur, gelisi onceden bildirilmistir.",
            {ClaimType.FRIENDLY_ID, ClaimType.MOVING_TO_BASE},
            ["car"],
            None,
        ),
        (
            "Kuzeydogu Kavsagi bolgesinde agir arac hareketi yok, yalnizca binek araclar goruluyor.",
            {ClaimType.ZONE_NO_HEAVY},
            ["truck", "bus"],
            None,
        ),
        (
            "Planli tatbikat nedeniyle gun icinde bolgede dost unsurlar bulunacak.",
            {ClaimType.NOISE},
            [],
            None,
        ),
        (
            "39.9255N 32.9039E bolgesinde beklenmedik bir yogunluk var; olagan trafik 4 arac civaridir.",
            {ClaimType.DENSITY},
            [],
            None,
        ),
        ("Güneydoğu Yerleşimi bölgesinde trafik akışı normal seyrediyor.", {ClaimType.ZONE_NORMAL}, [], None),
    ],
)
def test_parse_examples(repo, text, types, labels, count):
    from sentinel.domain.models import FieldReport

    c = ReportParser(repo.zone_index.names()).parse(
        FieldReport(report_id="X", time="12:00", source="official", text=text)
    )
    assert set(c.types) == types
    assert c.vehicle_labels == labels
    assert c.count == count


def _report(repo, time, prefix):
    return next(r for r in repo.reports if r.time == time and r.text.startswith(prefix))


def test_1235_report_contradicted_in_frame_context(packet_860):
    r = next(r for r in packet_860.reports if r.time == "12:35" and "agir arac" in r.text)
    assert r.verdict == Verdict.CELISIYOR
    assert "T0122 5,6 km" in r.reason


def test_1225_friendly_id_contradicted_and_raises_risk(packet_860):
    r = next(r for r in packet_860.reports if r.time == "12:25" and r.identity_claim)
    assert r.verdict == Verdict.CELISIYOR
    assert "T0122" in r.related_tracks
    v = next(v for v in packet_860.vehicles if v.track_id == "T0122")
    assert any(f.code == "identity_contradicted" and f.points > 0 for f in v.factors)


def test_location_only_mode_would_accept_the_same_report(pipeline, repo):
    """Regression guard: the difference from location-only checking is intentional."""
    rep = _report(repo, "12:35", "39.9253N")
    claim = pipeline.claims[rep.report_id]
    assert pipeline.verifier.verify(rep, claim, time_aware=False).verdict == Verdict.DOGRULANDI
    assert pipeline.verifier.verify(rep, claim, time_aware=True).verdict == Verdict.CELISIYOR


def test_location_only_accepts_all_72_but_20_have_nobody_at_report_time(pipeline, repo):
    pts = [(r, pipeline.claims[r.report_id]) for r in repo.reports if pipeline.claims[r.report_id].has_point]
    assert all(pipeline.verifier.verify(r, c, time_aware=False).verdict == Verdict.DOGRULANDI for r, c in pts)
    nobody = [r for r, c in pts if not repo.tracks_near(c.lat, c.lon, r.t_min, 200)]
    assert len(nobody) == 20


def test_absence_of_evidence_is_not_contradiction(pipeline, repo):
    """A contradiction always names positive counter-evidence (a track elsewhere or a mismatch)."""
    for r in repo.reports:
        c = pipeline.claims[r.report_id]
        v = pipeline.verifier.verify(r, c)
        if v.verdict == Verdict.CELISIYOR:
            assert any(ch.isdigit() for ch in v.reason) and ("T0" in v.reason), v.reason


def test_noise_is_irrelevant(pipeline, repo):
    r = _report(repo, "08:45", "Hava acik")
    assert pipeline.verifier.verify(r, pipeline.claims[r.report_id]).verdict == Verdict.ILGISIZ
