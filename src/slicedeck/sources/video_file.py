"""Looping local video file source.

Uses OpenCV when it is installed; otherwise raises a clear message rather than
failing deep inside a decoder. Handy for reproducible demos - point it at a
public-domain NASA clip and the pipeline behaves exactly as it does on a camera.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from .base import FrameSource, SourceError


class VideoFileSource(FrameSource):
    def __init__(self, path: str | Path, loop: bool = True) -> None:
        try:
            import cv2  # noqa: PLC0415 - optional dependency
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise SourceError(
                "video_file source needs OpenCV: pip install 'slicedeck[video]'"
            ) from exc

        self._cv2 = cv2
        self._path = Path(path)
        if not self._path.is_file():
            raise SourceError(f"video file not found: {self._path}")
        self.label = f"video:{self._path.name}"
        self._loop = loop
        self._capture = cv2.VideoCapture(str(self._path))
        if not self._capture.isOpened():
            raise SourceError(f"could not open video: {self._path}")

    def read(self) -> Image.Image:
        ok, frame = self._capture.read()
        if not ok:
            if not self._loop:
                raise SourceError("end of video")
            self._capture.set(self._cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._capture.read()
            if not ok:
                raise SourceError("could not rewind video")
        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)

    def close(self) -> None:
        self._capture.release()
