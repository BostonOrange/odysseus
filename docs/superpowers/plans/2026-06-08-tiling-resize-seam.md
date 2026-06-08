# Tiling Resize Seam (Phase 2a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user resize tiles by dragging the seam between them — via two global grid splits (`splitX`, `splitY`, default 0.5) that every tile and the chat derive from, with min clamps and localStorage persistence.

**Architecture:** All cell→pixel geometry is centralized in the pure `tileLayout.js` (`rectForCells` + `freeCellsForChat`), made split-aware. `tileManager.js` holds the split state, routes its three rect-producers (`_rectForZone`, `_zoneForPointer`, `_reflowChat`) through that math, and adds two draggable seam elements that update the splits and live-rebalance.

**Tech Stack:** Vanilla ES modules, CSS in `static/style.css`, Python+`node` test harness (`node --input-type=module`, skips when node absent). Work happens in the worktree at `.claude/worktrees/tiling-resize` on branch `feat/tiling-resize`.

---

## File Structure

- **Modify** `static/js/tileLayout.js` — add `rectForCells(cells, canvas, splitX, splitY)` and `freeCellsForChat(occupiedCells)`; make `largestFreeRect` split-aware via them; remove the now-obsolete private `_cellsToRect` and the unused `GRID_COLS`/`GRID_ROWS`.
- **Modify** `tests/test_tile_layout_js.py` — add split-aware cases; existing default-0.5 cases stay green.
- **Modify** `static/js/tileManager.js` — split state + constants + persistence; rewire `_rectForZone`, `_zoneForPointer`, `_reflowChat`; add seam elements, `_positionSeams`, drag handlers, and wire into the existing reclamp/resize/sidebar hooks.
- **Modify** `static/style.css` — `.tile-seam` handle styling.

Cell-key format is unchanged from Phase 1: `"c,r"`, `c∈{0,1}` column, `r∈{0,1}` row.

---

## Task 1: Split-aware pure layout core (`tileLayout.js`)

**Files:**
- Modify: `static/js/tileLayout.js`
- Test: `tests/test_tile_layout_js.py`

- [ ] **Step 1: Add failing tests.** Append these to `tests/test_tile_layout_js.py` (the file already has the `_run`, `_CANVAS`, and node-skip harness; reuse it). Note `_run`'s import line must include the new exports — update the import in the existing `_run` helper from `import { cellsForZone, largestFreeRect } from ...` to `import { cellsForZone, largestFreeRect, rectForCells, freeCellsForChat } from ...`.

```python
@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_rect_for_cells_default_split_matches_halves():
    # default split 0.5 → identical to the old halving math
    assert _run("rectForCells(['1,0','1,1'], CANVAS)") == {"left": 500, "top": 0, "width": 400, "height": 600}
    assert _run("rectForCells(['0,0'], CANVAS)") == {"left": 100, "top": 0, "width": 400, "height": 300}


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_rect_for_cells_custom_split_x():
    # splitX=0.3 → left column is 800*0.3=240 wide, right column 560 wide starting at x=340
    assert _run("rectForCells(['0,0','0,1'], CANVAS, 0.3, 0.5)") == {"left": 100, "top": 0, "width": 240, "height": 600}
    assert _run("rectForCells(['1,0','1,1'], CANVAS, 0.3, 0.5)") == {"left": 340, "top": 0, "width": 560, "height": 600}


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_rect_for_cells_custom_split_y():
    # splitY=0.4 → top row 600*0.4=240 tall; TL cell with splitX=0.3 → 240x240
    assert _run("rectForCells(['0,0'], CANVAS, 0.3, 0.4)") == {"left": 100, "top": 0, "width": 240, "height": 240}
    assert _run("rectForCells(['0,1'], CANVAS, 0.3, 0.4)") == {"left": 100, "top": 240, "width": 240, "height": 360}


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_free_cells_for_chat():
    assert _run("freeCellsForChat([])") == ['0,0', '1,0', '0,1', '1,1']
    assert _run("freeCellsForChat(cellsForZone('right-half'))") == ['0,0', '0,1']
    assert _run("freeCellsForChat(cellsForZone('maximize'))") is None


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_largest_free_rect_honors_split():
    # right-half occupied + splitX=0.3 → chat (left col) is 240 wide
    assert _run("largestFreeRect(cellsForZone('right-half'), CANVAS, 0.3, 0.5)") == {"left": 100, "top": 0, "width": 240, "height": 600}
```

