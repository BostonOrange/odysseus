/**
 * tileManager.js — desktop window tiling for tool modals.
 *
 * Hooks into any modal whose `.modal-header` is dragged (each tool wires its
 * own drag; we just watch pointer moves). Shows a translucent ghost preview
 * when the cursor is near a snap zone. On release, snaps the modal-content
 * to fill that zone with a springy animation.
 *
 * Snap zones (9):
 *   - top edge (10% strip)        → maximize
 *   - top-left corner             → top-left quarter
 *   - top-right corner            → top-right quarter
 *   - left edge                   → left half
 *   - right edge                  → right half
 *   - bottom-left corner          → bottom-left quarter
 *   - bottom-right corner         → bottom-right quarter
 *   - bottom edge                 → bottom half
 *   - sidebar edge (if present)   → snap next to the sidebar
 *
 * Mobile (≤768px) is excluded — the swipe-dismiss UX takes precedence.
 *
 * Each modal-content remembers its pre-snap geometry so dragging away restores
 * the original size.
 */

import { cellsForZone, largestFreeRect, rectForCells, freeCellsForChat } from './tileLayout.js';

const EDGE_THRESHOLD_PX = 24;     // how close to an edge counts as "near"
const CORNER_THRESHOLD_PX = 64;   // corner box size
const TOP_FULL_STRIP_PX = 8;      // top strip → maximize
const SNAP_ANIM_S = 0.22;         // spring transition duration (seconds)
const SNAP_ANIM_CLEAR_MS = 250;   // timeout to clear transition after snap (ms)
const DEFAULT_SPLIT = 0.5;        // even 2x2 grid
const MIN_TILE_PX = 240;          // a tile/chat may not be dragged narrower/shorter than this
const CHAT_DRAG_W_FRAC = 0.5;     // floating chat width while dragging (fraction of canvas)
const CHAT_DRAG_H_FRAC = 0.6;     // floating chat height while dragging (fraction of canvas)
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

let _ghost = null;
let _activeZone = null;
let _tracking = null; // { content, startRect }
let _chatDragging = false; // true while the chat is being live-dragged as a floating window

function _isDesktop() { return window.innerWidth > 768; }

function _dockClassForSide(side) {
  return side === 'left' ? 'modal-left-docked' : 'modal-right-docked';
}

function _hasOtherDockedWindow(side, owner) {
  const cls = _dockClassForSide(side);
  return Array.from(document.querySelectorAll(`.${cls}`)).some((el) => {
    if (!el || el === owner) return false;
    if (owner && el.contains && el.contains(owner)) return false;
    if (owner && owner.contains && owner.contains(el)) return false;
    return true;
  });
}

function _clearDockSide(side, owner = null) {
  if (side !== 'left' && side !== 'right') return;
  if (_hasOtherDockedWindow(side, owner)) return;
  document.body.classList.remove(side === 'left' ? 'left-dock-active' : 'right-dock-active');
  document.documentElement.style.removeProperty(side === 'left' ? '--left-dock-w' : '--right-dock-w');
  if (side === 'left') {
    try { window._restoreSidebarIfRouteCollapsed?.(); } catch (_) {}
  }
}

function _ensureGhost() {
  if (_ghost) return _ghost;
  _ghost = document.createElement('div');
  _ghost.id = 'tile-ghost';
  document.body.appendChild(_ghost);
  return _ghost;
}

function _hideGhost() {
  if (_ghost) _ghost.classList.remove('visible');
}

function _showGhost(rect) {
  const g = _ensureGhost();
  g.style.left = rect.left + 'px';
  g.style.top  = rect.top  + 'px';
  g.style.width  = rect.width  + 'px';
  g.style.height = rect.height + 'px';
  g.classList.add('visible');
}

function _viewportSafeRect() {
  // Account for the icon rail / sidebar on the left side of the viewport.
  const sidebar = document.getElementById('sidebar');
  const rail = document.querySelector('.icon-rail') || document.querySelector('#icon-rail');
  let leftEdge = 0;
  const sb = sidebar?.getBoundingClientRect();
  if (sb && sb.right > 0 && !sidebar.classList.contains('hidden')) leftEdge = Math.max(leftEdge, sb.right);
  const rr = rail?.getBoundingClientRect();
  if (rr && rr.right > 0) leftEdge = Math.max(leftEdge, rr.right);
  return {
    left: leftEdge + 4,
    top: 4,
    right: window.innerWidth - 4,
    bottom: window.innerHeight - 4,
  };
}

