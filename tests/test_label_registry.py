import sqlite3
import pytest
import src.email_labeling.registry as reg


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import routes.email_helpers as eh
    db = tmp_path / "sched.db"
    monkeypatch.setattr(eh, "SCHEDULED_DB", db)
    return db


def test_seed_and_list_dedup(temp_db):
    r = reg.LabelRegistry("alice")
    r.seed(["Work", "Finance", "Work"])
    assert sorted(r.list_names()) == ["Finance", "Work"]
    assert r.count() == 2


def test_add_idempotent_by_normalized(temp_db):
    r = reg.LabelRegistry("alice")
    assert r.add("Job Hunt") is True
    assert r.add("job hunt") is False
    assert r.count() == 1


def test_owner_scoped(temp_db):
    reg.LabelRegistry("alice").add("Work")
    reg.LabelRegistry("bob").add("Cooking")
    assert reg.LabelRegistry("alice").list_names() == ["Work"]
    assert reg.LabelRegistry("bob").list_names() == ["Cooking"]


def test_suggestion_upsert_keeps_first_example(temp_db):
    r = reg.LabelRegistry("alice")
    r.add_suggestion("travel", "msg1")
    r.add_suggestion("travel", "msg2")
    conn = sqlite3.connect(temp_db)
    try:
        row = conn.execute(
            "SELECT count, example_message_id FROM label_suggestions "
            "WHERE owner='alice' AND name='travel'"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == 2
    assert row[1] == "msg1"
