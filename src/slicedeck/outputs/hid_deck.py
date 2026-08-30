"""Writes tiles straight to Stream Deck hardware over USB HID.

This is the path that removes the file-and-local-web-server workaround: instead
of dropping JPEGs in a folder for a Stream Deck plugin to poll, the images are
pushed to the device directly, which is both faster and free of disk churn.

Needs the optional dependency: ``pip install 'slicedeck[hid]'``
"""

from __future__ import annotations

from PIL import Image

from ..config import DeckSpec
from ..slicer import Cell
from .base import TileSink


class HidDeckSink(TileSink):
    def __init__(self, serial: str | None = None, brightness: int = 80) -> None:
        try:
            from StreamDeck.DeviceManager import DeviceManager  # noqa: PLC0415
            from StreamDeck.ImageHelpers import PILHelper  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - hardware-only path
            raise RuntimeError(
                "HID output needs the streamdeck package: pip install 'slicedeck[hid]'"
            ) from exc

        self._helper = PILHelper
        devices = DeviceManager().enumerate()
        if not devices:
            raise RuntimeError("no Stream Deck found on USB")
        self._deck = next(
            (d for d in devices if serial and d.get_serial_number() == serial), devices[0]
        )
        self._deck.open()
        self._deck.reset()
        self._deck.set_brightness(brightness)

    @property
    def spec(self) -> DeckSpec:
        """Geometry reported by the attached hardware."""
        rows, cols = self._deck.key_layout()
        width, _height = self._deck.key_image_format()["size"]
        return DeckSpec(self._deck.deck_type(), cols=cols, rows=rows, key_px=width)

    def write(self, cell: Cell, tile: Image.Image, key: int) -> int:
        native = self._helper.to_native_key_format(self._deck, tile)
        with self._deck:
            self._deck.set_key_image(key, native)
        return 0  # The device consumes the image; nothing is written to disk.

    def close(self) -> None:
        try:
            with self._deck:
                self._deck.reset()
        finally:
            self._deck.close()
