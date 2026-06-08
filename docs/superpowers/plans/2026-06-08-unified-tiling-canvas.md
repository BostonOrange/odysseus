# Unified Tiling Canvas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Demote the chat from a fixed background to a reactive "fill" tile on a unified tiling canvas, so snapping a tool reflows the chat into the complementary space (true tiling) and the dock/push model is removed.

**Architecture:** A new pure module `static/js/tileLayout.js` owns the layout math (which canvas cells a zone occupies, and the largest free rectangle for the chat). `tileManager.js` becomes the single layout authority: it re-enables all 9 snap zones, registers the chat container as a managed tile, and reflows the chat whenever tiles change. The push-dock (`modalSnap.js`) is deleted and its callers rewired; the email/document split is rebuilt as two tiles.

**Tech Stack:** Vanilla ES modules (no framework), CSS in `static/style.css`, Python+`node` test harness (`subprocess.run(["node", "--input-type=module"], ...)`, skips when node absent).

---

## File Structure

- **Create** `static/js/tileLayout.js` — pure layout math. Exports `cellsForZone(zoneName)` and `largestFreeRect(occupiedCells, canvasRect)`. No DOM access. Single responsibility: geometry. Unit-tested.
- **Create** `tests/test_tile_layout_js.py` — node-harness unit tests for the pure math.
- **Modify** `static/js/tileManager.js` — re-enable all 9 zones in `_zoneForPointer`; import `tileLayout`; register chat as a managed tile; add `_reflowChat()` and call it from snap/unsnap/close/resize/sidebar paths.
- **Modify** `static/js/windowDrag.js` — drag-to-edge triggers tile zones; remove `modalSnap` import and the `rightDock`/`leftDock` controller usage.
- **Modify** `static/style.css` — chat container becomes a positioned tile; remove `*-dock-active` margin-push rules.
- **Modify** `static/js/emailLibrary.js`, `static/js/emailInbox.js` — rebuild the email+document split as two tiles.
- **Modify** `static/js/notes.js`, `static/js/settings.js` — rewire `modalSnap` callers.
- **Delete** `static/js/modalSnap.js`.

Cell model (used throughout): the canvas is a 2×2 grid. A cell key is `"c,r"` with `c∈{0,1}` (column) and `r∈{0,1}` (row). `0,0`=top-left, `1,0`=top-right, `0,1`=bottom-left, `1,1`=bottom-right.

---

## Task 1: Pure layout core (`tileLayout.js`)

**Files:**
- Create: `static/js/tileLayout.js`
- Test: `tests/test_tile_layout_js.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tile_layout_js.py`:

