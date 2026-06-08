# Plan 1 — Reliable Thinking Classifier (of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the email urgency classifier reliably return JSON even when the local model reasons, fixing the "model returned no JSON" failure without disabling reasoning.

**Architecture:** Add a generic `extra_body` passthrough to the async LLM helper, then a small `email_labeling` module that (1) calls the model with a generous token budget, (2) extracts the first balanced JSON object from `content`/`reasoning_content`, and (3) retries once with thinking disabled. Wire the existing classifier to it.

**Tech Stack:** Python 3.12, httpx, pytest (`asyncio_mode = "auto"`).

**Critical constraints (verified live, 2026-06-08):**
- `response_format` / `json_schema` grammars **crash this llama.cpp build** — DO NOT use them.
- The serve defaults to thinking on; llama.cpp returns reasoning in `reasoning_content` and leaves `content` empty until `</think>`. `llm_call_async` already returns `content or reasoning_content`, so a generous `max_tokens` + tolerant parse is the fix.
- `chat_template_kwargs:{"enable_thinking":false}` is verified to return clean JSON and is the safe retry lever.

**Do not run or restart the local llama serve during this plan. All tasks are verifiable with `pytest` alone.**

---

## File Structure

- **Modify** `src/llm_core.py` — add `extra_body` passthrough to `llm_call_async`.
- **Create** `src/email_labeling/__init__.py` — empty package marker.
- **Create** `src/email_labeling/thinking_classifier.py` — `classify_email_json`, `_extract_json_obj`, `normalize_verdict`.
- **Modify** `src/builtin_actions.py:1654-1699` — call the new classifier instead of the inline call + brittle parse.
- **Create** `tests/test_llm_extra_body.py`
- **Create** `tests/test_thinking_classifier.py`

---

## Task 1: `extra_body` passthrough in `llm_call_async`

**Files:**
- Modify: `src/llm_core.py:1128-1138` (signature), `:1156-1160` (cache read), `:1188-1190` (payload), `:1226` (cache write)
- Test: `tests/test_llm_extra_body.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_extra_body.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_extra_body.py -v`
Expected: FAIL — `TypeError: llm_call_async() got an unexpected keyword argument 'extra_body'`.

- [ ] **Step 3: Add the `extra_body` parameter**

In `src/llm_core.py`, change the signature (currently ends `prompt_type: Optional[str] = None`):

```python
async def llm_call_async(
    url: str,
    model: str,
    messages: List[Dict],
    temperature: float = LLMConfig.DEFAULT_TEMPERATURE,
    max_tokens: int = LLMConfig.DEFAULT_MAX_TOKENS,
    headers: Optional[Dict] = None,
    timeout: int = LLMConfig.STREAM_TIMEOUT,
    max_retries: int = LLMConfig.MAX_RETRIES,
    prompt_type: Optional[str] = None,
    extra_body: Optional[Dict] = None,
) -> str:
```

- [ ] **Step 4: Merge `extra_body` into the OpenAI-compatible payload and bypass cache when set**

In the `else` branch, immediately after the `max_tokens` block (`payload[tok_key] = max_tokens`), add:

```python
        if extra_body:
            payload.update(extra_body)
```

Change the cache read (currently `cached_response = _get_cached_response(cache_key)`):

```python
    cached_response = None if extra_body else _get_cached_response(cache_key)
```

Change the cache write (currently `_set_cached_response(cache_key, response)`):

```python
                if not extra_body:
                    _set_cached_response(cache_key, response)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_llm_extra_body.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/llm_core.py tests/test_llm_extra_body.py
git commit -m "feat(llm): add extra_body passthrough to llm_call_async

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `_extract_json_obj` + `classify_email_json`

**Files:**
- Create: `src/email_labeling/__init__.py`
- Create: `src/email_labeling/thinking_classifier.py`
- Test: `tests/test_thinking_classifier.py`

- [ ] **Step 1: Create the package marker**

```python
# src/email_labeling/__init__.py
```
(empty file)

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_thinking_classifier.py
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_thinking_classifier.py -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: module ... has no attribute '_extract_json_obj'`.

- [ ] **Step 4: Implement `thinking_classifier.py`**

