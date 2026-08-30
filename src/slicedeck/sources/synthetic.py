"""A generated orbital scene, so the project runs with no camera and no network.

This is what the test suite and the offline demo use. It renders a rotating
planet, a starfield, and a satellite that tracks across the frame - the moving
satellite gives the motion detector something real to fire on.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

from .base import FrameSource


def _value_noise(height: int, width: int, cells: int, seed: int) -> np.ndarray:
    """Smooth pseudo-random field in [0, 1], used as a continent mask."""
    rng = np.random.default_rng(seed)
    coarse = rng.random((cells, cells))
    ys = np.linspace(0, cells - 1, height)
    xs = np.linspace(0, cells - 1, width)
    y0 = np.floor(ys).astype(int).clip(0, cells - 2)
    x0 = np.floor(xs).astype(int).clip(0, cells - 2)
    ty = (ys - y0)[:, None]
    tx = (xs - x0)[None, :]
    # Smoothstep keeps the blobs from looking like a bilinear grid.
    ty = ty * ty * (3 - 2 * ty)
    tx = tx * tx * (3 - 2 * tx)
    c00 = coarse[np.ix_(y0, x0)]
    c01 = coarse[np.ix_(y0, x0 + 1)]
    c10 = coarse[np.ix_(y0 + 1, x0)]
    c11 = coarse[np.ix_(y0 + 1, x0 + 1)]
    top = c00 * (1 - tx) + c01 * tx
    bottom = c10 * (1 - tx) + c11 * tx
    return top * (1 - ty) + bottom * ty


class SyntheticSource(FrameSource):
    label = "synthetic"

    def __init__(self, width: int = 1280, height: int = 720, seed: int = 7) -> None:
        self.width, self.height = width, height
        self._frame = 0
        self._seed = seed
        self._stars = self._make_stars(seed)
        # One wide noise band, scrolled horizontally to fake rotation.
        self._surface = _value_noise(height, width * 2, cells=10, seed=seed)

    def _make_stars(self, seed: int) -> np.ndarray:
        rng = np.random.default_rng(seed + 1)
        field = np.zeros((self.height, self.width), dtype=np.float32)
        count = (self.width * self.height) // 900
        ys = rng.integers(0, self.height, count)
        xs = rng.integers(0, self.width, count)
        field[ys, xs] = rng.random(count) ** 2
        return field

    def read(self) -> Image.Image:
        self._frame += 1
        t = self._frame

        yy, xx = np.mgrid[0 : self.height, 0 : self.width].astype(np.float32)
        cx, cy = self.width * 0.5, self.height * 0.56
        radius = min(self.width, self.height) * 0.42
        dx = (xx - cx) / radius
        dy = (yy - cy) / radius
        dist = np.sqrt(dx * dx + dy * dy)
        on_planet = dist <= 1.0

        # Sphere normal, used for both the terminator and the limb darkening.
        dz = np.sqrt(np.clip(1.0 - dist * dist, 0.0, 1.0))

        shift = int(t * 2) % self.width
        surface = np.roll(self._surface[:, : self.width], -shift, axis=1)
        land = surface > 0.55

        rgb = np.zeros((self.height, self.width, 3), dtype=np.float32)

        # Space and stars.
        twinkle = 0.6 + 0.4 * math.sin(t * 0.15)
        for channel in range(3):
            rgb[:, :, channel] = self._stars * 255 * twinkle
        rgb[:, :, 2] += 6

        ocean = np.array([12, 48, 110], dtype=np.float32)
        landmass = np.array([46, 96, 52], dtype=np.float32)
        planet = np.where(land[:, :, None], landmass, ocean)

        # Cloud band scrolling at a different rate than the surface.
        clouds = np.roll(self._surface[:, self.width :], -int(t * 3) % self.width, axis=1)
        cloud_alpha = np.clip((clouds - 0.62) * 3.0, 0, 1)[:, :, None]
        planet = planet * (1 - cloud_alpha) + np.array([235, 240, 245]) * cloud_alpha

        # Sunlight sweeping around, so brightness genuinely changes over time.
        sun = np.array([math.cos(t * 0.01), -0.25, math.sin(t * 0.01) * 0.5 + 0.6])
        sun /= np.linalg.norm(sun)
        lambert = np.clip(dx * sun[0] + dy * sun[1] + dz * sun[2], 0.05, 1.0)
        planet *= lambert[:, :, None]

        rgb = np.where(on_planet[:, :, None], planet, rgb)

        # Atmospheric rim just outside the disc.
        rim = np.exp(-((dist - 1.0) ** 2) / 0.004) * (dist > 0.985)
        rgb += rim[:, :, None] * np.array([70, 140, 255], dtype=np.float32)

        frame = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
        self._draw_satellite(frame, t)
        return frame

    def _draw_satellite(self, frame: Image.Image, t: int) -> None:
        from PIL import ImageDraw

        # Slow diagonal drift with a gentle bob; wraps across the frame.
        x = (t * 4) % (self.width + 80) - 40
        y = self.height * 0.22 + math.sin(t * 0.05) * self.height * 0.08
        draw = ImageDraw.Draw(frame)
        draw.line([(x - 14, y), (x + 14, y)], fill=(180, 190, 210), width=3)
        draw.rectangle([x - 5, y - 5, x + 5, y + 5], fill=(240, 240, 250))
        draw.ellipse([x - 22, y - 22, x + 22, y + 22], outline=(90, 110, 150), width=1)
