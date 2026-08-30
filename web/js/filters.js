/**
 * Client-side filters mirroring src/slicedeck/filters/__init__.py.
 *
 * Filters run once on the whole frame before slicing, not per tile, so effects
 * with spatial extent - edges, pixelate, scanlines - stay continuous across key
 * boundaries instead of restarting inside every key.
 *
 * Cheap point operations go through a canvas filter string (the browser runs
 * them on the GPU); the rest walk the pixel buffer.
 */

const clamp = (value) => (value < 0 ? 0 : value > 255 ? 255 : value);

// Reused across frames; resized only when the frame size changes.
let byteScratch = null;
let floatScratch = null;

function scratchBytes(length, copyFrom) {
  if (!byteScratch || byteScratch.length !== length) byteScratch = new Uint8ClampedArray(length);
  byteScratch.set(copyFrom);
  return byteScratch;
}

function scratchFloats(length) {
  if (!floatScratch || floatScratch.length !== length) floatScratch = new Float32Array(length);
  return floatScratch;
}

/** Filters expressible as a CSS filter string, which is far faster than JS pixel loops. */
const CSS_FILTERS = {
  grayscale: () => 'grayscale(1)',
  invert: () => 'invert(1)',
  blur: (arg) => `blur(${arg ?? 2}px)`,
  contrast: (arg) => `contrast(${arg ?? 1.6})`,
  sepia: () => 'sepia(0.85)',
  saturate: (arg) => `saturate(${arg ?? 2.2})`,
};

function thermalRamp() {
  const stops = [
    [0.0, [0, 0, 24]],
    [0.25, [60, 0, 130]],
    [0.5, [200, 30, 120]],
    [0.75, [250, 150, 30]],
    [1.0, [255, 255, 220]],
  ];
  const lut = new Uint8Array(256 * 3);
  for (let value = 0; value < 256; value++) {
    const t = value / 255;
    for (let i = 0; i < stops.length - 1; i++) {
      const [t0, c0] = stops[i];
      const [t1, c1] = stops[i + 1];
      if (t >= t0 && t <= t1) {
        const k = t1 === t0 ? 0 : (t - t0) / (t1 - t0);
        for (let ch = 0; ch < 3; ch++) lut[value * 3 + ch] = Math.round(c0[ch] + (c1[ch] - c0[ch]) * k);
        break;
      }
    }
  }
  return lut;
}

const THERMAL = thermalRamp();

/** Filters that need the pixel buffer. Each mutates `data` in place. */
const PIXEL_FILTERS = {
  threshold(data, _w, _h, arg) {
    // Compare in the scaled integer domain so the hot loop has no division.
    const cut = (arg ?? 128) * 1000;
    for (let i = 0; i < data.length; i += 4) {
      const value = data[i] * 299 + data[i + 1] * 587 + data[i + 2] * 114 >= cut ? 255 : 0;
      data[i] = data[i + 1] = data[i + 2] = value;
    }
  },

  posterize(data, _w, _h, arg) {
    const bits = Math.max(1, Math.min(8, Math.round(arg ?? 3)));
    const mask = (0xff << (8 - bits)) & 0xff;
    for (let i = 0; i < data.length; i += 4) {
      data[i] &= mask;
      data[i + 1] &= mask;
      data[i + 2] &= mask;
    }
  },

  thermal(data) {
    for (let i = 0; i < data.length; i += 4) {
      // Fixed-point luma: >> 10 divides by 1024, close enough to the 1000 scale
      // for a lookup index and far cheaper than a divide plus a round.
      const luma = (data[i] * 306 + data[i + 1] * 601 + data[i + 2] * 117) >> 10;
      const at = luma * 3;
      data[i] = THERMAL[at];
      data[i + 1] = THERMAL[at + 1];
      data[i + 2] = THERMAL[at + 2];
    }
  },

  scanlines(data, width, height, arg) {
    const period = Math.max(2, Math.round(arg ?? 3));
    for (let y = 0; y < height; y += period) {
      const row = y * width * 4;
      for (let x = 0; x < width; x++) {
        const i = row + x * 4;
        data[i] /= 3;
        data[i + 1] /= 3;
        data[i + 2] /= 3;
      }
    }
  },

  edges(data, width, height) {
    // Sobel on luminance. Reads from a copy so the kernel never sees pixels it
    // has already overwritten. The buffers are cached across frames: allocating
    // two megabyte-scale arrays every frame is what makes naive canvas filters
    // stutter under GC.
    const source = scratchBytes(data.length, data);
    const luma = scratchFloats(width * height);
    for (let i = 0, p = 0; i < source.length; i += 4, p++) {
      luma[p] = (source[i] * 306 + source[i + 1] * 601 + source[i + 2] * 117) >> 10;
    }
    for (let y = 1; y < height - 1; y++) {
      for (let x = 1; x < width - 1; x++) {
        const p = y * width + x;
        const gx =
          -luma[p - width - 1] + luma[p - width + 1] +
          -2 * luma[p - 1] + 2 * luma[p + 1] +
          -luma[p + width - 1] + luma[p + width + 1];
        const gy =
          -luma[p - width - 1] - 2 * luma[p - width] - luma[p - width + 1] +
          luma[p + width - 1] + 2 * luma[p + width] + luma[p + width + 1];
        // Math.hypot guards against overflow that cannot happen on 0-255 data,
        // and costs several times a plain sqrt for it.
        const magnitude = clamp(Math.sqrt(gx * gx + gy * gy));
        const i = p * 4;
        data[i] = data[i + 1] = data[i + 2] = magnitude;
      }
    }
  },
};

