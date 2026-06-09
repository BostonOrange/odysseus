"""Apply labels to a Gmail message over IMAP via the ``X-GM-LABELS`` extension.

Gmail exposes labels through IMAP: ``UID STORE <uid> +X-GM-LABELS (<labels>)``
adds labels (auto-creating any that don't exist). This module is the ONLY place
that writes to the real mailbox, so it is:
  - gated by the caller behind an opt-in setting (``email_apply_gmail_labels``),
  - a no-op for non-Gmail hosts,
  - exception-safe (never raises into the triage loop),
  - unit-tested against a fake connection (no real Gmail in tests).
"""
import logging

logger = logging.getLogger(__name__)


def is_gmail_host(host: str) -> bool:
    """True for Gmail IMAP hosts (only there does X-GM-LABELS exist)."""
    return "gmail" in (host or "").lower()


def _quote_label(name: str) -> str:
    """Quote one label for an X-GM-LABELS list. Labels may contain spaces, so
    wrap in double quotes and backslash-escape backslashes and quotes."""
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def apply_gmail_labels(conn, uid, labels) -> bool:
    """Add ``labels`` to message ``uid`` via ``UID STORE +X-GM-LABELS``.

    conn:   an authenticated imaplib IMAP4 connection (Gmail).
    uid:    the message UID (str/int).
    labels: iterable of label names.

    Returns True only on an ``OK`` store. Never raises — a mailbox/IMAP error
    must not break the surrounding classification loop.
    """
    names = [str(l).strip() for l in (labels or []) if str(l).strip()]
    if not names:
        return False
    label_list = "(" + " ".join(_quote_label(n) for n in names) + ")"
    try:
        typ, _data = conn.uid("STORE", str(uid), "+X-GM-LABELS", label_list)
        return typ == "OK"
    except Exception as e:
        logger.warning("apply_gmail_labels failed for uid %s: %s", uid, e)
        return False


def apply_labels_for_account(connect_fn, items, per_uid_scores, *, enabled, imap_host) -> int:
    """Apply each freshly-classified item's tags to Gmail for one account.

    No-op (returns 0) unless ``enabled`` AND the account is a Gmail host. Opens
    ONE writable IMAP session via ``connect_fn()``, STOREs +X-GM-LABELS per
    message, then logs out. Never raises — a mailbox error must not break triage.

    items:          per-account scan results (dicts with "uid", "key", optional "cached").
    per_uid_scores: {key: verdict}; verdict["tags"] are the labels to apply.
    Returns the count of messages a label STORE succeeded on.
    """
    if not enabled or not is_gmail_host(imap_host):
        return 0
    to_label = [
        (it["uid"], (per_uid_scores.get(it.get("key")) or {}).get("tags") or [])
        for it in items
        if not it.get("cached") and it.get("uid")
    ]
    to_label = [(uid, tags) for uid, tags in to_label if tags]
    if not to_label:
        return 0
    applied = 0
    try:
        conn = connect_fn()
        try:
            conn.select("INBOX")
            for uid, tags in to_label:
                if apply_gmail_labels(conn, uid, tags):
                    applied += 1
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception as e:
        logger.warning("apply_labels_for_account failed (%s): %s", imap_host, e)
    return applied