```python
"""Pin the pure tiling layout math in static/js/tileLayout.js.
Driven through `node --input-type=module`; skips without node.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_HELPER = _REPO / "static" / "js" / "tileLayout.js"
_HAS_NODE = shutil.which("node") is not None

# Canvas rect used by every case: left=100 (sidebar), top=0, 800x600.
_CANVAS = {"left": 100, "top": 0, "width": 800, "height": 600}


def _run(js_expr):
    js = f"""
    import {{ cellsForZone, largestFreeRect }} from '{_HELPER.as_posix()}';
    const CANVAS = {json.dumps(_CANVAS)};
    console.log(JSON.stringify({js_expr}));
    """
    proc = subprocess.run(
        ["node", "--input-type=module"],
        input=js, capture_output=True, text=True, cwd=str(_REPO), timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip())


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_cells_for_zone_halves_and_quarters():
    assert sorted(_run("cellsForZone('left-half')")) == ["0,0", "0,1"]
    assert sorted(_run("cellsForZone('right-half')")) == ["1,0", "1,1"]
    assert sorted(_run("cellsForZone('top-half')")) == ["0,0", "1,0"]
    assert sorted(_run("cellsForZone('bottom-half')")) == ["0,1", "1,1"]
    assert _run("cellsForZone('top-left')") == ["0,0"]
    assert sorted(_run("cellsForZone('maximize')")) == ["0,0", "0,1", "1,0", "1,1"]
    assert sorted(_run("cellsForZone('fullscreen')")) == ["0,0", "0,1", "1,0", "1,1"]


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_largest_free_rect_empty_is_full_canvas():
    r = _run("largestFreeRect([], CANVAS)")
    assert r == {"left": 100, "top": 0, "width": 800, "height": 600}


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_largest_free_rect_tool_right_half_chat_takes_left():
    # tool occupies right column -> chat = left half
    r = _run("largestFreeRect(cellsForZone('right-half'), CANVAS)")
    assert r == {"left": 100, "top": 0, "width": 400, "height": 600}


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_largest_free_rect_right_plus_bottom_right_chat_keeps_left():
    occ = _run("cellsForZone('right-half').concat(cellsForZone('bottom-right'))")
    # union still just the right column -> chat = left half
    r = _run(f"largestFreeRect({json.dumps(occ)}, CANVAS)")
    assert r == {"left": 100, "top": 0, "width": 400, "height": 600}


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_largest_free_rect_diagonal_takes_single_cell():
    # tools in top-left + bottom-right -> free cells are TR and BL (not a rect).
    # Return the first free quarter in scan order (top-left scan: TR = 1,0).
    occ = _run("cellsForZone('top-left').concat(cellsForZone('bottom-right'))")
    r = _run(f"largestFreeRect({json.dumps(occ)}, CANVAS)")
    assert r == {"left": 500, "top": 0, "width": 400, "height": 300}  # top-right cell


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_largest_free_rect_maximized_returns_null():
    r = _run("largestFreeRect(cellsForZone('maximize'), CANVAS)")
    assert r is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tile_layout_js.py -v`
Expected: FAIL — module `static/js/tileLayout.js` does not exist (node import error → non-zero exit → assertion in `_run`).

- [ ] **Step 3: Write minimal implementation**

Create `static/js/tileLayout.js`:

```javascript
/**
 * tileLayout.js — pure layout math for the tiling canvas. No DOM access.
 *
 * The canvas is a 2x2 grid of cells, keyed "c,r" with c in {0,1} (column)
 * and r in {0,1} (row): "0,0"=top-left, "1,0"=top-right, "0,1"=bottom-left,
 * "1,1"=bottom-right.
 */

// Which cells a snap zone occupies. maximize/fullscreen cover all four
// (for chat-occlusion the fullscreen tool hides the chat entirely).
const ZONE_CELLS = {
  'left-half':    ['0,0', '0,1'],
  'right-half':   ['1,0', '1,1'],
  'top-half':     ['0,0', '1,0'],
  'bottom-half':  ['0,1', '1,1'],
  'top-left':     ['0,0'],
  'top-right':    ['1,0'],
  'bottom-left':  ['0,1'],
  'bottom-right': ['1,1'],
  'maximize':     ['0,0', '1,0', '0,1', '1,1'],
  'fullscreen':   ['0,0', '1,0', '0,1', '1,1'],
};

export function cellsForZone(zoneName) {
  return (ZONE_CELLS[zoneName] || []).slice();
}

// Candidate rectangles in descending area: full -> halves -> quarters.
// Each entry is the list of cells it needs. First fully-free candidate wins.
const CANDIDATES = [
  ['0,0', '1,0', '0,1', '1,1'], // full
  ['0,0', '0,1'],               // left half
  ['1,0', '1,1'],               // right half
  ['0,0', '1,0'],               // top half
  ['0,1', '1,1'],               // bottom half
  ['0,0'],                      // TL quarter
  ['1,0'],                      // TR quarter
  ['0,1'],                      // BL quarter
  ['1,1'],                      // BR quarter
];

// Convert a set of cells (assumed to form a rectangle) to a pixel rect.
function _cellsToRect(cells, canvas) {
  const halfW = canvas.width / 2;
  const halfH = canvas.height / 2;
  const cols = cells.map((k) => Number(k.split(',')[0]));
  const rows = cells.map((k) => Number(k.split(',')[1]));
  const minC = Math.min(...cols), maxC = Math.max(...cols);
  const minR = Math.min(...rows), maxR = Math.max(...rows);
  return {
    left: canvas.left + minC * halfW,
    top: canvas.top + minR * halfH,
    width: (maxC - minC + 1) * halfW,
    height: (maxR - minR + 1) * halfH,
  };
}

// Largest free rectangle for the chat. `occupiedCells` is an array of cell
// keys claimed by tiled tools. Returns a pixel rect, or null if no cell is
// free (a maximized/fullscreen tool covers the whole canvas).
export function largestFreeRect(occupiedCells, canvas) {
  const occ = new Set(occupiedCells || []);
  for (const cand of CANDIDATES) {
    if (cand.every((c) => !occ.has(c))) {
      return _cellsToRect(cand, canvas);
    }
  }
  return null;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tile_layout_js.py -v`
