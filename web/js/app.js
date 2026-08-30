/**
 * Wiring for the demo: source -> filters -> slice -> motion -> keys.
 *
 * The same order as src/slicedeck/pipeline.py, including the part that
 * matters most for throughput: only keys the motion detector marks dirty are
 * redrawn. On a still scene that turns 32 draws per frame into none.
 */

import { Deck } from './deck.js';
import { CATALOGUE, applyChain } from './filters.js';
import { MotionDetector } from './motion.js';
import { DECKS, ZoomStack, cells } from './slicer.js';
import { ApiSource, NASA_CLIPS, VideoSource, WebcamSource, createScene, nasaClipUrl } from './sources.js';

const state = {
  deckKey: 'xl',
  deck: DECKS.xl,
  sourceKey: 'scene',
  source: null,
  chain: [],
  motionEnabled: true,
  targetFps: 24,
  zoom: new ZoomStack(),
  // Which key was pressed at each zoom level, so going back can animate into it.
  trail: [],
  running: true,
};

const detector = new MotionDetector();
const deck = new Deck(document.querySelector('.deck'));

const frame = document.createElement('canvas');
const frameCtx = frame.getContext('2d', { willReadFrequently: true });

const minimap = document.querySelector('#minimap');
const minimapCtx = minimap.getContext('2d');

const metrics = {
  frames: 0,
  drawn: 0,
  skipped: 0,
  lastFrames: [],
  stages: { filter: 0, slice: 0, motion: 0 },
};

const el = (selector) => document.querySelector(selector);

// --- source management -----------------------------------------------------

/** Which options pane is on show. Tracked separately from the running source:
    picking "your own video file" opens a file dialogue that may be cancelled. */
function showPane(kind) {
  for (const pane of document.querySelectorAll('.source-extra__pane')) {
    pane.hidden = pane.dataset.for !== kind;
  }
}

function currentClip() {
  const id = el('#nasa-clip').value;
  return NASA_CLIPS.find((clip) => clip.id === id) ?? NASA_CLIPS[0];
}

function setCredit(source) {
  el('#source-credit').textContent = source?.credit ?? '';
}

async function setSource(kind, { silent = false, file = null } = {}) {
  const previous = state.source;
  let next;

  try {
    if (kind === 'webcam') {
      next = await new WebcamSource().start();
    } else if (kind === 'api') {
      next = await new ApiSource(el('#api-url').value.trim() || window.location.origin).start();
    } else if (kind === 'nasa') {
      const clip = currentClip();
      // The clip streams in over range requests, so say so rather than letting
      // the deck sit on the previous frame with no explanation.
      setStatus(`Buffering "${clip.label}" from NASA...`, 'ok');
      next = await new VideoSource(nasaClipUrl(clip.asset), {
        label: clip.label,
        credit: 'Footage: NASA, public domain.',
        start: clip.start,
        end: clip.end,
      }).start();
    } else if (kind === 'file') {
      next = await new VideoSource(URL.createObjectURL(file), {
        label: file.name,
        credit: 'Local file - never uploaded.',
        revoke: true,
      }).start();
    } else {
      next = createScene();
    }
  } catch (error) {
    // Falling back silently would leave the visitor staring at a dead deck.
    const reasons = {
      webcam: 'Camera unavailable - permission denied or no device.',
      api: `Could not reach the API: ${error.message}.`,
      nasa: `Could not stream the clip: ${error.message}.`,
      file: `Could not play that file: ${error.message}.`,
    };
    setStatus(`${reasons[kind] ?? error.message} Staying on ${previous?.label ?? 'the simulated feed'}.`, 'warn');
    el(`#source-${state.sourceKey}`).checked = true;
    showPane(state.sourceKey);
    return;
  }

  previous?.stop?.();
  state.source = next;
  state.sourceKey = kind;
  state.zoom.clear();
  state.trail.length = 0;
  detector.reset();
  showPane(kind);
  setCredit(next);
  // The radio always reflects what is actually running - a file can arrive
  // without its radio having been the thing that asked for it.
  el(`#source-${kind}`).checked = true;
  if (!silent) setStatus(`Source: ${next.label}`, 'ok');
  updateBreadcrumb();
}

// --- deck and zoom ---------------------------------------------------------