function _zoneForPointer(x, y) {
  const safe = _viewportSafeRect();

  // Dragged OVER the top edge (cursor at/past the very top) → fullscreen: fills
  // the viewport edge-to-edge but still reserves the sidebar (never covers it).
  if (y <= 0) return { name: 'fullscreen', rect: _rectForZone('fullscreen', safe) };
  // Near the top edge (but not over it) → "maximize": fill the safe area,
  // which sits NEXT TO the sidebar/rail rather than covering it.
  if (y <= safe.top + TOP_FULL_STRIP_PX) return { name: 'maximize', rect: _rectForZone('maximize', safe) };

  // Corner quarters take precedence over edges: a corner point is also near
  // two edges, so check the corner box (CORNER_THRESHOLD_PX) of a vertical AND
  // a horizontal edge first, then fall back to single-edge halves. Rects come
  // from _rectForZone so they honor the current grid split fractions.
  const nearL = x <= safe.left + CORNER_THRESHOLD_PX;
  const nearR = x >= safe.right - CORNER_THRESHOLD_PX;
  const nearT = y <= safe.top + CORNER_THRESHOLD_PX;
  const nearB = y >= safe.bottom - CORNER_THRESHOLD_PX;

  if (nearT && nearL) return { name: 'top-left',     rect: _rectForZone('top-left', safe) };
  if (nearT && nearR) return { name: 'top-right',    rect: _rectForZone('top-right', safe) };
  if (nearB && nearL) return { name: 'bottom-left',  rect: _rectForZone('bottom-left', safe) };
  if (nearB && nearR) return { name: 'bottom-right', rect: _rectForZone('bottom-right', safe) };

  // Single-edge halves (EDGE_THRESHOLD_PX is the thin band right at the edge).
  if (x <= safe.left + EDGE_THRESHOLD_PX)  return { name: 'left-half',   rect: _rectForZone('left-half', safe) };
  if (x >= safe.right - EDGE_THRESHOLD_PX) return { name: 'right-half',  rect: _rectForZone('right-half', safe) };
  if (y >= safe.bottom - EDGE_THRESHOLD_PX) return { name: 'bottom-half', rect: _rectForZone('bottom-half', safe) };

  return null;
}

function _zoneForContent(content, x, y) {
  // Any modal/window may tile to any zone. The previous per-modal restrictions
  // (settings → right-half only; cookbook/theme/memory → fullscreen only) were
  // removed at the user's request; dense layouts adapt via their own CSS.
  return _zoneForPointer(x, y);
}

function _clearEdgeDockResidue(modal, content) {
  const hadDockState = !!(
    (modal && (modal.classList.contains('modal-left-docked') || modal.classList.contains('modal-right-docked')))
    || (content && (content._preDockSnapshot || content._dockSide || content._dockSuspended))
  );
  if (modal) {
    const hadLeft = modal.classList.contains('modal-left-docked');
    const hadRight = modal.classList.contains('modal-right-docked');
    modal.classList.remove('modal-left-docked', 'modal-right-docked');
    if (hadLeft) _clearDockSide('left', modal);
    if (hadRight) _clearDockSide('right', modal);
    if (modal._dockCloseWatcher) {
      try { modal._dockCloseWatcher.obs && modal._dockCloseWatcher.obs.disconnect(); } catch (_) {}
      try { modal._dockCloseWatcher.parentObs && modal._dockCloseWatcher.parentObs.disconnect(); } catch (_) {}
      delete modal._dockCloseWatcher;
    }
  }
  if (!content) return;
  if (content._leftDockNavObs) {
    try { content._leftDockNavObs.navObs.disconnect(); } catch (_) {}
    try { window.removeEventListener('resize', content._leftDockNavObs.reanchor); } catch (_) {}
    delete content._leftDockNavObs;
  }
  delete content._preDockSnapshot;
  delete content._dockSide;
  delete content._dockSuspended;
  if (hadDockState) {
    ['right', 'bottom', 'max-width', 'border-radius']
      .forEach(p => content.style.removeProperty(p));
  }
}

