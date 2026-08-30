"""Motion detection, dirty-tile skipping, zoom state, and the end-to-end pass."""

from __future__ import annotations

from dataclasses import replace

import pytest
from PIL import Image, ImageDraw

from slicedeck.config import DECKS, Config
from slicedeck.motion import MotionDetector
from slicedeck.outputs.base import TileSink
from slicedeck.pipeline import Pipeline
from slicedeck.slicer import Cell
from slicedeck.sources.base import FrameSource, SourceError


class ScriptedSource(FrameSource):
    """Replays a fixed list of frames, then repeats the last one."""

    label = "scripted"

    def __init__(self, frames: list[Image.Image]) -> None:
        self._frames = frames
        self.reads = 0

    def read(self) -> Image.Image:
        frame = self._frames[min(self.reads, len(self._frames) - 1)]
        self.reads += 1
        return frame


class BrokenSource(FrameSource):
    label = "broken"

    def read(self) -> Image.Image:
        raise SourceError("camera unplugged")


class RecordingSink(TileSink):
    def __init__(self) -> None:
        self.writes: list[int] = []
        self.frames = 0

    def frame_start(self, cols: int, rows: int) -> None:
        self.frames += 1

    def write(self, cell: Cell, tile: Image.Image, key: int) -> int:
        self.writes.append(key)
        return 100


def make_frame(colour: str = "navy", spot: tuple[int, int] | None = None) -> Image.Image:
    img = Image.new("RGB", (640, 360), colour)
    if spot:
        draw = ImageDraw.Draw(img)
        x, y = spot
        draw.rectangle([x - 30, y - 30, x + 30, y + 30], fill="white")
    return img


def make_config(**overrides) -> Config:
    base = Config(source="synthetic", deck=DECKS["mk2"], fps=10, motion=True)
    return replace(base, **overrides) if overrides else base


# --- motion detector -------------------------------------------------------


def test_first_sighting_of_a_key_is_always_dirty():
    detector = MotionDetector()
    state = detector.update(0, Image.new("RGB", (72, 72), "black"))
    assert state.dirty and state.moving


def test_an_unchanged_tile_is_neither_dirty_nor_moving():
    detector = MotionDetector()
    tile = Image.new("RGB", (72, 72), "black")
    detector.update(0, tile)
    state = detector.update(0, tile)
    assert not state.dirty
    assert not state.moving
    assert state.score == 0.0


def test_a_changed_tile_scores_above_the_threshold():
    detector = MotionDetector(threshold=12.0)
    detector.update(0, Image.new("RGB", (72, 72), "black"))
    state = detector.update(0, Image.new("RGB", (72, 72), "white"))
    assert state.moving
    assert state.score == pytest.approx(255.0, abs=1.0)
    assert state.area == pytest.approx(1.0)


def test_a_small_mover_is_caught_by_area_even_though_the_mean_barely_moves():
    # A dot crossing a large tile shifts the mean by well under the threshold;
    # only the changed-area signal sees it.
    detector = MotionDetector(threshold=12.0)

    def tile_with_dot(x: int) -> Image.Image:
        img = Image.new("RGB", (240, 240), "black")
        ImageDraw.Draw(img).rectangle([x, 100, x + 24, 124], fill="white")
        return img

    detector.update(0, tile_with_dot(10))
    state = detector.update(0, tile_with_dot(80))

    assert state.score < 12.0, "mean difference alone would miss this"
    assert state.area >= detector.motion_area
    assert state.moving and state.dirty


def test_a_uniform_brightness_shift_is_caught_by_the_mean():
    detector = MotionDetector(threshold=12.0)
    detector.update(0, Image.new("RGB", (72, 72), (100, 100, 100)))
    state = detector.update(0, Image.new("RGB", (72, 72), (140, 140, 140)))
    assert state.score >= 12.0
    assert state.moving


def test_keys_are_tracked_independently():
    detector = MotionDetector()
    black = Image.new("RGB", (72, 72), "black")
    detector.update(0, black)
    detector.update(1, black)
    assert not detector.update(0, black).dirty
    assert detector.update(1, Image.new("RGB", (72, 72), "white")).moving


def test_reset_forces_every_key_dirty_again():
    detector = MotionDetector()
    tile = Image.new("RGB", (72, 72), "black")
    detector.update(0, tile)
    detector.reset()
    assert detector.update(0, tile).dirty


# --- dirty-tile skipping ---------------------------------------------------


def test_a_static_scene_writes_every_tile_once_then_stops():
    frame = make_frame()
    sink = RecordingSink()
    pipeline = Pipeline(make_config(), ScriptedSource([frame]), [sink])

    first = pipeline.process_frame()
    assert first.written == DECKS["mk2"].keys
    assert first.skipped == 0

    second = pipeline.process_frame()
    assert second.written == 0
    assert second.skipped == DECKS["mk2"].keys
    assert pipeline.metrics.skip_ratio == 0.5


def test_only_the_keys_covering_the_change_are_rewritten():
    sink = RecordingSink()
    frames = [make_frame(), make_frame(spot=(100, 100))]
    pipeline = Pipeline(make_config(), ScriptedSource(frames), [sink])

    pipeline.process_frame()
    sink.writes.clear()
    result = pipeline.process_frame()

    assert 0 < result.written < DECKS["mk2"].keys
    assert result.moving_keys
    assert set(sink.writes) == set(result.moving_keys) | {
        k for k, s in result.keys.items() if s.dirty
    }


