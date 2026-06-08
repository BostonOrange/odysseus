# Plan 2 — Dynamic Label Registry + Reconciliation (internal-only) (of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** Replace the fixed 13-tag taxonomy with a per-owner dynamic label registry. The classifier proposes labels; a reconciler reuses an existing label, creates a new one (only when the opt-in setting is on and guardrails pass), or queues a suggestion. Internal `email_tags` only — **no Gmail writes** (that's Plan 3).

**Architecture:** Pure `reconciler` (string + injected embedding dedup) + `LabelRegistry` (sqlite, owner-scoped) + new settings + an embed adapter over `src/embeddings.py`. The urgency classifier's prompt grows a `proposed_labels` field; verdicts route through the reconciler.

**Tech Stack:** Python 3.12/3.13, sqlite3, fastembed (`src/embeddings.py`), pytest.

**Verify with `pytest` only. Do not run the llama serve.** Live behavior (model proposing labels) is the user's final test.

---

## Task 1 — Reconciler ✅ DONE

`src/email_labeling/reconciler.py` (`normalize_label_name`, `reconcile`, pure-Python `_cosine`) + `tests/test_label_reconciler.py` (10 tests, passing). Decides apply/create/suggest with guardrails: exact-match → reuse; embedding cosine ≥ `dedup_cosine` → reuse; else create (if `auto_create` AND `confidence ≥ confidence_min` AND under `cap` AND under `new_per_run`) else suggest.

---

## Task 2 — Settings keys

**Files:** Modify `src/settings.py` — add to `DEFAULT_SETTINGS` and `_PER_USER_KEYS`.

- [ ] Add to `DEFAULT_SETTINGS` (defaults chosen safe; auto-create OFF):

```python
    "email_auto_create_labels": False,
    "email_label_cap": 50,
    "email_label_confidence_min": 0.7,
    "email_label_dedup_cosine": 0.85,
    "email_label_new_per_run": 3,
```

- [ ] Add `"email_auto_create_labels"` to `_PER_USER_KEYS` (the rest stay global).
- [ ] Test `tests/test_email_label_settings.py`: `from src.settings import get_setting; assert get_setting("email_auto_create_labels") is False; assert get_setting("email_label_cap") == 50`.
- [ ] Run `pytest tests/test_email_label_settings.py -v`; commit.

---

## Task 3 — Registry tables + `LabelRegistry`

**Files:** Modify `routes/email_helpers.py` `_init_scheduled_db()`; Create `src/email_labeling/registry.py`; Test `tests/test_label_registry.py`.

- [ ] In `_init_scheduled_db()`, after the `email_tags` `CREATE TABLE`, add:

```python
    conn.execute("""
        CREATE TABLE IF NOT EXISTS label_registry (
            owner TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL,
            normalized TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'model',
            created_at TEXT,
            PRIMARY KEY (owner, normalized)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS label_suggestions (
            owner TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL,
            example_message_id TEXT,
            count INTEGER DEFAULT 1,
            first_seen TEXT,
            last_seen TEXT,
            PRIMARY KEY (owner, name)
        )
    """)
    conn.commit()
```

- [ ] `src/email_labeling/registry.py` — `LabelRegistry(owner)` with: `seed(names)` (insert-or-ignore with `source='seed'`), `list_names() -> list[str]`, `add(name, source='model')`, `count()`, `add_suggestion(name, message_id)` (upsert count++). Uses `sqlite3.connect(SCHEDULED_DB)` + `_init_scheduled_db()` (import from `routes.email_helpers`). `normalized` via `reconciler.normalize_label_name`.
- [ ] Tests use a temp DB (monkeypatch `SCHEDULED_DB`) — seed 13 tags, assert `list_names`, assert dup `add` is idempotent, assert `add_suggestion` increments `count`.
- [ ] Run; commit.

---

## Task 4 — Embed adapter

**Files:** Create `src/email_labeling/embed.py`; Test `tests/test_label_embed.py` (skips if fastembed absent).

- [ ] `embed_names(names: list[str]) -> list[list[float]]` wrapping `from src.embeddings import get_embedding_client; get_embedding_client().encode(names)` → `.tolist()`. Catches import/runtime errors → returns `None` (reconciler then falls back to string-only). Memoize the client.
- [ ] Test: `pytest.importorskip("fastembed")`; assert `len(embed_names(["work","cooking"])) == 2` and vectors are non-empty.
- [ ] Run; commit.

---

## Task 5 — Wire classifier → reconciler (proposes labels; applies internally)

**Files:** Modify `src/builtin_actions.py` (prompt + per-email flow in `action_check_email_urgency`).

- [ ] Extend the classifier prompt to additionally request:
  `"labels": [{"name": "<short topic label, lowercase>", "confidence": 0..1}]` — "reuse one of these existing labels when it fits: <registry list>; only propose a new name when none fit."
- [ ] After `normalize_verdict`, read settings (`get_user_setting`/`get_setting` for the 5 keys, owner-scoped), load `LabelRegistry(owner)` (seed from `CATEGORY_TAGS` on first run), call `reconcile(obj.get("labels") or [], registry.list_names(), embed_fn=embed_names, **settings)`.
- [ ] `apply` + `create` → merge into the verdict `tags`; `create` → `registry.add(...)`; `suggest` → `registry.add_suggestion(...)`. Existing internal `email_tags` mirror (L1767+) then stores them. **No Gmail calls.**
- [ ] Tests: monkeypatch `classify_email_json` to return a fixed `labels` payload + a temp registry/DB; assert created labels land in `email_tags` and suggestions table. Run `pytest tests/ -k "label or urgency"`; commit.

> Live check (user, with serve up): run Email Tags; confirm sensible topic labels appear and the suggestions list populates when auto-create is off.

---

## Self-Review
- Spec coverage: registry (§5), reconciler+embeddings (§4 Approach B), settings + suggestions (§5/§7), classifier proposes labels (§6). Gmail application is Plan 3 (out of scope here, per spec §6/§10).
- No placeholders in Task 1 (implemented); Tasks 2-5 carry exact code/anchors from the verified API reference.
