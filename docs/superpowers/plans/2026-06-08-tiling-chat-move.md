# Movable (Hybrid) Chat — Phase 2b Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user drag the chat by its top bar to pin it into a snap zone (tools tile around it); the chat keeps auto-filling until placed, and reverts to auto-fill when dragged away.

**Architecture:** Reuse Phase 1's snap engine entirely — a *pinned* chat is just `#chat-container` carrying `dataset._tileZone` (the same marker tools use). Four small edits in `static/js/tileManager.js` (recognize the chat top bar as a drag target; clamp a pinned chat in `_reflowChat`; stop auto-assigning chat cells in `_ownerGrid` when pinned; exclude the chat from `_reclampAll`'s loop) plus a CSS affordance.

**Tech Stack:** Vanilla ES modules, CSS in `static/style.css`. No new layout math, no new unit tests (the pure `tileLayout` core is unchanged). Work in the worktree `.claude/worktrees/tiling-resize` on branch `feat/tiling-chat-move`.

---

## File Structure

- **Modify** `static/js/tileManager.js` — `_findDragTarget` (chat handle), `_reflowChat` (pinned branch + extracted `_sizeChat`), `_ownerGrid` (pinned guard), `_reclampAll` (chat exclusion).
- **Modify** `static/style.css` — `.chat-top-bar` move-cursor + grip affordance (desktop only).

No new files. The pinned marker is `dataset._tileZone` on `#chat-container`; no new state.

---

## Task 1: Make the chat top bar a drag handle

**Files:**
- Modify: `static/js/tileManager.js` (`_findDragTarget`, ~line 258)
- Modify: `static/style.css` (`.chat-top-bar` affordance, near the `#tile-ghost` block ~line 838)

- [ ] **Step 1: Recognize the chat top bar in `_findDragTarget`.** Replace the whole function:

```javascript
function _findDragTarget(e) {
  // Chat tile: dragging its top bar (not a button on it) moves the whole chat,
  // reusing the same snap/unsnap flow as tool windows. A *pinned* chat carries
  // dataset._tileZone on #chat-container; an unpinned (auto-fill) chat does not.
  const chatBar = e.target.closest('.chat-top-bar');
  if (chatBar && chatBar.closest('#chat-container')) {
    if (e.target.closest('button')) return null;
    return document.getElementById('chat-container');
  }
  const header = e.target.closest('.modal-header');
  if (!header) return null;
  // Skip clicks on header buttons (close, minimize, etc.)
  if (e.target.closest('button')) return null;
  const modal = header.closest('.modal, .research-overlay');
  if (!modal) return null;
  const content = modal.querySelector('.modal-content, .research-pane');
  return content || null;
}
```

