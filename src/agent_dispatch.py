"""Sub-agent dispatch — Phase A foundation.

`run_agent_text` is the shared loop-driver extracted from
`task_scheduler._run_agent_loop` so that the scheduler, the upcoming
`dispatch_agent` tool, and the `@agent` chat trigger all share ONE
capture-to-string implementation (with the grace-summarization + endpoint
fallback that make it robust on a fragile local model). Later Phase A tasks add
the dispatch tool, the trigger, and the agent importer on top of this.
"""
import json
import logging

logger = logging.getLogger(__name__)

# --- dispatch tuning (named — no magic numbers) ---
MAX_AGENT_DEPTH = 3                 # max nesting of sub-agent -> sub-agent dispatch
AGENT_DISPATCH_MAX_ROUNDS = 12      # tool-call rounds for a dispatched sub-agent
AGENT_DISPATCH_TIMEOUT_S = 240      # wall-clock cap per dispatch
DISPATCH_RESULT_MAX_CHARS = 10_000  # truncate the returned string
AGENT_DISPATCH_RAG_K = 8            # RAG-selected tool count for a dispatch
GRACE_SUMMARY_TIMEOUT_S = 30        # final summarization call timeout
_TOOL_SUMMARY_MAX_CHARS = 500       # per-tool-output snippet kept for grace summary
_GRACE_TOOL_RESULTS_KEPT = 5        # how many recent tool snippets feed the grace summary


def _resolve_headers(endpoint_url: str) -> dict:
    """Resolve API auth headers for an endpoint URL from the ModelEndpoint table."""
    headers: dict = {}
    try:
        from core.database import SessionLocal, ModelEndpoint
        from src.endpoint_resolver import normalize_base, build_headers
        db = SessionLocal()
        try:
            eps = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all()  # noqa: E712
            for ep in eps:
                if normalize_base(ep.base_url) in endpoint_url or endpoint_url in normalize_base(ep.base_url):
                    headers = build_headers(ep.api_key, normalize_base(ep.base_url))
                    break
        finally:
            db.close()
    except Exception:
        pass
    return headers


async def run_agent_text(
    *,
    endpoint_url: str,
    model: str,
    system_prompt: str,
    user_message: str,
    owner: str | None = None,
    session_id: str | None = None,
    disabled_tools: set | None = None,
    relevant_tools: set | None = None,
    max_rounds: int = AGENT_DISPATCH_MAX_ROUNDS,
    headers: dict | None = None,
) -> str:
    """Run the full agent loop in an isolated context and collect the final text.

    Drives `stream_agent_loop` over a fresh [system, user] message list,
    accumulating the assistant's streamed deltas. If the model exhausts its
    rounds on tool calls without a final answer, a grace-summarization call
    guarantees a non-empty result. Returns the collected text (or "(no output)").

    This is the single capture-to-string path shared by the scheduler, the
    dispatch_agent tool, and the @agent trigger.
    """
    from src.agent_loop import stream_agent_loop

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    if headers is None:
        headers = _resolve_headers(endpoint_url)

    full_text = ""
    tool_results: list = []

    # Share the Utility model's fallback chain so a downed primary endpoint
    # doesn't silently yield "(no output)".
    try:
        from src.endpoint_resolver import resolve_utility_fallback_candidates
        _fallbacks = resolve_utility_fallback_candidates()
    except Exception:
        _fallbacks = []

    async for event_str in stream_agent_loop(
        endpoint_url=endpoint_url,
        model=model,
        messages=messages,
        max_rounds=max_rounds,
        session_id=session_id,
        owner=owner,
        headers=headers,
        disabled_tools=disabled_tools,
        relevant_tools=relevant_tools,
        fallbacks=_fallbacks,
    ):
        if event_str.startswith("data: ") and not event_str.startswith("data: [DONE]"):
            try:
                data = json.loads(event_str[6:])
                # Capture text from all event types, not just delta.
                if "delta" in data:
                    full_text += data["delta"]
                elif data.get("type") == "tool_output":
                    # Keep a tool-output summary so we have SOMETHING even if the
                    # model never produces a final text response.
                    tool_summary = data.get("stdout") or data.get("output") or data.get("result") or ""
                    if isinstance(tool_summary, str) and tool_summary.strip():
                        tool_results.append(f"[{data.get('tool', '?')}] {tool_summary[:_TOOL_SUMMARY_MAX_CHARS]}")
            except (json.JSONDecodeError, KeyError):
                pass

    # Grace summarization — if the model exhausted its rounds on tool calls
    # without a final text response, do one last LLM call to summarize.
    if not full_text.strip():
        try:
            from src.llm_core import llm_call_async_with_fallback
            from src.endpoint_resolver import resolve_utility_fallback_candidates
            grace_context = "You ran out of steps. "
            if tool_results:
                grace_context += "Here's what your tools returned:\n" + "\n".join(tool_results[-_GRACE_TOOL_RESULTS_KEPT:])
            else:
                grace_context += "No tool results were captured."
            grace_context += "\n\nSummarize what you accomplished and what's still pending. Be concise."
            _grace_candidates = [(endpoint_url, model, headers)] + resolve_utility_fallback_candidates()
            full_text = await llm_call_async_with_fallback(
                _grace_candidates,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": grace_context},
                ],
                timeout=GRACE_SUMMARY_TIMEOUT_S,
            )
            full_text = (full_text or "").strip()
        except Exception as e:
            logger.warning(f"Grace summarization failed: {e}")
            if tool_results:
                full_text = "\n".join(tool_results[-_GRACE_TOOL_RESULTS_KEPT:])

    return full_text or "(no output)"
