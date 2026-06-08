import asyncio
import src.email_labeling.thinking_classifier as tc


def test_extract_json_with_leading_thinking():
    raw = 'Let me reason... I think {"score": 2, "reason": "promo"} done'
    assert tc._extract_json_obj(raw) == {"score": 2, "reason": "promo"}


def test_extract_json_returns_none_when_truncated():
    raw = 'thinking... {"score": 2, "tags": ["work"'
    assert tc._extract_json_obj(raw) is None


def test_extract_json_skips_unparseable_first_brace():
    raw = '{not json} then {"ok": true}'
    assert tc._extract_json_obj(raw) == {"ok": True}


def test_classify_uses_first_pass(monkeypatch):
    seen = []

    async def fake(cands, messages, **kw):
        seen.append(kw)
        return '{"score": 1, "spam": false}'

    monkeypatch.setattr(tc, "llm_call_async_with_fallback", fake)
    out = asyncio.run(tc.classify_email_json(["c"], "prompt"))
    assert out == {"score": 1, "spam": False}
    assert len(seen) == 1
    assert "extra_body" not in seen[0]


def test_classify_retries_without_thinking(monkeypatch):
    seq = ['reasoning, no closing brace {"score": 3', '{"score": 3, "spam": false}']
    seen = []

    async def fake(cands, messages, **kw):
        seen.append(kw)
        return seq.pop(0)

    monkeypatch.setattr(tc, "llm_call_async_with_fallback", fake)
    out = asyncio.run(tc.classify_email_json(["c"], "prompt"))
    assert out == {"score": 3, "spam": False}
    assert seen[1]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


def test_classify_returns_none_when_both_fail(monkeypatch):
    async def fake(cands, messages, **kw):
        return "no json at all"

    monkeypatch.setattr(tc, "llm_call_async_with_fallback", fake)
    assert asyncio.run(tc.classify_email_json(["c"], "prompt")) is None


_ALLOWED = {"work", "marketing", "newsletter", "finance"}


def test_normalize_filters_unknown_and_aliases_promo():
    obj = {"score": "2", "tags": ["Promo", "work", "lego-football"], "spam": "true", "reason": "x" * 300}
    v = tc.normalize_verdict(obj, _ALLOWED)
    assert v["score"] == 2
    assert v["tags"] == ["marketing", "work"]
    assert v["spam"] is True
    assert len(v["reason"]) == 200


def test_normalize_bad_score_defaults_zero():
    assert tc.normalize_verdict({"score": "high"}, _ALLOWED)["score"] == 0


def test_normalize_string_tags():
    assert tc.normalize_verdict({"tags": "work"}, _ALLOWED)["tags"] == ["work"]
