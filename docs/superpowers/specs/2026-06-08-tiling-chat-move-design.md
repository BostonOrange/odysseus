# Tiling Canvas — Phase 2b: Movable (Hybrid) Chat

**Date:** 2026-06-08
**Status:** Approved design, pending implementation plan
**Builds on:** Phase 1 (PR #1, unified tiling canvas) + Phase 2a (PR #2, resize seams)
**Area:** Front-end layout (`static/js/tileManager.js`, `static/style.css`)

## Summary

Today the chat is a purely *reactive* fill tile — it auto-occupies the largest free
rectangle and cannot be grabbed. Phase 2b makes it a **hybrid**: drag the chat's
top bar to snap it into a zone of your choosing (it becomes a pinned tile that tools
tile around), and if you never place it, it keeps auto-filling exactly as today.
Dragging a pinned chat away reverts it to auto-fill.

This completes the user's original "I wish I could move the chat too" request (the
resize half shipped in Phase 2a).

## Goals

- Drag the chat by its `.chat-top-bar` to any snap zone (halves / quarters /
  maximize / fullscreen), reusing the existing ghost preview + snap animation.
- A *placed* chat is **pinned**: fixed to its zone; tools tile around it; leftover
  space is empty canvas.
- An *unplaced* chat keeps today's reactive auto-fill behavior, unchanged.
- Drag a pinned chat away → it reverts to auto-fill.
- Resize seams (Phase 2a) work between a pinned chat and tools with no extra code.

## Non-Goals (YAGNI)

- **Persisting** the pinned placement across reload — consistent with tool windows,
  which don't persist their tiled state yet; deferred to a future layout-persistence
  phase.
- A separate chat-drag system, new layout math, or a dedicated grip element (the top
  bar is the handle).
- Mobile drag — chat stays full-screen below 768px (existing guard).

## Decisions (from brainstorming)

1. **Hybrid model:** grab handle to place; auto-fill until placed (chosen in the
   Phase 2 brainstorm).
2. **Handle = the existing `.chat-top-bar`** (window-title-bar pattern, like tool
   windows drag by `.modal-header`), with a 'move' cursor + subtle grip affordance.
   Its buttons stay clickable.

## Architecture

The whole feature reuses Phase 1's snap engine. The **pinned marker is simply
`dataset._tileZone` set on `#chat-container`** — the same attribute tools use. Five
small touch points in `static/js/tileManager.js`:

1. **`_findDragTarget(e)`** — currently matches `.modal-header` inside
   `.modal, .research-overlay`. Extend it: if the event target is inside a
   `.chat-top-bar` that lives inside `#chat-container` (and not on a button), return
   `#chat-container` as the draggable content. Then the existing global
   `pointerdown`/`pointermove`/`pointerup` handlers drive the chat drag: ghost
   preview via `_zoneForContent`, snap via `_applySnap`, drag-away via `_unsnap` —
   all unchanged. (`_zoneForContent` applies no per-modal restriction to the chat
   because `content.closest('.modal, .research-overlay')` is null for it.)

2. **`_applySnap` / `_unsnap` reused as-is.** Snapping the chat sets
   `chat.dataset._tileZone` and stashes `_tilePreSnap`; dragging away clears them.
   The pointerdown `willUnsnap` check (`if (content.dataset._tileZone)`) already
   makes a pinned chat un-pin on drag and re-snap elsewhere.

3. **`_reflowChat`** — add one branch at the top (after the mobile guard): if
   `chat.dataset._tileZone` is set, the chat is PINNED — clamp it to
   `_rectForZone(chat.dataset._tileZone)` (with `!important`, same property set as
   the fill path), reposition seams, and return. Otherwise run today's
   `largestFreeRect` fill path. This makes `_reflowChat` the single owner of chat
   geometry in both modes.

4. **`_ownerGrid`** (Phase 2a) — only assign the `freeCellsForChat(...)` cells to
   `'chat'` when the chat is **unpinned**. Guard: read
   `chatEl = document.getElementById('chat-container')`; do the fill-assignment only
   if `chatEl && !chatEl.dataset._tileZone`. When pinned, the chat already appears in
   the `[data-_tile-zone]` query (owner id `chat-container`), so seams between it and
   tools work automatically and empty cells stay unowned.

5. **`_reclampAll`** — exclude `#chat-container` from its re-clamp loop selector
   (alongside the existing `:not(#doc-editor-pane)`), because `_reflowChat` owns the
   chat's geometry (it is called at the end of `_reclampAll`). Without the exclusion
   the chat would be clamped twice (harmless, but the exclusion keeps one owner).

Plus **CSS**: on `.chat-top-bar`, `cursor: move` and a subtle grip affordance
(e.g. a small `⋮⋮`-style handle via a pseudo-element or a low-opacity icon), desktop
only. Buttons inside keep their own cursor.

## Data flow

- **Place chat:** drag top bar → ghost shows target zone → release → `_applySnap`
  sets `chat.dataset._tileZone` + clamps geometry → `_reflowChat` (pinned branch)
  holds it there → tools tile into other zones via their own snaps → `_ownerGrid`
  no longer fills empty cells with chat → seams appear at real chat/tool boundaries.
- **Un-pin chat:** drag pinned chat away → `_unsnap` clears `dataset._tileZone` →
  `_reflowChat` (fill branch) recomputes `largestFreeRect` → chat returns to fill.

## Edge cases / error handling

- **Mobile (≤768px):** `_isDesktop()` guards the global drag handlers and
  `_reflowChat` (mobile branch strips inline styles); the chat stays full-screen and
  the top-bar drag is inert. A pinned zone set on desktop is simply not applied on
  mobile; it resumes when the viewport grows back.
- **Pinned chat + a tool maximizes:** the tool occupies all cells; `_reflowChat`
  pinned branch still clamps the chat to its zone, but the maximized tool sits above
  it — consistent with how maximize covers the canvas. When the tool un-snaps, the
  chat is visible again in its zone.
- **Click vs drag on the top bar:** the existing 6px move threshold + button-skip in
  the pointer handlers mean a click (rename, export, etc.) never starts a drag.
- **Snapping the chat when nothing else is tiled:** allowed — chat pins to e.g.
  right-half, left stays empty canvas. That is the point of manual placement.

## Testing

- **Unit:** none new — the pure `tileLayout` core is unchanged; pinned-chat geometry
  reuses `_rectForZone` → `rectForCells`, already covered by Phase 2a tests. Run the
  existing suite to confirm no regression (`tests/test_tile_layout_js.py`, 14/14).
- **`node --check`** on `tileManager.js`.
- **Manual matrix (browser):** grab the chat top bar → ghost preview → snap to each
  zone (halves, quarters, maximize) → chat pinned there; open a tool and snap it →
  it tiles around the pinned chat; drag a vertical/horizontal seam between pinned
  chat and tool → both rebalance (Phase 2a); drag the pinned chat away → reverts to
  auto-fill; top-bar buttons still click; resize viewport + toggle sidebar → pinned
  chat re-clamps; mobile → top-bar drag inert, chat full-screen.

## Design-principles compliance

- **No magic numbers:** reuses existing constants; the only literal is the CSS grip
  size, a local style value.
- **Generalized/reusable:** pinning the chat is "the chat is a tile" — it routes
  through the same `_applySnap`/`_unsnap`/`_rectForZone`/seam machinery as tools, with
  no parallel code path.
