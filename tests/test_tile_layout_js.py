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
    # as_uri() yields a file:/// URL; Node's ESM loader on Windows rejects a
    # bare C:/... path (as_posix()) with ERR_UNSUPPORTED_ESM_URL_SCHEME.
    js = f"""
    import {{ cellsForZone, largestFreeRect, rectForCells, freeCellsForChat }} from '{_HELPER.as_uri()}';
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
    assert _run("cellsForZone('top-right')") == ["1,0"]
    assert _run("cellsForZone('bottom-left')") == ["0,1"]
    assert _run("cellsForZone('bottom-right')") == ["1,1"]
    assert sorted(_run("cellsForZone('maximize')")) == ["0,0", "0,1", "1,0", "1,1"]
    assert sorted(_run("cellsForZone('fullscreen')")) == ["0,0", "0,1", "1,0", "1,1"]


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_cells_for_zone_unknown_returns_empty():
    # Unknown zone names fall back to an empty cell list (no occlusion).
    assert _run("cellsForZone('nonexistent-zone')") == []


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_largest_free_rect_empty_is_full_canvas():
    r = _run("largestFreeRect([], CANVAS)")
    assert r == {"left": 100, "top": 0, "width": 800, "height": 600}


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_largest_free_rect_null_input_is_full_canvas():
    # A null occupiedCells (no tiled tools yet) is treated as empty.
    r = _run("largestFreeRect(null, CANVAS)")
    assert r == {"left": 100, "top": 0, "width": 800, "height": 600}


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_largest_free_rect_tool_right_half_chat_takes_left():
    # tool occupies right column -> chat = left half
    r = _run("largestFreeRect(cellsForZone('right-half'), CANVAS)")
    assert r == {"left": 100, "top": 0, "width": 400, "height": 600}


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_largest_free_rect_tool_left_half_chat_takes_right():
    # tool occupies left column -> chat = right half
    r = _run("largestFreeRect(cellsForZone('left-half'), CANVAS)")
    assert r == {"left": 500, "top": 0, "width": 400, "height": 600}


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