function _applySnap(content, rect, zoneName) {
  // A tile-snap supersedes any edge-dock on this same modal. The two
  // systems (windowDrag→modalSnap edge-dock, and this tile manager) both
  // fire on a left/right-edge drag-release. If we leave modalSnap's
  // `left-dock-active` body class + `--left-dock-w` padding in place, it
  // reserves a strip on the left AND this manager's safe-rect already
  // accounts for the sidebar's (now padding-shifted) position — the two
  // double-count and jam the window to the right behind a massive empty
  // zone, which gets worse each time the sidebar is toggled. Clear the
  // orphaned edge-dock state so only the tile-snap positions the window.
  const _modal = content.closest && content.closest('.modal, .research-overlay');
  const _fromRect = content.getBoundingClientRect();
  _clearEdgeDockResidue(_modal, content);

  // Stash pre-snap geometry once; if we re-snap, keep the original. Capture a
  // CONCRETE fixed position (from the rendered rect when the inline value is
  // empty) and the position itself — otherwise un-snap restored empty left/top
  // + no position, and the .modal flex parent re-centered the window.
  if (!content.dataset._tilePreSnap) {
    content.dataset._tilePreSnap = JSON.stringify({
      position: 'fixed',
      left:   content.style.left || (Math.round(_fromRect.left) + 'px'),
      top:    content.style.top  || (Math.round(_fromRect.top)  + 'px'),
      width:  content.style.width,
      height: content.style.height,
      maxHeight: content.style.maxHeight,
      transform: content.style.transform,
    });
  }
  content.style.transition = `left ${SNAP_ANIM_S}s cubic-bezier(0.34, 1.56, 0.64, 1), top ${SNAP_ANIM_S}s cubic-bezier(0.34, 1.56, 0.64, 1), width ${SNAP_ANIM_S}s cubic-bezier(0.34, 1.56, 0.64, 1), height ${SNAP_ANIM_S}s cubic-bezier(0.34, 1.56, 0.64, 1)`;
  // Use !important — some modals (e.g. cookbook) carry inline width/height
  // and CSS that otherwise re-center the .modal-content, which made the snap
  // "jump back to the middle" on release.
  content.style.setProperty('position', 'fixed', 'important');
  content.style.setProperty('left',   rect.left   + 'px', 'important');
  content.style.setProperty('top',    rect.top    + 'px', 'important');
  content.style.setProperty('width',  rect.width  + 'px', 'important');
  content.style.setProperty('height', rect.height + 'px', 'important');
  content.style.setProperty('max-height', rect.height + 'px', 'important');
  content.style.setProperty('margin', '0', 'important');
  content.style.setProperty('transform', 'none', 'important');
  content.dataset._tileZone = zoneName;
  setTimeout(() => { content.style.transition = ''; }, SNAP_ANIM_CLEAR_MS);
  _reflowChat(true);
}

function _unsnap(content) {
  const pre = content.dataset._tilePreSnap;
  if (!pre) return;
  // Clear the !important snap props first — Object.assign can't override them.
  ['position', 'left', 'top', 'width', 'height', 'max-height', 'margin', 'transform']
    .forEach(p => content.style.removeProperty(p));
  try {
    const r = JSON.parse(pre);
    Object.assign(content.style, r);
  } catch {}
  // Keep it a fixed floating window so the restored left/top actually take
  // effect — without position:fixed the .modal flex parent re-centers it.
  if (!content.style.position) content.style.position = 'fixed';
  delete content.dataset._tilePreSnap;
  delete content.dataset._tileZone;
  _reflowChat(true);
}

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

