"""Import Claude-Code-style agent `.md` files into odysseus as CrewMembers.

A framework agent file looks like:

    ---
    name: code-reviewer
    description: Reviews code changes for bugs, security issues, ...
    tools: Read, Glob, Grep, Bash
    model: opus
    ---
    # Code Reviewer
    You are a senior code reviewer. ...

It maps onto a `CrewMember` row 1:1 — body -> personality (system prompt),
`tools` -> enabled_tools (after name-mapping to odysseus tools), imported as a
non-default crew member so it never collides with the per-owner personal
assistant. Re-import upserts by (owner, name); it never duplicates.

`model`/`endpoint_url` are left null so a dispatched agent inherits the caller's
current local model (the framework's `model: opus` is meaningless here).
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Dict, List, Optional, Tuple

from services.memory.skill_format import parse_frontmatter

logger = logging.getLogger(__name__)

# Claude-Code tool names -> odysseus tool names. Unmapped names are dropped
# (and logged) rather than silently kept. `Agent`/`Task` map to dispatch_agent
# so a coordinator agent can sub-dispatch (depth-capped).
FRAMEWORK_TOOL_MAP: Dict[str, str] = {
    "read": "read_file",
    "write": "write_file",
    "edit": "edit_file",
    "multiedit": "edit_file",
    "grep": "grep",
    "glob": "glob",
    "ls": "ls",
    "bash": "bash",
    "webfetch": "web_fetch",
    "websearch": "web_search",
    "agent": "dispatch_agent",
    "task": "dispatch_agent",
}

_MAX_AGENT_FILE_BYTES = 200_000  # an agent persona far exceeding this is suspect


def map_framework_tools(names: List[str]) -> Tuple[List[str], List[str]]:
    """Map framework tool names to odysseus tool names.

    Returns (mapped, dropped) — mapped is de-duplicated and order-preserving;
    dropped lists framework names with no odysseus equivalent (logged, not kept).
    """
    mapped: List[str] = []
    dropped: List[str] = []
    for raw in names or []:
        key = (raw or "").strip().lower()
        if not key:
            continue
        target = FRAMEWORK_TOOL_MAP.get(key)
        if target is None:
            dropped.append(raw)
            continue
        if target not in mapped:
            mapped.append(target)
    if dropped:
        logger.info("agent import: dropped unmapped tools: %s", ", ".join(dropped))
    return mapped, dropped


def parse_agent_md(text: str) -> Dict[str, object]:
    """Parse a framework agent `.md` into its fields.

    Returns {name, description, tools (list[str]), model, body}. `tools` accepts
    either a comma-separated scalar (`Read, Grep`) or a YAML list.
    """
    fm, body = parse_frontmatter(text or "")
    name = str(fm.get("name") or "").strip()
    description = str(fm.get("description") or "").strip()
    model = str(fm.get("model") or "").strip()

    raw_tools = fm.get("tools")
    if isinstance(raw_tools, list):
        tool_names = [str(t).strip() for t in raw_tools if str(t).strip()]
    elif isinstance(raw_tools, str):
        tool_names = [t.strip() for t in raw_tools.split(",") if t.strip()]
    else:
        tool_names = []

    return {
        "name": name,
        "description": description,
        "tools": tool_names,
        "model": model,
        "body": (body or "").strip(),
    }


def import_agents_from_dir(path: str, owner: Optional[str], db=None) -> List[Dict[str, object]]:
    """Import every `*.md` agent in `path` as a CrewMember for `owner`.

    Idempotent: upserts by (owner, name). Returns one result dict per file:
    {name, action: created|updated|skipped, tools, dropped_tools, error}.
    Pass `db` to reuse a session (tests); otherwise a SessionLocal is opened.
    """
    from core.database import SessionLocal, CrewMember

    if not path or not os.path.isdir(path):
        raise ValueError(f"not a directory: {path!r}")

    own_session = db is None
    if own_session:
        db = SessionLocal()

    results: List[Dict[str, object]] = []
    try:
        for entry in sorted(os.listdir(path)):
            if not entry.lower().endswith(".md"):
                continue
            fpath = os.path.join(path, entry)
            if not os.path.isfile(fpath):
                continue
            try:
                if os.path.getsize(fpath) > _MAX_AGENT_FILE_BYTES:
                    results.append({"name": entry, "action": "skipped", "error": "file too large"})
                    continue
                with open(fpath, "r", encoding="utf-8") as fh:
                    parsed = parse_agent_md(fh.read())
            except (OSError, UnicodeDecodeError) as e:
                results.append({"name": entry, "action": "skipped", "error": str(e)})
                continue

            name = parsed["name"]
            if not name or not parsed["body"]:
                results.append({"name": entry, "action": "skipped", "error": "missing name or body"})
                continue

            mapped, dropped = map_framework_tools(parsed["tools"])
            enabled_tools = json.dumps(mapped)

            existing = (
                db.query(CrewMember)
                .filter(CrewMember.owner == owner, CrewMember.name == name)
                .first()
            )
            if existing is not None:
                existing.personality = parsed["body"]
                existing.enabled_tools = enabled_tools
                existing.is_default_assistant = False
                action = "updated"
            else:
                db.add(CrewMember(
                    id=uuid.uuid4().hex,
                    owner=owner,
                    name=name,
                    personality=parsed["body"],
                    enabled_tools=enabled_tools,
                    model=None,           # inherit the caller's local model at dispatch time
                    endpoint_url=None,
                    is_default_assistant=False,
                    is_active=True,
                ))
                action = "created"

            results.append({
                "name": name,
                "action": action,
                "tools": mapped,
                "dropped_tools": dropped,
            })
        db.commit()
    finally:
        if own_session:
            db.close()

    return results