(Why this is enough: the global `pointerdown` handler already does `if (content.dataset._tileZone)` to decide whether to un-snap on drag — that works for a pinned chat. `pointerup` calls `_applySnap(content, zone.rect, zone.name)` which sets `dataset._tileZone` on the chat and stashes `_tilePreSnap`. `_zoneForContent` applies no per-modal restriction because the chat's `closest('.modal, .research-overlay')` is null.)

- [ ] **Step 2: Add the CSS affordance.** In `static/style.css`, immediately after the `.tile-seam-y { ... }` rule added in Phase 2a (just before `/* Bottom dock — chip per minimized modal */`), add:

```css
    /* The chat top bar is a drag handle (desktop) — grab it to tile the chat,
       like a tool window's title bar. Buttons inside keep their pointer cursor. */
    @media (min-width: 769px) {
      .chat-top-bar { cursor: move; }
      .chat-top-bar button { cursor: pointer; }
      /* subtle grip cue at the bar's leading edge */
      .chat-top-bar::before {
        content: "⠿";
        margin-right: 6px;
        opacity: 0.35;
        font-size: 13px;
        line-height: 1;
        pointer-events: none;
        align-self: center;
      }
    }
```

- [ ] **Step 3: Verify.** Run `node --check static/js/tileManager.js` → no output (OK). The chat drag/pin behavior is verified in the browser in Task 4; here just confirm the file parses.

- [ ] **Step 4: Commit.**

```bash
git add static/js/tileManager.js static/style.css
git commit -m "feat(tiling): make the chat top bar a drag handle for tiling the chat"
```

---

## Task 2: Clamp a pinned chat in `_reflowChat`

**Files:**
- Modify: `static/js/tileManager.js` (`_reflowChat`, ~line 322)

- [ ] **Step 1: Extract a `_sizeChat` helper.** Add it immediately BEFORE `function _reflowChat(` (~line 322):

```javascript
// Apply a pixel rect to the chat tile (shared by the fill path and the pinned
// path). Sets the springy transition when animating, then the !important
// geometry — same property set the snap uses, so the chat behaves like a tile.
function _sizeChat(chat, rect, animate) {
  if (animate) {
    chat.style.transition = `left ${SNAP_ANIM_S}s cubic-bezier(0.34, 1.56, 0.64, 1), top ${SNAP_ANIM_S}s cubic-bezier(0.34, 1.56, 0.64, 1), width ${SNAP_ANIM_S}s cubic-bezier(0.34, 1.56, 0.64, 1), height ${SNAP_ANIM_S}s cubic-bezier(0.34, 1.56, 0.64, 1)`;
    setTimeout(() => { chat.style.transition = ''; }, SNAP_ANIM_CLEAR_MS);
  }
  chat.style.removeProperty('display');
  chat.style.setProperty('position', 'fixed', 'important');
  chat.style.setProperty('left', rect.left + 'px', 'important');
  chat.style.setProperty('top', rect.top + 'px', 'important');
  chat.style.setProperty('width', rect.width + 'px', 'important');
  chat.style.setProperty('height', rect.height + 'px', 'important');
  chat.style.setProperty('max-height', rect.height + 'px', 'important');
}
```

- [ ] **Step 2: Add the pinned branch + use `_sizeChat` in the fill path.** In `_reflowChat`, insert the pinned branch right after the mobile guard's closing `}` (after the line `  }` that ends the `if (!_isDesktop())` block, ~line 331):

```javascript
  // Pinned: the user dragged the chat into a zone, so it is a fixed tile now and
  // tools tile around it. Clamp it to its zone instead of auto-filling.
  if (chat.dataset._tileZone) {
    const r = _rectForZone(chat.dataset._tileZone);
    if (r) _sizeChat(chat, r, animate);
    _positionSeams();
    return;
  }
```

Then replace the fill path's inline geometry block (the `if (animate) { ... }` transition block plus the six `chat.style.setProperty(...)` lines, currently ~lines 347-356) with a single call. The fill path becomes:

```javascript
  const rect = largestFreeRect(occupied, canvas, _splitX, _splitY);
  if (!rect) { chat.style.display = 'none'; _positionSeams(); return; }
  _sizeChat(chat, rect, animate);
  _positionSeams();
```

(The `const safe`/`const canvas`/occupancy-query lines above `largestFreeRect` stay unchanged. Note the unpinned fill path's occupancy query `querySelectorAll('[data-_tile-zone]')` naturally excludes the chat, because an unpinned chat has no `_tileZone`.)

- [ ] **Step 3: Verify.** `node --check static/js/tileManager.js` → OK. `python -m pytest tests/test_tile_layout_js.py -q` (or `py -m pytest`) → 14 passed (pure core unchanged).

- [ ] **Step 4: Commit.**

```bash
git add static/js/tileManager.js
git commit -m "feat(tiling): clamp a pinned chat to its zone (hybrid chat geometry)"
```

---

## Task 3: Seam + reclamp integration for a pinned chat

**Files:**
- Modify: `static/js/tileManager.js` (`_ownerGrid` ~line 486; `_reclampAll` selector ~line 389)

- [ ] **Step 1: Guard the chat-fill assignment in `_ownerGrid`.** Replace `_ownerGrid` (~lines 486-496):

```javascript
function _ownerGrid() {
  const grid = { '0,0': null, '1,0': null, '0,1': null, '1,1': null };
  document.querySelectorAll('[data-_tile-zone]').forEach((c, i) => {
    const id = c.id || ('tile' + i);
    cellsForZone(c.dataset._tileZone).forEach((k) => { grid[k] = id; });
  });
  // Assign the chat's auto-fill cells ONLY when the chat is unpinned. A pinned
  // chat already appears above as a [data-_tile-zone] owner (#chat-container),
  // so remaining cells are genuinely empty canvas — not chat.
  const chatEl = document.getElementById('chat-container');
  if (chatEl && !chatEl.dataset._tileZone) {
    const occupied = Object.keys(grid).filter((k) => grid[k] !== null);
    const chatCells = freeCellsForChat(occupied);
    if (chatCells) chatCells.forEach((k) => { grid[k] = 'chat'; });
  }
  return grid;
}
```

- [ ] **Step 2: Exclude the chat from `_reclampAll`'s loop.** `_reflowChat` owns the chat's geometry (it is called at the end of `_reclampAll`), so the chat must not also be re-clamped in the loop. Change the selector (~line 389) from:

```javascript
  document.querySelectorAll('[data-_tile-zone]:not(#doc-editor-pane)').forEach(c => {
```

to:

```javascript
  document.querySelectorAll('[data-_tile-zone]:not(#doc-editor-pane):not(#chat-container)').forEach(c => {
```

Also update the comment block just above the selector: append a sentence noting `#chat-container` is excluded because `_reflowChat` owns the chat (pinned or fill).

- [ ] **Step 3: Verify.** `node --check static/js/tileManager.js` → OK. `python -m pytest tests/test_tile_layout_js.py -q` → 14 passed.

- [ ] **Step 4: Commit.**

```bash
git add static/js/tileManager.js
git commit -m "feat(tiling): seams + reclamp treat a pinned chat as a tile"
```

---

## Task 4: Verification matrix

**Files:** none (verification only)

- [ ] **Step 1: Static checks.** `node --check static/js/tileManager.js` and `node --check static/js/tileLayout.js` → OK. `python -m pytest tests/test_tile_layout_js.py -q` → 14 passed. `python -m pytest tests/ -k "_js" -q` → no NEW failures vs. the branch point.
- [ ] **Step 2: Manual matrix (browser).** Grab the chat top bar (move cursor + grip visible) and:
  - Drag to left/right/bottom half, each corner, and the top (maximize) → ghost preview shows, chat pins there on release.
  - With chat pinned to a half, open a tool and snap it to the complementary zone → it tiles beside the pinned chat (chat does NOT auto-move).
  - Pin chat left, leave the right empty → right stays empty canvas (no auto-fill).
  - Drag a vertical/horizontal seam between the pinned chat and a tool → both rebalance (Phase 2a).
  - Drag the pinned chat away from its zone → it reverts to auto-fill (re-occupies the largest free rectangle).
  - Click the top-bar buttons (rename/export/incognito) → they still work, no drag triggered.
  - Resize the viewport + toggle the sidebar with the chat pinned → it re-clamps to its zone.
  - Maximize a tool over a pinned chat → chat hidden behind; un-snap the tool → chat reappears in its zone.
  - Shrink to ≤768px → top-bar drag inert, chat full-screen.
  - Console clean.

---

## Self-Review Notes

- **Spec coverage:** chat top bar as handle (Task 1) + CSS affordance (Task 1); pinned-clamp vs auto-fill in `_reflowChat` via the `dataset._tileZone` marker (Task 2); `_ownerGrid` pinned guard so seams + empty-canvas are correct (Task 3 Step 1); `_reclampAll` chat exclusion (Task 3 Step 2). Reuse of `_applySnap`/`_unsnap`/ghost/zone-detection requires no edits (verified against current code). Persistence explicitly out of scope. Mobile guarded by existing `_isDesktop()` + the `@media (min-width:769px)` CSS.
- **Type/name consistency:** the pinned marker is `dataset._tileZone` on `#chat-container` everywhere; `_sizeChat(chat, rect, animate)` is defined in Task 2 and used by both `_reflowChat` branches; `_rectForZone`, `freeCellsForChat`, `cellsForZone` are existing functions used with their established signatures.
- **No placeholders:** every edit shows complete old→new code; integration behavior (drag, pin, seams) is verified by the Task 4 browser matrix + `node --check` + the existing unit suite, consistent with how this DOM-coupled module is tested.
- **No magic numbers:** reuses existing constants; the only literals are local CSS values (grip size/opacity, the 769px desktop breakpoint that matches the existing 768px mobile guard).
