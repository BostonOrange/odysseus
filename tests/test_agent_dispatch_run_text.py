"""Unit tests for the shared run_agent_text loop-driver (agent-dispatch Phase A).

run_agent_text was extracted from task_scheduler._run_agent_loop; these pin its
contract — accumulate streamed deltas, grace-summarize when the model produces
no final text, and fall back to a sentinel.
"""
import asyncio
import json

import src.agent_dispatch as ad


def _sse(obj):
    return f"data: {json.dumps(obj)}"


def _run(**overrides):
    kwargs = dict(
        endpoint_url="http://x", model="m",
        system_prompt="sys", user_message="hi", headers={},
    )
    kwargs.update(overrides)
    return asyncio.run(ad.run_agent_text(**kwargs))


def test_accumulates_deltas(monkeypatch):
    async def fake_loop(**kwargs):
        yield _sse({"delta": "Hello "})
        yield _sse({"delta": "world"})
        yield "data: [DONE]"

    monkeypatch.setattr("src.agent_loop.stream_agent_loop", fake_loop)
    assert _run() == "Hello world"


def test_grace_summarizes_when_no_text(monkeypatch):
    async def fake_loop(**kwargs):
        yield _sse({"type": "tool_output", "tool": "bash", "stdout": "ran ok"})
        yield "data: [DONE]"

    async def fake_grace(candidates, messages, timeout):
        # the grace prompt should carry the captured tool output
        assert "ran ok" in messages[-1]["content"]
        return "summary of work"

    monkeypatch.setattr("src.agent_loop.stream_agent_loop", fake_loop)
    monkeypatch.setattr("src.llm_core.llm_call_async_with_fallback", fake_grace)
    monkeypatch.setattr("src.endpoint_resolver.resolve_utility_fallback_candidates", lambda owner=None: [])
    assert _run() == "summary of work"


def test_no_output_sentinel(monkeypatch):
    async def fake_loop(**kwargs):
        yield "data: [DONE]"

    async def fake_grace(candidates, messages, timeout):
        return ""

    monkeypatch.setattr("src.agent_loop.stream_agent_loop", fake_loop)
    monkeypatch.setattr("src.llm_core.llm_call_async_with_fallback", fake_grace)
    monkeypatch.setattr("src.endpoint_resolver.resolve_utility_fallback_candidates", lambda owner=None: [])
    assert _run() == "(no output)"


def test_passes_tool_filters_through(monkeypatch):
    seen = {}

    async def fake_loop(**kwargs):
        seen.update(kwargs)
        yield _sse({"delta": "ok"})
        yield "data: [DONE]"

    monkeypatch.setattr("src.agent_loop.stream_agent_loop", fake_loop)
    out = _run(disabled_tools={"bash"}, relevant_tools={"read_file"}, max_rounds=7, owner="alice")
    assert out == "ok"
    assert seen["disabled_tools"] == {"bash"}
    assert seen["relevant_tools"] == {"read_file"}
    assert seen["max_rounds"] == 7
    assert seen["owner"] == "alice"
