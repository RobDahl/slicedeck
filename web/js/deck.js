/**
 * The virtual Stream Deck: key rendering, press feedback, and the zoom
 * transition that makes drilling into a key legible.
 *
 * Every key is its own canvas sized to the real hardware's key resolution
 * (72px on an MK.2, 96px on an XL), so what the demo shows is pixel-for-pixel
 * what the device would receive.
 */

const PRESS_MS = 130;
const ZOOM_MS = 420;

export class Deck {
  constructor(root) {
    this.root = root;
    this.grid = root.querySelector('.deck__grid');
    this.overlay = root.querySelector('.deck__overlay');
    this.keys = [];
    this.spec = null;
    this.onPress = () => {};
    this.onHover = () => {};

    this.grid.addEventListener('pointerleave', () => this.onHover(null));
  }

  /** Rebuild the key grid for a deck model. */
  setLayout(spec) {
    this.spec = spec;
    // On the root, not the grid: the CSS height cap on .deck reads them too,
    // and custom properties inherit down to the grid from here.
    this.root.style.setProperty('--cols', spec.cols);
    this.root.style.setProperty('--rows', spec.rows);
    this.grid.replaceChildren();
    this.keys = [];

    for (let row = 0; row < spec.rows; row++) {
      for (let col = 0; col < spec.cols; col++) {
        const index = row * spec.cols + col;
        const button = document.createElement('button');
        button.className = 'key';
        button.type = 'button';
        button.dataset.key = String(index);
        button.setAttribute('aria-label', `Key row ${row + 1}, column ${col + 1}`);

        const canvas = document.createElement('canvas');
        canvas.width = spec.keyPx;
        canvas.height = spec.keyPx;
        canvas.className = 'key__screen';

        const flash = document.createElement('span');
        flash.className = 'key__flash';

        button.append(canvas, flash);
        button.addEventListener('click', () => this.press(index, row, col));
        button.addEventListener('pointerenter', () => this.onHover({ index, row, col }));

        this.grid.append(button);
        this.keys.push({
          index, row, col, button, canvas,
          ctx: canvas.getContext('2d', { willReadFrequently: true }),
        });
      }
    }
  }

  /** Copy one region of the source frame onto one key. */
  draw(index, source, sx, sy, sw, sh) {
    const key = this.keys[index];
    if (!key) return;
    key.ctx.drawImage(source, sx, sy, sw, sh, 0, 0, key.canvas.width, key.canvas.height);
  }

  press(index, row, col) {
    this.playPress(index);
    this.onPress({ index, row, col });
  }

  /** The physical-feeling part: the key dips, then a light flashes off it. */
  playPress(index) {
    const key = this.keys[index];
    if (!key) return;
    key.button.animate(
      [
        { transform: 'translateY(0) scale(1)' },
        { transform: 'translateY(2px) scale(0.94)' },
        { transform: 'translateY(0) scale(1)' },
      ],
      { duration: PRESS_MS * 2, easing: 'cubic-bezier(.3,.8,.4,1)' },
    );
    const flash = key.button.querySelector('.key__flash');
    flash.animate(
      [{ opacity: 0.72 }, { opacity: 0 }],
      { duration: PRESS_MS * 2.4, easing: 'ease-out' },
    );
  }

  /**
   * Zoom transition: lift the pressed key's image out of the grid and grow it
   * until it covers the whole deck. That single movement is what tells the
   * viewer the deck is now showing the inside of that one key.
   */
  zoomInto(index) {
    const key = this.keys[index];
    if (!key) return Promise.resolve();

    const from = key.button.getBoundingClientRect();
    const to = this.grid.getBoundingClientRect();
    const host = this.overlay.getBoundingClientRect();

    const clone = document.createElement('canvas');
    clone.width = key.canvas.width;
    clone.height = key.canvas.height;
    clone.getContext('2d').drawImage(key.canvas, 0, 0);
    clone.className = 'deck__zoomer';
    Object.assign(clone.style, {
      left: `${from.left - host.left}px`,
      top: `${from.top - host.top}px`,
      width: `${from.width}px`,
      height: `${from.height}px`,
    });
    this.overlay.append(clone);

    const animation = clone.animate(
      [
        { transform: 'translate(0,0) scale(1)', opacity: 1, borderRadius: '10px' },
        {
          transform:
            `translate(${to.left - from.left}px, ${to.top - from.top}px) ` +
            `scale(${to.width / from.width}, ${to.height / from.height})`,
          opacity: 0,
          borderRadius: '2px',
        },
      ],
      { duration: ZOOM_MS, easing: 'cubic-bezier(.16,.84,.34,1)', fill: 'forwards' },
    );
    // transform-origin has to match the corner the offsets were measured from.
    clone.style.transformOrigin = 'top left';

    return animation.finished.then(() => clone.remove()).catch(() => clone.remove());
  }

  /** Reverse of zoomInto: the whole deck collapses back into one key. */
  zoomOutTo(index) {
    const key = this.keys[index];
    const to = key ? key.button.getBoundingClientRect() : this.grid.getBoundingClientRect();
    const from = this.grid.getBoundingClientRect();
    const host = this.overlay.getBoundingClientRect();

    const clone = document.createElement('div');
    clone.className = 'deck__zoomer deck__zoomer--out';
    Object.assign(clone.style, {
      left: `${from.left - host.left}px`,
      top: `${from.top - host.top}px`,
      width: `${from.width}px`,
      height: `${from.height}px`,
      transformOrigin: 'top left',
    });
    this.overlay.append(clone);

    const animation = clone.animate(
      [
        { transform: 'translate(0,0) scale(1)', opacity: 0.85 },
        {
          transform:
            `translate(${to.left - from.left}px, ${to.top - from.top}px) ` +
            `scale(${to.width / from.width}, ${to.height / from.height})`,
          opacity: 0,
        },
      ],
      { duration: ZOOM_MS * 0.8, easing: 'cubic-bezier(.16,.84,.34,1)', fill: 'forwards' },
    );
    return animation.finished.then(() => clone.remove()).catch(() => clone.remove());
  }
}