Expected: PASS (6 tests). If node is absent they SKIP — run on a machine with node to verify.

- [ ] **Step 5: Commit**

```bash
git add static/js/tileLayout.js tests/test_tile_layout_js.py
git commit -m "feat(tiling): pure layout core — zone cells + largest free rect"
```

---

## Task 2: Re-enable all 9 snap zones in `tileManager._zoneForPointer`

**Files:**
- Modify: `static/js/tileManager.js:98-123` (the `_zoneForPointer` function)

- [ ] **Step 1: Replace `_zoneForPointer` body**

The current function (lines 98-123) returns only `fullscreen`, `maximize`, `right-half`, `bottom-half`. Replace the body from the `// Corner quarter-snaps DISABLED` comment through the final `return null;` with corner-first detection. Keep the `fullscreen` (`y <= 0`) and `maximize` (`y <= safe.top + TOP_FULL_STRIP_PX`) checks above it unchanged. New code:

```javascript
  // Corner quarters take precedence over edges: a corner point is also near
  // two edges, so check the corner box (CORNER_THRESHOLD_PX) of a vertical AND
  // a horizontal edge first, then fall back to single-edge halves.
  const nearL = x <= safe.left + CORNER_THRESHOLD_PX;
  const nearR = x >= safe.right - CORNER_THRESHOLD_PX;
  const nearT = y <= safe.top + CORNER_THRESHOLD_PX;
  const nearB = y >= safe.bottom - CORNER_THRESHOLD_PX;

  if (nearT && nearL) return { name: 'top-left',     rect: { left: safe.left,         top: safe.top,         width: W / 2, height: H / 2 } };
  if (nearT && nearR) return { name: 'top-right',    rect: { left: safe.left + W / 2, top: safe.top,         width: W / 2, height: H / 2 } };
  if (nearB && nearL) return { name: 'bottom-left',  rect: { left: safe.left,         top: safe.top + H / 2, width: W / 2, height: H / 2 } };
  if (nearB && nearR) return { name: 'bottom-right', rect: { left: safe.left + W / 2, top: safe.top + H / 2, width: W / 2, height: H / 2 } };

  // Single-edge halves (EDGE_THRESHOLD_PX is the thin band right at the edge).
  if (x <= safe.left + EDGE_THRESHOLD_PX)
    return { name: 'left-half',   rect: { left: safe.left,         top: safe.top, width: W / 2, height: H } };
  if (x >= safe.right - EDGE_THRESHOLD_PX)
    return { name: 'right-half',  rect: { left: safe.left + W / 2, top: safe.top, width: W / 2, height: H } };
  if (y >= safe.bottom - EDGE_THRESHOLD_PX)
    return { name: 'bottom-half', rect: { left: safe.left, top: safe.top + H / 2, width: W, height: H / 2 } };

  return null;
```

