/**
 * tileLayout.js — pure layout math for the tiling canvas. No DOM access.
 *
 * The canvas is a 2x2 grid of cells, keyed "c,r" with c in {0,1} (column)
 * and r in {0,1} (row): "0,0"=top-left, "1,0"=top-right, "0,1"=bottom-left,
 * "1,1"=bottom-right.
 */

// The canvas is split into a fixed 2x2 grid of cells. Naming the dimensions
// keeps the halving math below from being a bare literal.
const GRID_COLS = 2;
const GRID_ROWS = 2;

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
  const halfW = canvas.width / GRID_COLS;
  const halfH = canvas.height / GRID_ROWS;
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
