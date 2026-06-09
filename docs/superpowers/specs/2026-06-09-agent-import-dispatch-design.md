# Framework Agent Import + Sub-Agent Dispatch — Phase A

**Date:** 2026-06-09
**Status:** Design — pending user review, then implementation plan
**Area:** Backend agent runtime (`src/`, `routes/`, `core/database.py`), plus a thin chat-frontend hook
**Branch/worktree:** `feat/agent-dispatch` (off `dev`) at `.claude/worktrees/agent-dispatch`

## Summary

Bring the local "Claude Code framework" agents into odysseus so the assistant —
running on the **locally-served model** — can run a named specialist agent (its own
system prompt + a restricted tool set) in an isolated context and get its result back.
This is **true sub-agent dispatch**, triggered two ways: a user typing `@agent-name <task>`
in chat (reliable, available now) and a `dispatch_agent` tool the assistant may call
itself (autonomous, best-effort on a local model).

The key finding from code verification: **odysseus already runs a `CrewMember`
(persona + tool subset) through the agent loop and captures the result as a string** —
that's how scheduled assistant tasks work (`src/task_scheduler.py:_run_agent_loop`).
Phase A mostly *exposes* that existing capability (extract it into a shared helper, add
a tool + an `@`-trigger) and adds an **importer** that turns framework agent `.md` files
into `CrewMember` rows. We are **not** building a sub-agent engine from scratch.

Skills ingestion is a **separate later phase** (the framework's skills are prose wrappers
that mostly *spawn* these agents; their bodies need lossy prose→structured conversion).

## Goals

- Import the **12** framework agents in `C:\Developer\claude-code-framework\.claude\agents\*.md`
  into odysseus as `CrewMember` rows (`is_default_assistant=False`), idempotently
  (re-import upserts by `owner`+`name`, never duplicates).
- A `dispatch_agent(name, task)` tool: looks up the agent by name, runs it in an isolated
  context on the session's model with its mapped tool subset, returns its final text.
- A user-driven trigger: `@agent-name <task>` typed in chat dispatches that agent and
  streams its result into the conversation.
- Coordinator agents (those whose framework def lists the `Agent` tool) can sub-dispatch
  (via the mapped `dispatch_agent` tool), bounded by a recursion-depth cap.
- Robust on a fragile local model: inherit the scheduler's grace-summarization, endpoint
  fallback, think-stripping, and RAG tool-capping; add depth cap + per-dispatch timeout.

## Non-Goals (YAGNI)

- **Skills ingestion** — deferred to a later phase (own spec). This phase is agents only.
- **Parallel orchestration** — the local model serves ~one request at a time, so dispatch
  is **sequential**. No fan-out, no concurrent sub-agents.
- **Faithful framework orchestration** — the framework's `.claude/state/*.json` pipelines
  and `/slash-command` flows are Claude-Code-CLI-specific; imported bodies that reference
  them run as personas, not as stateful coordinators. Rewriting coordinators for real
  orchestration is out of scope here.
- **Importing the 40 `templates/agents/`** — those are `{{placeholder}}` scaffolds for new
  projects, not runnable agents.
- **New DB columns / schema migration** — Phase A reuses `CrewMember` as-is. (A `source`
  column to tag "imported framework agent" for a future library UI is noted as optional.)
- **A full agent-library management UI** — Phase A surfaces agents via the `@`-trigger and
  an import action; rich CRUD UI is later.

## Decisions (from brainstorming)

1. **Agents model = true sub-agent dispatch** (user chose this over personas/skills-conversion).
2. **Trigger = both** — user-driven `@agent` now; model-driven `dispatch_agent` tool ready,
   treated as best-effort given local-model tool-call reliability.
3. **Reuse `CrewMember`** as the agent registry rather than building new storage — it already
   has `name`, `personality` (system prompt), `model`, `endpoint_url`, `enabled_tools`.
4. **Agents first; skills later.**
5. **Import the 12 real agents**, not the 40 templates.
6. **Sequential, depth-capped** dispatch (local-model reality).

## Verified existing infrastructure (the precedents)

These were confirmed by reading the source, not assumed:

- **`CrewMember`** (`core/database.py`): fields `id, owner, name, personality, model,
  endpoint_url, enabled_tools (JSON), greeting, session_id, is_default_assistant,
  timezone, created_at`. Every "assistant" lookup filters `is_default_assistant == True`
  (`routes/assistant_routes.py`, `src/task_scheduler.py`), and the scheduler actively
  *demotes* duplicate defaults — so adding `is_default_assistant=False` rows is safe and
  collides with nothing.