Note: top-half is intentionally omitted — the top edge is the maximize strip. Corners + L/R/bottom halves + maximize + fullscreen = the 9-zone scheme minus a redundant top-half. `CORNER_THRESHOLD_PX` (64) and `EDGE_THRESHOLD_PX` (24) already exist at the top of the file — no new constants.

- [ ] **Step 2: Manual verify in the running app**

Open the app (`http://localhost:7000`), open a tool window (e.g. Tasks), drag its header toward each edge and corner. Expected: the translucent ghost preview appears for left/right/bottom halves and all four corners; releasing snaps the window there; dragging away un-snaps. (Chat reflow comes in Task 3 — for now the chat is unchanged.)

- [ ] **Step 3: Commit**

```bash
git add static/js/tileManager.js
git commit -m "feat(tiling): re-enable corner + left-half snap zone detection"
```

---

## Task 3: Register chat as a managed tile + reflow

**Files:**
- Modify: `static/js/tileManager.js` (import tileLayout; add tracking + `_reflowChat`; call from snap/unsnap/close/resize/sidebar)

- [ ] **Step 1: Add the import** at the top of `tileManager.js` (after the file's opening comment block, before the constants):

```javascript
import { cellsForZone, largestFreeRect } from './tileLayout.js';
```

- [ ] **Step 2: Add chat reflow helper.** Add near `_reclampAll` (around line 296). The chat container is `<main id="chat-container">` (`static/index.html:933`). Tiled tools are `.modal-content[data-_tile-zone]` / `.research-pane[data-_tile-zone]` (the `dataset._tileZone` set by `_applySnap`).

```javascript
// Reflow the chat into the largest free rectangle left by tiled tool windows.
// Chat is the implicit "fill" tile: it always occupies whatever cells the
// tiled tools don't. Hidden (display:none) only when a tool covers everything.
function _reflowChat(animate = false) {
  const chat = document.getElementById('chat-container');
  if (!chat) return;
  if (!_isDesktop()) {
    // Mobile: chat is full-screen; drop any tile inline styles we set.
    ['position', 'left', 'top', 'width', 'height', 'max-height'].forEach(p => chat.style.removeProperty(p));
    chat.style.removeProperty('display');
    return;
  }
  const occupied = [];
  document.querySelectorAll('.modal-content[data-_tile-zone], .research-pane[data-_tile-zone]')
    .forEach(c => { occupied.push(...cellsForZone(c.dataset._tileZone)); });
  const safe = _viewportSafeRect();
  const canvas = { left: safe.left, top: safe.top, width: safe.right - safe.left, height: safe.bottom - safe.top };
  const rect = largestFreeRect(occupied, canvas);
  if (!rect) { chat.style.display = 'none'; return; }
  chat.style.removeProperty('display');
  if (animate) {
    chat.style.transition = 'left 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), top 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), width 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), height 0.22s cubic-bezier(0.34, 1.56, 0.64, 1)';
    setTimeout(() => { chat.style.transition = ''; }, 250);
  }
  chat.style.setProperty('position', 'fixed', 'important');
  chat.style.setProperty('left', rect.left + 'px', 'important');
  chat.style.setProperty('top', rect.top + 'px', 'important');
  chat.style.setProperty('width', rect.width + 'px', 'important');
  chat.style.setProperty('height', rect.height + 'px', 'important');
  chat.style.setProperty('max-height', rect.height + 'px', 'important');
}
```

- [ ] **Step 3: Call `_reflowChat` from every layout-change path.**
  - In `_applySnap` (end of function, after `content.dataset._tileZone = zoneName;` ~line 213): add `_reflowChat(true);`
  - In `_unsnap` (end, after `delete content.dataset._tileZone;` ~line 231): add `_reflowChat(true);`
  - In `_reclampAll` (end of function ~line 326): add `_reflowChat(animate);`
  - In the `pointerup` handler, after `_applySnap(...)` is called (~line 290): already covered by `_applySnap`; no extra call.

- [ ] **Step 4: Watch for tiled tools closing.** A tiled tool can be closed (modal hidden/removed) without un-snapping. Add a MutationObserver near `_watchSidebar` (~line 341) that reflows when a `[data-_tile-zone]` element is removed or hidden:

```javascript
// Reflow chat when a tiled tool is closed/hidden (not just un-snapped).
function _watchTiledClose() {
  const root = document.body;
  if (!root) { requestAnimationFrame(_watchTiledClose); return; }
  const mo = new MutationObserver((muts) => {
    let touched = false;
    for (const m of muts) {
      if (m.removedNodes && m.removedNodes.length) touched = true;
      if (m.type === 'attributes') touched = true;
    }
    if (touched) _reflowChatThrottled(true);
  });
  mo.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style'] });
}
let _reflowPending = false;
function _reflowChatThrottled(animate) {
  if (_reflowPending) return;
  _reflowPending = true;
  requestAnimationFrame(() => { try { _reflowChat(animate); } finally { _reflowPending = false; } });
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _watchTiledClose);
} else { _watchTiledClose(); }
```

- [ ] **Step 5: Manual verify.** In the app: snap a tool to the right half → chat slides to the left half. Snap a second tool to bottom-right → chat keeps the full left column. Close/un-snap the tools → chat expands back to fill the canvas. Resize the viewport and toggle the sidebar → chat + tiles re-clamp together. Switch to a narrow (≤768px) viewport → chat returns to full-screen, no tile styles.

- [ ] **Step 6: Commit**

```bash
git add static/js/tileManager.js
git commit -m "feat(tiling): chat reflows into largest free rect as tools tile"
```

---

## Task 4: Chat container CSS becomes a positioned tile

**Files:**
- Modify: `static/style.css` (the `.chat-container` rule at ~line 1765; the dock-push rules near lines 14890-14902)

- [ ] **Step 1: Neutralize the dock-push rules.** Delete these rules (they reshaped chat via body padding/margins — replaced by `_reflowChat`):
  - `body.right-dock-active { padding-right: 0; }` and `body.left-dock-active { padding-left: 0; }` (lines ~14890-14895)
  - `body.left-dock-active:not(.email-doc-split-active) .chat-container { margin-left: var(--left-dock-w, 0px); }` (~14896-14898)
  - `body.right-dock-active .chat-container, body.right-dock-active:not(.email-doc-split-active) .doc-editor-pane { margin-right: var(--right-dock-w, 0px); }` (~14899-14902)

- [ ] **Step 2: Ensure the chat tile coexists with `flex:1`.** The base `.chat-container { flex:1; ... }` (line ~1765) stays for the default (untiled, mobile) case. When `_reflowChat` sets `position:fixed !important`, the inline `!important` overrides flex positioning, so no CSS change is needed for the tiled case. Confirm no existing rule forces `position` on `.chat-container` with `!important` that would conflict (the print rule `main.chat-container` at line ~7478 is `@media print` only — safe).

- [ ] **Step 3: Manual verify.** Default (no tools tiled): chat looks identical to before — fills the area right of the sidebar. Snap a tool: chat is a fixed-position tile in the complementary rect. No leftover empty padding strip on the right (the old dock artifact).

- [ ] **Step 4: Commit**

```bash
git add static/style.css
git commit -m "refactor(tiling): drop dock-push margins; chat sized by layout engine"
```

---

## Task 5: Rewire `windowDrag.js` drag-to-edge to tile zones

**Files:**
- Modify: `static/js/windowDrag.js:39` (import), `:95-100` (controllers), and the mousemove/mouseup edge-handling (`:192-260`)

- [ ] **Step 1: Replace the import.** Remove line 39 `import { makeEdgeDockController } from './modalSnap.js';`. Add: `import { previewZoneAt, clearPreview, snapModalToZone } from './tileManager.js';` (these are already exported by tileManager.js:361-384).

- [ ] **Step 2: Remove the dock controllers.** Delete the `rightDock`/`leftDock` declarations (lines 95-100) and every `rightDock.*`/`leftDock.*` call in the move/up handlers (lines ~192-260). In their place, during a drag the tileManager's global `pointerdown`/`pointermove`/`pointerup` listeners already detect zones and snap on release (tileManager.js:245-293) — so a draggable window dragged to an edge is handled by tileManager directly. The only `windowDrag` responsibility that remains is the top-edge fullscreen snap (`onEnterFullscreen`), which is unrelated to docking — leave it intact.

  Concretely: in the mousemove handler, delete the `if (nearRight && rightDock) {...}` / `if (nearLeft && leftDock) {...}` blocks (lines ~192-210) and the `rightDock.onMove`/`leftDock.onMove`/`.release()` calls (lines ~240-246). In the mouseup handler delete the dock `.commit()`/`.release()` calls. Keep the fullscreen `_enterFs()`/`_exitFs()` logic.

- [ ] **Step 3: Remove the dock-class resize lock.** In `makeWindowResizable` options (lines 81-88) the `isLocked` checks `modal-right-docked`/`modal-left-docked`. Those classes are no longer set; simplify `isLocked` to only the fullscreen check: `isLocked: () => !!(fsClass && modal && modal.classList.contains(fsClass))`.

- [ ] **Step 4: Manual verify.** Drag a tool window to the left/right edge → it snaps to the half via tileManager (ghost preview from tileManager), and the chat reflows (Task 3). Top-edge drag still triggers fullscreen. Edge/corner resize still works on a floating (un-tiled) window.

- [ ] **Step 5: Commit**

```bash
git add static/js/windowDrag.js
git commit -m "refactor(tiling): route window drag-to-edge through tile zones, drop dock controllers"
```

---

## Task 6: Rebuild the email + document split as two tiles

**Files:**
- Modify: `static/js/emailLibrary.js`, `static/js/emailInbox.js` (the `email-doc-split` / `email-snap-left` usage)

- [ ] **Step 1: Locate the split callers.** Grep both files for `applyEdgeDock`, `applyRightDock`, `email-snap-left`, `email-doc-split`, `clearRightDock`. These currently dock the email window left and let the document pane fill the right via the `--email-doc-split-*` CSS vars (set in `modalSnap.js:_anchorLeftDock`).

- [ ] **Step 2: Replace with two-tile snaps.** When a document opens beside an email: snap the email window to `left-half` and the document pane to `right-half` using `snapModalToZone(modal, { name, rect })` from tileManager (compute rects via `_viewportSafeRect`-equivalent, or expose a helper). Because the chat reflow (Task 3) treats both as tiled tools, the chat hides only if both halves are filled — which is the intended email+doc full-canvas split. Fixed 50/50 ratio (adjustable seam is Phase 1b).

- [ ] **Step 3: Manual verify.** Open the email library, open an email, open its document/draft beside it → email occupies the left half, document the right half, no overlap, sized to the canvas. Close the document → email remains tiled left, chat reclaims the right. Close the email → chat fills the canvas.

- [ ] **Step 4: Commit**

```bash
git add static/js/emailLibrary.js static/js/emailInbox.js
git commit -m "refactor(tiling): rebuild email+document split as two tiles"
```

---

## Task 7: Rewire remaining callers and delete `modalSnap.js`

**Files:**
- Modify: `static/js/notes.js`, `static/js/settings.js`
- Delete: `static/js/modalSnap.js`

- [ ] **Step 1: Find remaining importers.** Run `git grep -n "modalSnap" -- static/js` and `git grep -n "applyEdgeDock\|applyRightDock\|clearRightDock\|makeEdgeDockController\|makeRightDockController\|suspendDock\|resumeDock" -- static/js`. Every hit outside `modalSnap.js` itself must be removed or replaced.

- [ ] **Step 2: Rewire `notes.js` / `settings.js`.** Replace any `applyEdgeDock`/`clearRightDock`/`suspendDock`/`resumeDock` calls with the tiling equivalents: snap via `snapModalToZone` / un-snap by clearing `dataset._tileZone` (tileManager handles reflow). For minimize/restore (`suspendDock`/`resumeDock`), the tiled state lives in `dataset._tileZone` on the content — minimizing hides the modal (its `[data-_tile-zone]` element leaves the layout via the Task 3 close-observer, chat reflows); restoring re-shows it and re-applies the snap. Verify no remaining reference to the deleted module.

- [ ] **Step 3: Delete the module.** `git rm static/js/modalSnap.js`. Confirm `git grep -n "modalSnap" -- static/js` returns nothing.

- [ ] **Step 4: Manual verify.** Open Notes and Settings; snap each to a zone (Settings is restricted to right-half by `_zoneForContent`, line 132 — confirm that still holds); minimize a tiled window and restore it; confirm chat reflows correctly throughout and there are no console errors about a missing `modalSnap.js` import.

- [ ] **Step 5: Commit**

```bash
git add -A static/js
git commit -m "refactor(tiling): rewire remaining dock callers and delete modalSnap.js"
```

---

## Task 8: Full verification matrix

**Files:** none (verification only)

- [ ] **Step 1: Run the JS unit suite.**

Run: `python -m pytest tests/test_tile_layout_js.py -v`
Expected: PASS (or SKIP if node absent — then run where node exists).

- [ ] **Step 2: Run the broader JS test suite** to catch regressions in sibling modules:

Run: `python -m pytest tests/ -k "_js" -v`
Expected: no new failures vs. `dev`.

- [ ] **Step 3: Manual matrix in the running app.** Confirm each:
  - Snap a tool to left/right/bottom half + all four corners + maximize → ghost preview, snap, chat reflow into the complement.
  - Two tools tiled (e.g. right-half + bottom-right) → chat keeps the left column.
  - Diagonal tools (top-left + bottom-right) → chat takes a single free quarter (documented edge case).
  - Maximize a tool → chat hidden; un-snap → chat returns.
  - Email + document split → two tiles side by side.
  - Un-snap / close every tool → chat fills the canvas, no leftover padding strips.
  - Toggle sidebar + resize viewport → chat and tiles re-clamp together.
  - Narrow viewport (≤768px) → chat full-screen, tiling disabled.
  - No console errors; no reference to `modalSnap.js`.

- [ ] **Step 4: Final commit (if any verification fixes were needed).**

```bash
git add -A
git commit -m "test(tiling): verification matrix fixes"
```

---

## Self-Review Notes

- **Spec coverage:** canvas + reactive chat fill (Tasks 3-4), all 9 zones (Task 2), pure largest-free-rect with diagonal edge case (Task 1), dock removal + caller rewire + `modalSnap.js` deletion (Tasks 5,7), email/doc split rebuild (Task 6), mobile exclusion (Task 3 `_isDesktop` guard), per-modal restrictions preserved (Task 7 Step 4). Adjustable seam explicitly deferred to Phase 1b (not in this plan). Persistence/launcher deferred (not in this plan).
- **Types/names consistency:** `cellsForZone` / `largestFreeRect` signatures match between `tileLayout.js`, its test, and `tileManager._reflowChat`. Cell-key format `"c,r"` consistent. `dataset._tileZone` is the existing field set by `_applySnap`.
- **No placeholders:** pure-logic task (Task 1) has complete code + tests. Integration tasks (2-7) give exact file/line targets and the specific symbols to add/remove; they are DOM-integration changes verified by the manual matrix + the existing `_js` suite rather than pure unit tests (consistent with how the codebase tests DOM-coupled modules).