def test_disabling_motion_writes_every_tile_every_frame():
    sink = RecordingSink()
    pipeline = Pipeline(make_config(motion=False), ScriptedSource([make_frame()]), [sink])
    for _ in range(3):
        result = pipeline.process_frame()
        assert result.written == DECKS["mk2"].keys
        assert result.skipped == 0


# --- zoom ------------------------------------------------------------------


def test_pressing_a_key_pushes_a_smaller_viewport():
    pipeline = Pipeline(make_config(), ScriptedSource([make_frame()]), [])
    pipeline.process_frame()

    assert pipeline.zoom is None
    box = pipeline.press(1, 2)
    assert pipeline.zoom_depth == 1
    assert box.width < 640


def test_back_pops_one_level_and_reset_clears_all():
    # A 4K frame leaves room for two zoom levels before the upscale guard.
    frame = Image.new("RGB", (3840, 2160), "navy")
    pipeline = Pipeline(make_config(), ScriptedSource([frame]), [])
    pipeline.process_frame()
    pipeline.press(0, 0)
    pipeline.process_frame()
    pipeline.press(0, 0)
    assert pipeline.zoom_depth == 2

    pipeline.back()
    assert pipeline.zoom_depth == 1
    pipeline.reset_zoom()
    assert pipeline.zoom_depth == 0
    assert pipeline.zoom is None


def test_back_at_the_top_level_is_harmless():
    pipeline = Pipeline(make_config(), ScriptedSource([make_frame()]), [])
    pipeline.process_frame()
    assert pipeline.back() is None
    assert pipeline.zoom_depth == 0


def test_zoom_stops_once_a_viewport_holds_too_little_to_divide():
    pipeline = Pipeline(make_config(), ScriptedSource([make_frame()]), [])
    pipeline.process_frame()
    for _ in range(12):
        pipeline.press(0, 0)
        pipeline.process_frame()

    # The stack settles rather than running away: the guard looks one step
    # ahead, so what is blocked is the child of the settled viewport.
    assert pipeline.zoom is not None
    settled = pipeline.zoom_depth
    pipeline.press(0, 0)
    assert pipeline.zoom_depth == settled

    child = pipeline.grid.zoom_into((640, 360), 0, 0, pipeline.zoom)
    assert not pipeline.grid.can_divide(child)


def test_zoom_goes_more_than_one_level_deep_on_an_hd_frame():
    # The interaction is the point of the project; one level would be a
    # degenerate version of it.
    pipeline = Pipeline(make_config(), ScriptedSource([Image.new("RGB", (1280, 720), "navy")]), [])
    pipeline.process_frame()
    pipeline.press(1, 2)
    pipeline.process_frame()
    pipeline.press(1, 2)
    assert pipeline.zoom_depth >= 2


def test_interpolation_is_reported_once_keys_outrun_the_source():
    pipeline = Pipeline(make_config(), ScriptedSource([Image.new("RGB", (1280, 720), "navy")]), [])
    pipeline.process_frame()
    assert not pipeline.interpolated  # full frame: 240px cells on a 72px key

    pipeline.press(0, 0)
    pipeline.process_frame()
    pipeline.press(0, 0)
    pipeline.process_frame()
    assert pipeline.interpolated


def test_pressing_before_the_first_frame_is_rejected():
    pipeline = Pipeline(make_config(), ScriptedSource([make_frame()]), [])
    with pytest.raises(RuntimeError):
        pipeline.press(0, 0)


def test_zoom_is_dropped_when_the_frame_size_changes():
    frames = [make_frame(), Image.new("RGB", (320, 180), "navy")]
    pipeline = Pipeline(make_config(), ScriptedSource(frames), [])
    pipeline.process_frame()
    pipeline.press(2, 4)  # bottom-right key, out of bounds on a smaller frame
    assert pipeline.zoom_depth == 1

    pipeline.process_frame()
    assert pipeline.zoom_depth == 0


# --- filters and failures --------------------------------------------------


def test_changing_filters_forces_a_full_redraw():
    sink = RecordingSink()
    pipeline = Pipeline(make_config(), ScriptedSource([make_frame()]), [sink])
    pipeline.process_frame()
    assert pipeline.process_frame().written == 0

    pipeline.set_filters(["thermal"])
    assert pipeline.process_frame().written == DECKS["mk2"].keys


def test_a_source_failure_is_counted_not_raised():
    pipeline = Pipeline(make_config(), BrokenSource(), [])
    assert pipeline.process_frame_safe() is None
    assert pipeline.metrics.errors == 1
    assert pipeline.metrics.frames == 0


def test_metrics_record_each_stage():
    pipeline = Pipeline(make_config(), ScriptedSource([make_frame()]), [RecordingSink()])
    pipeline.process_frame()
    snapshot = pipeline.metrics.snapshot()
    assert snapshot["frames"] == 1
    assert {"fetch", "slice", "encode", "motion"} <= set(snapshot["stages_ms"])
    assert snapshot["bytes_written"] > 0