// Detach the chat from its tile geometry into a free-floating window under the
// cursor so it can be dragged like a tool window. Called on the first
// significant move of a chat drag. Sets _chatDragging so _reflowChat won't fight
// the live position (deleting data-_tile-zone below fires the close-observer).
function _detachChatForDrag(t, cx, cy) {
  const chat = t.content;
  _chatDragging = true;
  chat.classList.add('chat-dragging');
  ['position', 'left', 'top', 'width', 'height', 'max-height', 'margin', 'transform', 'transition']
    .forEach((p) => chat.style.removeProperty(p));
  delete chat.dataset._tileZone;
  delete chat.dataset._tilePreSnap;
  chat.style.removeProperty('display');
  const safe = _viewportSafeRect();
  const w = Math.round((safe.right - safe.left) * CHAT_DRAG_W_FRAC);
  const h = Math.round((safe.bottom - safe.top) * CHAT_DRAG_H_FRAC);
  const left = Math.round(cx - w / 2);
  const top = Math.max(safe.top, cy - 18); // sit the grabbed top bar under the cursor
  chat.style.setProperty('position', 'fixed', 'important');
  chat.style.setProperty('width', w + 'px', 'important');
  chat.style.setProperty('height', h + 'px', 'important');
  chat.style.setProperty('max-height', h + 'px', 'important');
  chat.style.setProperty('margin', '0', 'important');
  chat.style.setProperty('transform', 'none', 'important');
  chat.style.setProperty('left', left + 'px', 'important');
  chat.style.setProperty('top', top + 'px', 'important');
  t.startX = cx; t.startY = cy;
  t.floatLeft = left; t.floatTop = top;
  t.detached = true;
}

document.addEventListener('pointerdown', (e) => {
  if (!_isDesktop()) return;
  const content = _findDragTarget(e);
  if (!content) return;
  const isChat = content.id === 'chat-container';
  // A snapped tool un-snaps on first move; the chat instead detaches into a
  // floating window (handled in pointermove). willUnsnap stays false for the
  // chat so _unsnap (which restores tool pre-snap geometry) is not used on it.
  _tracking = {
    content, startX: e.clientX, startY: e.clientY, isChat, detached: false,
    willUnsnap: !isChat && !!content.dataset._tileZone,
  };
});

document.addEventListener('pointermove', (e) => {
  if (!_tracking) return;
  if (!_isDesktop()) return;
  const dx = e.clientX - _tracking.startX;
  const dy = e.clientY - _tracking.startY;
  if (!_tracking.detached && Math.hypot(dx, dy) < 6) return;

  if (_tracking.isChat) {
    // Chat: detach into a floating window on first move, then follow the cursor.
    if (!_tracking.detached) _detachChatForDrag(_tracking, e.clientX, e.clientY);
    _tracking.content.style.setProperty('left', (_tracking.floatLeft + (e.clientX - _tracking.startX)) + 'px', 'important');
    _tracking.content.style.setProperty('top',  (_tracking.floatTop  + (e.clientY - _tracking.startY)) + 'px', 'important');
  } else if (_tracking.willUnsnap) {
    // Unsnap a tool on first significant move
    _unsnap(_tracking.content);
    _tracking.willUnsnap = false;
  }

  // Detect snap zone under cursor (ghost preview)
  const zone = _zoneForContent(_tracking.content, e.clientX, e.clientY);
  if (zone) {
    _showGhost(zone.rect);
    _activeZone = zone;
  } else {
    _hideGhost();
    _activeZone = null;
  }
});

document.addEventListener('pointerup', () => {
  if (!_tracking) return;
  const t = _tracking;
  _tracking = null;
  _hideGhost();
  if (t.isChat) {
    _chatDragging = false;
    t.content.classList.remove('chat-dragging');
  }
  if (_activeZone && _isDesktop()) {
    _applySnap(t.content, _activeZone.rect, _activeZone.name);
  } else if (t.isChat && t.detached) {
    // Dropped loose (not over a zone) → the chat is not a free-floating window;
    // revert it to the auto-fill tile.
    ['position', 'left', 'top', 'width', 'height', 'max-height', 'margin', 'transform', 'transition']
      .forEach((p) => t.content.style.removeProperty(p));
    delete t.content.dataset._tileZone;
    delete t.content.dataset._tilePreSnap;
    _reflowChat(true);
  }
  _activeZone = null;
});

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

