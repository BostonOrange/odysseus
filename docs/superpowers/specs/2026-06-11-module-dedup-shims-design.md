# SP-A — Module De-duplication (canonical + shim)

**Date:** 2026-06-11
**Status:** Approved (user delegated the decisions) — implementing
**Area:** `core/`, `src/`, `services/` module structure
**Branch:** `refactor/dedup-shims` (stacked on `fix/diverged-duplicates` / PR #8, off `dev`)

## Summary

Finish the de-duplication of the few module pairs that silently drifted, by
applying the codebase's **own** established single-source pattern: one canonical
module + a thin re-export shim, so two import paths can never diverge again.

## Background (from the assessment + a duplicate-pair scout)

Of 14 same-name module pairs across `core/` `src/` `services/`, **12 are already
safe**: 11 use a deliberate single-source pattern (`sys.modules` aliasing for
`src/search/*`, or `from X import *` shims like `src/database.py`→`core.database`
and `services/memory/memory.py`→`src.memory`), and 1 (`exceptions.py`) is
byte-identical. The `THREAT_MODEL.md` "Known Gaps" #3 claim that the search
submodules are "still independent copies" is **stale** — they are all aliased now.

Only **two** pairs genuinely drifted (both already had their *symptom* bugs fixed
in PR #8): `constants` and `youtube`. A third, `research_handler`, is **not** a
duplicate — see Out of Scope.

## Decisions

1. **Pattern:** canonical module + re-export shim (the existing precedent), never a
   second live copy.
2. **`constants` → core-canonical, `src` shim.** Matches `src/database.py`→`core.database`
   and respects layering (`src`→`core`, never `core`→`src`).
3. **`youtube` → `src`-canonical, `services` shim.** Matches `services/memory/memory.py`→`src.memory`
   (the app already imports `src.youtube_handler` on the hot path).
4. **`research_handler` is out of scope** (see below) — it is a parallel
   implementation decision, not a de-dup.

## Changes

### A1 — `constants`
- `core/constants.py`: add the three tool-output limits it lacks
  (`MAX_OUTPUT_CHARS`, `MAX_READ_CHARS`, `MAX_DIFF_LINES`) so it is a strict
  superset of `src/constants.py`. (APP_VERSION already synced to `1.0.0` in PR #8.)
- `src/constants.py`: replace the body with a `from core.constants import *` shim
  + explicit re-exports for IDE/type-checker visibility (mirroring `src/database.py`),
  keeping the module docstring.
- Safe: `core/constants.py` imports only `os` (no circular import); `BASE_DIR`
  resolves to the repo root from either file (both are one directory deep), so all
  derived paths are unchanged; all 20 `src.constants` importers keep working via `*`.

### A2 — `youtube`
- `src/youtube_handler.py` (canonical): add the two defensive guards the `services`
  copy had and `src` lacked — `extract_youtube_id`: `if not isinstance(url, str): return None`;
  `format_comments_for_context`: `if not isinstance(c, dict): continue`. (Union of
  both copies' guards; `src` already had the transcript dict-guard.)
- `services/youtube/youtube_handler.py`: replace with a re-export shim of
  `src.youtube_handler` (`import *` + explicit re-export of the 7 public functions
  `services/youtube/__init__.py` consumes).
- Delete `tests/test_youtube_svc_comments_timeout.py` (added in PR #8): it
  monkeypatches the `services` module's private internals, which a re-export shim
  cannot carry, and it is redundant with the canonical `tests/test_youtube_comments_timeout.py`.
  The remaining `services`-copy tests (`extract_id_nonstring`, `svc_comments_nondict`,
  `is_youtube_url_nonstring_svc`) call public functions through the shim and now
  also assert the guards landed in `src`.

### Doc
- `THREAT_MODEL.md` gap #3: correct the stale claim — the `src/search/*` submodules
  are consolidated via aliasing; the remaining drift was `constants`/`youtube`,
  resolved here.

## Out of scope — `research_handler` (a decision, not a de-dup)

`src/research_handler.py` is the live handler (instantiated by `src/app_initializer.py`
and injected into chat/research/diagnostics routes). `services/research/`
(`ResearchService` + its own `research_handler.py`) is a cleaner *parallel* stack
that has a unit test but **is not wired into the running app**. That is an
abandoned-migration decision — finish it, delete it, or leave it — and deleting a
tested subsystem is destructive and possibly premature. It is recorded here and
deferred to its own decision; SP-A does not touch it.

## Testing

- New `tests/test_module_dedup_equivalence.py`: assert that for each consolidated
  pair, the shim path and canonical path resolve to the **same object** for every
  public symbol (`src.constants.X is core.constants.X`; `services.youtube.youtube_handler.fn
  is src.youtube_handler.fn`), so future drift is impossible by construction.
- Existing `test_app_version_consistent.py`, the youtube nonstring/nondict tests,
  and the constants/tool-limit consumers all keep passing.
- Full suite as the regression net (≈2600 tests).

## Design-principles compliance

- **DRY / single source of truth** — the whole point.
- **No new patterns** — reuses the existing shim/aliasing convention already in the tree.
