"""slicedeck - split one live camera frame across the keys of a Stream Deck."""

from __future__ import annotations

from .config import DECKS, Config, DeckSpec, load_config
from .metrics import Metrics
from .motion import MotionDetector
from .pipeline import FrameResult, Pipeline
from .slicer import Box, Cell, Grid

__version__ = "1.0.0"

__all__ = [
    "Config",
    "DeckSpec",
    "DECKS",
    "load_config",
    "Grid",
    "Cell",
    "Box",
    "Pipeline",
    "FrameResult",
    "MotionDetector",
    "Metrics",
    "__version__",
]
