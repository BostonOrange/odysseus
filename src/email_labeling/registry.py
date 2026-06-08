"""Per-owner dynamic email-label registry, backed by the scheduled_emails DB.

Stores the set of labels an owner's mailbox uses (seeded from the legacy fixed
tags, grown by the model) plus a queue of suggested-but-not-yet-created labels.
Owner-scoped so multi-user installs don't share taxonomies.
"""
import sqlite3
from datetime import datetime
from typing import List

from src.email_labeling.reconciler import normalize_label_name


def _conn():
    from routes.email_helpers import SCHEDULED_DB, _init_scheduled_db
    _init_scheduled_db()
    return sqlite3.connect(SCHEDULED_DB)


class LabelRegistry:
    """Load/persist an owner's label set and suggestion queue."""

    def __init__(self, owner: str = ""):
        self.owner = owner or ""

    def list_names(self) -> List[str]:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT name FROM label_registry WHERE owner = ? ORDER BY name",
                (self.owner,),
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    def count(self) -> int:
        conn = _conn()
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM label_registry WHERE owner = ?", (self.owner,)
            ).fetchone()[0]
        finally:
            conn.close()

    def add(self, name: str, source: str = "model") -> bool:
        """Insert a label (idempotent by normalized name). Returns True if newly added."""
        norm = normalize_label_name(name)
        if not norm:
            return False
        conn = _conn()
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO label_registry (owner, name, normalized, source, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (self.owner, name.strip(), norm, source, datetime.utcnow().isoformat()),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def seed(self, names) -> None:
        for n in names:
            self.add(n, source="seed")

    def add_suggestion(self, name: str, message_id: str = "") -> None:
        """Record a proposed-but-not-created label, bumping its count on repeat."""
        sug = (name or "").strip()
        if not sug:
            return
        now = datetime.utcnow().isoformat()
        conn = _conn()
        try:
            cur = conn.execute(
                "UPDATE label_suggestions SET count = count + 1, last_seen = ?, "
                "example_message_id = COALESCE(NULLIF(example_message_id, ''), ?) "
                "WHERE owner = ? AND name = ?",
                (now, message_id, self.owner, sug),
            )
            if cur.rowcount == 0:
                conn.execute(
                    "INSERT INTO label_suggestions "
                    "(owner, name, example_message_id, count, first_seen, last_seen) "
                    "VALUES (?, ?, ?, 1, ?, ?)",
                    (self.owner, sug, message_id, now, now),
                )
            conn.commit()
        finally:
            conn.close()