/** Filters that resample, so they need their own canvas pass. */
const RESAMPLE_FILTERS = {
  pixelate(ctx, width, height, arg) {
    const target = Math.max(2, Math.round(arg ?? 32));
    const small = Math.max(1, Math.round((target * height) / width));
    const scratch = document.createElement('canvas');
    scratch.width = target;
    scratch.height = small;
    const scratchCtx = scratch.getContext('2d');
    scratchCtx.drawImage(ctx.canvas, 0, 0, target, small);
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(scratch, 0, 0, target, small, 0, 0, width, height);
    ctx.imageSmoothingEnabled = true;
  },
};

export const CATALOGUE = [
  { name: 'grayscale', label: 'Grayscale', doc: 'Desaturate to luminance.' },
  { name: 'invert', label: 'Invert', doc: 'Photographic negative.' },
  { name: 'threshold', label: 'Threshold', doc: 'Hard black/white cut.', default: 128, min: 16, max: 240 },
  { name: 'posterize', label: 'Posterize', doc: 'Reduce bits per channel.', default: 3, min: 1, max: 8 },
  { name: 'pixelate', label: 'Pixelate', doc: 'Downsample, then blow back up.', default: 48, min: 8, max: 160 },
  { name: 'edges', label: 'Edge detect', doc: 'Sobel edge detection.' },
  { name: 'thermal', label: 'Thermal', doc: 'False-colour heat ramp.' },
  { name: 'scanlines', label: 'Scanlines', doc: 'CRT scanlines.', default: 3, min: 2, max: 12 },
  { name: 'blur', label: 'Blur', doc: 'Gaussian blur.', default: 3, min: 1, max: 20 },
  { name: 'sharpen', label: 'Contrast', doc: 'Push contrast.', default: 1.8, min: 1, max: 4, step: 0.1, css: 'contrast' },
  { name: 'sepia', label: 'Sepia', doc: 'Warm tone.' },
  { name: 'saturate', label: 'Saturate', doc: 'Boost colour.', default: 2.2, min: 1, max: 5, step: 0.1 },
];

/**
 * Apply a chain in order to a canvas context.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Array<{name: string, arg?: number}>} chain
 */
export function applyChain(ctx, chain) {
  if (!chain.length) return;
  const { width, height } = ctx.canvas;

  // Group consecutive CSS-expressible filters into one GPU pass.
  let cssRun = [];
  const flushCss = () => {
    if (!cssRun.length) return;
    ctx.save();
    ctx.filter = cssRun.join(' ');
    ctx.globalCompositeOperation = 'copy';
    ctx.drawImage(ctx.canvas, 0, 0);
    ctx.restore();
    cssRun = [];
  };

  for (const step of chain) {
    const entry = CATALOGUE.find((f) => f.name === step.name);
    const cssName = entry?.css ?? step.name;
    if (CSS_FILTERS[cssName]) {
      cssRun.push(CSS_FILTERS[cssName](step.arg));
      continue;
    }
    flushCss();

    if (RESAMPLE_FILTERS[step.name]) {
      RESAMPLE_FILTERS[step.name](ctx, width, height, step.arg);
    } else if (PIXEL_FILTERS[step.name]) {
      const image = ctx.getImageData(0, 0, width, height);
      PIXEL_FILTERS[step.name](image.data, width, height, step.arg);
      ctx.putImageData(image, 0, 0);
    }
  }
  flushCss();
}
