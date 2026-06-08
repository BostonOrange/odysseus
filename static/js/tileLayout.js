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
