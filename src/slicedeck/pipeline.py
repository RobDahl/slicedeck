"""The frame pipeline: fetch, filter, slice, detect motion, write changed tiles.

One pass looks like::

    source.read()  ->  filters  ->  grid.slice()  ->  motion  ->  sinks

Only tiles the motion detector marks dirty are encoded and written. On a static
scene that turns ``cols * rows`` JPEG encodes per frame into roughly zero, which
is the difference between the pipeline being usable at 10 fps and not.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from PIL import Image

from . import filters as filter_registry
from .config import Config, DeckSpec
from .metrics import Metrics
from .motion import KeyState, MotionDetector
from .outputs.base import TileSink
from .slicer import Box, Grid
from .sources.base import FrameSource, SourceError

log = logging.getLogger("slicedeck")


@dataclass
class FrameResult:
    frame_size: tuple[int, int]
    keys: dict[int, KeyState] = field(default_factory=dict)
    written: int = 0
    skipped: int = 0
    bytes_written: int = 0

    @property
    def moving_keys(self) -> list[int]:
        return [key for key, state in self.keys.items() if state.moving]


class Pipeline:
    """Runs frames end to end and holds the zoom state.

    Zoom is a stack of source rectangles. Pressing a key pushes that key's
    rectangle, so the whole deck then shows what one key was showing; popping
    returns to the previous view. Because the rectangle is in *source* pixels,
    drilling in genuinely increases detail rather than upscaling a tile.
    """

    def __init__(
        self,
        config: Config,
        source: FrameSource,
        sinks: Sequence[TileSink],
        filters: Sequence[str] | None = None,
    ) -> None:
        self.config = config
        self.source = source
        self.sinks = list(sinks)
        self.filters = list(filters if filters is not None else config.filters)
        self.grid = Grid(config.deck)
        self.motion = MotionDetector(threshold=config.motion_threshold)
        self.metrics = Metrics()
        self._zoom_stack: list[Box] = []
        self._last_frame: Image.Image | None = None
        self._last_frame_size: tuple[int, int] | None = None

    # --- zoom ------------------------------------------------------------

    @property
    def zoom(self) -> Box | None:
        return self._zoom_stack[-1] if self._zoom_stack else None

    @property
    def zoom_depth(self) -> int:
        return len(self._zoom_stack)

    @property
    def interpolated(self) -> bool:
        """Whether the current viewport magnifies past one source pixel per key pixel."""
        if self._last_frame_size is None:
            return False
        return self.grid.is_interpolated(self._last_frame_size, self.zoom)

    def press(self, row: int, col: int) -> Box:
        """Drill into one key. Returns the new viewport."""
        if self._last_frame_size is None:
            raise RuntimeError("no frame has been processed yet")
        box = self.grid.zoom_into(self._last_frame_size, row, col, self.zoom)
        # Look one step ahead: pressing is only useful if the resulting viewport
        # can still be divided into cells that carry pixels.
        if not self.grid.can_divide(box):
            log.debug("zoom limit reached at depth %d", self.zoom_depth)
            return self.zoom or box
        self._zoom_stack.append(box)
        self.motion.reset()  # Every key is showing something new.
        return box

    def back(self) -> Box | None:
        if self._zoom_stack:
            self._zoom_stack.pop()
            self.motion.reset()
        return self.zoom

    def reset_zoom(self) -> None:
        if self._zoom_stack:
            self._zoom_stack.clear()
            self.motion.reset()

    def set_filters(self, filters: Sequence[str]) -> None:
        self.filters = list(filters)
        self.motion.reset()  # Filtered output differs everywhere; force a redraw.

    def set_deck(self, deck: DeckSpec) -> None:
        self.config = replace(self.config, deck=deck)
        self.grid = Grid(deck)
        self.motion.reset()

    # --- frames ----------------------------------------------------------

    def process_frame(self) -> FrameResult:
        metrics = self.metrics
        with metrics.time("fetch"):
            frame = self.source.read()
        if frame.mode != "RGB":
            frame = frame.convert("RGB")

        if self.filters:
            with metrics.time("filter"):
                frame = filter_registry.apply_chain(frame, self.filters)

        self._last_frame = frame
        self._last_frame_size = frame.size
        result = FrameResult(frame_size=frame.size)

        # A zoom rectangle from a previous, differently-sized frame would crop
        # out of bounds; drop it rather than crash.
        zoom = self.zoom
        if zoom and (zoom.right > frame.width or zoom.bottom > frame.height):
            log.warning("frame size changed to %s; clearing zoom", frame.size)
            self.reset_zoom()
            zoom = None

        for sink in self.sinks:
            sink.frame_start(self.config.deck.cols, self.config.deck.rows)

        with metrics.time("slice"):
            tiles = list(self.grid.slice(frame, zoom))

        for cell, tile in tiles:
            key = self.grid.index_of(cell.row, cell.col)
            with metrics.time("motion"):
                state = self.motion.update(key, tile) if self.config.motion else KeyState(dirty=True)
            result.keys[key] = state

            if not state.dirty:
                result.skipped += 1
                continue

            with metrics.time("encode"):
                for sink in self.sinks:
                    result.bytes_written += sink.write(cell, tile, key)
            result.written += 1

        for sink in self.sinks:
            sink.frame_end()

        metrics.tiles_written += result.written
        metrics.tiles_skipped += result.skipped
        metrics.bytes_written += result.bytes_written
        metrics.frame_done()
        return result

    def process_frame_safe(self) -> FrameResult | None:
        """As :meth:`process_frame`, but logs source failures instead of raising."""
        try:
            return self.process_frame()
        except SourceError as exc:
            self.metrics.errors += 1
            log.warning("source error: %s", exc)
        except (OSError, ValueError) as exc:
            self.metrics.errors += 1
            log.warning("frame dropped: %s: %s", type(exc).__name__, exc)
        return None

    def render_preview(self, max_width: int = 640) -> Image.Image:
        """The current viewport as a single image, for the web UI's full view.

        Reuses the frame the last pass already fetched and filtered, so opening
        the preview does not cost an extra camera round-trip.
        """
        frame = self._last_frame if self._last_frame is not None else self.source.read().convert("RGB")
        zoom = self.zoom
        if zoom:
            frame = frame.crop(zoom.as_tuple())
        if frame.width > max_width:
            height = round(frame.height * max_width / frame.width)
            frame = frame.resize((max_width, height), Image.Resampling.LANCZOS)
        return frame

    def close(self) -> None:
        self.source.close()
        for sink in self.sinks:
            sink.close()
