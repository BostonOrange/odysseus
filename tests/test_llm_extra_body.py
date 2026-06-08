import asyncio
import httpx
from src import llm_core


def _resp(content):
    req = httpx.Request("POST", "http://test/v1/chat/completions")
    return httpx.Response(200, request=req, json={"choices": [{"message": {"content": content}}]})


def test_extra_body_merged_into_payload(monkeypatch):
    captured = {}

    class _FakeClient:
        async def post(self, url, headers=None, json=None, timeout=None):
            captured["payload"] = json
            return _resp('{"ok":true}')

    monkeypatch.setattr(llm_core, "_get_http_client", lambda: _FakeClient())
    out = asyncio.run(llm_core.llm_call_async(
        "http://test/v1", "qwen", [{"role": "user", "content": "hi"}],
        max_tokens=50, extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    ))
    assert out == '{"ok":true}'
    assert captured["payload"]["chat_template_kwargs"] == {"enable_thinking": False}


def test_no_extra_body_leaves_payload_clean(monkeypatch):
    captured = {}

    class _FakeClient:
        async def post(self, url, headers=None, json=None, timeout=None):
            captured["payload"] = json
            return _resp('{"ok":true}')

    monkeypatch.setattr(llm_core, "_get_http_client", lambda: _FakeClient())
    asyncio.run(llm_core.llm_call_async(
        "http://test/v1", "qwen", [{"role": "user", "content": "hi"}], max_tokens=50,
    ))
    assert "chat_template_kwargs" not in captured["payload"]
