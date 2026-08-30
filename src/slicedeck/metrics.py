"""Timing and throughput counters for the pipeline.

Kept deliberately small: a rolling window per stage, so the CLI and the web
demo can both show where the frame budget actually goes.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class Stage:
    name: str
    samples: deque[float] = field(default_factory=lambda: deque(maxlen=60))

    def add(self, seconds: float) -> None:
        self.samples.append(seconds * 1000)

    @property
    def ms(self) -> float:
        return sum(self.samples) / len(self.samples) if self.samples else 0.0

    @property
    def peak_ms(self) -> float:
        return max(self.samples) if self.samples else 0.0


@dataclass
class Metrics:
    frames: int = 0
    errors: int = 0
    tiles_written: int = 0
    tiles_skipped: int = 0
    bytes_written: int = 0
    started: float = field(default_factory=time.perf_counter)
    _stages: dict[str, Stage] = field(default_factory=dict, repr=False)
    _frame_times: deque[float] = field(default_factory=lambda: deque(maxlen=30), repr=False)

    @contextmanager
    def time(self, stage: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self._stages.setdefault(stage, Stage(stage)).add(time.perf_counter() - start)

    def frame_done(self) -> None:
        self.frames += 1
        self._frame_times.append(time.perf_counter())

    @property
    def fps(self) -> float:
        if len(self._frame_times) < 2:
            return 0.0
        span = self._frame_times[-1] - self._frame_times[0]
        return (len(self._frame_times) - 1) / span if span > 0 else 0.0

    @property
    def skip_ratio(self) -> float:
        """Share of tiles the dirty check saved from being re-encoded."""
        total = self.tiles_written + self.tiles_skipped
        return self.tiles_skipped / total if total else 0.0

    def snapshot(self) -> dict[str, object]:
        return {
            "frames": self.frames,
            "errors": self.errors,
            "fps": round(self.fps, 2),
            "uptime_s": round(time.perf_counter() - self.started, 1),
            "tiles_written": self.tiles_written,
            "tiles_skipped": self.tiles_skipped,
            "skip_ratio": round(self.skip_ratio, 4),
            "bytes_written": self.bytes_written,
            "stages_ms": {
                name: {"avg": round(stage.ms, 2), "peak": round(stage.peak_ms, 2)}
                for name, stage in sorted(self._stages.items())
            },
        }

    def summary_line(self) -> str:
        stages = " ".join(f"{n}={s.ms:.0f}ms" for n, s in sorted(self._stages.items()))
        return (
            f"frame {self.frames} | {self.fps:.1f} fps | "
            f"wrote {self.tiles_written} skipped {self.tiles_skipped} "
            f"({self.skip_ratio:.0%} saved) | {stages}"
        )