// Reflow the chat into the largest free rectangle left by tiled tool windows.
// Chat is the implicit "fill" tile: it always occupies whatever cells the
// tiled tools don't. Hidden (display:none) only when a tool covers everything.
// A PINNED chat (dataset._tileZone set by dragging it into a zone) is instead
// clamped to that zone — it becomes a fixed tile and tools tile around it.
function _reflowChat(animate = false) {
  // A live chat drag is positioning the chat as a floating window — don't fight it.
  if (_chatDragging) return;
  const chat = document.getElementById('chat-container');
  if (!chat) return;
  if (!_isDesktop()) {
    // Mobile: chat is full-screen; drop any tile inline styles we set.
    ['position', 'left', 'top', 'width', 'height', 'max-height'].forEach(p => chat.style.removeProperty(p));
    chat.style.removeProperty('display');
    _positionSeams();
    return;
  }
  // Pinned: the user dragged the chat into a zone, so it is a fixed tile now and
  // tools tile around it. Clamp it to its zone instead of auto-filling.
  if (chat.dataset._tileZone) {
    const r = _rectForZone(chat.dataset._tileZone);
    if (r) _sizeChat(chat, r, animate);
    _positionSeams();
    return;
  }
  const occupied = [];
  // Every element carrying data-_tile-zone counts as a tile for OCCUPANCY: a
  // snapped .modal-content / .research-pane, an externally-driven pane such as
  // #notes-pane, or #doc-editor-pane (the right-half leaf of the email+document
  // split — a real tile for occupancy even though it owns its own geometry via
  // the email-doc split CSS rule rather than tileManager's snap clamp). Counting
  // them all lets the chat reflow into whatever they leave free, and hide when
  // they cover everything.
  document.querySelectorAll('[data-_tile-zone]')
    .forEach(c => { occupied.push(...cellsForZone(c.dataset._tileZone)); });
  const safe = _viewportSafeRect();
  const canvas = { left: safe.left, top: safe.top, width: safe.right - safe.left, height: safe.bottom - safe.top };
  const rect = largestFreeRect(occupied, canvas, _splitX, _splitY);
  if (!rect) { chat.style.display = 'none'; _positionSeams(); return; }
  _sizeChat(chat, rect, animate);
  _positionSeams();
}

// Resolve a named zone to its pixel rect for the CURRENT safe-rect. Single
// source of truth shared by _reclampAll (re-clamp on resize) and the public
// zoneByName() helper (external callers re-applying a remembered tile).
function _rectForZone(name, safe = _viewportSafeRect()) {
  // fullscreen fills the viewport edge-to-edge but RESERVES the sidebar/icon-rail
  // (it must never cover the left column), so it stays special — not a cell rect.
  if (name === 'fullscreen') {
    const left = Math.max(0, safe.left - 4);  // safe.left = sidebar/rail edge + 4
    return { left, top: 0, width: window.innerWidth - left, height: window.innerHeight };
  }
  const cells = cellsForZone(name);
  if (!cells.length) return null;
  const canvas = { left: safe.left, top: safe.top, width: safe.right - safe.left, height: safe.bottom - safe.top };
  return rectForCells(cells, canvas, _splitX, _splitY);
}

