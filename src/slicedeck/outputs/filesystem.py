"""Writes tiles to disk as JPEGs for the Stream Deck HTTP/image plugins.

Writes go to a temporary file and are then atomically renamed into place. The
original version of this project wrote JPEGs in-place while an HTTP server was
serving the same directory, so a client could read a half-written file and show
a torn image.
"""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

from PIL import Image

from ..slicer import Cell
from .base import TileSink


class FilesystemSink(TileSink):
    def __init__(self, directory: str | Path, quality: int = 85) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.quality = quality

    def path_for(self, cell: Cell) -> Path:
        return self.directory / f"slice_{cell.row}_{cell.col}.jpg"

    def write(self, cell: Cell, tile: Image.Image, key: int) -> int:
        buffer = BytesIO()
        tile.save(buffer, "JPEG", quality=self.quality, optimize=True)
        payload = buffer.getvalue()

        target = self.path_for(cell)
        temp = target.with_suffix(".jpg.tmp")
        temp.write_bytes(payload)
        os.replace(temp, target)  # Atomic on both POSIX and Windows.
        return len(payload)
