"""Grid maths: coverage, aspect handling, and zoom."""

from __future__ import annotations

import pytest
from PIL import Image

from slicedeck.config import DECKS, DeckSpec
from slicedeck.slicer import Box, Grid, source_rect

XL = DECKS["xl"]
MK2 = DECKS["mk2"]


def test_cell_count_matches_key_count():
    grid = Grid(XL)
    assert len(grid.cells((1920, 1080))) == XL.keys == 32


def test_cells_tile_the_source_rect_with_no_gaps_or_overlap():
    grid = Grid(MK2)
    cells = grid.cells((1920, 1080))
    rect = source_rect((1920, 1080), MK2)

    covered = sum(cell.box.width * cell.box.height for cell in cells)
    assert covered == rect.width * rect.height

    # Neighbours must share an edge exactly - rounding must not leave seams.
    by_position = {(cell.row, cell.col): cell.box for cell in cells}
    for (row, col), box in by_position.items():
        right = by_position.get((row, col + 1))
        if right:
            assert box.right == right.left
        below = by_position.get((row + 1, col))
        if below:
            assert box.bottom == below.top


def test_cover_fit_yields_square_cells_from_a_16_by_9_frame():
    # This is the bug the original script had: 1920/4 x 1080/3 cells are 4:3,
    # squashed into a square key.
    cells = Grid(XL).cells((1920, 1080))
    for cell in cells:
        assert abs(cell.box.width - cell.box.height) <= 1


def test_cover_crops_the_long_axis_and_stays_centred():
    rect = source_rect((1920, 1080), XL)  # deck aspect 8:4 = 2.0, frame 1.777
    assert rect.width == 1920  # too tall for 2:1, so height is trimmed
    assert rect.height == 960
    assert rect.top == (1080 - 960) // 2


def test_stretch_and_contain_use_the_whole_frame():
    for fit in ("stretch", "contain"):
        rect = source_rect((1920, 1080), XL, fit=fit)
        assert rect.as_tuple() == (0, 0, 1920, 1080)


def test_slice_returns_key_sized_tiles():
    frame = Image.new("RGB", (1920, 1080), "navy")
    tiles = list(Grid(XL).slice(frame))
    assert len(tiles) == 32
    for _cell, tile in tiles:
        assert tile.size == (XL.key_px, XL.key_px)


def test_zoom_into_returns_that_keys_rectangle():
    grid = Grid(XL)
    box = grid.zoom_into((1920, 1080), row=1, col=3)
    cell = next(c for c in grid.cells((1920, 1080)) if (c.row, c.col) == (1, 3))
    assert box.as_tuple() == cell.box.as_tuple()


def test_zoom_is_recursive_and_shrinks_the_viewport():
    grid = Grid(XL)
    first = grid.zoom_into((1920, 1080), 0, 0)
    second = grid.zoom_into((1920, 1080), 0, 0, zoom=first)
    assert second.width < first.width
    assert second.left >= first.left and second.right <= first.right


def test_zoomed_cells_stay_inside_the_zoom_rectangle():
    grid = Grid(MK2)
    zoom = Box(400, 300, 1000, 700)
    for cell in grid.cells((1920, 1080), zoom=zoom):
        assert zoom.left <= cell.box.left < cell.box.right <= zoom.right
        assert zoom.top <= cell.box.top < cell.box.bottom <= zoom.bottom


def test_odd_grid_dimensions_still_tile_exactly():
    deck = DeckSpec("odd", cols=7, rows=3, key_px=72)
    cells = Grid(deck).cells((1001, 667))
    rect = source_rect((1001, 667), deck)
    assert sum(c.box.width * c.box.height for c in cells) == rect.width * rect.height


def test_rejects_degenerate_input():
    with pytest.raises(ValueError):
        source_rect((0, 100), XL)
    with pytest.raises(ValueError):
        source_rect((100, 100), XL, zoom=Box(50, 50, 50, 50))


def test_zoom_into_rejects_a_key_that_does_not_exist():
    with pytest.raises(IndexError):
        Grid(MK2).zoom_into((1920, 1080), row=9, col=9)


def test_can_divide_guards_the_information_floor():
    grid = Grid(MK2)
    assert grid.can_divide(Box(0, 0, 1920, 1080))
    # 5 columns of an 18px-wide box give 3px cells, below MIN_CELL_PX.
    assert not grid.can_divide(Box(0, 0, 18, 18))


def test_is_interpolated_flips_once_cells_are_smaller_than_a_key():
    grid = Grid(MK2)
    assert not grid.is_interpolated((1920, 1080))
    assert grid.is_interpolated((1920, 1080), zoom=Box(0, 0, 200, 120))
