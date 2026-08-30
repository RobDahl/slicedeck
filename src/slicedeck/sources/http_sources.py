"""Frame sources that pull over HTTP: Reolink snapshots, MJPEG, plain stills."""

from __future__ import annotations

import threading
from io import BytesIO

import requests
from PIL import Image, UnidentifiedImageError

from .base import FrameSource, SourceError

_JPEG_SOI = b"\xff\xd8"
_JPEG_EOI = b"\xff\xd9"


def _decode(payload: bytes, what: str) -> Image.Image:
    try:
        return Image.open(BytesIO(payload)).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise SourceError(f"{what} returned {len(payload)} bytes that are not an image") from exc


class SnapshotSource(FrameSource):
    """Re-fetches a still image URL on every frame.

    Covers Reolink's ``cmd=Snap`` endpoint and any other camera or satellite
    feed that exposes a single current-image URL.
    """

    def __init__(self, url: str, label: str = "snapshot", timeout: float = 5.0) -> None:
        if not url:
            raise ValueError("snapshot source needs a URL")
        self._url = url
        self.label = label
        self._timeout = timeout
        self._session = requests.Session()

    def read(self) -> Image.Image:
        try:
            response = self._session.get(self._url, timeout=self._timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            # Never echo the URL: for Reolink it carries the password.
            raise SourceError(f"{self.label} fetch failed: {type(exc).__name__}") from exc
        return _decode(response.content, self.label)

    def close(self) -> None:
        self._session.close()


class MjpegSource(FrameSource):
    """Reads a ``multipart/x-mixed-replace`` MJPEG stream in a background thread.

    The thread keeps only the newest frame, so a slow pipeline drops frames
    instead of falling behind the stream.
    """

    def __init__(self, url: str, label: str = "mjpeg", timeout: float = 10.0) -> None:
        if not url:
            raise ValueError("mjpeg source needs a URL")
        self._url = url
        self.label = label
        self._timeout = timeout
        self._latest: bytes | None = None
        self._error: str | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._pump, name="mjpeg-reader", daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        buffer = bytearray()
        while not self._stop.is_set():
            try:
                with requests.get(self._url, stream=True, timeout=self._timeout) as response:
                    response.raise_for_status()
                    for chunk in response.iter_content(chunk_size=8192):
                        if self._stop.is_set():
                            return
                        buffer.extend(chunk)
                        start = buffer.find(_JPEG_SOI)
                        end = buffer.find(_JPEG_EOI, start + 2)
                        if start != -1 and end != -1:
                            with self._lock:
                                self._latest = bytes(buffer[start : end + 2])
                                self._error = None
                            del buffer[: end + 2]
                        elif len(buffer) > 8 * 1024 * 1024:
                            buffer.clear()  # Not actually MJPEG; do not grow forever.
            except requests.RequestException as exc:
                with self._lock:
                    self._error = f"{type(exc).__name__}"
                self._stop.wait(2.0)

    def read(self) -> Image.Image:
        with self._lock:
            payload, error = self._latest, self._error
        if payload is None:
            raise SourceError(f"{self.label} has no frame yet ({error or 'connecting'})")
        return _decode(payload, self.label)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
