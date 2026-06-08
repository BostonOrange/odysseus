# Unified Tiling Canvas — Phase 1 Design

**Date:** 2026-06-08
**Status:** Approved design, pending implementation plan
**Area:** Front-end window/layout management (`static/js/`, `static/style.css`, chat markup)

## Summary

Replace the current two-system layout model — "edge-dock" (a tool pushes/reshapes
the chat via body margins) and "tile-snap" (a tool floats over the chat) — with a
single **tiling canvas**. The region right of the sidebar/rail becomes a canvas on
which windows tile. The **chat is demoted from a fixed background to a reactive
"fill" tile**: it always occupies the largest free rectangle and reflows as tools
are snapped, un-snapped, or closed.

This eliminates the dock-vs-tile duality that makes current snapping behavior
inconsistent ("drag right pushes the chat, but how do the others work?").

## Goals

- One uniform layout model: everything tiles against everything else.
- Chat requires zero management — it auto-fills leftover space; the common
  "just chat, fullscreen" case is unchanged (chat fills the whole canvas when
  nothing else is tiled).
- Snapping a tool to a zone reflows the chat into the complementary space as a
  **true tile** (no margin push).
- Full set of snap zones: left/right/top/bottom halves, four corner quarters,
  maximize, fullscreen.
- Remove the push-dock entirely (`modalSnap.js`), including rebuilding the two
  features currently built on it: the email+document side-by-side split and
  sidebar auto-collapse behavior.

## Non-Goals (this phase)

- **Adjustable resize seam** between tiles (drag to make chat 60% / tool 40%).
  Deferred to **Phase 1b**. Phase 1 uses fixed ratios (50/50 halves, even quarters).
- **Layout persistence** across reloads. Deferred to a later phase.
- **Empty-canvas launcher** niceties (chat is never closed, so the canvas is
  never truly empty). Later phase.
- Mobile tiling. Mobile (≤768px) keeps chat fullscreen, tiling disabled —
  unchanged from today.

## Decisions (from brainstorming)

1. **Canvas model:** unified canvas; chat is the canvas's default occupant, not a
   fussy closable window.
2. **Chat tiling:** **reactive** — chat fills the largest free rectangle
   automatically; the user never drags the chat. No chat title bar.
3. **Dock transition:** **full replacement in Phase 1** — `modalSnap.js` is
   deleted; email/doc split and sidebar-collapse are rebuilt on the tiling model.
4. **Adjustable seam:** **Phase 1b** (fixed ratios in Phase 1).

## The Model

- **Canvas:** the viewport region right of the sidebar/rail, full height. The
  existing `_viewportSafeRect()` in `tileManager.js` already computes this and
  accounts for the sidebar/rail width.
- **Chat tile:** reactive fill. Always present, never closes. Occupies the
  largest free rectangle of the canvas.
- **Tiled tool:** a tool window snapped to a zone. Reserves that zone; chat
  reflows around it.
- **Floating tool:** an un-snapped tool window. Floats over the canvas as a
  normal movable window; NOT part of the reflow (does not reserve space).

## Layout Engine

Extend `tileManager.js` into the single layout authority (rather than a CSS-Grid
rewrite, which would require reparenting every tool modal into a grid container —
invasive and risky). `tileManager.js` already computes zone rectangles and applies
them with `position:fixed` + `!important`; we add the chat as a managed tile and a
reflow pass.

**Cell model:** represent the canvas as a 2×2 grid of cells — TL, TR, BL, BR.

- quarter zone = 1 cell
- half zone = 2 cells (left = TL+BL, right = TR+BR, top = TL+TR, bottom = BL+BR)
- maximize = 4 cells
- fullscreen = covers the whole viewport including sidebar (special; chat hides
  behind it — chat reflow treats fullscreen tool as occupying all 4 cells)

**Reflow algorithm** (runs on every snap / unsnap / close / viewport resize /
sidebar toggle):

1. Collect the set of cells occupied by all currently **tiled** tools.
2. Compute the **largest free rectangle** over the remaining cells. With a 2×2
   grid the candidates are, in order of area: full (4) → a half (2) → a quarter
   (1). Pick the largest rectangle of contiguous free cells.
3. Size the chat tile to that rectangle (or hide it only if zero cells are free —
   e.g. a maximized tool).
4. Edge case: if free cells are non-contiguous (e.g. tools in TL and BR, leaving
   TR and BL free), chat takes the largest single free cell; the other free cell
   is left as empty canvas. This is a rare arrangement; document it, do not
   over-engineer.

