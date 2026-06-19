"""Tests for the framework-agent importer (agent-dispatch Phase A task 2)."""
import json

import pytest

from services.agents.agent_importer import (
    parse_agent_md,
    map_framework_tools,
    import_agents_from_dir,
)

_CODE_REVIEWER = """---
name: code-reviewer
description: Reviews code changes for bugs and security issues
tools: Read, Glob, Grep, Bash
model: opus
---
# Code Reviewer

You are a senior code reviewer. Analyze the diff.
"""

_COORDINATOR = """---
name: build-coordinator
description: Orchestrates the build by spawning sub-agents
tools: Read, Agent, TodoWrite
model: opus
---
You coordinate the build. Spawn specialists as needed.
"""


# --- parse_agent_md ---------------------------------------------------------

def test_parse_agent_md_basic():
    p = parse_agent_md(_CODE_REVIEWER)
    assert p["name"] == "code-reviewer"
    assert "bugs and security" in p["description"]
    assert p["tools"] == ["Read", "Glob", "Grep", "Bash"]
    assert p["model"] == "opus"
    assert p["body"].startswith("# Code Reviewer")


def test_parse_agent_md_tolerates_missing_fields():
    p = parse_agent_md("---\nname: x\n---\nbody here")
    assert p["name"] == "x"
    assert p["tools"] == []
    assert p["description"] == ""
    assert p["body"] == "body here"


def test_parse_agent_md_no_frontmatter():
    p = parse_agent_md("just a body, no frontmatter")
    assert p["name"] == ""
    assert p["body"] == "just a body, no frontmatter"


# --- map_framework_tools ----------------------------------------------------

def test_map_framework_tools_basic():
    mapped, dropped = map_framework_tools(["Read", "Glob", "Grep", "Bash"])
    assert mapped == ["read_file", "glob", "grep", "bash"]
    assert dropped == []


def test_map_framework_tools_agent_maps_to_dispatch():
    mapped, dropped = map_framework_tools(["Read", "Agent", "Task"])
    assert "dispatch_agent" in mapped
    # Agent + Task both map to dispatch_agent, de-duplicated
    assert mapped.count("dispatch_agent") == 1


def test_map_framework_tools_drops_unknown():
    mapped, dropped = map_framework_tools(["Read", "TodoWrite", "NotebookEdit"])
    assert mapped == ["read_file"]
    assert dropped == ["TodoWrite", "NotebookEdit"]


def test_map_framework_tools_empty():
    assert map_framework_tools([]) == ([], [])


# --- import_agents_from_dir (DB-backed, isolated engine) ---------------------

@pytest.fixture
def db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from core.database import Base

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


def _write_agents(tmp_path):
    (tmp_path / "code-reviewer.md").write_text(_CODE_REVIEWER, encoding="utf-8")
    (tmp_path / "build-coordinator.md").write_text(_COORDINATOR, encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not an agent", encoding="utf-8")  # ignored


def test_import_creates_crew_members(tmp_path, db_session):
    from core.database import CrewMember
    _write_agents(tmp_path)

    results = import_agents_from_dir(str(tmp_path), owner="alice", db=db_session)

    assert {r["name"] for r in results} == {"code-reviewer", "build-coordinator"}
    assert all(r["action"] == "created" for r in results)

    rows = db_session.query(CrewMember).filter(CrewMember.owner == "alice").all()
    assert len(rows) == 2
    cr = next(r for r in rows if r.name == "code-reviewer")
    assert cr.is_default_assistant is False
    assert cr.model is None  # inherits caller's model at dispatch
    assert json.loads(cr.enabled_tools) == ["read_file", "glob", "grep", "bash"]
    assert cr.personality.startswith("# Code Reviewer")

    coord = next(r for r in rows if r.name == "build-coordinator")
    assert "dispatch_agent" in json.loads(coord.enabled_tools)


def test_reimport_upserts_without_duplicating(tmp_path, db_session):
    from core.database import CrewMember
    _write_agents(tmp_path)

    import_agents_from_dir(str(tmp_path), owner="alice", db=db_session)
    # Change a file, re-import
    (tmp_path / "code-reviewer.md").write_text(
        _CODE_REVIEWER.replace("Analyze the diff.", "Analyze the diff CAREFULLY."),
        encoding="utf-8",
    )
    results = import_agents_from_dir(str(tmp_path), owner="alice", db=db_session)

    assert all(r["action"] == "updated" for r in results)
    rows = db_session.query(CrewMember).filter(CrewMember.owner == "alice").all()
    assert len(rows) == 2  # no duplicates
    cr = next(r for r in rows if r.name == "code-reviewer")
    assert "CAREFULLY" in cr.personality


def test_import_rejects_bad_path(db_session):
    with pytest.raises(ValueError):
        import_agents_from_dir("/no/such/dir", owner="alice", db=db_session)
