# Tiling Canvas — Phase 2a: Adjustable Grid Dividers (Resize Seam)

**Date:** 2026-06-08
**Status:** Approved design, pending implementation plan
**Builds on:** Phase 1 (unified tiling canvas, branch `feat/tiling-canvas` / PR #1)
**Area:** Front-end layout (`static/js/tileLayout.js`, `static/js/tileManager.js`, `static/style.css`)

## Summary

Phase 1 made tiles snap to a fixed 2×2 grid at exactly 50%. Tiled windows therefore
cannot be resized (per-window resize is locked while tiled, and there is no seam).
Phase 2a adds **two global, draggable grid dividers** — a vertical split and a
horizontal split — so the user can rebalance tile sizes by dragging the seam between
adjacent tiles. The layout stays a clean grid: one fraction per axis governs every
tile (and the reactive chat) on that axis.

This is the deferred "Phase 1b" from the Phase 1 spec, promoted because "I can't
resize" is the top user pain after shipping Phase 1.

## Goals

- Drag the seam between two adjacent tiles to rebalance them; all tiles on that axis
  (and the chat fill tile) resize together, live, staying a grid.
- One vertical fraction `splitX` and one horizontal fraction `splitY` (default `0.5`)
  define the grid — no per-pair freeform seams (that was explicitly rejected).
- Min-size clamps prevent crushing a tile to nothing.
- The chosen splits persist across reloads (mirrors the old dock's remembered width).
- Zero behavior change when the user never touches a seam (splits stay 0.5 → identical
  to Phase 1).

## Non-Goals (this phase)

- **Movable chat / chat grab handle** — that is Phase 2b (separate spec).
- Per-pair / freeform independent seams (rejected in brainstorming).
- Resizing *floating* (un-tiled) windows — unchanged; they keep edge/corner resize.
- More than one division per axis (no 3-column layouts). The grid is 2×2.

## Decisions (from brainstorming)

1. **Resize model:** adjustable GRID dividers — one global `splitX`, one global
   `splitY`, default `0.5`. Dragging a seam moves the shared divider; every tile on
   that axis rebalances together.
2. The seam is the resize mechanism for tiled windows; per-window edge-resize stays
   locked while a window is tiled (no change to that lock).

## Architecture

### Pure layout core — `static/js/tileLayout.js`

Centralize all cell→pixel geometry here (it is pure and unit-testable). Add an
exported `rectForCells` and make it split-aware; `largestFreeRect` reuses it.

- **`rectForCells(cells, canvas, splitX = 0.5, splitY = 0.5)`** — given a list of cell
  keys that form a rectangle, return its pixel rect using the split fractions:
  - column edges: `x0 = canvas.left`, `x1 = canvas.left + canvas.width * splitX`,
    `x2 = canvas.left + canvas.width`
  - row edges: `y0 = canvas.top`, `y1 = canvas.top + canvas.height * splitY`,
    `y2 = canvas.top + canvas.height`
  - for cells spanning columns `[minC..maxC]` and rows `[minR..maxR]`:
    `left = colEdge[minC]`, `top = rowEdge[minR]`,
    `width = colEdge[maxC+1] - colEdge[minC]`, `height = rowEdge[maxR+1] - rowEdge[minR]`
  - This replaces the current private `_cellsToRect` (which hardcoded `width/GRID_COLS`).
    With `splitX = splitY = 0.5` it produces identical output to Phase 1.
- **`largestFreeRect(occupiedCells, canvas, splitX = 0.5, splitY = 0.5)`** — unchanged
  candidate-scan logic, but calls `rectForCells(cand, canvas, splitX, splitY)` for the
  winning rectangle.
- **`cellsForZone(zoneName)`** — unchanged.
- `GRID_COLS`/`GRID_ROWS` constants remain (still describe the 2×2 grid); the divisor
  literal is gone (replaced by split-fraction math).

### Layout engine — `static/js/tileManager.js`

- Module state: `_splitX` and `_splitY` (default from a named `DEFAULT_SPLIT = 0.5`),
  loaded from `localStorage` on init.
- Every place that builds a zone/tile rect now routes through
  `rectForCells(cellsForZone(name), canvas, _splitX, _splitY)`:
  - `_zoneForPointer` (zone detection stays; rect built via `rectForCells`)
  - `_reclampAll` (re-derives every tiled window's rect from current splits)
  - `_reflowChat` (already calls `largestFreeRect`; pass `_splitX, _splitY`)
- **Seam UI** (new, modeled on the deleted modalSnap resize-handle IIFE):
  - Create one vertical seam element and one horizontal seam element once at init,
    appended to `document.body`, `position:fixed`, `display:none` by default.
  - A `_positionSeams()` function (called from `_reclampAll`, on resize, and on the
    sidebar MutationObserver) shows/positions them:
    - **Vertical seam** shown only when the layout is divided left↔right (some tile or
      chat occupies a col-0 cell AND some tile occupies a col-1 cell). Positioned at
      `x = safe.left + W * _splitX`, spanning the divided height.
    - **Horizontal seam** shown only when divided top↔bottom. Positioned at
      `y = safe.top + H * _splitY`.
    - Hidden on mobile (`!_isDesktop()`) and when no division exists (e.g. a maximized
      tile, or chat-only).
  - **Drag** (pointerdown/move/up with pointer capture, mirroring the old handle): on
    move, set `_splitX` (vertical seam) or `_splitY` (horizontal) from the cursor
    position as a fraction of the safe rect, clamped so neither side is below
    `MIN_TILE_PX` (named constant, e.g. `240`); then call `_reclampAll(false)` +
    `_reflowChat(false)` live (no spring animation during drag). On release, persist
    the split to `localStorage`.
- **Persistence:** keys `odysseus-tile-split-x` / `odysseus-tile-split-y`; parse on
  init with a safe fallback to `DEFAULT_SPLIT`; clamp loaded values to
  `[minFrac, 1 - minFrac]`.

### Styling — `static/style.css`

- A `.tile-seam` class for the two seam handles (the modalSnap handle's inline styles
  were deleted with that file). Thin (e.g. 10px hit area), `cursor: col-resize` /
  `row-resize`, subtle accent gradient matching the app, `z-index` above tiles, only
  visible (`display:block`) when positioned by `_positionSeams`.

## Edge cases / error handling

- **Mobile (≤768px):** seams hidden, splits ignored (chat is full-screen).
- **Resize / sidebar toggle:** `_positionSeams` re-runs (same hooks as `_reclampAll`);
  the split fractions are viewport-independent so they survive resize naturally.
- **Min clamp:** dragging past the min leaves the split at the clamped fraction; the
  seam stops following the cursor past that point.
- **Diagonal layout** (tiles in TL + BR): both axes are divided; both seams show and
  move their global divider. Still coherent (global fractions).
- **No division** (chat-only, or a maximized tile): both seams hidden.
- **Loaded split out of range / NaN:** fall back to `DEFAULT_SPLIT`.

## Testing

- **Unit (`tests/test_tile_layout_js.py`)**, via the existing node harness:
  - `rectForCells(['1,0','1,1'], CANVAS, 0.3, 0.5)` → right column at splitX=0.3:
    `{left: 100 + 800*0.3, top: 0, width: 800*0.7, height: 600}` = `{left:340, width:560, ...}`.
  - `rectForCells(['0,0'], CANVAS, 0.3, 0.4)` → top-left cell `{left:100, top:0,
    width:240, height:240}`.
  - `largestFreeRect(cellsForZone('right-half'), CANVAS, 0.3)` → chat left col width
    `800*0.3 = 240`.
  - Existing default-split tests must still pass unchanged (call sites omit splits →
    default 0.5).
- **Manual matrix:** with chat + a right-half tool, drag the vertical seam left/right →
  both rebalance live; release and reload → split persists; drag to the min → clamp
  holds; add a bottom-tile and drag the horizontal seam; toggle sidebar + resize
  viewport → seams reposition and tiles stay correct; mobile → no seams; floating
  window still edge-resizes.

## Design-principles compliance

- **No magic numbers:** `DEFAULT_SPLIT`, `MIN_TILE_PX` named; existing
  `EDGE_THRESHOLD_PX`/`CORNER_THRESHOLD_PX`/`SNAP_ANIM_*` reused.
- **Generalized/reusable:** all geometry centralized in `tileLayout.rectForCells`;
  one seam mechanism drives both axes.