// Re-clamp every currently-snapped window so it keeps filling its zone after
// the safe-rect changes (viewport resize, sidebar toggle, etc.).
function _reclampAll(animate = false) {
  // Re-clamp every tiled element EXCEPT panes that own their own geometry.
  // #doc-editor-pane is driven by the email-doc split CSS vars (clamping here
  // would fight emailLibrary), so it stays excluded via the selector. #notes-pane
  // is re-clamped for normal zones (e.g. right-half) — its standard rect IS
  // correct and must track the safe-rect on resize/sidebar toggle. The ONE case
  // we skip is its 'fullscreen' zone: notes snaps that with a CUSTOM rect
  // (_notesFullscreenSafeRect) that deliberately reserves the
  // sidebar/icon-rail/hamburger, and re-deriving the rect from the zone NAME here
  // returns a true viewport-covering rect that would snap fullscreen Notes over
  // that navigation chrome. Both panes still count toward chat occupancy in
  // _reflowChat — only their geometry is theirs.
  // #chat-container is also excluded — _reflowChat owns the chat's geometry
  // (pinned-clamp or auto-fill), and it is called at the end of this function.
  document.querySelectorAll('[data-_tile-zone]:not(#doc-editor-pane):not(#chat-container)').forEach(c => {
    const name = c.dataset._tileZone;
    if (!name) return;
    // Preserve notes' custom chrome-aware fullscreen rect; re-clamp every other
    // notes zone (right-half, etc.) normally.
    if (c.id === 'notes-pane' && name === 'fullscreen') return;
    const r = _rectForZone(name);
    if (!r) return;
    if (animate) {
      c.style.transition = `left ${SNAP_ANIM_S}s cubic-bezier(0.34, 1.56, 0.64, 1), top ${SNAP_ANIM_S}s cubic-bezier(0.34, 1.56, 0.64, 1), width ${SNAP_ANIM_S}s cubic-bezier(0.34, 1.56, 0.64, 1), height ${SNAP_ANIM_S}s cubic-bezier(0.34, 1.56, 0.64, 1)`;
      setTimeout(() => { c.style.transition = ''; }, SNAP_ANIM_CLEAR_MS);
    }
    c.style.setProperty('left', r.left + 'px', 'important');
    c.style.setProperty('top',  r.top  + 'px', 'important');
    c.style.setProperty('width', r.width + 'px', 'important');
    c.style.setProperty('height', r.height + 'px', 'important');
    c.style.setProperty('max-height', r.height + 'px', 'important');
  });
  _reflowChat(animate);
}

let _reclampPending = false;
function _reclampAllThrottled(animate) {
  if (_reclampPending) return;
  _reclampPending = true;
  requestAnimationFrame(() => {
    try { _reclampAll(animate); } finally { _reclampPending = false; }
  });
}

window.addEventListener('resize', () => _reclampAllThrottled(false));

// Watch the sidebar's class attribute so toggling hidden/right-side re-tiles
// any snapped modal that was anchored to the old safe-rect.
function _watchSidebar() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) {
    // Sidebar may not be in the DOM yet during early init.
    requestAnimationFrame(_watchSidebar);
    return;
  }
  const mo = new MutationObserver(() => _reclampAllThrottled(true));
  mo.observe(sidebar, { attributes: true, attributeFilter: ['class'] });
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _watchSidebar);
} else {
  _watchSidebar();
}

// Reflow chat when a tiled tool is closed/hidden (not just un-snapped). A tool
// stops occupying its zone in exactly two ways: its `data-_tile-zone` attribute
// is removed (the tools' close/reset handlers delete `dataset._tileZone`) or the
// element is removed from the DOM. Watch ONLY those two signals. Observing
// `style` on the whole subtree would catch our own `_reflowChat` style writes —
// including the `setTimeout` that clears `chat.style.transition` — and
// self-trigger an endless reflow loop; observing `class` would fire on every
// unrelated hover/animation class toggle in the app.
function _watchTiledClose() {
  const root = document.body;
  if (!root) { requestAnimationFrame(_watchTiledClose); return; }
  const mo = new MutationObserver((muts) => {
    let touched = false;
    for (const m of muts) {
      // Only `data-_tile-zone` attribute mutations reach us (attributeFilter),
      // so any attribute change means a tool gained/lost its tiled state.
      if (m.type === 'attributes') { touched = true; break; }
      for (const node of m.removedNodes) {
        if (node.nodeType !== 1) continue;
        if (node.matches('[data-_tile-zone]') || node.querySelector('[data-_tile-zone]')) {
          touched = true;
          break;
        }
      }
      if (touched) break;
    }
    if (touched) _reflowChatThrottled(true);
  });
  mo.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-_tile-zone'] });
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

// ── Resizable grid seams ──────────────────────────────────────────────────
// Two global split fractions (_splitX/_splitY) define the grid. Dragging a seam
// moves the shared divider so every tile + the chat on that axis rebalance.

// 2x2 ownership grid: each cell -> owner id ('chat', a tile's id, or null). A
// divider is a real (draggable) boundary only where two DIFFERENT non-null
// owners meet across it — so a single tile spanning both columns shows no seam.
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
function _axisDivided() {
  const g = _ownerGrid();
  const diff = (a, b) => g[a] !== null && g[b] !== null && g[a] !== g[b];
  return {
    x: diff('0,0', '1,0') || diff('0,1', '1,1'),
    y: diff('0,0', '0,1') || diff('1,0', '1,1'),
  };
}

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

// Show/position both seams for the current layout + splits. Safe to call before
// _ensureSeams (no-ops) and on mobile (hides both).
function _positionSeams() {
  if (!_seamX) return;
  if (!_isDesktop()) { _seamX.style.display = 'none'; _seamY.style.display = 'none'; return; }
  const safe = _viewportSafeRect();
  const W = safe.right - safe.left, H = safe.bottom - safe.top;
  const div = _axisDivided();
  if (div.x) {
    const x = safe.left + W * _splitX;
    _seamX.style.display = 'block';
    _seamX.style.left = (x - 5) + 'px';
    _seamX.style.top = safe.top + 'px';
    _seamX.style.height = H + 'px';
  } else { _seamX.style.display = 'none'; }
  if (div.y) {
    const y = safe.top + H * _splitY;
    _seamY.style.display = 'block';
    _seamY.style.top = (y - 5) + 'px';
    _seamY.style.left = safe.left + 'px';
    _seamY.style.width = W + 'px';
  } else { _seamY.style.display = 'none'; }
}

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
      // _reclampAll re-clamps every tile to the new split AND calls _reflowChat,
      // which re-lays the chat and repositions the seams.
      _reclampAll(false);
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

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _ensureSeams);
} else { _ensureSeams(); }

