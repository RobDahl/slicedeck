"""Configuration loaded from environment variables.

Credentials are never hardcoded. Copy ``.env.example`` to ``.env`` and fill it
in; ``.env`` is gitignored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

_TRUE = {"1", "true", "yes", "on"}


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so the package has no hard dependency on python-dotenv."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Real environment always wins over the file.
        os.environ.setdefault(key, value)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name) or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = _env(name)
    return default if not value else value.lower() in _TRUE


@dataclass(frozen=True)
class DeckSpec:
    """Physical layout of a Stream Deck model."""

    name: str
    cols: int
    rows: int
    key_px: int

    @property
    def keys(self) -> int:
        return self.cols * self.rows


DECKS: dict[str, DeckSpec] = {
    "mini": DeckSpec("Stream Deck Mini", cols=3, rows=2, key_px=80),
    "mk2": DeckSpec("Stream Deck MK.2", cols=5, rows=3, key_px=72),
    "xl": DeckSpec("Stream Deck XL", cols=8, rows=4, key_px=96),
    "plus": DeckSpec("Stream Deck +", cols=4, rows=2, key_px=120),
}


@dataclass(frozen=True)
class Config:
    source: str = "synthetic"
    reolink_host: str = ""
    reolink_user: str = ""
    reolink_password: str = ""
    reolink_channel: int = 0
    mjpeg_url: str = ""
    image_url: str = ""
    video_file: str = ""

    deck: DeckSpec = field(default_factory=lambda: DECKS["xl"])
    fps: float = 2.0
    filters: tuple[str, ...] = ()
    motion: bool = True
    motion_threshold: float = 12.0
    jpeg_quality: int = 85
    output_dir: Path = Path("streamdeck_slices")

    host: str = "127.0.0.1"
    port: int = 8080
    cors_origins: tuple[str, ...] = ("*",)

    @property
    def interval(self) -> float:
        """Seconds between frames."""
        return 1.0 / self.fps if self.fps > 0 else 0.0

    def reolink_snapshot_url(self) -> str:
        """Build the Reolink snapshot URL from credentials held in the environment."""
        if not self.reolink_host:
            raise ValueError("REOLINK_HOST is not set")
        if not self.reolink_password:
            raise ValueError("REOLINK_PASSWORD is not set (see .env.example)")
        return (
            f"http://{self.reolink_host}/cgi-bin/api.cgi"
            f"?cmd=Snap&channel={self.reolink_channel}&rs=slicedeck"
            f"&user={quote(self.reolink_user)}&password={quote(self.reolink_password)}"
        )

    def redacted(self) -> dict[str, object]:
        """Config safe to log or expose over HTTP."""
        return {
            "source": self.source,
            "deck": self.deck.name,
            "cols": self.deck.cols,
            "rows": self.deck.rows,
            "key_px": self.deck.key_px,
            "fps": self.fps,
            "filters": list(self.filters),
            "motion": self.motion,
            "motion_threshold": self.motion_threshold,
            "jpeg_quality": self.jpeg_quality,
        }


def load_config(env_file: str | os.PathLike[str] | None = ".env") -> Config:
    if env_file is not None:
        _load_dotenv(Path(env_file))

    deck_key = _env("SLICEDECK_DECK", "xl").lower()
    deck = DECKS.get(deck_key, DECKS["xl"])
    cols = _env_int("SLICEDECK_GRID_COLS", deck.cols)
    rows = _env_int("SLICEDECK_GRID_ROWS", deck.rows)
    key_px = _env_int("SLICEDECK_KEY_PX", deck.key_px)
    if (cols, rows, key_px) != (deck.cols, deck.rows, deck.key_px):
        deck = DeckSpec(f"{deck.name} (custom {cols}x{rows})", cols, rows, key_px)

    filters = tuple(f.strip() for f in _env("SLICEDECK_FILTERS").split(",") if f.strip())
    origins = tuple(o.strip() for o in _env("SLICEDECK_CORS_ORIGINS", "*").split(",") if o.strip())

    return Config(
        source=_env("SLICEDECK_SOURCE", "synthetic").lower(),
        reolink_host=_env("REOLINK_HOST"),
        reolink_user=_env("REOLINK_USER", "admin"),
        reolink_password=_env("REOLINK_PASSWORD"),
        reolink_channel=_env_int("REOLINK_CHANNEL", 0),
        mjpeg_url=_env("MJPEG_URL"),
        image_url=_env("IMAGE_URL"),
        video_file=_env("VIDEO_FILE"),
        deck=deck,
        fps=_env_float("SLICEDECK_FPS", 2.0),
        filters=filters,
        motion=_env_bool("SLICEDECK_MOTION", True),
        motion_threshold=_env_float("SLICEDECK_MOTION_THRESHOLD", 12.0),
        jpeg_quality=_env_int("SLICEDECK_JPEG_QUALITY", 85),
        output_dir=Path(_env("SLICEDECK_OUTPUT_DIR", "streamdeck_slices")),
        host=_env("SLICEDECK_HOST", "127.0.0.1"),
        port=_env_int("SLICEDECK_PORT", 8080),
        cors_origins=origins,
    )
