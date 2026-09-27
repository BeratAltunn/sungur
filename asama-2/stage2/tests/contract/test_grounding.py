"""LLM output contract: schema + grounding + level rules, and the analyst's degradation path."""

import json

from sentinel.agent import grounding
from sentinel.agent.analyst import Analyst
from sentinel.agent.llm import CachedLLM, LLMError, MockLLM, default_mock_responder, extract_packet
from sentinel.agent.masking import mask_packet
from sentinel.agent.template import template_brief
from sentinel.domain.models import RiskLevel, Verdict
from sentinel.observability.trace import Tracer


def _masked(settings, packet):
    return mask_packet(packet, Analyst(None, settings).constants())


def test_template_briefs_pass_grounding_on_all_frames(settings, pipeline, repo):
    for image_id in repo.meta:
        p = pipeline.evaluate(image_id)
        g = grounding.check(template_brief(p), p, _masked(settings, p))
        assert g.passed, (image_id, g)


def test_invented_number_is_caught(settings, packet_860):
    b = template_brief(packet_860)
    b.headline = "Kamyon üsse 0,9 km'de, ETA ~2,3 dk."
    g = grounding.check(b, packet_860, _masked(settings, packet_860))
    assert not g.passed and any("2.3" in f for f in g.failed)


def test_unknown_id_and_time_are_caught(settings, packet_860):
    b = template_brief(packet_860)
    b.key_findings[0].statement = "T9999 07:05'te görüldü."
    g = grounding.check(b, packet_860, _masked(settings, packet_860))
    assert "T9999" in g.unknown_refs and any("07:05" in f for f in g.failed)


def test_changed_report_verdict_is_caught(settings, packet_860):
    b = template_brief(packet_860)
    ra = next(r for r in b.report_assessment if r.verdict == Verdict.CELISIYOR)
    ra.verdict = Verdict.DOGRULANDI
    assert not grounding.check(b, packet_860, _masked(settings, packet_860)).passed


def test_level_below_floor_or_without_rationale_is_rejected(settings, packet_860):
    m = _masked(settings, packet_860)
    b = template_brief(packet_860)
    b.risk_level = RiskLevel.YUKSEK  # 1 step, but below the KRİTİK floor
    b.level_rationale = "gerekçe"
    assert not grounding.check(b, packet_860, m).level_ok
    assert grounding.clamp_level(RiskLevel.DUSUK, packet_860) == RiskLevel.KRITIK


def _analyst(settings, responder):
    return Analyst(MockLLM(responder), settings)


def test_mock_llm_brief_is_accepted(settings, packet_860):
    out = _analyst(settings, None).brief(packet_860, Tracer(None, "t"))
    assert out.source == "llm" and out.grounding.passed


def test_hallucinating_llm_gets_one_retry_then_template(settings, packet_860):
    calls = []

    def bad(messages, json_mode, tools):
        calls.append(1)
        d = json.loads(default_mock_responder(messages, json_mode, tools))
        d["headline"] = "Araç üsse 0,4 km'de, ETA 1,1 dk."
        return json.dumps(d, ensure_ascii=False)

    out = _analyst(settings, bad).brief(packet_860, Tracer(None, "t"))
    assert len(calls) == 2
    assert out.source == "template" and out.grounding.passed
    assert out.brief.risk_level == RiskLevel.KRITIK


def test_llm_fixed_on_retry_is_accepted(settings, packet_860):
    calls = []

    def flaky(messages, json_mode, tools):
        calls.append(1)
        d = json.loads(default_mock_responder(messages, json_mode, tools))
        if len(calls) == 1:
            d["headline"] = "ETA 1,1 dk."
        return json.dumps(d, ensure_ascii=False)

    out = _analyst(settings, flaky).brief(packet_860, Tracer(None, "t"))
    assert out.source == "llm" and len(calls) == 2


def test_cache_replays_the_correction_round(settings, packet_860, tmp_path):
    # a brief that passed only after the correction round must also open from cache (demo previews)
    calls = []

    def flaky(messages, json_mode, tools):
        calls.append(1)
        d = json.loads(default_mock_responder(messages, json_mode, tools))
        if len(calls) == 1:
            d["headline"] = "ETA 1,1 dk."
        return json.dumps(d, ensure_ascii=False)

    analyst = Analyst(CachedLLM(MockLLM(flaky), tmp_path, "ns"), settings)
    assert analyst.brief(packet_860, Tracer(None, "t")).source == "llm"
    out = analyst.brief(packet_860, Tracer(None, "t"), cache_only=True)
    assert out.source == "llm_cache" and out.grounding.passed and len(calls) == 2


def test_llm_outage_degrades_to_template(settings, packet_860):
    def down(messages, json_mode, tools):
        raise LLMError("timeout")

    out = _analyst(settings, down).brief(packet_860, Tracer(None, "t"))
    assert out.source == "template" and "erişilemedi" in (out.note or "")


def test_non_json_output_is_handled(settings, packet_860):
    out = _analyst(settings, lambda m, j, t: "üzgünüm, yapamam").brief(packet_860, Tracer(None, "t"))
    assert out.source == "template"


def test_llm_never_sees_absolute_coordinates(settings, packet_860):
    llm = MockLLM()
    Analyst(llm, settings).brief(packet_860, Tracer(None, "t"))
    user_msg = llm.calls[0][-1]["content"]
    assert "39.92" not in user_msg and "32.87" not in user_msg
    assert extract_packet(llm.calls[0])["kare"]["id"] == "img_000860"


def test_free_text_may_not_restate_a_verdict_differently(settings, packet_860):
    m = _masked(settings, packet_860)
    b = template_brief(packet_860)
    rid = next(r.report_id for r in packet_860.reports if r.verdict == Verdict.CELISIYOR)
    b.key_findings[0].statement = f"{rid} raporu saha tarafından doğrulandı."
    g = grounding.check(b, packet_860, m)
    assert any(rid in f for f in g.failed)
    b.key_findings[0].statement = f"{rid} raporu kanıtla çelişiyor."
    assert grounding.check(b, packet_860, m).passed


def test_package_names_the_shortest_eta_vehicle(settings, packet_860, pipeline):
    # the headline leads with this vehicle; the code picks it so the LLM never compares ETAs
    first = _masked(settings, packet_860)["risk"]["en_kisa_eta"]
    etas = [v for v in _masked(settings, packet_860)["araclar"] if v.get("yaklasiyor") and v.get("eta_dk")]
    assert first["eta_dk"] == min(v["eta_dk"] for v in etas)
    assert next(v for v in etas if v["ref"] == first["ref"])["track"] == "T0122"  # oracle: class unknown
    calm = pipeline.evaluate("img_001733")  # contrast frame: nothing approaches
    assert _masked(settings, calm)["risk"]["en_kisa_eta"] is None