function setDeck(key) {
  state.deckKey = key;
  state.deck = DECKS[key];
  state.zoom.clear();
  state.trail.length = 0;
  detector.reset();
  deck.setLayout(state.deck);
  el('#deck-caption').textContent =
    `${state.deck.name} - ${state.deck.cols} x ${state.deck.rows} keys at ${state.deck.keyPx}px`;
  updateBreadcrumb();
}

async function pressKey({ index, row, col }) {
  const { width, height } = sourceSize();
  if (!width) return;

  // Check before animating, so a rejected press does not show a zoom that
  // then snaps back.
  const probe = new ZoomStack();
  probe.stack = [...state.zoom.stack];
  if (!probe.push(width, height, state.deck, row, col)) {
    setStatus('Zoom limit reached - the viewport is already at one source pixel per key pixel.', 'warn');
    return;
  }

  await deck.zoomInto(index);
  state.zoom.push(width, height, state.deck, row, col);
  state.trail.push(index);
  detector.reset();
  updateBreadcrumb();
}

async function zoomBack() {
  if (!state.zoom.depth) return;
  const index = state.trail.pop() ?? 0;
  state.zoom.pop();
  detector.reset();
  updateBreadcrumb();
  await deck.zoomOutTo(index);
}

function zoomHome() {
  if (!state.zoom.depth) return;
  state.zoom.clear();
  state.trail.length = 0;
  detector.reset();
  updateBreadcrumb();
}

function updateBreadcrumb() {
  const { width, height } = sourceSize();
  const depth = state.zoom.depth;
  const magnification = width ? state.zoom.magnification(width) : 1;

  // Past 1:1 the keys are interpolating, not resolving new detail. Saying so is
  // more honest than a magnification figure that implies detail is still there.
  const interpolated = width ? state.zoom.isInterpolated(width, height, state.deck) : false;

  el('#zoom-depth').textContent = depth ? `Depth ${depth}` : 'Full frame';
  el('#zoom-mag').textContent = `${magnification.toFixed(1)}x`;
  el('#zoom-mag').classList.toggle('badge--soft', interpolated);
  el('#zoom-mag').title = interpolated
    ? 'Interpolated: each key now shows fewer source pixels than it has pixels.'
    : 'Native: each key still has at least one source pixel per key pixel.';
  el('#zoom-quality').textContent = depth ? (interpolated ? 'interpolated' : 'native detail') : '';
  el('#btn-back').disabled = depth === 0;
  el('#btn-home').disabled = depth === 0;
}

// --- render loop -----------------------------------------------------------

function sourceSize() {
  const source = state.source;
  if (!source) return { width: 0, height: 0 };
  const drawable = source.read?.() ?? source.canvas;
  if (!drawable) return { width: 0, height: 0 };
  return {
    width: drawable.videoWidth || drawable.naturalWidth || drawable.width || 0,
    height: drawable.videoHeight || drawable.naturalHeight || drawable.height || 0,
    drawable,
  };
}

function renderFrame() {
  const { width, height, drawable } = sourceSize();
  if (!width || !height) return;

  if (frame.width !== width || frame.height !== height) {
    frame.width = width;
    frame.height = height;
    detector.reset();
  }

  frameCtx.globalCompositeOperation = 'source-over';
  frameCtx.filter = 'none';
  frameCtx.drawImage(drawable, 0, 0, width, height);

  let mark = performance.now();
  applyChain(frameCtx, state.chain);
  metrics.stages.filter = performance.now() - mark;

  if (state.zoom.clampTo(width, height)) {
    state.trail.length = 0;
    updateBreadcrumb();
  }

  mark = performance.now();
  const grid = cells(width, height, state.deck, state.zoom.current);
  metrics.stages.slice = performance.now() - mark;

  mark = performance.now();
  let drawn = 0;
  let skipped = 0;

  for (const cell of grid) {
    const { left, top } = cell.box;
    const w = cell.box.width;
    const h = cell.box.height;

    if (state.motionEnabled) {
      const result = detector.update(cell.key, frame, left, top, w, h);
      if (!result.dirty) {
        skipped++;
        continue;
      }
    }
    deck.draw(cell.key, frame, left, top, w, h);
    drawn++;
  }
  metrics.stages.motion = performance.now() - mark;

  metrics.drawn += drawn;
  metrics.skipped += skipped;
  metrics.frames++;
  drawMinimap(width, height, grid);
}

