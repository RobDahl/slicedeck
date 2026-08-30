/**
 * Per-key motion detection - a port of src/slicedeck/motion.py.
 *
 * Two signals, because either alone misses a class of motion:
 *   mean difference  - catches whole-tile changes, blind to small fast movers
 *   changed area     - catches the small mover, blind to uniform drift
 * A key is moving if either fires; a key is dirty (worth redrawing) at much
 * lower bars. Skipping clean keys is what keeps the frame budget flat as the
 * grid grows from 6 keys to 32.
 */

export const PROBE = 24;

export class MotionDetector {
  constructor(options = {}) {
    this.threshold = options.threshold ?? 12;
    this.pixelFloor = options.pixelFloor ?? 10;
    this.motionArea = options.motionArea ?? 0.02;
    this.dirtyThreshold = options.dirtyThreshold ?? 1;
    this.dirtyArea = options.dirtyArea ?? 0.004;

    this.probes = new Map();
    // One reusable scratch canvas: allocating per key per frame is what makes
    // naive canvas pipelines stutter once the grid gets large.
    this.scratch = document.createElement('canvas');
    this.scratch.width = PROBE;
    this.scratch.height = PROBE;
    this.ctx = this.scratch.getContext('2d', { willReadFrequently: true });
  }

  reset() { this.probes.clear(); }

  /** Downsample a tile to a PROBE x PROBE luminance array. */
  probe(source, sx, sy, sw, sh) {
    this.ctx.drawImage(source, sx, sy, sw, sh, 0, 0, PROBE, PROBE);
    const { data } = this.ctx.getImageData(0, 0, PROBE, PROBE);
    const luma = new Uint8Array(PROBE * PROBE);
    for (let i = 0, p = 0; i < data.length; i += 4, p++) {
      // Rec. 601 luma, matching PIL's ImageOps.grayscale.
      luma[p] = (data[i] * 299 + data[i + 1] * 587 + data[i + 2] * 114) / 1000;
    }
    return luma;
  }

  update(key, source, sx, sy, sw, sh) {
    const current = this.probe(source, sx, sy, sw, sh);
    const previous = this.probes.get(key);
    this.probes.set(key, current);

    if (!previous) {
      return { score: 255, area: 1, moving: true, dirty: true };
    }

    let total = 0;
    let changed = 0;
    for (let i = 0; i < current.length; i++) {
      const diff = Math.abs(current[i] - previous[i]);
      total += diff;
      if (diff > this.pixelFloor) changed++;
    }
    const score = total / current.length;
    const area = changed / current.length;

    return {
      score,
      area,
      moving: score >= this.threshold || area >= this.motionArea,
      dirty: score >= this.dirtyThreshold || area >= this.dirtyArea,
    };
  }
}
