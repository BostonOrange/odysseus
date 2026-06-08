# Plan 3 — Gmail Application + Suggestion UI (of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** Apply the reconciled labels to the real Gmail mailbox (via IMAP `X-GM-LABELS`), and give the user a way to review/approve suggested labels and filter by the now-dynamic tag set.

**Architecture:** A small `gmail_labeler` writes labels over the existing IMAP path, gated behind an opt-in setting. New API endpoints expose the registry + suggestion queue; the inbox filter dropdown and a suggestions panel consume them.

**Safety:** Gmail writes are OFF by default (`email_apply_gmail_labels`). The write function is exception-safe and a no-op for non-Gmail hosts.

**Tasks 2-4 touch the real mailbox / need the live serve — do them WITH the user, not on autopilot.**

---

## Task 1 — Gmail label writer + opt-in gate ✅ DONE

- `src/email_labeling/gmail_labeler.py` — `apply_gmail_labels(conn, uid, labels)` issues `UID STORE <uid> +X-GM-LABELS (...)` (quoted/escaped), returns bool, never raises; `is_gmail_host(host)`. `tests/test_gmail_labeler.py` (6 tests, fake connection).
- Setting `email_apply_gmail_labels` (default **False**) + per-user, in `src/settings.py`.

---

## Task 2 — Wire application into the urgency action  ⚠️ needs real Gmail + serve

**Wrinkle:** `action_check_email_urgency` scans IMAP inside `_scan_one` (a threaded helper that `conn.logout()`s) and classifies AFTER the connection is closed. To apply labels you must either (a) apply during the scan once the verdict exists, or (b) reopen a short IMAP session keyed by `(account, uid)` after classification.

- [ ] Capture per-account `imap_host` + a way to reopen the connection (reuse `_get_email_config` / the same connect code `_scan_one` uses).
- [ ] After the dynamic-label step, when `get_user_setting("email_apply_gmail_labels", owner)` is true AND `is_gmail_host(account.imap_host)`: open IMAP, select the folder, `apply_gmail_labels(conn, uid, final_tags)`, logout. Batch per account to avoid many logins.
- [ ] Guard everything (a Gmail failure must not break triage or the internal `email_tags` write).
- [ ] Test with a fake IMAP/connect monkeypatch: assert STORE issued only when the setting is on and host is Gmail; assert no-op otherwise.
- **Live check (user):** enable the setting, run Email Tags on a couple of test messages, confirm the labels appear in Gmail.

---

## Task 3 — Registry + suggestions API

- [ ] `GET /api/email/labels` → the owner's registry names (for the dropdown).
- [ ] `GET /api/email/label-suggestions` → pending suggestions (name, count, example).
- [ ] `POST /api/email/label-suggestions/approve` {name} → promote to `label_registry` (source `approved`), backfill-apply to the example message if Gmail-apply is on, delete the suggestion.
- [ ] `POST /api/email/label-suggestions/dismiss` {name} → drop it + remember an ignore-list so it isn't re-suggested.
- [ ] Owner-scope every query via `_email_tag_owner_clause`. Tests with a temp DB.

---

## Task 4 — Frontend

- [ ] `static/js/emailLibrary.js` (~L913-918): replace the hardcoded `<option>` tag list with a fetch of `GET /api/email/labels` (keep urgent/reply-soon/spam pinned at top).
- [ ] Suggestions panel: list pending suggestions with Approve / Dismiss buttons calling Task 3's endpoints.
- [ ] Update the task description copy in `static/js/tasks.js:1103` to reflect dynamic labels.

---

## Self-Review
- Spec coverage: Gmail application (§6 step 4, §2), suggestion review (§7), dynamic dropdown (§7). Task 1 implemented + tested; Tasks 2-4 carry exact anchors and are gated behind the off-by-default setting.
- Risk: Task 2's IMAP-reopen is the one architectural unknown — confirm the connect/credential path before coding it.