- **`task_scheduler._run_agent_loop(...)`** (`src/task_scheduler.py:1563`): runs
  `stream_agent_loop` and **accumulates `full_text` from `delta` SSE events into a return
  string**; captures tool-output summaries; has a **grace-summarization** fallback when the
  model exhausts rounds without a final answer; uses an endpoint **fallback chain**; honors
  `max_rounds`. This is the capture-to-string primitive we extract and reuse.
- **`enabled_tools` → `disabled_tools` inversion** (`src/task_scheduler.py:1356-1364`):
  `disabled_tools = set(BUILTIN_TOOL_DESCRIPTIONS) - set(crew.enabled_tools)`. Confirms the
  whitelist→blacklist conversion.
- **RAG tool-capping** (`src/task_scheduler.py:1368-1379`): `get_tool_index().get_tools_for_query(prompt, k=8)`
  + `ASSISTANT_ALWAYS_AVAILABLE`, minus `disabled_tools`, so a local model gets ~8 tools, not 40+.
- **`strip_think(result, prose=True, prompt_echo=True)`** (`src/text_helpers.py`): strips the
  local model's chain-of-thought / prompt echo from a captured result.
- **In-tool model calls** (`src/ai_interaction.py`): `do_chat_with_model`, `do_send_to_session`,
  `do_pipeline` already call a model from inside a tool handler and return strings — precedent
  that calling the loop from within `execute_tool_block` is fine.
- **Tool registry**: `TOOL_TAGS` (`src/agent_tools.py:30`), `FUNCTION_TOOL_SCHEMAS`
  (`src/tool_schemas.py:23`), `do_*` handlers, dispatch in `src/tool_execution.py:execute_tool_block`.
- **Chat entry**: `POST /api/chat_stream` (`routes/chat_routes.py:380`) → `stream_agent_loop`
  (line ~1079); drives the loop via `disabled_tools` only. Frontend posts from
  `static/js/chat.js`.

## Architecture

Six focused units. Each has one responsibility; the dispatch core is shared by all three
consumers (scheduler, tool, trigger).

### 1. Shared run helper — `src/agent_dispatch.py` (new)

Extract the body of `task_scheduler._run_agent_loop` into a standalone async function so it
is no longer coupled to a `task` object (it currently uses only `task.prompt`, `task.owner`,
`task.max_steps`):

```
async def run_agent_text(
    *, endpoint_url, model, system_prompt, user_message, owner,
    session_id=None, disabled_tools=None, relevant_tools=None,
    max_rounds=AGENT_DISPATCH_MAX_ROUNDS, headers=None,
) -> str
```

It builds `messages=[{system}, {user}]`, runs `stream_agent_loop`, accumulates `full_text`,
applies the grace-summarization + fallback logic, and returns the string. `task_scheduler`
is refactored to call this helper (behavior-preserving — its existing tests must still pass).
This module also owns the dispatch constants, the depth `ContextVar`, and the tool mapper
(below).

**Constants (no magic numbers):**
- `MAX_AGENT_DEPTH = 3` — max nesting of sub-agent → sub-agent dispatch.
- `AGENT_DISPATCH_MAX_ROUNDS = 12` — tool-call rounds per sub-agent.
- `AGENT_DISPATCH_TIMEOUT_S = 240` — wall-clock cap per dispatch.
- `DISPATCH_RESULT_MAX_CHARS = 10000` — truncate the returned string (matches `do_chat_with_model`).
- `AGENT_DISPATCH_RAG_K = 8` — RAG tool count (matches scheduler).

### 2. Agent registry lookup

A thin helper (in `src/agent_dispatch.py`) to resolve an agent by name for an owner:
`get_agent_by_name(db, owner, name) -> CrewMember | None`, case-insensitive, matching on
`CrewMember.name`. Used by both the tool and the trigger. No new table — it queries
`crew_members`.

### 3. Tool-name mapper — `map_framework_tools(names: list[str]) -> list[str]`

Translate Claude-Code tool names (from agent frontmatter `tools:`) to odysseus tool names.
Unmapped names are **dropped and logged** (never silently). Mapping:

| Framework | odysseus | Notes |
|-----------|----------|-------|
| `Read` | `read_file` | |
| `Write` | `write_file` | |
| `Edit`, `MultiEdit` | `edit_file` | |
| `Grep` | `grep` | |
| `Glob` | `glob` | |
| `LS` | `ls` | |
| `Bash` | `bash` | |
| `WebFetch` | `web_fetch` | |
| `WebSearch` | `web_search` | |
| `Agent`, `Task` | `dispatch_agent` | enables sub-dispatch (gated by depth) |
| `TodoWrite`, `NotebookEdit`, `*` (unknown) | — | dropped + logged |

The mapped list is stored as the CrewMember's `enabled_tools` (JSON whitelist). At dispatch
time it's inverted to `disabled_tools` exactly as the scheduler does.