- [ ] **Step 2: Run tests, verify the new ones fail.** Run: `python -m pytest tests/test_tile_layout_js.py -q` (or `py -m pytest`). Expected: the 5 new tests FAIL (`rectForCells`/`freeCellsForChat` not exported); the existing 9 still pass.

- [ ] **Step 3: Implement.** Replace the body of `static/js/tileLayout.js` from the `GRID_COLS`/`GRID_ROWS` block through `largestFreeRect` with the following (keeps `cellsForZone`, `ZONE_CELLS`, `CANDIDATES` as-is; removes `GRID_COLS`/`GRID_ROWS` and `_cellsToRect`):

```javascript
// (delete the GRID_COLS / GRID_ROWS constants — rectForCells uses explicit
// split fractions instead of a fixed divisor.)

// ... ZONE_CELLS and cellsForZone unchanged ...

// ... CANDIDATES unchanged ...

// Convert a set of cells (assumed to form a rectangle) to a pixel rect, using
// the grid split fractions. splitX/splitY default to 0.5 (an even 2x2 grid),
// so callers that omit them get the original halving behavior.
export function rectForCells(cells, canvas, splitX = 0.5, splitY = 0.5) {
  const colEdge = [canvas.left, canvas.left + canvas.width * splitX, canvas.left + canvas.width];
  const rowEdge = [canvas.top, canvas.top + canvas.height * splitY, canvas.top + canvas.height];
  const cols = cells.map((k) => Number(k.split(',')[0]));
  const rows = cells.map((k) => Number(k.split(',')[1]));
  const minC = Math.min(...cols), maxC = Math.max(...cols);
  const minR = Math.min(...rows), maxR = Math.max(...rows);
  return {
    left: colEdge[minC],
    top: rowEdge[minR],
    width: colEdge[maxC + 1] - colEdge[minC],
    height: rowEdge[maxR + 1] - rowEdge[minR],
  };
}

// The cells the chat fills: the largest free rectangle's cell set (candidates
// scanned largest-area-first). Returns null when no cell is free.
export function freeCellsForChat(occupiedCells) {
  const occ = new Set(occupiedCells || []);
  for (const cand of CANDIDATES) {
    if (cand.every((c) => !occ.has(c))) return cand.slice();
  }
  return null;
}

// Largest free rectangle for the chat, in pixels, honoring the split fractions.
export function largestFreeRect(occupiedCells, canvas, splitX = 0.5, splitY = 0.5) {
  const cells = freeCellsForChat(occupiedCells);
  return cells ? rectForCells(cells, canvas, splitX, splitY) : null;
}
```

- [ ] **Step 4: Run tests, verify all pass.** Run: `python -m pytest tests/test_tile_layout_js.py -q`. Expected: **14 passed** (9 existing + 5 new). Also `node --check static/js/tileLayout.js`.

- [ ] **Step 5: Commit.**

```bash
git add static/js/tileLayout.js tests/test_tile_layout_js.py
git commit -m "feat(tiling): split-aware rectForCells + freeCellsForChat in tileLayout"
```

---

## Task 2: Split state + wiring in `tileManager.js`

**Files:**
- Modify: `static/js/tileManager.js`

This task makes the engine split-aware. With splits defaulting to 0.5 there is NO visible behavior change yet — it's pure plumbing that Task 3's seam will drive.

- [ ] **Step 1: Update the import** (line 26):

```javascript
import { cellsForZone, largestFreeRect, rectForCells } from './tileLayout.js';
```

- [ ] **Step 2: Add constants + split state.** After the existing constants (after `SNAP_ANIM_CLEAR_MS` on line 32), add:

```javascript
const DEFAULT_SPLIT = 0.5;        // even 2x2 grid
const MIN_TILE_PX = 240;          // a tile/chat may not be dragged narrower/shorter than this
const SPLIT_X_KEY = 'odysseus-tile-split-x';
const SPLIT_Y_KEY = 'odysseus-tile-split-y';

function _loadSplit(key) {
  try {
    const n = parseFloat(localStorage.getItem(key) || '');
    return Number.isFinite(n) && n > 0 && n < 1 ? n : DEFAULT_SPLIT;
  } catch (_) { return DEFAULT_SPLIT; }
}
let _splitX = _loadSplit(SPLIT_X_KEY);
let _splitY = _loadSplit(SPLIT_Y_KEY);
```

- [ ] **Step 3: Rewrite `_rectForZone`** (currently lines ~356-370) to derive rects from the splits via `rectForCells`, keeping the `fullscreen` true-viewport special case:

```javascript
function _rectForZone(name, safe = _viewportSafeRect()) {
  // fullscreen covers the ENTIRE viewport (including the sidebar) — not a
  // canvas-cell rect, so it stays special.
  if (name === 'fullscreen') {
    return { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
  }
  const cells = cellsForZone(name);
  if (!cells.length) return null;
  const canvas = { left: safe.left, top: safe.top, width: safe.right - safe.left, height: safe.bottom - safe.top };
  return rectForCells(cells, canvas, _splitX, _splitY);
}
```

(Note: `maximize` = all four cells → `rectForCells` returns the full safe area regardless of split, matching the old behavior.)

- [ ] **Step 4: Make `_zoneForPointer` build rects via `_rectForZone`** so detection and geometry share one source. Replace each inline `rect: { ... }` (lines 110-137) with `rect: _rectForZone('<name>', safe)`. The function becomes detection-only:

```javascript
function _zoneForPointer(x, y) {
  const safe = _viewportSafeRect();
  if (y <= 0) return { name: 'fullscreen', rect: _rectForZone('fullscreen', safe) };
  if (y <= safe.top + TOP_FULL_STRIP_PX) return { name: 'maximize', rect: _rectForZone('maximize', safe) };

  const nearL = x <= safe.left + CORNER_THRESHOLD_PX;
  const nearR = x >= safe.right - CORNER_THRESHOLD_PX;
  const nearT = y <= safe.top + CORNER_THRESHOLD_PX;
  const nearB = y >= safe.bottom - CORNER_THRESHOLD_PX;
  if (nearT && nearL) return { name: 'top-left',     rect: _rectForZone('top-left', safe) };
  if (nearT && nearR) return { name: 'top-right',    rect: _rectForZone('top-right', safe) };
  if (nearB && nearL) return { name: 'bottom-left',  rect: _rectForZone('bottom-left', safe) };
  if (nearB && nearR) return { name: 'bottom-right', rect: _rectForZone('bottom-right', safe) };

  if (x <= safe.left + EDGE_THRESHOLD_PX)  return { name: 'left-half',   rect: _rectForZone('left-half', safe) };
  if (x >= safe.right - EDGE_THRESHOLD_PX) return { name: 'right-half',  rect: _rectForZone('right-half', safe) };
  if (y >= safe.bottom - EDGE_THRESHOLD_PX) return { name: 'bottom-half', rect: _rectForZone('bottom-half', safe) };
  return null;
}
```

`_rectForZone` is a function declaration (hoisted), so referencing it above its definition is fine.

- [ ] **Step 5: Pass splits to `largestFreeRect` in `_reflowChat`** (line ~338):

```javascript
  const rect = largestFreeRect(occupied, canvas, _splitX, _splitY);
```

- [ ] **Step 6: Verify.** `node --check static/js/tileManager.js`; `python -m pytest tests/test_tile_layout_js.py -q` (14 passed). Manual sanity (optional now): snapping still lands at 50% since splits default to 0.5 — unchanged from Phase 1.

- [ ] **Step 7: Commit.**

```bash
git add static/js/tileManager.js
git commit -m "feat(tiling): route zone + chat geometry through split fractions"
```

---

## Task 3: Draggable resize seams

**Files:**
- Modify: `static/js/tileManager.js` (seam elements, `_positionSeams`, drag, wiring)
- Modify: `static/style.css` (`.tile-seam`)

- [ ] **Step 1: Add the owner-grid helper + axis-division detection.** Add near `_reflowChat` in `tileManager.js`. Import `freeCellsForChat` too — update the Task 2 import line to: `import { cellsForZone, largestFreeRect, rectForCells, freeCellsForChat } from './tileLayout.js';`

```javascript
// Build the 2x2 ownership grid: each cell -> owner id ('chat', a tile's id, or
// null). Used to decide whether a divider is a real boundary between two
// different occupants (only then is its seam draggable).
function _ownerGrid() {
  const grid = { '0,0': null, '1,0': null, '0,1': null, '1,1': null };
  document.querySelectorAll('[data-_tile-zone]').forEach((c, i) => {
    const id = c.id || ('tile' + i);
    cellsForZone(c.dataset._tileZone).forEach((k) => { grid[k] = id; });
  });
  const occupied = Object.keys(grid).filter((k) => grid[k] !== null);
  const chatCells = freeCellsForChat(occupied);
  if (chatCells) chatCells.forEach((k) => { grid[k] = 'chat'; });
  return grid;
}

// A divider is "active" (draggable) only where two DIFFERENT non-null owners
// meet across it — so a single tile spanning both columns shows no seam.
function _axisDivided() {
  const g = _ownerGrid();
  const diff = (a, b) => g[a] !== null && g[b] !== null && g[a] !== g[b];
  return {
    x: diff('0,0', '1,0') || diff('0,1', '1,1'),
    y: diff('0,0', '0,1') || diff('1,0', '1,1'),
  };
}
```

