# Slicedeck

Split one live camera frame across the keys of an Elgato Stream Deck, so the
whole device becomes a single low-resolution display. Press any key and the deck
zooms into it.

**[Live demo](https://robdahl.github.io/slicedeck/)** &mdash; runs entirely in the browser, no
camera or hardware needed. Slice a generated orbital scene, real NASA footage
(Earth from the ISS, Perseverance's descent to Mars, the Sun, Jupiter), a video
file off your own disk, or your webcam. **[How it works](#how-it-works)**

<!-- TODO: drop a capture at docs/demo.gif -->

---

## What it does

A Stream Deck is 32 tiny LCDs in a grid. Given a frame from an IP camera, the
pipeline crops it to the deck's aspect ratio, splits it into per-key tiles, and
pushes each tile to its key &mdash; either straight over USB HID, or as JPEGs on
disk for the Stream Deck HTTP plugins to pick up.

Pressing a key pushes that key's rectangle onto a zoom stack, so the whole deck
becomes a magnified view of what one key was showing.

```
source ──> filters ──> slice ──> motion ──> sinks
  │           │           │         │         │
  │           │           │         │         ├── USB HID (real hardware)
  │           │           │         │         ├── JPEG files on disk
  │           │           │         │         └── HTTP + WebSocket API
  │           │           │         └── per-key change scores; clean keys skip re-encoding
  │           │           └── aspect-correct grid, zoom stack
  │           └── ordered, composable, applied whole-frame
  └── Reolink snapshot | MJPEG | still image URL | video file | generated scene
```

## Requirements

Python 3.10 or newer. Nothing else is required to run the pipeline: the default
source generates its own scene, so it works with no camera, no network and no
Stream Deck plugged in.

Optional extras, installed on demand:

| Extra | Install | Needed for |
| --- | --- | --- |
| `server` | `pip install -e ".[server]"` | `--serve`: the HTTP API and the demo page |
| `hid` | `pip install -e ".[hid]"` | `--hid`: pushing tiles to real hardware over USB |
| `video` | `pip install -e ".[video]"` | `--source video_file` |
| `dev` | `pip install -e ".[dev]"` | running the tests and the linter |

## Quick start

1. Clone the repository and install it, with the server extra:

   ```bash
   pip install -e ".[server]"
   ```

2. Start it:

   ```bash
   slicedeck --serve
   ```

   On Windows you can double-click [`start_slicedeck.bat`](start_slicedeck.bat)
   instead; it runs the same command.

3. Open <http://localhost:8080>. You get the virtual deck, the generated scene
   running through it, and live telemetry. Nothing has touched a camera yet.

To change what it does, pass flags or set environment variables &mdash; the
flags win:

```bash
slicedeck --list-filters                       # what filters exist
slicedeck --source synthetic --deck mk2        # a different deck model
slicedeck --filter thermal --filter edges      # ordered filter chain
slicedeck --fps 10                             # target frame rate
slicedeck --no-motion                          # turn off dirty-tile skipping
slicedeck --serve --port 9000                  # serve somewhere else
```

## Using the demo page

The page at `/` (also published as a static site &mdash; it needs no server) is
the pipeline running in the browser.

- **Click any key** to zoom the whole deck into it. <kbd>Esc</kbd> returns to the
  full frame, <kbd>&#8592;</kbd> or right-click steps back one level, and
  <kbd>Space</kbd> pauses.
- **Source** picks what gets sliced: the generated orbital scene, real NASA
  footage streamed from the agency's public asset host, a video file off your own
  disk, your webcam, or a running `--serve` instance (*Live API*).
- **Filters** apply to the whole frame before slicing, in the order you turn them
  on. The chain is printed under the heading; *Clear* resets it.
- **Deck model** switches the grid, and **Pipeline** toggles motion detection and
  the target frame rate. Watch *redraws skipped* in the telemetry panel fall to
  zero when you turn skipping off.

Nothing leaves the browser: the webcam stream and any file you pick are read
straight into a `<video>` element, and the NASA clips are fetched from NASA.

## Run it on a real Stream Deck

1. Put your camera details in `.env`:

   ```bash
   cp .env.example .env      # then fill in REOLINK_HOST / REOLINK_USER / REOLINK_PASSWORD
   ```

2. Check the feed works before involving hardware &mdash; this writes JPEG tiles
   to `streamdeck_slices/` and prints per-frame metrics:

   ```bash
   slicedeck --source reolink --deck xl
   ```

3. Push to the device over USB:

   ```bash
   pip install -e ".[hid]"
   slicedeck --source reolink --deck xl --hid
   ```

   On Linux this needs a udev rule granting access to the device. Write
   `/etc/udev/rules.d/70-streamdeck.rules`:

   ```
   SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
   ```

   then `sudo udevadm control --reload-rules` and replug the deck.

If you would rather drive the deck through a Stream Deck plugin that watches a
folder, skip `--hid` and point the plugin at the output directory:

```bash
slicedeck --source mjpeg --deck mk2 --output ./tiles
```

Writes there are atomic, so a plugin polling the folder can never pick up a
half-written JPEG.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `the API needs FastAPI` | `pip install -e ".[server]"` |
| `HID output needs the streamdeck package` | `pip install -e ".[hid]"` |
| `no Stream Deck found on USB` | The package is installed but the device is not visible &mdash; check the cable, and on Linux the udev rule above |
| Camera source fails immediately | Wrong host or credentials in `.env`. Errors never echo the URL, because it carries the password &mdash; check the values by hand |
| `Address already in use` | Something else holds 8080; use `--port` or `SLICEDECK_PORT` |
| Demo page loads but the deck stays black | A NASA clip is still buffering, or the source failed and the status line under the deck says why |
| Nothing skips redraws | Motion detection is off, or the scene genuinely changes everywhere every frame |

## Configuration

Everything is environment-driven; see [`.env.example`](.env.example) for the
full list. **No credentials live in the source tree** &mdash; `.env` is
gitignored, `Config.redacted()` is what gets logged and served, and source
errors never echo the URL, because a Reolink snapshot URL carries the password
in its query string.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SLICEDECK_SOURCE` | `synthetic` | `reolink`, `mjpeg`, `image_url`, `video_file`, `synthetic` |
| `SLICEDECK_DECK` | `xl` | `mini` (3&times;2), `mk2` (5&times;3), `xl` (8&times;4), `plus` (4&times;2) |
| `SLICEDECK_FPS` | `2.0` | Target frame rate |
| `SLICEDECK_FILTERS` | *(none)* | Ordered chain, e.g. `thermal,edges:2` |
| `SLICEDECK_MOTION` | `true` | Motion detection and dirty-tile skipping |
| `REOLINK_HOST` / `REOLINK_USER` / `REOLINK_PASSWORD` | | Camera credentials |

## How it works

### Aspect-correct slicing

The obvious approach &mdash; `width // cols` by `height // rows` &mdash; is
wrong. A Stream Deck key is square, so cells cut from a 16:9 frame arrive
stretched. The frame is cropped to the deck's aspect ratio *first*, then
divided, and rounding error is distributed across cells so they tile the crop
exactly with no seams. `tests/test_slicer.py` pins both properties.

### Two-signal motion detection

Mean frame difference catches a whole tile changing but a small fast object
averages away to nothing across a 240px cell. Changed-area &mdash; the share of
pixels moving past a noise floor &mdash; catches the small object but ignores
uniform brightness drift. A key is *moving* if either signal fires.

### Dirty-tile skipping

The same difference, at a much lower bar, decides whether a tile is worth
re-encoding at all. On the reference feed that skips **around 88% of JPEG
encodes**; on a genuinely static scene it approaches 100%. This is what keeps
the frame budget flat as the grid grows from 6 keys to 32.

```
frame 30 | 5.7 fps | wrote 52 skipped 398 (88% saved) | encode=2ms fetch=161ms motion=0ms slice=9ms
```

### Zoom is a stack of rectangles

Each press pushes the pressed key's rectangle, in source pixels. How deep it
goes is pure geometry: an XL divides by 8 across, so a 720p frame is spent in
one press, while a Mini (&divide;3) manages three levels. Past 1:1 the viewport
is reported as *interpolated* rather than pretending detail is still there, and
a press that would leave cells with almost no pixels is refused.

### One algorithm, two runtimes

The grid maths and the motion detector exist twice: Python for the hardware
pipeline, JavaScript for the browser demo. They are deliberate ports of each
other so the demo is not a mock-up of the real thing &mdash; it is the same
algorithm. The Python test suite is the shared specification.

## Project layout

```
src/slicedeck/
  config.py          environment-driven config, credential redaction
  slicer.py          grid maths, cover fit, zoom rectangles
  motion.py          two-signal per-key change detection
  metrics.py         per-stage timings, skip ratio, throughput
  pipeline.py        fetch -> filter -> slice -> motion -> sinks
  server.py          FastAPI + WebSocket API
  cli.py             command line entry point
  filters/           composable named filters
  sources/           Reolink, MJPEG, still image, video file, generated
  outputs/           filesystem, in-memory, USB HID
web/                 the static demo (no build step, no dependencies)
tests/               67 tests over the maths, filters, and pipeline
```

## HTTP API

`slicedeck --serve` exposes the pipeline and serves the demo page.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/config` | Deck geometry, filters, source label (never credentials) |
| `GET /api/state` | Per-key change scores, zoom depth, metrics |
| `GET /api/key/{n}.jpg` | One key's current tile, with an `X-Tile-Version` header |
| `GET /api/preview.jpg` | The current viewport as one image |
| `POST /api/press` | `{"row": 1, "col": 3}` &mdash; zoom into a key |
| `POST /api/back` / `POST /api/reset` | Pop one level / return to the full frame |
| `POST /api/filters` | Set the filter chain |
| `WS /ws` | Per-frame changed-key list, so clients fetch only what moved |

## Development

```bash
pip install -e ".[dev,server]"
pytest
ruff check .
```

The demo is plain ES modules with no build step. Serve `web/` with any static
server, or let `--serve` mount it.

Its NASA clips stream from `images-assets.nasa.gov`, which sends
`Access-Control-Allow-Origin` and honours range requests. That header is the
whole constraint on which feeds the demo can offer: every frame is read back out
of the canvas, so anything without it taints the canvas and takes the filters
and the motion detector with it.

Static hosting of `web/` is what
[`.github/workflows/pages.yml`](.github/workflows/pages.yml) publishes on any
push touching that directory. There is no build step to add.

## Licence

MIT.