```python
# src/email_labeling/thinking_classifier.py
"""Reliable JSON classification over a (possibly thinking) local model.

The local serve defaults to thinking-on: llama.cpp fills `reasoning_content`
and leaves `content` empty until `</think>`, and a small max_tokens truncates
before any JSON. `llm_call_async_with_fallback` already returns
`content or reasoning_content`, so we (1) give thinking room via a generous
max_tokens, (2) extract the first balanced JSON object from whatever channel
carried it, and (3) if that fails, retry once with thinking disabled via
`chat_template_kwargs={"enable_thinking": False}`.

`response_format` / json_schema grammars are intentionally NOT used — they
crash this llama.cpp build.
"""
import json
import logging
from typing import Optional

from src.llm_core import llm_call_async_with_fallback

logger = logging.getLogger(__name__)

_NO_THINK_EXTRA = {"chat_template_kwargs": {"enable_thinking": False}}


def _extract_json_obj(text: str) -> Optional[dict]:
    """Return the first balanced top-level JSON object in `text`, or None.

    Scans for the first '{' and walks to its matching '}' (brace-counting,
    string-aware), tolerant of leading prose/thinking and code fences. If that
    span doesn't parse, advances to the next '{'.
    """
    if not text:
        return None
    s = text.find("{")
    while s != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(s, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[s:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
        s = text.find("{", s + 1)
    return None


async def classify_email_json(candidates, prompt: str, *,
                              max_tokens: int = 1024, timeout: int = 30) -> Optional[dict]:
    """Call the model and return a parsed JSON dict, or None.

    First pass keeps reasoning on (generous budget). If no JSON is parseable,
    one retry disables thinking. Returns None only when both fail.
    """
    messages = [{"role": "user", "content": prompt}]
    try:
        raw = await llm_call_async_with_fallback(
            candidates, messages, temperature=0.1, max_tokens=max_tokens, timeout=timeout,
        )
    except Exception as e:
        logger.warning("classify_email_json: primary call failed: %s", e)
        raw = ""
    obj = _extract_json_obj(raw or "")
    if obj is not None:
        return obj
    try:
        raw2 = await llm_call_async_with_fallback(
            candidates, messages, temperature=0.1, max_tokens=max_tokens, timeout=timeout,
            extra_body=_NO_THINK_EXTRA,
        )
    except Exception as e:
        logger.warning("classify_email_json: no-think retry failed: %s", e)
        return None
    return _extract_json_obj(raw2 or "")


def normalize_verdict(obj: dict, allowed_tags) -> dict:
    """Coerce a raw classifier dict into {score, tags, spam, reason}.

    Mirrors the legacy inline logic: score via tolerant int (default 0);
    tags lowercased, '_'->'-', 'promo'->'marketing', filtered to allowed_tags,
    de-duplicated; spam coerced to bool; reason truncated to 200 chars.
    """
    try:
        score = int(obj.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    reason = str(obj.get("reason", ""))[:200]
    raw_tags = obj.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    tags = []
    for t in raw_tags:
        if not isinstance(t, str):
            continue
        tag = t.strip().lower().replace("_", "-")
        if tag == "promo":
            tag = "marketing"
        if tag in allowed_tags and tag not in tags:
            tags.append(tag)
    sp = obj.get("spam")
    if isinstance(sp, bool):
        spam = sp
    elif isinstance(sp, (int, float)):
        spam = bool(sp)
    else:
        spam = str(sp or "").strip().lower() in {"1", "true", "yes", "y"}
    return {"score": score, "tags": tags, "spam": spam, "reason": reason}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_thinking_classifier.py -v`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add src/email_labeling/__init__.py src/email_labeling/thinking_classifier.py tests/test_thinking_classifier.py
git commit -m "feat(email): reliable thinking-aware JSON classifier

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Unit-test `normalize_verdict`

**Files:**
- Test: `tests/test_thinking_classifier.py` (append)

- [ ] **Step 1: Append failing tests**

```python
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
```

- [ ] **Step 2: Run to verify they pass** (implementation already exists from Task 2)

Run: `pytest tests/test_thinking_classifier.py -v`
Expected: PASS (8 passed total).

- [ ] **Step 3: Commit**

```bash
git add tests/test_thinking_classifier.py
git commit -m "test(email): cover normalize_verdict edge cases

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Wire the urgency classifier to use the new module

**Files:**
- Modify: `src/builtin_actions.py` (import near top of file with the other `src.` imports; body at `:1654-1699`)

- [ ] **Step 1: Add the import**

Near the other top-level `from src...` imports in `src/builtin_actions.py`, add:

```python
from src.email_labeling.thinking_classifier import classify_email_json, normalize_verdict
```

- [ ] **Step 2: Replace the inline call + brittle parse**

Replace the block from `raw = await llm_call_async_with_fallback(` (currently L1655) through the spam-coercion block that ends just before `_blob = ...` (currently L1699). The enclosing `try:` (L1654) and everything from `_blob = ...` onward (the keyword/bulk post-processing, verdict assembly, and `except Exception` at L1745) stay unchanged. New body:

```python
                    obj = await classify_email_json(candidates, prompt, max_tokens=1024, timeout=30)
                    if obj is None:
                        failed_classifications.append({
                            "subject": item.get("subject") or "(no subject)",
                            "from": item.get("from") or "",
                            "reason": "model returned no JSON",
                        })
                        continue
                    _verdict = normalize_verdict(obj, CATEGORY_TAGS)
                    score = _verdict["score"]
                    reason = _verdict["reason"]
                    tags = _verdict["tags"]
                    spam = _verdict["spam"]
```

(The subsequent code already reads `score`, `tags`, `spam`, `reason` and clamps `score` to `0..3` in the verdict dict at L1730, so behavior downstream is unchanged.)

- [ ] **Step 3: Verify nothing else references the removed locals**

Run: `pytest tests/ -k "email or builtin or urgency" -v`
Expected: PASS (no regression in existing email/builtin tests).

- [ ] **Step 4: Full suite sanity check**

Run: `pytest tests/ -q`
Expected: PASS (no new failures).

- [ ] **Step 5: Commit**

```bash
git add src/builtin_actions.py
git commit -m "refactor(email): route urgency classify through reliable JSON helper

max_tokens 220 -> 1024; thinking-aware parse + no-think retry replaces the
content-only brittle parse that returned 'model returned no JSON'.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

- **Spec coverage:** Implements the spec's §6 "ThinkingClassifier" reliability requirement and §8 JSON error-handling (content/reasoning fallback + thinking-off retry). Schema-constrained output from the spec is **deliberately dropped** — verified to crash this build; `normalize_verdict` + tolerant extraction replace it. Dynamic labels / Gmail / settings are Plans 2-3 (out of scope here).
- **Placeholder scan:** none — every step has full code and exact commands.
- **Type consistency:** `classify_email_json` returns `dict | None`; `normalize_verdict(obj, allowed_tags) -> {score,tags,spam,reason}`; `_extract_json_obj(text) -> dict | None`. Call sites match.

## End-to-end check (deferred to user)

The unit tests above need no serve. The one live check — re-running the Email Tags task against the real Qwen3.6 serve and confirming all emails classify instead of "no JSON" — is left for the user once the serve is back up.