- [ ] **Step 2: Create the seam elements + positioning.** Add an init block near the bottom of `tileManager.js` (mirroring the structure of `_watchSidebar`):

```javascript
let _seamX = null, _seamY = null;
function _ensureSeams() {
  if (_seamX) return;
  _seamX = document.createElement('div');
  _seamX.className = 'tile-seam tile-seam-x';
  _seamY = document.createElement('div');
  _seamY.className = 'tile-seam tile-seam-y';
  document.body.appendChild(_seamX);
  document.body.appendChild(_seamY);
  _wireSeamDrag(_seamX, 'x');
  _wireSeamDrag(_seamY, 'y');
}

// Show/position both seams for the current layout + splits.
function _positionSeams() {
  if (!_seamX) return;
  if (!_isDesktop()) { _seamX.style.display = 'none'; _seamY.style.display = 'none'; return; }
  const safe = _viewportSafeRect();
  const W = safe.right - safe.left, H = safe.bottom - safe.top;
  const div = _axisDivided();
  // Vertical seam at x = split line, spanning the canvas height.
  if (div.x) {
    const x = safe.left + W * _splitX;
    _seamX.style.display = 'block';
    _seamX.style.left = (x - 5) + 'px';
    _seamX.style.top = safe.top + 'px';
    _seamX.style.height = H + 'px';
  } else { _seamX.style.display = 'none'; }
  // Horizontal seam at y = split line, spanning the canvas width.
  if (div.y) {
    const y = safe.top + H * _splitY;
    _seamY.style.display = 'block';
    _seamY.style.top = (y - 5) + 'px';
    _seamY.style.left = safe.left + 'px';
    _seamY.style.width = W + 'px';
  } else { _seamY.style.display = 'none'; }
}
```

- [ ] **Step 3: Add the drag handler.** Mirrors the pointer-capture pattern of the old (deleted) edge-dock resize handle:

```javascript
function _wireSeamDrag(handle, axis) {
  handle.addEventListener('pointerdown', (e) => {
    if (handle.style.display === 'none') return;
    e.preventDefault();
    handle.setPointerCapture?.(e.pointerId);
    const prevCursor = document.body.style.cursor;
    document.body.style.cursor = axis === 'x' ? 'col-resize' : 'row-resize';
    document.body.style.userSelect = 'none';
    const apply = (ev) => {
      const safe = _viewportSafeRect();
      const W = safe.right - safe.left, H = safe.bottom - safe.top;
      if (axis === 'x') {
        const minF = MIN_TILE_PX / W, maxF = 1 - minF;
        _splitX = Math.min(maxF, Math.max(minF, (ev.clientX - safe.left) / W));
      } else {
        const minF = MIN_TILE_PX / H, maxF = 1 - minF;
        _splitY = Math.min(maxF, Math.max(minF, (ev.clientY - safe.top) / H));
      }
      _reclampAll(false);
      _reflowChat(false);
      _positionSeams();
    };
    const onMove = (ev) => { ev.preventDefault(); apply(ev); };
    const onUp = (ev) => {
      try { handle.releasePointerCapture?.(e.pointerId); } catch (_) {}
      document.removeEventListener('pointermove', onMove, true);
      document.removeEventListener('pointerup', onUp, true);
      document.removeEventListener('pointercancel', onUp, true);
      document.body.style.cursor = prevCursor;
      document.body.style.userSelect = '';
      try { localStorage.setItem(axis === 'x' ? SPLIT_X_KEY : SPLIT_Y_KEY, String(axis === 'x' ? _splitX : _splitY)); } catch (_) {}
      ev.preventDefault();
    };
    document.addEventListener('pointermove', onMove, true);
    document.addEventListener('pointerup', onUp, true);
    document.addEventListener('pointercancel', onUp, true);
  });
}
```

