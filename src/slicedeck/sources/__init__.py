"""Frame sources and the factory that picks one from configuration."""

from __future__ import annotations

from ..config import Config
from .base import FrameSource, SourceError
from .http_sources import MjpegSource, SnapshotSource
from .synthetic import SyntheticSource

__all__ = [
    "FrameSource",
    "SourceError",
    "MjpegSource",
    "SnapshotSource",
    "SyntheticSource",
    "build_source",
]


def build_source(config: Config) -> FrameSource:
    kind = config.source
    if kind == "reolink":
        return SnapshotSource(config.reolink_snapshot_url(), label="reolink")
    if kind == "mjpeg":
        return MjpegSource(config.mjpeg_url)
    if kind == "image_url":
        return SnapshotSource(config.image_url, label="image_url")
    if kind == "video_file":
        from .video_file import VideoFileSource  # Optional OpenCV dependency.

        return VideoFileSource(config.video_file)
    if kind == "synthetic":
        return SyntheticSource()
    raise ValueError(
        f"unknown SLICEDECK_SOURCE {kind!r}; "
        "expected reolink, mjpeg, image_url, video_file or synthetic"
    )