### 4. `dispatch_agent` tool (capture mode)

- **Tag:** add `"dispatch_agent"` to `TOOL_TAGS`.
- **Schema:** add to `FUNCTION_TOOL_SCHEMAS` — params `{name: string, task: string}`.
- **Handler:** `do_dispatch_agent(content, session_id=None, owner=None)` in
  `src/tool_implementations.py` (parses `name` + `task`; or a structured handler matching the
  codebase's convention). It:
  1. Resolves the `CrewMember` by `name`+`owner`; error string if not found.
  2. Checks the depth `ContextVar` against `MAX_AGENT_DEPTH`; refuses (returns a clear message)
     if exceeded.
  3. **Resolves model + endpoint** in the same order the scheduler uses: the CrewMember's
     `model`/`endpoint_url` if set, else the **parent session's** (looked up via `session_id`),
     else system defaults. (Imported agents leave these null, so they inherit the caller's
     local model — which is the intent.) Resolves auth `headers` from the matching
     `ModelEndpoint`, as `_run_agent_loop` does today.
  4. Inverts `enabled_tools` → `disabled_tools`; RAG-caps `relevant_tools` for the task text.
  5. **Saves** `_active_document_id` / `_active_model` (the module globals in
     `tool_implementations.py:71`), increments depth, runs `run_agent_text(...)` under
     `asyncio.wait_for(timeout=AGENT_DISPATCH_TIMEOUT_S)` with **an ephemeral/None session_id**
     so the sub-agent's internal transcript does not persist into the parent session, then
     **restores** the globals and decrements depth in a `finally`.
  6. `strip_think`s the result, truncates to `DISPATCH_RESULT_MAX_CHARS`, returns
     `{"agent": name, "result": ...}`.

### 5. `@agent-name` trigger (stream mode)

In `routes/chat_routes.py`, before the normal loop dispatch: if the user message matches
`^@([a-z0-9][a-z0-9-]*)\s+(.*)$` (case-insensitive) **and** a `CrewMember` of that name exists
for the owner, route to a streamed dispatch: run `stream_agent_loop` with the agent's
persona + inverted/RAG tools, **streaming its SSE into the chat** (passing the parent
`session_id`, because this is the user's explicit, visible invocation — unlike the captured
tool path). If the `@name` doesn't resolve to an agent, fall through to normal chat unchanged
(so `@` typed for other reasons is harmless). A small `static/js/chat.js` affordance
(autocomplete of agent names) is optional polish, not required for Phase A.

### 6. Agent importer — `services/agents/agent_importer.py` (new)

- `import_agents_from_dir(path, owner) -> list[dict]`: lists `*.md` in the folder (depth 0,
  flat — agents are single files), parses each via `parse_agent_md` (YAML frontmatter
  `name`/`description`/`tools`/`model` + markdown body), maps tools via `map_framework_tools`,
  and **upserts** a `CrewMember` keyed on (`owner`, `name`): body→`personality`,
  mapped tools→`enabled_tools` (JSON), `is_default_assistant=False`,
  `model`/`endpoint_url` left null so dispatch uses the session's current model/endpoint
  (the framework `model: opus` is meaningless locally; null = "use caller's model").
- A path-safety guard: only allow importing from a directory the user supplies explicitly
  (no traversal outside it); reuse/extend the local-path validation being considered for
  `skill_importer` if convenient, but this importer is otherwise independent (agents are flat
  `.md`, not SKILL.md bundles).
- **Trigger:** a route `POST /api/agents/import` (new `routes/agents_routes.py` or folded into
  an existing admin route) taking `{path}` and returning the imported list. Also a
  `GET /api/agents` listing the owner's dispatchable agents (name + description) for the UI
  and for an `@`-autocomplete later.

## Data flow

**User-driven (`@code-reviewer review auth.py`):**
chat.js POSTs message → `chat_routes` detects `@name` + resolves CrewMember → builds
persona system prompt + inverted/RAG tools → `stream_agent_loop` streamed into the chat
(parent session) → user sees the agent's work live.

**Model-driven (assistant calls the tool):**
main loop emits `dispatch_agent{name, task}` → `execute_tool_block` → `do_dispatch_agent`
→ depth check → `run_agent_text(...)` (isolated, ephemeral session, timeout) → `strip_think`
+ truncate → returned as the tool result string → main loop continues with that result in
context.

**Nested (coordinator):** a dispatched agent whose tools include `dispatch_agent` may itself
call it; the depth `ContextVar` increments per level and refuses past `MAX_AGENT_DEPTH`.

## Error handling / safety

- **Unknown agent name** → tool returns a clear error string; `@trigger` falls through to
  normal chat.
- **Depth exceeded** → dispatch refused with a message naming the cap (no silent drop).
- **Timeout** → `asyncio.wait_for` cancels; return a "agent timed out after Ns" string.
- **Global-state isolation** → save/restore `_active_document_id`/`_active_model` around each
  dispatch (stack-safe because dispatch is awaited and sequential). *Robust follow-up (noted,
  not Phase A): migrate these to `contextvars.ContextVar`.*
- **No final text from a weak model** → inherited grace-summarization guarantees a non-empty
  result.
- **Endpoint down** → inherited utility fallback chain.
- **Unmapped framework tools** → dropped with a log line; import result reports which were
  dropped per agent.
- **Re-import** → upsert by (owner, name); no duplicates.
- **session_id semantics** → capture-mode uses ephemeral/None so sub-agent transcript doesn't
  pollute the parent session; stream-mode uses the parent session (visible to the user).
  *(Implementation check: confirm `stream_agent_loop` tolerates `session_id=None`; if it
  requires one, mint a throwaway id not surfaced in the session list.)*

## Edge cases

- **Agent body references `.claude/state/*` or `/slash-commands`** → harmless dead text in the
  persona; the agent still acts as a specialist. Documented as a known imperfection.
- **`@name` with no following task** → treat as no-match → normal chat (require a task arg).
- **Two agents, same name across owners** → lookup is always scoped by `owner`.
- **Importing a folder twice / partially** → idempotent upsert; unchanged rows are updated in
  place.
- **Local model emits a malformed `dispatch_agent` call** → the existing tolerant tool-parsing
  handles it; a bad call yields a tool error string, not a crash (best-effort, per the trigger
  decision).

## Testing

- **Unit — `parse_agent_md`**: frontmatter (`name/description/tools/model`) + body extracted
  correctly; missing/extra keys tolerated.
- **Unit — `map_framework_tools`**: each mapping; `Agent→dispatch_agent`; unknown dropped +
  logged; empty list.
- **Unit — `import_agents_from_dir`**: creates N rows from a temp dir of fixture `.md`;
  re-import upserts (count stable, fields updated); `is_default_assistant=False`.
- **Unit — `run_agent_text`**: against a stubbed `stream_agent_loop` yielding delta events →
  returns concatenated text; grace path when no delta; timeout path.
- **Unit — depth cap**: nested `do_dispatch_agent` refuses at `MAX_AGENT_DEPTH`.
- **Unit — global-state save/restore**: `_active_document_id` restored after a dispatch that
  mutates it.
- **Regression**: existing `task_scheduler` tests pass after extracting `run_agent_text`
  (`tests/test_task_scheduler_session_delivery.py`).
- **Integration**: `dispatch_agent` end-to-end against a fake model returns a captured string.
- **Browser (running container)**: `@agent-name <task>` streams a real local-model dispatch
  into chat; verify a couple of the 12 agents produce sane output.

## Design-principles compliance

- **No magic numbers** — all caps/limits are named constants in `src/agent_dispatch.py`.
- **Generalized / DRY** — one `run_agent_text` helper serves scheduler + tool + trigger; the
  tool-mapper and registry lookup are single-purpose and reused by importer + dispatch; we
  reuse `stream_agent_loop`, `CrewMember`, RAG tool-capping, `strip_think`, and the fallback
  chain rather than reimplementing any of them.

## Honest open question (empirical, not architectural)

The **quality** of these personas on the Q2 local model is unproven: whether, e.g.,
`code-reviewer` actually emits correct tool calls and useful output on this quant. The
*mechanism* is sound and robust (grace-summary, fallbacks, think-strip). Mitigation: import
the 12, test a handful, keep what works, and tune or drop the rest. No code decision hinges
on this.

## File touch-list (for the plan)

- **New:** `src/agent_dispatch.py` (helper, constants, depth ContextVar, tool mapper, registry lookup).
- **New:** `services/agents/agent_importer.py` (`parse_agent_md`, `import_agents_from_dir`).
- **New:** `routes/agents_routes.py` (`POST /api/agents/import`, `GET /api/agents`) — or fold into an existing admin route.
- **Modify:** `src/task_scheduler.py` — refactor `_run_agent_loop` to call `run_agent_text`.
- **Modify:** `src/agent_tools.py` (`TOOL_TAGS` += `dispatch_agent`), `src/tool_schemas.py`
  (schema), `src/tool_implementations.py` (`do_dispatch_agent` + save/restore globals),
  `src/tool_execution.py` (register dispatch if not table-driven).
- **Modify:** `routes/chat_routes.py` — `@agent-name` detection → streamed dispatch.
- **Modify (optional):** `static/js/chat.js` — `@`-autocomplete of agent names.
- **Tests:** new unit/integration files under `tests/`.
