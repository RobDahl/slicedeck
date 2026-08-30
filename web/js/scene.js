/**
 * A procedurally generated orbital scene - the demo's default frame source.
 *
 * A live NASA stream would be the obvious choice, but embedded players do not
 * expose their pixels to canvas and the public HLS endpoints do not send CORS
 * headers, so neither can be sliced client-side. Generating the scene instead
 * means the demo needs no network, no camera permission and no server, and it
 * still gives the motion detector something real to track: a satellite crossing
 * the frame, drifting cloud, and a terminator sweeping around the planet.
 *
 * Mirrors src/slicedeck/sources/synthetic.py.
 */

const WIDTH = 1280;
const HEIGHT = 720;

/** Smooth value noise in [0,1], bilinear with a smoothstep - used as terrain. */
function valueNoise(width, height, cellCount, rand) {
  const coarse = new Float32Array(cellCount * cellCount);
  for (let i = 0; i < coarse.length; i++) coarse[i] = rand();

  const field = new Float32Array(width * height);
  const smooth = (t) => t * t * (3 - 2 * t);

  for (let y = 0; y < height; y++) {
    const fy = (y / height) * (cellCount - 1);
    const y0 = Math.min(Math.floor(fy), cellCount - 2);
    const ty = smooth(fy - y0);
    for (let x = 0; x < width; x++) {
      // Wrap horizontally so the texture can scroll forever without a seam.
      const fx = (x / width) * cellCount;
      const x0 = Math.floor(fx) % cellCount;
      const x1 = (x0 + 1) % cellCount;
      const tx = smooth(fx - Math.floor(fx));
      const c00 = coarse[y0 * cellCount + x0];
      const c01 = coarse[y0 * cellCount + x1];
      const c10 = coarse[(y0 + 1) * cellCount + x0];
      const c11 = coarse[(y0 + 1) * cellCount + x1];
      field[y * width + x] =
        (c00 * (1 - tx) + c01 * tx) * (1 - ty) + (c10 * (1 - tx) + c11 * tx) * ty;
    }
  }
  return field;
}

