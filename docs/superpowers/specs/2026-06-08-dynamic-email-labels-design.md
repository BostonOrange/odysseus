# Dynamic, Reasoning-Driven Email Labels — Design Spec

- **Date:** 2026-06-08
- **Status:** Approved design (pre-implementation)
- **Approach:** B — Label registry + deterministic reconciliation **+ embedding-similarity dedup**

## 1. Summary

Make the email labeler reasoning-driven and dynamic. On every unread email the model
**always reasons**, decides whether an **existing** label fits or a **new** topic label is
warranted, and the result is applied as **real Gmail labels** (via the IMAP `X-GM-LABELS`
extension) in addition to the internal triage tags. New-label creation is gated behind an
opt-in per-user setting; when off, novel proposals are parked for review instead of touching
the mailbox. The classifier is rebuilt so thinking cannot break its JSON output the way it
does today.

## 2. Goals / Requirements (decided during brainstorming)

1. **Label target:** real Gmail labels (account is `imap.gmail.com`, so `X-GM-LABELS` works
   over the existing IMAP connection — no separate OAuth integration), *in addition to* the
   internal `email_tags` store that already drives Odysseus's inbox UI.
2. **Creation control:** auto-create is **opt-in** — a per-user setting (default **off**).
   When off → reuse existing labels / park novel proposals as suggestions. When on →
   auto-create new labels with guardrails.
3. **Reasoning:** **always reason** (thinking on for every email). This makes JSON
   reliability a hard requirement (see §6) because thinking is exactly what broke labeling
   today (reasoning filled `reasoning_content`, left `content` empty, and `max_tokens=220`
   truncated before any JSON).
4. **Sprawl control:** near-duplicate proposals must be de-duplicated via embedding
   similarity, not just string matching.

## 3. Current State (for implementers)

- **Classifier:** `src/builtin_actions.py` `action_check_email_urgency` (~L1430-1998). Emits
  `{score, tags, spam, reason}` per email; validates tags against a fixed
  `CATEGORY_TAGS` set (L1474) and `MANAGED_TAGS` (L1479, used to purge/reapply system tags).
  LLM call at L1655 (`llm_call_async_with_fallback`, `max_tokens=220`); brittle parse at
  L1660-1678 reads only `content` → "model returned no JSON" (L1675) when no `{` present.
- **Second classifier path:** `routes/email_pollers.py` (~L834-894) has its own hardcoded
  tag list + `_ALLOWED_TAGS` validation. Must share the new logic.
- **Storage:** internal only — **no Gmail/IMAP label is ever applied today**.
  - SQLite `email_tags(message_id, owner, uid, folder, subject, sender, tags, spam_verdict,
    spam_reason, moved_to, model_used, created_at)` in `data/scheduled_emails.db`
    (`routes/email_helpers.py` ~L381-395).
  - Per-account cache `data/email_urgency_cache/{account.id}.json` (key `"{account.id}:{uid}"`).
  - Per-user state `data/email_urgency_state_{owner}.json`.
- **Scoping:** per-user + per-account; owner alias resolution in
  `routes/email_routes.py` `_email_tag_owner_aliases` / `_email_tag_owner_clause` (~L62-102).
- **Hardcoded tag locations to update:** `builtin_actions.py` L1474 (`CATEGORY_TAGS`),
  L1479 (`MANAGED_TAGS`), L1643-1644 (prompt); `email_pollers.py` L834-835 (prompt),
  L886-888 (`_ALLOWED_TAGS`); `promo→marketing` alias at `builtin_actions.py` L1689-1690,
  `email_routes.py` L705-706 + L783, `email_pollers.py` L893; frontend dropdown
  `static/js/emailLibrary.js` L913-918; task copy `static/js/tasks.js` L1103.
- **LLM helper gap:** no `response_format`/`json_schema` passthrough exists anywhere in
  `src/`. The call path must be extended to send a JSON schema + a larger token budget.
- **Embeddings:** `fastembed` (ONNX, `sentence-transformers/all-MiniLM-L6-v2`) is a core dep,
  already used server-side for RAG/memory (`FASTEMBED_MODEL`/`FASTEMBED_CACHE_PATH`). Reuse
  it for label-name similarity.

## 4. Modules (new `src/email_labeling/` package — isolated, separately testable)

- **`LabelRegistry`** — per-(owner) dynamic label set. Seeded once from the existing 13
  category tags + the labels already present on the Gmail account. Each entry: `name`,
  `normalized`, `source` (`seed`/`gmail`/`model`), cached `embedding`, `created_at`.
  Responsibilities: load/save, seed, lookup-by-normalized, list-for-prompt, enforce cap.
- **`ThinkingClassifier`** — calls the LLM with thinking **on**, a JSON **schema**
  (`response_format`), and an adequate budget (~1024 tokens). Returns validated
  `{score:int, spam:bool, reason:str, proposed_labels:[{name, believed_existing, confidence}]}`.
  Robust parse order: (1) `content`; (2) extract JSON object from `reasoning_content`;
  (3) one retry with thinking disabled (`enable_thinking:false`); (4) else mark failed.
