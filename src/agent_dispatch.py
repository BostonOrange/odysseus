"""Sub-agent dispatch — Phase A foundation.

`run_agent_text` is the shared loop-driver extracted from
`task_scheduler._run_agent_loop` so that the scheduler, the upcoming
`dispatch_agent` tool, and the `@agent` chat trigger all share ONE
capture-to-string implementation (with the grace-summarization + endpoint
fallback that make it robust on a fragile local model). Later Phase A tasks add
the dispatch tool, the trigger, and the agent importer on top of this.
"""
import asyncio
import contextvars
import json
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Per-async-context nesting counter so a coordinator agent can sub-dispatch but
# cannot runaway-spawn. It flows through the await chain (same task), so a
# nested do_dispatch_agent sees the incremented depth.
_dispatch_depth: "contextvars.ContextVar[int]" = contextvars.ContextVar(
    "agent_dispatch_depth", default=0
)

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


async def do_dispatch_agent(content: str, session_id: Optional[str] = None,
                            owner: Optional[str] = None) -> Dict:
    """Run a named agent (CrewMember) in isolation and return its result text.

    `content`: line 1 = agent name, line 2+ = the task. Resolves the agent's
    persona + tool subset, then runs it via `run_agent_text` on the session's
    model — sequential, depth-capped, and timed out — returning the captured
    result. The sub-agent runs with NO session so its transcript never persists
    into the parent chat; only the returned summary surfaces (as the tool result).
    """
    lines = (content or "").split("\n", 1)
    name = (lines[0] if lines else "").strip()
    task = (lines[1] if len(lines) > 1 else "").strip()
    if not name:
        return {"error": "dispatch_agent: first line must be the agent name"}
    if not task:
        return {"error": "dispatch_agent: provide a task on line 2+"}

    depth = _dispatch_depth.get()
    if depth >= MAX_AGENT_DEPTH:
        return {"error": f"dispatch_agent: max sub-agent depth ({MAX_AGENT_DEPTH}) reached"}

    from core.database import SessionLocal, CrewMember, Session as DbSession

    endpoint_url = model = system_prompt = None
    disabled_tools = relevant_tools = None
    db = SessionLocal()
    try:
        crew = (
            db.query(CrewMember)
            .filter(CrewMember.owner == owner, CrewMember.name.ilike(name))
            .first()
        )
        if crew is None:
            return {"error": f"dispatch_agent: no agent named {name!r} for this user"}
        system_prompt = (crew.personality or "").strip() or f"You are {name}."
        # Resolve model/endpoint: crew override -> parent session -> (error).
        endpoint_url = crew.endpoint_url
        model = crew.model
        if (not endpoint_url or not model) and session_id:
            sess = db.query(DbSession).filter(DbSession.id == session_id).first()
            if sess:
                endpoint_url = endpoint_url or sess.endpoint_url
                model = model or sess.model
        # Invert the agent's enabled_tools whitelist into a disabled_tools blacklist.
        try:
            enabled = json.loads(crew.enabled_tools or "[]")
        except (TypeError, ValueError):
            enabled = []
        if isinstance(enabled, list) and enabled:
            from src.tool_index import BUILTIN_TOOL_DESCRIPTIONS
            disabled_tools = set(BUILTIN_TOOL_DESCRIPTIONS.keys()) - set(enabled)
        # RAG-cap the tool set for this task so a local model isn't flooded.
        try:
            from src.tool_index import get_tool_index, ASSISTANT_ALWAYS_AVAILABLE
            idx = get_tool_index()
            if idx:
                relevant_tools = idx.get_tools_for_query(task, k=AGENT_DISPATCH_RAG_K) | ASSISTANT_ALWAYS_AVAILABLE
                if disabled_tools:
                    relevant_tools = relevant_tools - disabled_tools
        except Exception:
            relevant_tools = None
    finally:
        db.close()

    if not endpoint_url or not model:
        return {"error": "dispatch_agent: no model/endpoint available for the sub-agent"}

    # Isolate the parent's active document/model from the sub-agent's tools
    # (stack-safe save/restore — dispatch is awaited and sequential).
    import src.tool_implementations as _ti
    saved_doc = _ti.get_active_document()
    saved_model = _ti._active_model

    token = _dispatch_depth.set(depth + 1)
    try:
        result = await asyncio.wait_for(
            run_agent_text(
                endpoint_url=endpoint_url,
                model=model,
                system_prompt=system_prompt,
                user_message=task,
                owner=owner,
                session_id=None,
                disabled_tools=disabled_tools,
                relevant_tools=relevant_tools,
                max_rounds=AGENT_DISPATCH_MAX_ROUNDS,
            ),
            timeout=AGENT_DISPATCH_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        result = f"(agent {name!r} timed out after {AGENT_DISPATCH_TIMEOUT_S}s)"
    except Exception as e:
        logger.warning(f"dispatch_agent {name!r} failed: {e}")
        result = f"(agent {name!r} failed: {e})"
    finally:
        _dispatch_depth.reset(token)
        _ti.set_active_document(saved_doc)
        _ti.set_active_model(saved_model)

    try:
        from src.text_helpers import strip_think
        result = strip_think(result or "", prose=True, prompt_echo=True).strip() or result
    except Exception:
        pass
    if result and len(result) > DISPATCH_RESULT_MAX_CHARS:
        result = result[:DISPATCH_RESULT_MAX_CHARS] + "\n... (truncated)"
    return {"agent": name, "result": result}
