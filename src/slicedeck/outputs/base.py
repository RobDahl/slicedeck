"""Tile sink interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image

from ..slicer import Cell


class TileSink(ABC):
    """Receives one rendered tile per key, per frame."""

    @abstractmethod
    def write(self, cell: Cell, tile: Image.Image, key: int) -> int:
        """Persist one tile. Returns bytes written (0 if the sink does not encode)."""

    def frame_start(self, cols: int, rows: int) -> None:
        """Called before the tiles of a frame."""

    def frame_end(self) -> None:
        """Called after the tiles of a frame; flush or present here."""

    def close(self) -> None:
        """Release resources."""

    def __enter__(self) -> TileSink:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
