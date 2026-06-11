"""Tests for the dispatch_agent tool handler (agent-dispatch Phase A task 3)."""
import asyncio
import json

import pytest

import src.agent_dispatch as ad


@pytest.fixture
def seeded_db(monkeypatch):
    """An isolated DB with one agent, wired in as core.database.SessionLocal."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import core.database as cdb
    from core.database import Base, CrewMember

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(CrewMember(
        id="a1", owner="alice", name="code-reviewer",
        personality="You are a reviewer.",
        enabled_tools=json.dumps(["read_file", "grep"]),
        model="m", endpoint_url="http://x", is_default_assistant=False,
    ))
    s.commit()
    s.close()
    monkeypatch.setattr(cdb, "SessionLocal", Session)
    return Session


def test_dispatch_runs_named_agent(seeded_db, monkeypatch):
    captured = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        return "review done"

    monkeypatch.setattr(ad, "run_agent_text", fake_run)
    out = asyncio.run(ad.do_dispatch_agent("code-reviewer\nreview auth.py", owner="alice"))

    assert out == {"agent": "code-reviewer", "result": "review done"}
    assert captured["system_prompt"] == "You are a reviewer."
    assert captured["user_message"] == "review auth.py"
    assert captured["endpoint_url"] == "http://x"
    assert captured["session_id"] is None  # isolated from the parent session
    # enabled {read_file, grep} -> those are NOT in the inverted disabled set
    assert "read_file" not in captured["disabled_tools"]
    assert "grep" not in captured["disabled_tools"]
    assert "bash" in captured["disabled_tools"]


def test_dispatch_case_insensitive_name(seeded_db, monkeypatch):
    async def fake_run(**kwargs):
        return "ok"

    monkeypatch.setattr(ad, "run_agent_text", fake_run)
    out = asyncio.run(ad.do_dispatch_agent("Code-Reviewer\ndo it", owner="alice"))
    assert out["result"] == "ok"


def test_dispatch_unknown_agent(seeded_db):
    out = asyncio.run(ad.do_dispatch_agent("ghost\ndo it", owner="alice"))
    assert "error" in out and "ghost" in out["error"]


def test_dispatch_requires_name_and_task(seeded_db):
    assert "error" in asyncio.run(ad.do_dispatch_agent("", owner="alice"))
    assert "error" in asyncio.run(ad.do_dispatch_agent("code-reviewer", owner="alice"))


def test_dispatch_depth_cap(seeded_db, monkeypatch):
    async def fake_run(**kwargs):
        return "x"

    monkeypatch.setattr(ad, "run_agent_text", fake_run)
    token = ad._dispatch_depth.set(ad.MAX_AGENT_DEPTH)
    try:
        out = asyncio.run(ad.do_dispatch_agent("code-reviewer\ntask", owner="alice"))
    finally:
        ad._dispatch_depth.reset(token)
    assert "error" in out and "depth" in out["error"].lower()