function drawMinimap(width, height, grid) {
  const scale = Math.min(minimap.width / width, minimap.height / height);
  const w = width * scale;
  const h = height * scale;
  const ox = (minimap.width - w) / 2;
  const oy = (minimap.height - h) / 2;

  minimapCtx.fillStyle = '#07090f';
  minimapCtx.fillRect(0, 0, minimap.width, minimap.height);
  minimapCtx.drawImage(frame, ox, oy, w, h);

  // The viewport rectangle: without it, deep zoom loses all sense of place.
  const box = state.zoom.current ?? { left: 0, top: 0, right: width, bottom: height };
  minimapCtx.strokeStyle = '#5ce1c8';
  minimapCtx.lineWidth = 1.5;
  minimapCtx.strokeRect(
    ox + box.left * scale,
    oy + box.top * scale,
    (box.right - box.left) * scale,
    (box.bottom - box.top) * scale,
  );

  // The deck's own footprint inside that viewport, so the cover-fit crop is visible.
  if (grid.length) {
    const first = grid[0].box;
    const last = grid[grid.length - 1].box;
    minimapCtx.strokeStyle = 'rgba(255,255,255,0.28)';
    minimapCtx.lineWidth = 1;
    minimapCtx.strokeRect(
      ox + first.left * scale,
      oy + first.top * scale,
      (last.right - first.left) * scale,
      (last.bottom - first.top) * scale,
    );
  }
}

function updateHud(now) {
  metrics.lastFrames = metrics.lastFrames.filter((t) => now - t < 1000);
  const total = metrics.drawn + metrics.skipped;
  const ratio = total ? metrics.skipped / total : 0;

  el('#hud-fps').textContent = metrics.lastFrames.length.toString();
  el('#hud-keys').textContent = `${state.deck.cols * state.deck.rows}`;
  el('#hud-drawn').textContent = metrics.drawn.toLocaleString();
  el('#hud-skipped').textContent = `${(ratio * 100).toFixed(0)}%`;
  el('#hud-filter').textContent = `${metrics.stages.filter.toFixed(1)} ms`;
  el('#hud-slice').textContent = `${(metrics.stages.slice + metrics.stages.motion).toFixed(1)} ms`;
}

let lastRender = 0;
let lastHud = 0;

function loop(now) {
  requestAnimationFrame(loop);
  if (!state.running) return;

  const interval = 1000 / state.targetFps;
  if (now - lastRender < interval) return;
  lastRender = now;

  renderFrame();
  metrics.lastFrames.push(now);
  if (now - lastHud > 250) {
    lastHud = now;
    updateHud(now);
  }
}

// --- controls --------------------------------------------------------------

function setStatus(message, tone = 'ok') {
  const node = el('#status');
  node.textContent = message;
  node.dataset.tone = tone;
  clearTimeout(setStatus.timer);
  setStatus.timer = setTimeout(() => {
    node.textContent = '';
    node.dataset.tone = '';
  }, 6000);
}

function buildFilterControls() {
  const host = el('#filters');
  for (const entry of CATALOGUE) {
    const item = document.createElement('div');
    item.className = 'filter';

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'filter__toggle';
    toggle.textContent = entry.label;
    toggle.title = entry.doc;

    item.append(toggle);

    let slider = null;
    if (entry.default !== undefined) {
      slider = document.createElement('input');
      slider.type = 'range';
      slider.className = 'filter__slider';
      slider.min = entry.min;
      slider.max = entry.max;
      slider.step = entry.step ?? 1;
      slider.value = entry.default;
      slider.disabled = true;
      slider.addEventListener('input', () => {
        const step = state.chain.find((s) => s.name === entry.name);
        if (step) step.arg = Number(slider.value);
      });
      item.append(slider);
    } else {
      // Filters with no argument still get the slider's slot, so every toggle
      // in the grid sits on the same baseline.
      const spacer = document.createElement('span');
      spacer.className = 'filter__spacer';
      spacer.setAttribute('aria-hidden', 'true');
      item.append(spacer);
    }

    toggle.addEventListener('click', () => {
      const at = state.chain.findIndex((s) => s.name === entry.name);
      if (at >= 0) {
        state.chain.splice(at, 1);
        toggle.classList.remove('is-on');
        if (slider) slider.disabled = true;
      } else {
        // Appended, not inserted: the chain is ordered and order changes the result.
        state.chain.push({ name: entry.name, arg: slider ? Number(slider.value) : undefined });
        toggle.classList.add('is-on');
        if (slider) slider.disabled = false;
      }
      detector.reset();
      renderChainLabel();
    });

    host.append(item);
  }
}