// ── Public API for other drag sources (e.g. dragging a minimized dock chip
// to a screen edge) to reuse the same snap zones + ghost preview + apply. ──

// Show the snap-zone ghost for a point and return the zone (or null).
export function previewZoneAt(x, y, target = null) {
  if (!_isDesktop()) { _hideGhost(); _activeZone = null; return null; }
  const content = target && target.querySelector
    ? (target.querySelector('.modal-content, .research-pane') || target)
    : null;
  const zone = content ? _zoneForContent(content, x, y) : _zoneForPointer(x, y);
  if (zone) { _showGhost(zone.rect); _activeZone = zone; }
  else { _hideGhost(); _activeZone = null; }
  return zone;
}

export function clearPreview() {
  _hideGhost();
  _activeZone = null;
}

// Release a tiled element back to a free-floating window: drop the tile flag +
// the pre-snap snapshot and the !important geometry the snap wrote, then
// reclaim the freed canvas for the chat. For drag sources that dismantle a tile
// OUTSIDE the pointer-drag flow (e.g. the email/document split tearing itself
// down on a header click that never moved, or on minimize/dismiss) — where
// tileManager's own move-threshold unsnap never fires.
export function releaseTile(content) {
  if (!content) return;
  ['position', 'left', 'top', 'width', 'height', 'max-height', 'margin', 'transform']
    .forEach((p) => content.style.removeProperty(p));
  delete content.dataset._tileZone;
  delete content.dataset._tilePreSnap;
  _reflowChat(true);
}

// Resolve a zone NAME (e.g. 'left-half', 'right-half', 'maximize') to a
// {name, rect} for the current viewport. Lets external callers re-apply a
// remembered tile without replicating the private safe-rect math — the tiling
// equivalent of the old modalSnap "re-apply a remembered dock side" path.
// Returns null for an unrecognized name.
export function zoneByName(name) {
  if (!_isDesktop()) return null;
  const rect = _rectForZone(name);
  return rect ? { name, rect } : null;
}

// Snap a modal (its .modal-content) into a previously-detected zone.
export function snapModalToZone(modal, zone) {
  if (!modal || !zone) return;
  const content = modal.querySelector ? (modal.querySelector('.modal-content, .research-pane') || modal) : modal;
  if (!content) return;
  if (modal.id === 'settings-modal' && zone.name !== 'right-half') return;
  _applySnap(content, zone.rect, zone.name);
}

export {};

// Test-only hooks (added on the upstream sync) so test_tile_manager_snap_zones_js.py
// can exercise the private zone resolvers without a real DOM.
export function _zoneForPointerForTests(x, y) {
  return _zoneForPointer(x, y);
}

export function _zoneForContentForTests(content, x, y) {
  return _zoneForContent(content, x, y);
}
