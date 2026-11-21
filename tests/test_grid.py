"""Fifteen red tests for the MIDI quantization exercise.

The initial ``quantize/grid.py`` contains stubs only, so every test must fail
with ``NotImplementedError``.  Notes always use the public shape
``{"tick": int, "dur": int, "vel": int}``.
"""

import pytest

from quantize.grid import (
    QuantizeError,
    fix_overlaps,
    grid_ticks,
    groove_offset,
    quantize_batch,
    quantize_notes,
    quantize_velocity,
    snap,
    validate,
)


def test_swing_shifts_even_positions_later():
    """Swing must delay 1-based even grid positions, not odd ones."""
    straight = grid_ticks(480, 4, 0.0)
    swung = grid_ticks(480, 4, 1.0)

    assert straight == [0, 120, 240, 360, 480]
    assert swung == [0, 180, 240, 420, 480]
    assert groove_offset(straight, 1.0) == [0, 60, 0, 60, 0]


def test_snap_honours_strength():
    """snap must blend toward the nearest point instead of always jumping."""
    assert snap(30, [0, 120], 0.5) == 15
    assert snap(30, [0, 120], 0.0) == 30


def test_quantize_notes_sorts_timeline():
    """The quantized result must be sorted by tick and keep all note fields."""
    notes = [
        {"tick": 350, "dur": 20, "vel": 100},
        {"tick": 40, "dur": 20, "vel": 90},
        {"tick": 120, "dur": 20, "vel": 80},
    ]

    quantized = quantize_notes(notes, [0, 120, 240, 360], 1.0)

    assert [note["tick"] for note in quantized] == [0, 120, 360]
    assert [note["vel"] for note in quantized] == [90, 80, 100]
    assert [note["tick"] for note in notes] == [350, 40, 120]


def test_fix_overlaps_trims_notes_and_keeps_chord():
    """Overlaps must be trimmed while simultaneous chord notes are preserved."""
    notes = [
        {"tick": 0, "dur": 400, "vel": 100},
        {"tick": 0, "dur": 80, "vel": 90},
        {"tick": 240, "dur": 120, "vel": 80},
    ]

    fixed = fix_overlaps(notes, 20)

    assert len(fixed) == 3
    assert [note["tick"] for note in fixed] == [0, 0, 240]
    assert [note["dur"] for note in fixed] == [220, 80, 120]
    assert notes[0]["dur"] == 400


def test_quantize_velocity_uses_geometric_layers():
    """Velocity layers must follow the geometric curve, not a linear ramp."""
    notes = [
        {"tick": 0, "dur": 10, "vel": 30},
        {"tick": 120, "dur": 10, "vel": 100},
    ]

    quantized = quantize_velocity(notes, 4, 2.0)

    assert [note["vel"] for note in quantized] == [15, 127]
    assert [note["vel"] for note in notes] == [30, 100]


def test_grid_ticks_includes_final_tick():
    """The grid must include ppq as its final point, not stop one cell early."""
    grid = grid_ticks(480, 4, 0.0)

    assert len(grid) == 5
    assert grid[0] == 0
    assert grid[-1] == 480
    assert grid == [0, 120, 240, 360, 480]


def test_validate_reports_non_divisible_division():
    """An inexact division must be reported instead of silently misaligned."""
    problems = validate([{"tick": 0, "dur": 120, "vel": 100}], 480, 7)

    assert problems == ["division 7 does not divide ppq 480"]


def test_swing_is_clamped_to_unit_range():
    """Swing values outside [0, 1] must be clamped before shifting points."""
    straight = grid_ticks(480, 4, 0.0)

    assert grid_ticks(480, 4, 2.5) == grid_ticks(480, 4, 1.0)
    assert grid_ticks(480, 4, -2.0) == straight
    assert groove_offset(straight, 9.0) == [0, 60, 0, 60, 0]


def test_quantize_batch_builds_grid_per_track():
    """Each track must use its own ppq/division grid, and failure rolls back."""
    tracks = {
        "lead": {
            "ppq": 480,
            "division": 4,
            "notes": [{"tick": 110, "dur": 20, "vel": 100}],
        },
        "bass": {
            "ppq": 960,
            "division": 2,
            "notes": [{"tick": 110, "dur": 20, "vel": 90}],
        },
    }
    config = {"strength": 1.0, "swing": 0.0, "min_gap": 1}

    result = quantize_batch(tracks, config)

    assert result["lead"][0]["tick"] == 120
    assert result["bass"][0]["tick"] == 0

    bad_tracks = {
        "lead": {
            "ppq": 480,
            "division": 4,
            "notes": [{"tick": 110, "dur": 20, "vel": 100}],
        },
        "bass": {
            "ppq": 960,
            "division": 2,
            "notes": [{"tick": -1, "dur": 20, "vel": 90}],
        },
    }
    with pytest.raises(QuantizeError):
        quantize_batch(bad_tracks, config)
    assert bad_tracks["lead"]["notes"][0]["tick"] == 110


def test_non_positive_ppq_raises_quantize_error():
    """Non-positive ppq must be rejected before any tick division happens."""
    for ppq in (0, -480):
        with pytest.raises(QuantizeError):
            grid_ticks(ppq, 4, 0.0)


def test_strength_one_snaps_to_nearest_grid_point():
    """Full strength must land exactly on the nearest grid point."""
    grid = [0, 120, 240]
    assert snap(130, grid, 1.0) == 120

    quantized = quantize_notes(
        [{"tick": 130, "dur": 30, "vel": 64}], grid, 1.0
    )
    assert quantized[0]["tick"] == 120
    assert quantized[0]["tick"] - 120 == 0


def test_swing_zero_grid_is_evenly_spaced():
    """swing=0 must produce an evenly spaced grid and zero groove offsets."""
    grid = grid_ticks(480, 8, 0.0)

    assert grid == [0, 60, 120, 180, 240, 300, 360, 420, 480]
    assert all(right - left == 60 for left, right in zip(grid, grid[1:]))
    assert groove_offset(grid, 0.0) == [0] * 9


def test_validate_ppq_zero_raises_quantize_error():
    """validate must reject ppq=0 rather than attempt a division by zero."""
    with pytest.raises(QuantizeError):
        validate([], 0, 4)


def test_empty_notes_return_empty():
    """All note list helpers must accept an empty input and return []."""
    assert quantize_notes([], [0, 120], 1.0) == []
    assert fix_overlaps([], 20) == []
    assert quantize_velocity([], 5, 2.0) == []


def test_quantize_batch_preserves_track_order():
    """A successful batch must keep the input track order and note order."""
    tracks = {
        "drums": {
            "ppq": 480,
            "division": 4,
            "notes": [
                {"tick": 0, "dur": 60, "vel": 100},
                {"tick": 120, "dur": 60, "vel": 90},
            ],
        },
        "bass": {
            "ppq": 480,
            "division": 2,
            "notes": [{"tick": 0, "dur": 120, "vel": 80}],
        },
        "keys": {
            "ppq": 960,
            "division": 4,
            "notes": [{"tick": 480, "dur": 120, "vel": 70}],
        },
    }

    result = quantize_batch(
        tracks, {"strength": 1.0, "swing": 0.0, "min_gap": 10}
    )

    assert list(result) == ["drums", "bass", "keys"]
    assert [note["tick"] for note in result["drums"]] == [0, 120]
    assert [note["vel"] for note in result["drums"]] == [100, 90]