- [ ] **Step 4: Wire `_ensureSeams` + `_positionSeams` into the lifecycle.** (a) Call `_ensureSeams()` once at init: add it next to the `_watchSidebar()` init at the bottom (in both the `DOMContentLoaded` and eager branches). (b) Call `_positionSeams()` at the END of `_reflowChat` (after sizing the chat) and at the END of `_reclampAll` (after the forEach). (c) Add `_positionSeams` to the resize + sidebar hooks — the existing `window.addEventListener('resize', () => _reclampAllThrottled(false))` already triggers `_reclampAll`, and the sidebar MutationObserver triggers `_reclampAllThrottled(true)`; since `_reclampAll` now calls `_positionSeams`, no extra listener is needed. Confirm `_reflowChat` is also called by those paths (it is, via `_reclampAll`'s existing `_reflowChat` call from Phase 1 — verify and, if absent, add `_reflowChat(animate)` at the end of `_reclampAll`).

- [ ] **Step 5: Add `.tile-seam` CSS** to `static/style.css` (append near other overlay/handle styles):

```css
.tile-seam {
  position: fixed;
  z-index: 200;
  display: none;
  background: linear-gradient(var(--seam-dir, to right), transparent 0 3px,
    color-mix(in srgb, var(--accent, var(--accent-primary, #60a5fa)) 38%, transparent) 3px 7px,
    transparent 7px 10px);
  touch-action: none;
}
.tile-seam-x { width: 10px; cursor: col-resize; --seam-dir: to right; }
.tile-seam-y { height: 10px; cursor: row-resize; --seam-dir: to bottom; }
```

- [ ] **Step 6: Verify (manual — needs a browser).** `node --check static/js/tileManager.js`; rebuild/serve the worktree and confirm: snap a tool right-half (chat takes left) → a vertical seam appears at center; drag it left/right → chat + tool rebalance live and the seam follows; release + reload → split persists; drag to the far edge → clamp at `MIN_TILE_PX`; add a bottom tile → horizontal seam appears and drags; maximize a tool → no seam; mobile (≤768px) → no seams. (Browser verification is the Task 4 matrix; here just confirm no console errors via `node --check` + load.)

- [ ] **Step 7: Commit.**

```bash
git add static/js/tileManager.js static/style.css
git commit -m "feat(tiling): draggable grid resize seams (vertical + horizontal)"
```

---

## Task 4: Verification matrix

**Files:** none (verification only)

- [ ] **Step 1: Unit suite.** `python -m pytest tests/test_tile_layout_js.py -q` → 14 passed (or SKIP without node — run where node exists).
- [ ] **Step 2: Broader JS regression.** `python -m pytest tests/ -k "_js" -q` → no NEW failures vs. branch point (the pre-existing Windows `as_posix` failures in sibling tests are unrelated).
- [ ] **Step 3: `node --check`** on `static/js/tileLayout.js` and `static/js/tileManager.js`.
- [ ] **Step 4: Manual matrix in the running app** (rebuild the container from this worktree, or serve locally):
  - Vertical seam: right-half tool + chat → seam at center → drag → both rebalance live → persists across reload → min-clamp holds.
  - Horizontal seam: add a bottom-half/quarter tool → horizontal seam appears + drags.
  - Quarters: a corner tool → the relevant seam(s) appear and rebalance the grid.
  - No-seam cases: chat-only (nothing tiled) and a maximized tool → no seams shown.
  - Resize viewport + toggle sidebar → seams reposition, tiles + chat stay correct (splits are viewport-independent fractions).
  - Mobile (≤768px) → no seams, chat full-screen.
  - Console clean.

---

## Self-Review Notes

- **Spec coverage:** split fractions + default-0.5 backward-compat (Task 1-2); centralized split-aware geometry in `tileLayout.rectForCells` used by all three rect producers (Task 2); draggable vertical+horizontal seams with min-clamp + persistence + show-only-when-divided (Task 3); mobile exclusion + resize/sidebar reposition (Task 3 Step 4); unit + manual tests (Task 1, Task 4). Movable chat is explicitly out (Phase 2b).
- **Names/types consistency:** `rectForCells(cells, canvas, splitX, splitY)` and `freeCellsForChat(occupiedCells)` signatures match across `tileLayout.js`, its tests, and `tileManager.js` call sites. `_splitX`/`_splitY`/`DEFAULT_SPLIT`/`MIN_TILE_PX`/`SPLIT_X_KEY`/`SPLIT_Y_KEY` used consistently.
- **No placeholders:** Task 1 is full TDD with real code; Tasks 2-3 give exact edit targets + complete code; the browser-interactive seam drag is verified by the Task 4 manual matrix (consistent with how DOM-coupled code is tested in this repo).
- **No magic numbers:** `DEFAULT_SPLIT`, `MIN_TILE_PX`, storage-key constants named; `MIN_TILE_PX/W` and `/H` derive the clamp fractions; seam hit-area `10px`/`5px` offset are local CSS/positioning literals (acceptable, like the existing handle code).
