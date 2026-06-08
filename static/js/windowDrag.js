// Shared window-drag helper. Replaces the duplicated mousedown / mousemove
// / mouseup + snap-to-top fullscreen + left/right edge dock patterns that
// were copy-pasted across calendar.js, tasks.js, gallery.js, emailLibrary.js,
// documentLibrary.js, theme.js. Behavior stays identical to the old per-file
// copies — each callsite provides its own enter/exit-fullscreen callbacks
// since the CSS class + inline styles differ per modal.
//
// API:
//   makeWindowDraggable(modal, { content, header, ...options })
//     modal:           the wrapping .modal element (or a standalone pane)
//     content:         the element being moved (usually .modal-content)
//     header:          the drag handle (usually .modal-header)
//     fsClass:         optional class name representing "fullscreen" state
//     onEnterFullscreen: optional () => void — called when cursor releases
//                        near the top edge (within SNAP_PX). Caller is
//                        responsible for adding fsClass + applying inline
//                        styles that produce the fullscreen layout.
//     onExitFullscreen:  optional (cx, cy) => void — called mid-drag when
//                        the cursor leaves the fullscreen "unsnap" band
//                        (down > UNSNAP_PX OR near either horizontal edge
//                        in dock-snap range). Caller restores windowed
//                        inline styles centered around the cursor.
//     skipSelector:    CSS selector for elements inside `header` whose
//                        clicks should NOT start a drag (close button,
//                        form fields, etc). Default: 'button, input, select'
//     onDragEnd:       optional (state) => void — fires after mouseup
//                        WHEN no snap was committed. state = { rect } so
//                        callers can persist the final position.
//     enableTouch:     bool — also wire touchstart/touchmove/touchend
//                        with the same drag (no fs/dock on touch). Default
//                        true on desktop, irrelevant on mobile (mobileSkip).
//     mobileSkip:      drag is disabled below this viewport width.
//                        Default 768. Set to 0 to never skip.
//     enableFullscreen: bool — enable top-edge fullscreen snap.
//                        Default true when onEnterFullscreen is supplied.
//
// Left/right/corner edge snapping is owned by tileManager.js, which runs its
// own global pointerdown/move/up listeners over any `.modal-header` drag — so
// this helper no longer wires edge docks. The only edge gesture it still owns
// is the top-edge fullscreen snap (onEnterFullscreen/onExitFullscreen).

// NOTE: tileManager.js is loaded for its global pointer listeners via app.js;
// windowDrag does not call into it directly (zone detection + snapping happen
// in those global listeners), so it intentionally imports nothing from it.
import { makeWindowResizable } from './windowResize.js';

const SNAP_PX = 6;        // cursor distance from top edge for fullscreen snap
const UNSNAP_PX = 24;     // cursor distance from top before fullscreen exits
// tileManager's top strip ('maximize' for a near-top release, 'fullscreen' for
// a release at/over the very top edge) overlaps windowDrag's own top-edge
// fullscreen band (SNAP_PX). When a fullscreen-capable window is released in
// that overlap, the windowDrag fullscreen gesture wins (see _onEnd).
const TILE_TOP_STRIP_ZONES = ['maximize', 'fullscreen'];