/** Deterministic PRNG, so the scene looks the same on every load. */
function mulberry32(seed) {
  return function next() {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function buildLayer(width, height, cellCount, seed, paint) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  const image = ctx.createImageData(width, height);
  const noise = valueNoise(width, height, cellCount, mulberry32(seed));
  const fine = valueNoise(width, height, cellCount * 4, mulberry32(seed + 99));
  for (let p = 0; p < noise.length; p++) {
    // Two octaves: broad landmasses plus coastline detail.
    paint(image.data, p * 4, noise[p] * 0.75 + fine[p] * 0.25, p % width, Math.floor(p / width), height);
  }
  ctx.putImageData(image, 0, 0);
  return canvas;
}

export class OrbitalScene {
  constructor() {
    this.width = WIDTH;
    this.height = HEIGHT;
    this.label = 'Simulated orbit';
    this.frame = 0;

    this.canvas = document.createElement('canvas');
    this.canvas.width = WIDTH;
    this.canvas.height = HEIGHT;
    this.ctx = this.canvas.getContext('2d');

    this.surface = buildLayer(WIDTH, HEIGHT, 9, 7, (data, i, value, _x, y, height) => {
      // Latitude bias: ice at the poles, more land in the temperate bands.
      const latitude = Math.abs(y / height - 0.5) * 2;
      const level = value - latitude * 0.18;
      if (latitude > 0.86) {
        data[i] = 226; data[i + 1] = 234; data[i + 2] = 240;
      } else if (level > 0.56) {
        const green = 74 + (level - 0.56) * 260;
        data[i] = 42 + latitude * 40; data[i + 1] = green; data[i + 2] = 48;
      } else if (level > 0.52) {
        data[i] = 196; data[i + 1] = 178; data[i + 2] = 118; // coastal sand
      } else {
        const depth = 0.52 - level;
        data[i] = 10; data[i + 1] = 48 - depth * 40; data[i + 2] = 124 - depth * 80;
      }
      data[i + 3] = 255;
    });

    this.clouds = buildLayer(WIDTH, HEIGHT, 7, 21, (data, i, value) => {
      const alpha = Math.max(0, Math.min(1, (value - 0.58) * 3.4));
      data[i] = 240; data[i + 1] = 246; data[i + 2] = 252;
      data[i + 3] = alpha * 235;
    });

    this.stars = this.buildStars();
  }

  buildStars() {
    const canvas = document.createElement('canvas');
    canvas.width = WIDTH;
    canvas.height = HEIGHT;
    const ctx = canvas.getContext('2d');
    const rand = mulberry32(3);
    ctx.fillStyle = '#05060d';
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    for (let i = 0; i < 520; i++) {
      const x = rand() * WIDTH;
      const y = rand() * HEIGHT;
      const brightness = rand() ** 2.2;
      const radius = brightness * 1.5 + 0.2;
      ctx.globalAlpha = 0.25 + brightness * 0.75;
      ctx.fillStyle = rand() > 0.9 ? '#cfe0ff' : '#ffffff';
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    return canvas;
  }

  /** Render the next frame and return the canvas holding it. */
  read() {
    const ctx = this.ctx;
    const t = this.frame++;

    const cx = WIDTH * 0.5;
    const cy = HEIGHT * 0.58;
    const radius = Math.min(WIDTH, HEIGHT) * 0.44;

    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;
    ctx.drawImage(this.stars, 0, 0);

    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.clip();

    // Rotation: scroll the seamless texture and draw it twice so the wrap point
    // is always covered.
    const spin = (t * 0.6) % WIDTH;
    ctx.drawImage(this.surface, -spin, cy - radius, WIDTH, radius * 2);
    ctx.drawImage(this.surface, WIDTH - spin, cy - radius, WIDTH, radius * 2);

    const drift = (t * 1.1) % WIDTH;
    ctx.globalAlpha = 0.62;
    ctx.drawImage(this.clouds, -drift, cy - radius, WIDTH, radius * 2);
    ctx.drawImage(this.clouds, WIDTH - drift, cy - radius, WIDTH, radius * 2);
    ctx.globalAlpha = 1;

    // Sunlight: a moving highlight plus a hard-ish terminator into night.
    const angle = t * 0.006;
    const sunX = cx + Math.cos(angle) * radius * 0.85;
    const sunY = cy - radius * 0.35;
    const light = ctx.createRadialGradient(sunX, sunY, radius * 0.05, sunX, sunY, radius * 2.1);
    light.addColorStop(0, 'rgba(255,246,220,0.42)');
    light.addColorStop(0.32, 'rgba(255,238,200,0.06)');
    light.addColorStop(0.62, 'rgba(2,6,20,0.55)');
    light.addColorStop(1, 'rgba(0,1,8,0.94)');
    ctx.fillStyle = light;
    ctx.fillRect(cx - radius, cy - radius, radius * 2, radius * 2);

    // Limb darkening, so the sphere reads as curved rather than as a flat disc.
    const limb = ctx.createRadialGradient(cx, cy, radius * 0.62, cx, cy, radius);
    limb.addColorStop(0, 'rgba(0,0,0,0)');
    limb.addColorStop(1, 'rgba(0,2,12,0.8)');
    ctx.fillStyle = limb;
    ctx.fillRect(cx - radius, cy - radius, radius * 2, radius * 2);
    ctx.restore();

    // Atmosphere: a glow hugging the outside of the limb.
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    const halo = ctx.createRadialGradient(cx, cy, radius * 0.97, cx, cy, radius * 1.1);
    halo.addColorStop(0, 'rgba(80,150,255,0.55)');
    halo.addColorStop(1, 'rgba(60,120,255,0)');
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(cx, cy, radius * 1.12, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    this.drawSatellite(ctx, t);
    return this.canvas;
  }

  /** A satellite tracking across frame - the reference target for motion detection. */
  drawSatellite(ctx, t) {
    const span = WIDTH + 160;
    const x = ((t * 2.6) % span) - 80;
    const y = HEIGHT * 0.19 + Math.sin(t * 0.02) * HEIGHT * 0.07;

    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(Math.sin(t * 0.02) * 0.25);

    ctx.strokeStyle = 'rgba(150,170,210,0.9)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(-26, 0);
    ctx.lineTo(26, 0);
    ctx.stroke();

    ctx.fillStyle = '#3f5c96';
    ctx.fillRect(-26, -7, 16, 14);
    ctx.fillRect(10, -7, 16, 14);

    ctx.fillStyle = '#e8ecf6';
    ctx.fillRect(-6, -6, 12, 12);

    ctx.globalCompositeOperation = 'lighter';
    ctx.fillStyle = 'rgba(120,200,255,0.35)';
    ctx.beginPath();
    ctx.arc(0, 0, 16, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  stop() {}
}
