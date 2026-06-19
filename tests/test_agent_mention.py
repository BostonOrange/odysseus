"""Tests for @agent-name mention parsing (agent-dispatch Phase A task 5)."""
from src.agent_dispatch import parse_agent_mention


def test_parses_basic_mention():
    assert parse_agent_mention("@code-reviewer review auth.py") == ("code-reviewer", "review auth.py")


def test_strips_leading_whitespace():
    assert parse_agent_mention("   @architect do the thing") == ("architect", "do the thing")


def test_multiline_task_is_kept():
    name, task = parse_agent_mention("@planner plan this:\n- step one\n- step two")
    assert name == "planner"
    assert "step one" in task and "step two" in task


def test_no_mention_returns_none():
    assert parse_agent_mention("hello there") is None
    assert parse_agent_mention("") is None
    assert parse_agent_mention(None) is None


def test_at_not_at_start_is_not_a_mention():
    assert parse_agent_mention("please email me @ the office") is None


def test_name_without_task_is_not_a_mention():
    assert parse_agent_mention("@code-reviewer") is None
    assert parse_agent_mention("@code-reviewer   ") is None
