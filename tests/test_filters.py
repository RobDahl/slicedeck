"""Filter registry, argument parsing, and per-filter behaviour."""

from __future__ import annotations

import pytest
from PIL import Image

from slicedeck import filters


@pytest.fixture
def frame() -> Image.Image:
    # A horizontal gradient with a bright block, so edges and thresholds have
    # something unambiguous to act on.
    img = Image.new("RGB", (64, 64))
    pixels = img.load()
    for y in range(64):
        for x in range(64):
            pixels[x, y] = (x * 4, y * 4, 128)
    for y in range(20, 40):
        for x in range(20, 40):
            pixels[x, y] = (255, 255, 255)
    return img


def test_registry_is_populated_and_documented():
    catalogue = filters.available()
    names = {entry["name"] for entry in catalogue}
    assert {"grayscale", "thermal", "edges", "pixelate", "posterize"} <= names
    assert all(entry["doc"] for entry in catalogue)


@pytest.mark.parametrize("name", [entry["name"] for entry in filters.available()])
def test_every_filter_preserves_size_and_mode(frame, name):
    out = filters.apply_chain(frame, [name])
    assert out.size == frame.size
    assert out.mode == "RGB"


def test_parse_splits_name_and_argument():
    assert filters.parse("posterize:3") == ("posterize", 3.0)
    assert filters.parse("grayscale") == ("grayscale", None)
    assert filters.parse(" Thermal ") == ("thermal", None)


def test_parse_rejects_a_non_numeric_argument():
    with pytest.raises(ValueError):
        filters.parse("posterize:high")


def test_unknown_filter_raises_rather_than_silently_passing_through(frame):
    with pytest.raises(KeyError):
        filters.apply_chain(frame, ["nope"])


def test_chain_is_ordered(frame):
    # Blurring a hard threshold gives soft grey edges; thresholding a blur
    # gives a hard edge in a different place. Order matters.
    a = filters.apply_chain(frame, ["threshold:128", "blur:3"])
    b = filters.apply_chain(frame, ["blur:3", "threshold:128"])
    assert a.tobytes() != b.tobytes()


def test_empty_chain_is_a_no_op(frame):
    assert filters.apply_chain(frame, []).tobytes() == frame.tobytes()


def test_grayscale_equalises_channels(frame):
    out = filters.apply_chain(frame, ["grayscale"])
    r, g, b = out.getpixel((10, 10))
    assert r == g == b


def colour_count(img) -> int:
    """Distinct colours, via a histogram rather than the deprecated getdata()."""
    colours = img.convert("RGB").getcolors(maxcolors=1 << 24)
    assert colours is not None, "image has more colours than the histogram cap"
    return len(colours)


def test_threshold_produces_only_black_and_white(frame):
    out = filters.apply_chain(frame, ["threshold:128"])
    levels = {colour for _count, colour in out.convert("L").getcolors(256)}
    assert levels <= {0, 255}


def test_pixelate_collapses_detail_into_blocks(frame):
    out = filters.apply_chain(frame, ["pixelate:8"])
    # Neighbouring pixels inside one block must now be identical.
    assert out.getpixel((0, 0)) == out.getpixel((1, 0))
    assert colour_count(out) < colour_count(frame)


def test_posterize_reduces_the_palette(frame):
    out = filters.apply_chain(frame, ["posterize:2"])
    assert colour_count(out) < colour_count(frame)


def test_thermal_maps_luminance_to_colour(frame):
    out = filters.apply_chain(frame, ["thermal"])
    # The white block should land at the hot end of the ramp.
    assert out.getpixel((30, 30)) == (255, 255, 220)
    # And the dark corner at the cold end.
    r, g, b = out.getpixel((0, 0))
    assert b > r and b > g