function renderChainLabel() {
  const label = el('#chain');
  label.textContent = state.chain.length
    ? state.chain.map((s) => (s.arg !== undefined ? `${s.name}:${s.arg}` : s.name)).join(' -> ')
    : 'none';
}

function bindControls() {
  for (const key of Object.keys(DECKS)) {
    const input = el(`#deck-${key}`);
    if (input) input.addEventListener('change', () => setDeck(key));
  }
  for (const kind of ['scene', 'nasa', 'webcam', 'api']) {
    el(`#source-${kind}`).addEventListener('change', () => setSource(kind));
  }

  // A file source cannot start until there is a file, so selecting it only
  // opens the picker; the deck keeps running whatever it was running until one
  // arrives, and a cancelled dialogue changes nothing.
  el('#source-file').addEventListener('change', () => {
    showPane('file');
    setStatus('Choose a video file to slice.', 'ok');
    // Nothing is running from a file yet, and the dialogue may be cancelled, so
    // hand the radio back to the source that is actually playing.
    el(`#source-${state.sourceKey}`).checked = true;
    el('#file-input').click();
  });
  el('#file-input').addEventListener('change', (event) => {
    const [file] = event.target.files ?? [];
    if (file) setSource('file', { file });
  });

  el('#nasa-clip').addEventListener('change', () => {
    el('#nasa-note').textContent = currentClip().note;
    if (state.sourceKey === 'nasa') setSource('nasa');
  });

  el('#btn-back').addEventListener('click', zoomBack);
  el('#btn-home').addEventListener('click', zoomHome);

  el('#motion').addEventListener('change', (event) => {
    state.motionEnabled = event.target.checked;
    detector.reset();
  });

  el('#fps').addEventListener('input', (event) => {
    state.targetFps = Number(event.target.value);
    el('#fps-value').textContent = `${state.targetFps} fps`;
  });

  el('#btn-clear-filters').addEventListener('click', () => {
    state.chain.length = 0;
    document.querySelectorAll('.filter__toggle.is-on').forEach((node) => node.classList.remove('is-on'));
    document.querySelectorAll('.filter__slider').forEach((node) => { node.disabled = true; });
    detector.reset();
    renderChainLabel();
  });

  // Right-click anywhere on the deck steps back one level.
  el('.deck').addEventListener('contextmenu', (event) => {
    if (state.zoom.depth) {
      event.preventDefault();
      zoomBack();
    }
  });

  window.addEventListener('keydown', (event) => {
    if (event.target.matches('input, select, textarea')) return;
    if (event.key === 'Escape') zoomHome();
    else if (event.key === 'Backspace' || event.key === 'ArrowLeft') {
      event.preventDefault();
      zoomBack();
    } else if (event.key === ' ') {
      event.preventDefault();
      state.running = !state.running;
      setStatus(state.running ? 'Running' : 'Paused', 'ok');
    }
  });

  // Pause when the tab is hidden: a background tab burning CPU on a portfolio
  // page is a bad look.
  document.addEventListener('visibilitychange', () => {
    state.running = !document.hidden;
  });

  deck.onPress = pressKey;
  deck.onHover = (info) => {
    el('#hover').textContent = info ? `r${info.row + 1} c${info.col + 1} - key ${info.index}` : '';
  };
}

// --- boot ------------------------------------------------------------------

function buildClipOptions() {
  const select = el('#nasa-clip');
  for (const clip of NASA_CLIPS) {
    const option = document.createElement('option');
    option.value = clip.id;
    option.textContent = clip.label;
    select.append(option);
  }
  el('#nasa-note').textContent = currentClip().note;
}

async function main() {
  buildFilterControls();
  buildClipOptions();
  showPane('scene');
  renderChainLabel();
  bindControls();
  setDeck('xl');
  await setSource('scene', { silent: true });
  requestAnimationFrame(loop);
}

main();
