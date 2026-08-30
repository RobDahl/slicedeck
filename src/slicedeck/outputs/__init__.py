"""Destinations for rendered key tiles."""

from __future__ import annotations

from .base import TileSink
from .filesystem import FilesystemSink
from .memory import MemorySink

__all__ = ["TileSink", "FilesystemSink", "MemorySink", "HidDeckSink"]


def __getattr__(name: str):  # Defer the optional HID dependency until asked for.
    if name == "HidDeckSink":
        from .hid_deck import HidDeckSink

        return HidDeckSink
    raise AttributeError(name)
