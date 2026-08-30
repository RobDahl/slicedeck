"""Frame source interface.

A source is anything that can hand back the next RGB frame: an IP camera, an
MJPEG stream, a periodically-refreshed satellite still, a local video file, or
a synthetic scene for demos and tests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image


class FrameSource(ABC):
    """Produces frames on demand."""

    #: Human-readable label shown in the UI and logs.
    label: str = "source"

    @abstractmethod
    def read(self) -> Image.Image:
        """Return the next frame as RGB. Raise :class:`SourceError` on failure."""

    def close(self) -> None:
        """Release sockets, file handles, decoders."""

    def __enter__(self) -> FrameSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class SourceError(RuntimeError):
    """A frame could not be produced. The pipeline logs and retries."""