export function makeWindowDraggable(modal, options = {}) {
  const content = options.content;
  const header = options.header;
  if (!content || !header) return;
  const fsClass = options.fsClass || null;
  const onEnterFullscreen = options.onEnterFullscreen || null;
  const onExitFullscreen = options.onExitFullscreen || null;
  const enableFullscreen = options.enableFullscreen !== false && !!onEnterFullscreen;
  const onDragEnd = options.onDragEnd || null;
  const onDragStart = options.onDragStart || null;
  const skipSelector = options.skipSelector || 'button, input, select';
  const mobileSkip = (typeof options.mobileSkip === 'number') ? options.mobileSkip : 768;
  const enableTouch = options.enableTouch !== false;

  header.style.cursor = 'move';
  header.style.userSelect = 'none';

  // Edge/corner resize. Every draggable window also becomes resizable — the
  // same gesture a native desktop window uses (grab an edge or corner, drag).
  // Skipped on mobile (windows are full-screen sheets there) and while the
  // window is fullscreen-snapped or docked. Wired here so all ~12 callsites
  // get it without per-file changes.
  if (options.enableResize !== false) {
    // Lock resize whenever the window's layout is owned by something else:
    //  - fullscreen (caller's fsClass)
    //  - a tileManager snap (dataset._tileZone) — its !important inline styles
    //    would silently override windowResize's writes, yet windowResize.end()
    //    would still persist the tiled rect to localStorage and corrupt the
    //    saved windowed size on the next open.
    //  - an active edge-dock (modal-{left,right}-docked). modalSnap.applyEdgeDock
    //    still sets these classes from modalManager/emailInbox/notes until the
    //    remaining callers are rewired (plan Tasks 6-7); resizing a live dock
    //    corrupts its anchored geometry.
    const _dockClasses = ['modal-right-docked', 'modal-left-docked'];
    makeWindowResizable(content, {
      modal,
      mobileSkip,
      minWidth: options.minWidth,
      minHeight: options.minHeight,
      isLocked: () => !!(
        (fsClass && modal && modal.classList.contains(fsClass))
        || (content && content.dataset && content.dataset._tileZone)
        || (modal && _dockClasses.some((c) => modal.classList.contains(c)))
      ),
      storageKey: options.resizeStorageKey
        || (modal && modal.id ? 'winsize-' + modal.id
          : (content.id ? 'winsize-' + content.id : null)),
    });
  }

  // Per-drag state, reset on mousedown.
  let dragging = false;
  let startX = 0, startY = 0;
  let startLeft = 0, startTop = 0;
  let snapHint = null;
  // Whether the pointer actually moved beyond a small threshold this drag.
  // Used to suppress the synthetic click the browser fires on mouseup —
  // header click handlers (e.g. "collapse expanded card / back to list")
  // would otherwise fire after a drag and collapse the modal contents.
  let movedDuringDrag = false;
  const MOVE_THRESHOLD = 4;

  const _showSnapHint = (on) => {
    // Top-edge fullscreen hint. Side/corner ghosts are drawn by tileManager.
    if (!on) {
      if (snapHint) { snapHint.remove(); snapHint = null; }
      return;
    }
    if (snapHint) return;
    snapHint = document.createElement('div');
    snapHint.className = 'modal-snap-hint';
    snapHint.style.cssText =
      'position:fixed;left:0;top:0;right:0;bottom:0;' +
      'background:color-mix(in srgb, var(--accent-primary, #60a5fa) 12%, transparent);' +
      'border:2px dashed color-mix(in srgb, var(--accent-primary, #60a5fa) 60%, transparent);' +
      'z-index:9998;pointer-events:none;';
    document.body.appendChild(snapHint);
  };

  const _enterFs = () => {
    if (!onEnterFullscreen) return;
    if (fsClass && modal && modal.classList.contains(fsClass)) return;
    onEnterFullscreen();
  };
  const _exitFs = (cx, cy) => {
    if (!onExitFullscreen) return;
    if (fsClass && modal && !modal.classList.contains(fsClass)) return;
    onExitFullscreen(cx, cy);
    // After exit, re-anchor the drag offsets to the new windowed rect so
    // the drag continues smoothly from the cursor's position.
    const r = content.getBoundingClientRect();
    startX = cx; startY = cy;
    startLeft = r.left; startTop = r.top;
  };

  const _isFullscreen = () => fsClass && modal && modal.classList.contains(fsClass);

  // Strip a tile snap that tileManager committed on its global pointerup so the
  // caller's fullscreen styles (set by onEnterFullscreen) can actually take
  // effect — tileManager writes !important layout props that otherwise win.
  // Unlike tileManager._unsnap we deliberately do NOT restore the pre-snap
  // windowed geometry, because the very next step is fullscreen. Removing the
  // data-_tile-zone attribute also lets tileManager's close-observer reflow the
  // chat back to the full canvas.
  const _clearTileSnap = () => {
    if (!content) return;
    ['position', 'left', 'top', 'width', 'height', 'max-height', 'margin', 'transform']
      .forEach((p) => content.style.removeProperty(p));
    delete content.dataset._tileZone;
    delete content.dataset._tilePreSnap;
  };

  const _startDrag = (cx, cy) => {
    dragging = true;
    if (modal) modal.classList.add('modal-dragging');
    // Cancel any in-flight open animation so we don't pin a mid-animation
    // rect and then jump once the animation settles.
    try {
      content.getAnimations()
        .filter(a => a.playState !== 'finished')
        .forEach(a => a.cancel());
    } catch (_) {}
    const rect = content.getBoundingClientRect();
    if (onDragStart) {
      try { onDragStart({ rect, cx, cy }); } catch (_) {}
    }
    startX = cx; startY = cy;
    startLeft = rect.left; startTop = rect.top;
    // Pin position so the drag follows the cursor instead of fighting a
    // centering transform / margin. Inline styles win unless CSS uses
    // !important (the fullscreen rules do, by design).
    content.style.position = 'fixed';
    content.style.left = startLeft + 'px';
    content.style.top = startTop + 'px';
    content.style.transform = 'none';
    content.style.margin = '0';
  };

  const _onMove = (cx, cy) => {
    if (!dragging) return;
    // Fullscreen state: a downward drag past the unsnap band restores the
    // window to a windowed (centered) modal so it can be moved freely. Side /
    // corner edge snapping while dragging is handled by tileManager's global
    // pointer listeners — windowDrag no longer arms any edge dock here.
    if (_isFullscreen()) {
      if (cy > UNSNAP_PX) {
        _exitFs(cx, cy);
      }
      return;
    }
    // Windowed: just follow the cursor.
    if (Math.abs(cx - startX) > MOVE_THRESHOLD || Math.abs(cy - startY) > MOVE_THRESHOLD) {
      movedDuringDrag = true;
    }
    content.style.left = (startLeft + cx - startX) + 'px';
    content.style.top = (startTop + cy - startY) + 'px';
    // Top-edge fullscreen hint (left/right/corner ghosts come from tileManager).
    const inTopBand = cy <= SNAP_PX;
    _showSnapHint(enableFullscreen && inTopBand);
  };

  const _onEnd = (cx, cy) => {
    if (!dragging) return;
    dragging = false;
    if (modal) modal.classList.remove('modal-dragging');
    _showSnapHint(false);
    // tileManager's global pointerup fires BEFORE this mouseup handler, so if a
    // tile zone was committed the snapped rect is already written to `content`
    // and dataset._tileZone is set. Bail out before the fullscreen-enter /
    // onDragEnd paths: onDragEnd would persist the snapped half-canvas coords
    // (corrupting the saved window position), and a horizontal snap out of a
    // fullscreen window must also drop fsClass or the next drag wrongly takes
    // the fullscreen code path.
    if (content && content.dataset._tileZone) {
      // tileManager's top strip overlaps windowDrag's top-edge fullscreen band
      // (cy <= SNAP_PX): a release there commits 'maximize' (or 'fullscreen' at
      // the very top) BEFORE this mouseup runs. For a fullscreen-capable window
      // the fullscreen gesture wins — undo tileManager's snap so the caller's
      // fullscreen styles apply, then enter fullscreen. Without this, fsClass is
      // never added and downstream fullscreen-gated behavior (e.g. the email +
      // document split) silently breaks.
      if (enableFullscreen && typeof cy === 'number' && cy <= SNAP_PX
          && TILE_TOP_STRIP_ZONES.includes(content.dataset._tileZone)) {
        _clearTileSnap();
        _enterFs();
        return;
      }
      if (fsClass && modal) modal.classList.remove(fsClass);
      return;
    }
    // Top edge → fullscreen. Left/right/corner edge snapping is committed by
    // tileManager's global pointerup listener, not here.
    if (enableFullscreen && typeof cy === 'number' && cy <= SNAP_PX) {
      _enterFs();
      return;
    }
    if (onDragEnd) {
      const r = content.getBoundingClientRect();
      try { onDragEnd({ rect: r }); } catch (_) {}
    }
  };

  header.addEventListener('mousedown', (e) => {
    if (mobileSkip > 0 && window.innerWidth <= mobileSkip) return;
    if (skipSelector && e.target.closest(skipSelector)) return;
    e.preventDefault();
    movedDuringDrag = false;
    _startDrag(e.clientX, e.clientY);
    const onMove = (ev) => _onMove(ev.clientX, ev.clientY);
    const onUp = (ev) => {
      _onEnd(ev.clientX, ev.clientY);
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      // If the pointer actually moved, swallow the synthetic click the
      // browser fires next — otherwise a header click handler (collapse
      // expanded card / "back to list") runs and undoes the drag intent.
      if (movedDuringDrag) {
        const swallow = (clickEv) => {
          clickEv.stopPropagation();
          clickEv.preventDefault();
        };
        header.addEventListener('click', swallow, { capture: true, once: true });
        // Safety: if no click fires (some browsers), drop the listener.
        setTimeout(() => header.removeEventListener('click', swallow, { capture: true }), 50);
      }
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });

  if (enableTouch) {
    header.addEventListener('touchstart', (e) => {
      if (mobileSkip > 0 && window.innerWidth <= mobileSkip) return;
      if (skipSelector && e.target.closest(skipSelector)) return;
      const t = e.touches[0];
      if (!t) return;
      movedDuringDrag = false;
      _startDrag(t.clientX, t.clientY);
      const onMove = (ev) => {
        const tt = ev.touches[0];
        if (tt) _onMove(tt.clientX, tt.clientY);
      };
      const onEnd = (ev) => {
        const tt = (ev.changedTouches && ev.changedTouches[0]) || null;
        _onEnd(tt ? tt.clientX : null, tt ? tt.clientY : null);
        document.removeEventListener('touchmove', onMove);
        document.removeEventListener('touchend', onEnd);
        document.removeEventListener('touchcancel', onEnd);
      };
      document.addEventListener('touchmove', onMove, { passive: true });
      document.addEventListener('touchend', onEnd);
      document.addEventListener('touchcancel', onEnd);
    }, { passive: true });
  }
}
