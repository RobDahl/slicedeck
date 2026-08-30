/**
 * Frame sources for the browser demo, mirroring src/slicedeck/sources/.
 *
 * Each exposes the same contract as the Python side: `read()` returns something
 * drawable, plus `width`, `height` and a `label`.
 */

import { OrbitalScene } from './scene.js';

/** The visitor's own camera. The most convincing demo: they are the feed. */
export class WebcamSource {
  constructor() {
    this.label = 'Your camera';
    this.width = 0;
    this.height = 0;
    this.video = null;
    this.stream = null;
  }

  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' },
      audio: false,
    });
    const video = document.createElement('video');
    video.srcObject = this.stream;
    video.muted = true;
    video.playsInline = true;
    await video.play();
    // Metadata can still be pending right after play() resolves.
    if (!video.videoWidth) {
      await new Promise((resolve) => video.addEventListener('loadedmetadata', resolve, { once: true }));
    }
    this.video = video;
    this.width = video.videoWidth;
    this.height = video.videoHeight;
    return this;
  }

  read() {
    return this.video;
  }

  stop() {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.video = null;
  }
}

/**
 * A live feed served by the Python API, proving the browser and the hardware
 * pipeline are the same system. Optional: the static demo works without it.
 */
export class ApiSource {
  constructor(baseUrl) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.label = 'Live API';
    this.width = 0;
    this.height = 0;
    this.image = new Image();
    this.image.crossOrigin = 'anonymous';
    this.pending = false;
    this.ready = false;
  }

  async start() {
    // Fail fast with a clear message rather than showing an empty deck.
    const response = await fetch(`${this.baseUrl}/api/config`, { signal: AbortSignal.timeout(4000) });
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    const config = await response.json();
    this.label = `Live API - ${config.source_label ?? 'camera'}`;
    await this.fetchFrame();
    return this;
  }

  fetchFrame() {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.crossOrigin = 'anonymous';
      image.onload = () => {
        this.image = image;
        this.width = image.naturalWidth;
        this.height = image.naturalHeight;
        this.ready = true;
        resolve(image);
      };
      image.onerror = () => reject(new Error('preview fetch failed'));
      image.src = `${this.baseUrl}/api/preview.jpg?t=${Date.now()}`;
    });
  }

  read() {
    // Non-blocking: keep drawing the last frame while the next one loads, so a
    // slow network degrades the frame rate instead of stalling the render loop.
    if (!this.pending) {
      this.pending = true;
      this.fetchFrame()
        .catch(() => {})
        .finally(() => { this.pending = false; });
    }
    return this.ready ? this.image : null;
  }

  stop() {}
}

export function createScene() {
  const scene = new OrbitalScene();
  return scene;
}

/**
 * Real NASA footage, streamed straight from the agency's public asset host.
 *
 * These are the only real feeds the static demo can use: the pipeline needs
 * `getImageData` on every frame, so anything without `Access-Control-Allow-Origin`
 * taints the canvas and kills the filters and the motion detector. NASA's
 * images-assets host sends the header and supports range requests, so the clip
 * streams in rather than downloading first. Everything there is public domain.
 *
 * Renditions are `~medium` (1280x720), which matches the frame size the rest of
 * the demo is tuned for; `~small` is 640x360 and would leave an XL interpolating
 * at the very first zoom level.
 */
const NASA_HOST = 'https://images-assets.nasa.gov/video';

/**
 * `start`/`end` trim each clip to the stretch that is actually footage. These
 * are packaged videos: they open on a title card and some carry an interview or
 * an end slate. Looping the whole file would put a caption board on the keys.
 */
export const NASA_CLIPS = [
  {
    id: 'iss',
    label: 'Earth from the ISS',
    asset: 'Earth Views from the International Space Station',
    start: 14,
    end: 185,
    note: 'Coastlines and cloud banks sliding past. Almost every tile changes, so little gets skipped.',
  },
  {
    id: 'mars',
    label: 'Perseverance descends to Mars',
    asset: 'JPL-20201221-M2020f-0002-EDL Full Version w SFX',
    start: 100,
    end: 170,
    // The other landing cuts are pillarboxed, which puts eight dead black keys
    // on an XL. This one fills the frame.
    note: 'Descent camera over Jezero crater: dust, terrain, hard cuts. The worst case for dirty-tile skipping.',
  },
  {
    id: 'sun',
    label: 'Solar flare (SDO)',
    asset: 'GSFC_20160426_SDO_m12224_SolarFlare',
    start: 10,
    end: 62,
    note: 'Extreme-ultraviolet imagery of the Sun. Try thermal or threshold on it.',
  },
  {
    id: 'jupiter',
    label: 'Jupiter and the Great Red Spot',
    asset: 'GSFC_20180313_Jupiter_m12878_GreatRedSpot',
    start: 26,
    end: 44,
    note: 'Slow banded flow over the storm - a near-still scene, so the skip ratio climbs.',
  },
];

export function nasaClipUrl(asset) {
  const name = encodeURIComponent(asset);
  return `${NASA_HOST}/${name}/${name}~medium.mp4`;
}

/**
 * Any `<video>` the browser can decode: a NASA clip over the network, or a file
 * the visitor picked off their own disk.
 */
export class VideoSource {
  constructor(url, { label = 'Video', credit = '', revoke = false, start = 0, end = 0 } = {}) {
    this.url = url;
    this.label = label;
    this.credit = credit;
    this.revoke = revoke;
    // Not `this.start`: that is the method every source exposes.
    this.from = start;
    this.to = end;
    this.width = 0;
    this.height = 0;
    this.video = null;
  }

  async start() {
    const video = document.createElement('video');
    // Must be set before src, or the request goes out without the CORS mode and
    // the canvas is tainted even though the server would have allowed it.
    video.crossOrigin = 'anonymous';
    video.loop = true;
    video.muted = true;
    video.playsInline = true;
    video.preload = 'auto';
    video.src = this.url;

    await new Promise((resolve, reject) => {
      const cleanup = () => {
        clearTimeout(timer);
        video.removeEventListener('loadeddata', onReady);
        video.removeEventListener('error', onError);
      };
      const onReady = () => { cleanup(); resolve(); };
      const onError = () => { cleanup(); reject(new Error('the clip could not be decoded')); };
      // A stalled CDN should not leave the visitor watching a frozen deck.
      const timer = setTimeout(() => { cleanup(); reject(new Error('timed out while buffering')); }, 20000);
      video.addEventListener('loadeddata', onReady, { once: true });
      video.addEventListener('error', onError, { once: true });
    });

    if (this.from) {
      video.currentTime = this.from;
      await new Promise((resolve) => video.addEventListener('seeked', resolve, { once: true }));
    }
    // Loop the trimmed window rather than the file. `loop` stays on as the
    // fallback for a clip with no window set.
    if (this.to) {
      video.addEventListener('timeupdate', () => {
        if (video.currentTime >= this.to) video.currentTime = this.from;
      });
    }

    // Muted autoplay is allowed everywhere, but a rejected play() should not
    // take the whole source down: the first frame is already decoded.
    await video.play().catch(() => {});

    this.video = video;
    this.width = video.videoWidth;
    this.height = video.videoHeight;
    return this;
  }

  read() {
    // HAVE_CURRENT_DATA or better. While the buffer is refilling this returns
    // null and the render loop simply leaves the last frame on the keys.
    return this.video && this.video.readyState >= 2 ? this.video : null;
  }

  stop() {
    if (!this.video) return;
    this.video.pause();
    this.video.removeAttribute('src');
    this.video.load();
    if (this.revoke) URL.revokeObjectURL(this.url);
    this.video = null;
  }
}
