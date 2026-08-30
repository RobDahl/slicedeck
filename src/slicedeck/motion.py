"""Per-key motion detection and change tracking.

Two jobs, one cheap frame difference:

* **Motion** - which keys changed enough to be worth flagging in the UI.
* **Dirty tracking** - which keys changed at all. Only those get re-encoded and
  rewritten, which is where most of the pipeline's savings come from: a static
  scene costs one JPEG encode instead of ``cols * rows`` of them.

Scoring uses two signals, because either one alone gets a class of motion wrong:

* **mean difference** catches whole-tile changes (lights switching on, exposure
  shifts) but a small fast object averages away to nothing across a big tile;
* **changed area** - the share of pixels that moved by more than the noise floor
  - catches the small object but ignores a uniform brightness drift.

A key is moving if *either* fires.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageOps

#: Tiles are downsampled to this many pixels per side before comparison, so
#: sensor noise and JPEG artefacts average out and the check stays cheap.
PROBE = 24


@dataclass
class KeyState:
    #: Mean absolute luminance difference from the previous frame, 0-255.
    score: float = 0.0
    #: Share of the tile whose pixels moved past the noise floor, 0-1.
    area: float = 0.0
    moving: bool = False
    dirty: bool = True


@dataclass
class MotionDetector:
    """Tracks each key's previous tile and scores the new one against it."""

    #: Mean difference that counts as motion on its own.
    threshold: float = 12.0
    #: Per-pixel difference below this is treated as noise, not movement.
    pixel_floor: float = 10.0
    #: Changed area that counts as motion on its own.
    motion_area: float = 0.02
    #: Below these, a tile is considered unchanged and is not re-encoded.
    dirty_threshold: float = 1.0
    dirty_area: float = 0.004

    _probes: dict[int, np.ndarray] = field(default_factory=dict, repr=False)

    def reset(self) -> None:
        """Forget every key, so the next frame redraws all of them."""
        self._probes.clear()

    @staticmethod
    def _probe(tile: Image.Image) -> np.ndarray:
        small = ImageOps.grayscale(tile).resize((PROBE, PROBE), Image.Resampling.BILINEAR)
        return np.asarray(small, dtype=np.int16)

    def update(self, key: int, tile: Image.Image) -> KeyState:
        probe = self._probe(tile)
        previous = self._probes.get(key)
        self._probes[key] = probe

        if previous is None:
            # First sighting of this key: nothing to compare against, so draw it.
            return KeyState(score=255.0, area=1.0, moving=True, dirty=True)

        diff = np.abs(probe - previous)
        score = float(diff.mean())
        area = float((diff > self.pixel_floor).mean())

        return KeyState(
            score=score,
            area=area,
            moving=score >= self.threshold or area >= self.motion_area,
            dirty=score >= self.dirty_threshold or area >= self.dirty_area,
        )
