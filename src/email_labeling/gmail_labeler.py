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
