/**
 * Grid maths - a direct port of src/slicedeck/slicer.py.
 *
 * Kept in lockstep with the Python so the browser demo and the hardware
 * pipeline frame identically: same cover-fit rule, same rounding, same zoom
 * semantics. tests/test_slicer.py is the specification for both.
 */

/**
 * A viewport may not shrink below this many source pixels per cell. Past 1:1 a
 * key is interpolating rather than resolving new detail, but a couple of levels
 * of that is still useful digital zoom; below a handful of pixels there is no
 * information left at all, so the stack stops.
 */
export const MIN_CELL_PX = 8;

export const DECKS = {
  mini: { name: 'Stream Deck Mini', cols: 3, rows: 2, keyPx: 80 },
  mk2: { name: 'Stream Deck MK.2', cols: 5, rows: 3, keyPx: 72 },
  xl: { name: 'Stream Deck XL', cols: 8, rows: 4, keyPx: 96 },
  plus: { name: 'Stream Deck +', cols: 4, rows: 2, keyPx: 120 },
};

export class Box {
  constructor(left, top, right, bottom) {
    this.left = left;
    this.top = top;
    this.right = right;
    this.bottom = bottom;
  }
  get width() { return this.right - this.left; }
  get height() { return this.bottom - this.top; }
}

/**
 * The region of the frame that maps onto the whole deck.
 *
 * Dividing width by columns and height by rows - the obvious approach - gives
 * non-square cells, which a square key then stretches. Cropping to the deck's
 * aspect ratio first keeps every tile square and the mosaic undistorted.
 */
export function sourceRect(frameW, frameH, deck, zoom = null) {
  const left = zoom ? zoom.left : 0;
  const top = zoom ? zoom.top : 0;
  const width = (zoom ? zoom.right : frameW) - left;
  const height = (zoom ? zoom.bottom : frameH) - top;

  const target = deck.cols / deck.rows;
  const current = width / height;

  if (current > target) {
    const newW = Math.round(height * target);
    const inset = Math.floor((width - newW) / 2);
    return new Box(left + inset, top, left + inset + newW, top + height);
  }
  const newH = Math.round(width / target);
  const inset = Math.floor((height - newH) / 2);
  return new Box(left, top + inset, left + width, top + inset + newH);
}

/** Cell rectangles in reading order. Rounding is distributed so cells tile exactly. */
export function cells(frameW, frameH, deck, zoom = null) {
  const rect = sourceRect(frameW, frameH, deck, zoom);
  const out = [];
  for (let row = 0; row < deck.rows; row++) {
    const top = rect.top + Math.round((row * rect.height) / deck.rows);
    const bottom = rect.top + Math.round(((row + 1) * rect.height) / deck.rows);
    for (let col = 0; col < deck.cols; col++) {
      const left = rect.left + Math.round((col * rect.width) / deck.cols);
      const right = rect.left + Math.round(((col + 1) * rect.width) / deck.cols);
      out.push({ row, col, key: row * deck.cols + col, box: new Box(left, top, right, bottom) });
    }
  }
  return out;
}

/**
 * Zoom state: a stack of source rectangles.
 *
 * Pressing a key pushes that key's rectangle, so the entire deck then shows
 * what one key was showing. Because the rectangle lives in source pixels,
 * drilling in reveals real detail instead of upscaling a 96px tile.
 */
export class ZoomStack {
  constructor() { this.stack = []; }

  get current() { return this.stack.length ? this.stack[this.stack.length - 1] : null; }
  get depth() { return this.stack.length; }

  /** How much the current viewport magnifies the full frame. */
  magnification(frameW) {
    return this.current ? frameW / this.current.width : 1;
  }

  /** True once a key shows fewer source pixels than it has key pixels. */
  isInterpolated(frameW, frameH, deck) {
    const grid = cells(frameW, frameH, deck, this.current);
    return grid.length > 0 && grid[0].box.width < deck.keyPx;
  }

  /**
   * Drill into one key. Returns false when the viewport holds too little
   * information to divide again.
   */
  push(frameW, frameH, deck, row, col) {
    const cell = cells(frameW, frameH, deck, this.current)
      .find((c) => c.row === row && c.col === col);
    if (!cell) return false;
    // Look one step ahead: the press only helps if the resulting viewport can
    // still be split into cells that carry pixels.
    const next = cells(cell.box.width, cell.box.height, deck);
    if (Math.min(next[0].box.width, next[0].box.height) < MIN_CELL_PX) return false;
    this.stack.push(cell.box);
    return true;
  }

  pop() { return this.stack.pop() ?? null; }
  clear() { this.stack.length = 0; }

  /** Drop a viewport that no longer fits, e.g. after switching to a smaller source. */
  clampTo(frameW, frameH) {
    const box = this.current;
    if (box && (box.right > frameW || box.bottom > frameH)) {
      this.clear();
      return true;
    }
    return false;
  }
}
