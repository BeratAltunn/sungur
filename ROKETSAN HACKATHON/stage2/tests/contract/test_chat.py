"""Chat loop contract: tools are called, answers are grounded, failures degrade visibly."""

import json

import pytest

from sentinel.agent.chat import ChatAgent, ChatMessage
from sentinel.agent.llm import LLMError, LLMResponse
from sentinel.agent.tools import TOOL_SPECS, ChatTools, ToolError
from sentinel.service import SentinelService


class Scripted:
    """LLM stub: each step is either a tool call (name, args) or a final text."""

    model = "scripted"

    def __init__(self, *steps):
        self.steps = list(steps)
        self.seen: list[list[dict]] = []

    def chat(self, messages, *, json_mode=False, tools=None):
        self.seen.append(messages)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, tuple):
            name, args = step
            call = {"id": f"c{len(self.seen)}", "name": name, "arguments": json.dumps(args)}
            return LLMResponse(tool_calls=[call], model=self.model)
        return LLMResponse(content=step, model=self.model)


@pytest.fixture(scope="module")
def svc(settings):
    return SentinelService(settings, use_llm=False)


def agent(svc, llm):
    return ChatAgent(llm, ChatTools(svc), "sistem")


def test_tool_then_grounded_answer(svc):
    llm = Scripted(
        ("get_track", {"track_id": "T0122", "time": "12:35"}),
        "T0122 12:35'te Kuzey Yolu bölgesinde, üsse 6,0 km.",
    )
    turn = agent(svc, llm).ask("T0122 12:35'te neredeydi?")
    assert turn.grounded and turn.llm_calls == 2
    assert [c.name for c in turn.tool_calls] == ["get_track"]
    tool_msg = llm.seen[1][-1]
    assert tool_msg["role"] == "tool" and "zaman_cizelgesi" in tool_msg["content"]


def test_invented_number_gets_one_correction_then_is_flagged(svc):
    llm = Scripted(("get_track", {"track_id": "T0122"}), "Üsse 0,3 km.", "Üsse 0,3 km, ETA 1,1 dk.")
    turn = agent(svc, llm).ask("T0122 nerede?")
    assert not turn.grounded and any("0.3" in u for u in turn.unverified)
    assert "Cevabında araç çıktılarında olmayan" in llm.seen[2][-1]["content"]


def test_tool_error_is_reported_to_llm_not_raised(svc):
    llm = Scripted(("zone_summary", {"zone": "Mars"}), "Elimdeki kayıtlarda bu bölge yok.")
    turn = agent(svc, llm).ask("Mars bölgesinde ne oldu?")
    assert turn.tool_calls[0].error and "bilinmeyen bölge" in turn.tool_calls[0].error
    assert turn.grounded


def test_llm_outage_returns_message(svc):
    turn = agent(svc, Scripted(LLMError("503"))).ask("Durum?")
    assert turn.note == "llm_hata" and "ulaşılamıyor" in turn.answer


def test_frame_context_and_history_are_passed(svc):
    llm = Scripted("Tamam.")
    agent(svc, llm).ask(
        "Bu kamyon neden riskli?", [ChatMessage(role="user", content="önceki")], image_id="img_000860"
    )
    msgs = llm.seen[0]
    assert msgs[1]["content"] == "önceki" and msgs[-1]["content"].startswith("[Açık kare: img_000860]")


def test_dragged_vehicle_comes_after_the_frame_context(svc):
    llm = Scripted("Tamam.")
    agent(svc, llm).ask("Bu araç nereden geldi?", image_id="img_000860", focus="V4 · T0122")
    assert (
        llm.seen[0][-1]["content"]
        == "[Açık kare: img_000860]\n[Odak araç: V4 · T0122]\nBu araç nereden geldi?"
    )


def test_service_resolves_the_focus_track_and_adds_followups(settings):
    s = SentinelService(
        settings, llm=Scripted(("get_track", {"track_id": "T0122"}), "T0122 üsse yaklaşıyor.")
    )
    ref = next(v.ref for v in s.packet("img_000860").vehicles if v.track_id == "T0122")
    turn, _ = s.chat("Bu araç nereden geldi?", [], "img_000860", ref)
    user = [m for m in s.chat_agent.llm.seen[0] if m["role"] == "user"][-1]["content"]
    assert f"[Odak araç: {ref} · T0122]" in user  # the track comes from the packet, not the client
    assert turn.followups and all(ref in f.refs for f in turn.followups)
    # an unknown vehicle is dropped, like an unknown frame
    s2 = SentinelService(settings, llm=Scripted("Tamam."))
    s2.chat("Durum?", [], "img_000860", "V99")
    assert "Odak araç" not in s2.chat_agent.llm.seen[0][-1]["content"]


def test_tools_never_leak_absolute_coordinates(svc):
    tools = ChatTools(svc)
    out = json.dumps(
        [
            tools.call("analyze_image", {"image_id": "img_000860"}),
            tools.call("get_track", {"track_id": "T0122"}),
            tools.call("find_reports", {"t_from": "12:00", "t_to": "13:00"}),
            tools.call("zone_summary", {"zone": "Doğu Yolu"}),
        ],
        ensure_ascii=False,
    )
    assert "39.9" not in out and "32.8" not in out


def test_report_counts_come_from_the_tool(svc):
    out = ChatTools(svc).call(
        "find_reports", {"verdict": "ÇELİŞİYOR", "source": "official", "t_from": "12:00", "t_to": "13:00"}
    )
    assert out["toplam"] == len(out["raporlar"]) == out["kaynaklara_gore"]["official"]


def test_tool_specs_and_unknown_tool(svc):
    assert {s["function"]["name"] for s in TOOL_SPECS} == {
        "list_frames",
        "analyze_image",
        "get_track",
        "find_reports",
        "zone_summary",
    }
    with pytest.raises(ToolError):
        ChatTools(svc).call("rm_rf", {})
