"""Reliable JSON classification over a (possibly thinking) local model.

The local serve defaults to thinking-on: llama.cpp fills ``reasoning_content``
and leaves ``content`` empty until ``</think>``, and a small max_tokens
truncates before any JSON. ``llm_call_async_with_fallback`` already returns
``content or reasoning_content``, so we (1) give thinking room via a generous
max_tokens, (2) extract the first balanced JSON object from whatever channel
carried it, and (3) if that fails, retry once with thinking disabled via
``chat_template_kwargs={"enable_thinking": False}``.

``response_format`` / json_schema grammars are intentionally NOT used — they
crash this llama.cpp build.
"""
import json
import logging
from typing import Optional

from src.llm_core import llm_call_async_with_fallback

logger = logging.getLogger(__name__)

_NO_THINK_EXTRA = {"chat_template_kwargs": {"enable_thinking": False}}


def _extract_json_obj(text: str) -> Optional[dict]:
    """Return the first balanced top-level JSON object in ``text``, or None.

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
