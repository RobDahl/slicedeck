"""Keeps the latest encoded tile for each key in memory, for the HTTP API.

Avoids the disk round-trip entirely: the API serves these bytes directly, and
each tile carries a version number so clients can skip unchanged keys.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from ..slicer import Cell
from .base import TileSink


@dataclass(frozen=True)
class Tile:
    payload: bytes
    version: int


class MemorySink(TileSink):
    def __init__(self, quality: int = 85) -> None:
        self.quality = quality
        self._tiles: dict[int, Tile] = {}
        self._lock = threading.Lock()
        self._version = 0

    def frame_start(self, cols: int, rows: int) -> None:
        self._version += 1

    def write(self, cell: Cell, tile: Image.Image, key: int) -> int:
        buffer = BytesIO()
        tile.save(buffer, "JPEG", quality=self.quality, optimize=True)
        payload = buffer.getvalue()
        with self._lock:
            self._tiles[key] = Tile(payload, self._version)
        return len(payload)

    def get(self, key: int) -> Tile | None:
        with self._lock:
            return self._tiles.get(key)

    def versions(self) -> dict[int, int]:
        with self._lock:
            return {key: tile.version for key, tile in self._tiles.items()}
