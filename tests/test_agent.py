# tests/test_agent.py
from datetime import datetime

from fakes import ScriptedModel, fake_tools

from lowass.agent import Agent
from lowass.config import ROOT, load

CFG = load(ROOT, "lowass.toml.sample")  # the sample is the tested config, not a local lowass.toml


def make(turns, **over):
    model, log = ScriptedModel(turns), []
    a = {**CFG.section("agent"), **over}
    return Agent(model, fake_tools(log), CFG.deny_regex(), a, CFG.section("prompts")), model, log


def texts(messages):
    return [b["text"] for m in messages for b in m["content"] if "text" in b]


def test_tool_loop_runs_read_and_blocks_write():
    ag, model, log = make([("tool", "search_tools", {"query": "jira"}),
                           ("tool", "call_tool", {"toolName": "customer-jira-jira_add_comment", "arguments": {}}),
                           ("text", "hotovo")])
    status = []
    assert ag.run("zkontroluj", "[10:00:00] Ja: ahoj", status.append) == "hotovo"
    assert log == [("search_tools", {"query": "jira"})]  # the write never reached the tool
    blocked = [b for m in model.calls[-1]["messages"] for b in m["content"] if "toolResult" in b]
    assert any("BLOCKED" in r["toolResult"]["content"][0]["text"] for r in blocked)
    assert len(status) == 1  # blocked call is not announced


def test_nothing_not_remembered_and_history_kept():
    ag, model, _ = make([("text", "NOTHING"), ("text", "odpoved"), ("text", "dalsi")])
    assert ag.run("auto", "ctx", remember=True) == "NOTHING"
    assert ag.history == []
    ag.run("otazka", "")
    assert texts(ag.history) == ["otazka", "odpoved"]  # clean pair, no tool traffic
    ag.run("druha", "")
    assert texts(model.calls[-1]["messages"])[:2] == ["otazka", "odpoved"]


def test_tool_traffic_is_not_kept_in_history():
    ag, _, log = make([("tool", "search_tools", {"query": "x"}), ("text", "a")])
    ag.run("q", "")
    assert log and texts(ag.history) == ["q", "a"]
    assert all("toolUse" not in b and "toolResult" not in b for m in ag.history for b in m["content"])


def test_step_limit_cancels_further_tools():
    n = int(CFG.section("agent")["max_steps"])
    turns = [("tool", "search_tools", {"query": str(i)}) for i in range(n + 1)] + [("text", "final")]
    ag, _, log = make(turns)
    assert ag.run("loop", "") == "final"
    assert len(log) == n  # the call beyond the limit was cancelled, not executed


def test_runaway_model_is_stopped():
    ag, _, log = make([("tool", "search_tools", {"query": "x"})] * 40)
    assert ag.run("loop", "").startswith("NEOVERENO")
    assert len(log) == ag.max_steps


def test_big_tool_result_is_truncated():
    ag, model, _ = make([("tool", "call_tool", {"toolName": "big-tool"}), ("text", "ok")], max_tool_chars=1000)
    ag.run("q", "")
    res = next(b for m in model.calls[-1]["messages"] for b in m["content"] if "toolResult" in b)
    text = res["toolResult"]["content"][0]["text"]
    assert len(text) < 1200 and "truncated" in text


def test_model_switch_is_used_for_next_call():
    ag, model, _ = make([("text", "a"), ("text", "b")])
    ag.run("x", "")
    ag.set_model("other.global.anthropic.claude-haiku-5-5")
    ag.run("y", "")
    assert [c["model_id"] for c in model.calls] == ["m", "other.global.anthropic.claude-haiku-5-5"]
    assert ag.model == "other.global.anthropic.claude-haiku-5-5"


def test_clear_wipes_history_and_drops_answer_in_flight():
    ag, model, _ = make([("text", "a1"), ("text", "a2")])
    ag.run("q1", "")
    assert len(ag.history) == 2
    ag.clear()
    assert ag.history == []
    ag.run("q2", "")
    assert all("q1" not in t for t in texts(model.calls[-1]["messages"]))
    # Clear pressed while a request runs: its answer must not come back into the fresh history
    ag2, model2, _ = make([("text", "late")])
    orig = model2.stream

    async def stream_and_clear(*a, **kw):
        ag2.clear()  # lock is held by the running request, so only the generation moves
        async for ev in orig(*a, **kw):
            yield ev

    model2.stream = stream_and_clear
    assert ag2.run("q", "") == "late" and ag2.history == []


def test_date_only_in_system_prompt_and_stable_across_calls():
    ag, model, _ = make([("text", "a"), ("text", "b")])
    ag.run("q1", "[10:00:00] Ja: ahoj")
    ag.run("q2", "[10:01:00] Ja: ahoj znovu")
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    for call in model.calls:
        assert today in call["system"]
        assert all(today not in t for t in texts(call["messages"]))
    assert model.calls[0]["system"] == model.calls[1]["system"]  # identical system prompt = stable cache prefix