- **`LabelReconciler`** — maps each proposed label to the registry: (a) normalized string
  match; (b) fastembed cosine ≥ `dedup_threshold` → reuse the matched existing label.
  Unmatched proposals → *create* (if allowed by §5) or *suggest*. Returns
  `{apply:[existing], create:[new], suggested:[new]}`. Pure/deterministic given inputs.
- **`GmailLabeler`** — applies resolved labels to the message via
  `UID STORE <uid> +X-GM-LABELS (<label> ...)` on the existing IMAP connection (Gmail
  auto-creates a label on first apply). Mirrors applied labels into `email_tags`. No-op when
  the account is not Gmail (falls back to internal-only).

Both classifier paths call a single shared `classify_and_label(email, ctx)` service so the
duplication between `builtin_actions.py` and `email_pollers.py` ends.

## 5. Data model & settings

New tables in `data/scheduled_emails.db` (owner-scoped, consistent with `email_tags`):

```sql
CREATE TABLE label_registry (
  owner TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL,
  normalized TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'model',   -- seed | gmail | model
  embedding BLOB,                         -- cached fastembed vector (nullable)
  created_at TEXT,
  PRIMARY KEY (owner, normalized)
);

CREATE TABLE label_suggestions (
  owner TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL,
  example_message_id TEXT,
  count INTEGER DEFAULT 1,
  first_seen TEXT,
  last_seen TEXT,
  PRIMARY KEY (owner, name)
);
```

New per-user settings (defaults chosen for safety):
- `email_auto_create_labels` (bool, **default false**)
- `email_label_cap` (int, default 50)
- `email_label_confidence_min` (float, default 0.7)
- `email_label_dedup_cosine` (float, default 0.85)
- `email_label_new_per_run` (int, default 3) — per-run new-label budget

`email_tags` is unchanged in shape; tag values are now dynamic.

## 6. Per-email flow

1. Scan unread (existing IMAP scan, unchanged window).
2. **ThinkingClassifier** → schema JSON (always reasons; robust parse per §4).
3. **LabelReconciler** matches proposals to the registry (string → embedding).
4. Apply matched/approved labels to Gmail via `X-GM-LABELS`; write `email_tags`. The
   urgency **score stays internal** (not a Gmail label in v1).
5. Unmatched proposals:
   - setting **on** + guardrails pass → create in Gmail, register, apply.
   - setting **off** (or guardrail fails) → upsert into `label_suggestions`.

**Guardrails (auto-create on):** create only if `confidence ≥ email_label_confidence_min`
**and** max cosine to any existing label `< email_label_dedup_cosine` (else reuse that label)
**and** registry size `< email_label_cap` **and** new labels this run `< email_label_new_per_run`.

## 7. Settings / UI

- Toggle: "Let the labeler create new Gmail labels" (+ optional cap).
- "Suggested labels" review list: **approve** → promote to `label_registry` and backfill-apply
  to the example message; **dismiss** → ignore-list so it is not re-suggested.
- Frontend tag filter dropdown (`emailLibrary.js`) becomes data-driven from a
  `GET` labels endpoint instead of hardcoded `<option>`s.

## 8. Error handling

- **JSON:** schema-constrained + `reasoning_content` fallback + one thinking-off retry, then
  fail. Structurally fixes today's bug.
- **Gmail `STORE` failure:** keep the internal tag, log, continue the batch; retried next run.
- **Embeddings unavailable:** degrade to normalized-string dedup only.
- **Idempotency:** re-applying an existing label is a no-op; `label_registry` PK on
  `(owner, normalized)` prevents duplicate creation; `label_suggestions` upserts by count.

## 9. Testing

- **Unit:** Reconciler decisions across settings/thresholds (match / create / suggest);
  Registry seed/dedup/cap; ThinkingClassifier parse (`content` / `reasoning_content` /
  empty→retry); name normalization; `promo→marketing`-style aliases preserved.
- **Integration (mock LLM + IMAP):** setting-off → suggestion, **no** `X-GM-LABELS`;
  setting-on + near-duplicate → reuse existing; setting-on + novel + guardrails → `X-GM-LABELS`
  STORE issued and registry updated. Reuse existing owner-scope test patterns
  (`tests/test_builtin_actions_owner_scope.py`, `tests/test_email_owner_scope.py`).

## 10. Out of scope (v1)

- Urgency score / `urgent` / `reply-soon` are **not** pushed to Gmail (internal only).
- Non-Gmail IMAP accounts → internal-only labeling (no `X-GM-LABELS`).
- No bulk re-labeling of historical mail (only the existing unread-scan window).

## 11. Risks / open items

- `llm_call_async_with_fallback` must learn `response_format` + per-call `max_tokens`; verify
  the llama.cpp endpoint honors `response_format: {type:"json_schema"}` with thinking on
  (request-level `enable_thinking:false` fallback is already verified to produce clean JSON).
- Seeding from existing Gmail labels requires one `LIST`/`X-GM-LABELS` read of the account at
  first run; large label sets should be capped/paged.
- Embedding the registry adds a one-time cost per new label; cache vectors in `label_registry`.
