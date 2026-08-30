"""Grid math for splitting one frame across the keys of a Stream Deck.

The naive approach - divide width by columns and height by rows - stretches the
image, because a deck's key is square but ``frame_width / cols`` rarely matches
``frame_height / rows``. Everything here works on a *source rectangle* chosen so
each cell is square in source pixels, which keeps the mosaic undistorted.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from PIL import Image

from .config import DeckSpec

Fit = Literal["cover", "contain", "stretch"]

#: A viewport may not shrink below this many source pixels per cell. Past 1:1 a
#: key interpolates rather than resolving new detail, which is still useful
#: digital zoom; below a handful of pixels there is no information left at all.
MIN_CELL_PX = 8


@dataclass(frozen=True)
class Box:
    """Pixel rectangle, left/top inclusive and right/bottom exclusive."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)


@dataclass(frozen=True)
class Cell:
    row: int
    col: int
    box: Box


def source_rect(
    frame_size: tuple[int, int],
    deck: DeckSpec,
    fit: Fit = "cover",
    zoom: Box | None = None,
) -> Box:
    """Pick the region of the frame that maps onto the whole deck.

    ``cover``   - crop the frame to the deck's aspect ratio (fills every key,
                  loses the edges of the frame).
    ``contain`` - use the whole frame; the caller letterboxes when rendering.
    ``stretch`` - use the whole frame and accept the distortion.

    ``zoom`` restricts the operation to a sub-rectangle first, which is what
    drilling into a single key does.
    """
    frame_w, frame_h = frame_size
    if frame_w <= 0 or frame_h <= 0:
        raise ValueError(f"invalid frame size {frame_size!r}")

    left, top, right, bottom = (
        zoom.as_tuple() if zoom else (0, 0, frame_w, frame_h)
    )
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise ValueError("zoom rectangle is empty")

    if fit in ("stretch", "contain"):
        return Box(left, top, right, bottom)

    target = deck.cols / deck.rows
    current = width / height
    if current > target:
        # Too wide: trim the sides.
        new_w = round(height * target)
        inset = (width - new_w) // 2
        return Box(left + inset, top, left + inset + new_w, bottom)
    # Too tall: trim top and bottom.
    new_h = round(width / target)
    inset = (height - new_h) // 2
    return Box(left, top + inset, right, top + inset + new_h)


class Grid:
    """Maps deck keys onto rectangles of a frame."""

    def __init__(self, deck: DeckSpec, fit: Fit = "cover") -> None:
        self.deck = deck
        self.fit = fit

    def index_of(self, row: int, col: int) -> int:
        return row * self.deck.cols + col

    def cells(
        self, frame_size: tuple[int, int], zoom: Box | None = None
    ) -> list[Cell]:
        """Cell rectangles in reading order (row 0 left to right, then row 1)."""
        rect = source_rect(frame_size, self.deck, self.fit, zoom)
        cells: list[Cell] = []
        for row in range(self.deck.rows):
            # Distribute rounding error across cells instead of dropping pixels
            # off the right and bottom edges.
            top = rect.top + round(row * rect.height / self.deck.rows)
            bottom = rect.top + round((row + 1) * rect.height / self.deck.rows)
            for col in range(self.deck.cols):
                left = rect.left + round(col * rect.width / self.deck.cols)
                right = rect.left + round((col + 1) * rect.width / self.deck.cols)
                cells.append(Cell(row, col, Box(left, top, right, bottom)))
        return cells

    def slice(
        self, frame: Image.Image, zoom: Box | None = None
    ) -> Iterator[tuple[Cell, Image.Image]]:
        """Yield each key's cropped and key-sized tile."""
        size = (self.deck.key_px, self.deck.key_px)
        for cell in self.cells(frame.size, zoom):
            tile = frame.crop(cell.box.as_tuple())
            if tile.size != size:
                tile = tile.resize(size, Image.Resampling.LANCZOS)
            yield cell, tile

    def zoom_into(
        self, frame_size: tuple[int, int], row: int, col: int, zoom: Box | None = None
    ) -> Box:
        """The source rectangle for one key - the new viewport after a key press."""
        for cell in self.cells(frame_size, zoom):
            if cell.row == row and cell.col == col:
                return cell.box
        raise IndexError(f"no key at row={row} col={col} on a {self.deck.name}")

    def can_divide(self, box: Box) -> bool:
        """Whether a viewport still holds enough pixels to be split again."""
        cells = self.cells((box.width, box.height))
        return min(cells[0].box.width, cells[0].box.height) >= MIN_CELL_PX

    def is_interpolated(self, frame_size: tuple[int, int], zoom: Box | None = None) -> bool:
        """True once each key is showing fewer source pixels than it has key pixels."""
        return self.cells(frame_size, zoom)[0].box.width < self.deck.key_px