The largest-free-rectangle computation is a **pure function** of (occupied cells,
canvas rect) → chat rect, and is unit-tested in isolation.

## Component / File Breakdown

- **`static/js/tileManager.js`** — core changes:
  - Re-enable all 9 zones in `_zoneForPointer` (corners + left-half + top-half are
    currently disabled). Corner-first detection using existing `CORNER_THRESHOLD_PX`
    (64) and `EDGE_THRESHOLD_PX` (24) constants — no new magic numbers.
  - Register the chat container as a managed tile.
  - Add the reflow pass (occupied cells → chat rect) invoked on snap/unsnap/close/
    resize/sidebar-toggle. `_reclampAll` already re-clamps tool tiles on resize;
    extend it to also reflow chat.
- **`static/js/windowDrag.js`** — drag-to-edge triggers tile zones via tileManager
  instead of the edge-dock controllers. Remove `makeEdgeDockController` usage.
- **`static/js/modalSnap.js`** — **deleted**. All exports (`applyEdgeDock`,
  `clearRightDock`, `makeEdgeDockController`, `suspendDock`, `resumeDock`, etc.)
  removed; callers rewired to tiling equivalents.
- **`static/style.css`** — remove `*-dock-active` body-margin push rules
  (`body.right-dock-active .chat-container { margin-right: … }`, left equivalent,
  `--left-dock-w`/`--right-dock-w` usage). Chat container becomes a positioned tile
  (it is sized by the layout engine). Add canvas/tile styling as needed.
- **Chat markup** (`static/index.html` / `static/app.js`) — the chat container
  participates as a tile (positioned by the engine). Default (no tiled tools) =
  fills the canvas, visually identical to today.
- **`static/js/emailLibrary.js` / `static/js/emailInbox.js`** — rebuild the
  email+document split as **two tiles** (email | doc) on the tiling model instead
  of the dock-based `email-doc-split` geometry. Fixed ratio in Phase 1.
- **`static/js/notes.js` / `static/js/settings.js`** — rewire their `modalSnap`
  callers (left/right dock) to the tiling model.
- **`static/js/windowResize.js`** — unchanged (per-window edge/corner resize stays).

## Per-modal restrictions

Preserve the existing sensible limits in `_zoneForContent`: Settings → right-half
only; Cookbook/Theme/Memory → fullscreen only (their dense layouts break in
quarters). Regular tool windows (Library, Notes, Tasks, Calendar, Email, etc.) get
the full zone set.

## Error / edge handling

- **Mobile (≤768px):** tiling disabled; chat fullscreen; the `_isDesktop()` guard
  already gates this.
- **Sidebar toggle / viewport resize:** reflow re-runs (the existing sidebar
  MutationObserver and resize listener already drive `_reclampAll`; extend to
  reflow chat).
- **Tool closed while tiled:** its cells free up; chat reflows to reclaim them.
- **Maximized/fullscreen tool:** chat fully covered; no chat rect applied until the
  tool un-snaps or closes.
- **Non-contiguous free cells:** chat takes largest single free cell (documented
  above).

## Testing

- **Unit test:** the pure largest-free-rectangle function — for each combination of
  occupied cells, assert the expected chat rectangle. (Add to the existing `*_js`
  test harness pattern under `tests/`.)
- **Manual in-app matrix:** snap a tool to each of the 9 zones and confirm the
  ghost preview, the snap, and the chat reflow into the complement; open a second
  tool and confirm chat keeps the correct region; email+document split renders as
  two tiles; un-snap / close reclaims space; toggle the sidebar and resize the
  viewport and confirm everything re-tiles; verify mobile stays chat-fullscreen.

## Phasing

- **Phase 1 (this spec):** canvas + reactive chat reflow + full 9-zone tiling +
  email/doc split rebuild + delete `modalSnap.js`. Fixed ratios.
- **Phase 1b:** draggable resize seam between adjacent tiles (rebalance ratios).
- **Phase 2+:** layout persistence; empty-canvas/launcher niceties.

## Design principles compliance

- **No magic numbers:** reuse existing `EDGE_THRESHOLD_PX`, `CORNER_THRESHOLD_PX`,
  `TOP_FULL_STRIP_PX` constants; introduce named constants for any new thresholds.
- **Generalized/reusable:** one layout engine owns all tiling (chat + tools);
  no per-tool bespoke positioning.
