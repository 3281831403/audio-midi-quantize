"""Core MIDI quantization contract for the audio-midi-quantize exercise.

Coordinates are integer MIDI ticks.  A note is a mapping with three keys:
``tick`` (note-on position, int >= 0), ``dur`` (duration in ticks, int > 0)
and ``vel`` (MIDI velocity, int 1..127).  Public functions return new objects
and never mutate their inputs.

Swing always lives in the closed interval [0, 1].  Grid arithmetic rounds to
whole ticks, so callers may compare two positions with a tolerance of one
tick (``abs(a - b) <= 1``); values that divide evenly are expected to match
exactly.
"""

from __future__ import annotations

import bisect
import math
from typing import Mapping, Sequence


class QuantizeError(ValueError):
    """Raised when a quantization request is structurally invalid."""


def _clamp_unit(value: float) -> float:
    """Clamp ``value`` into the closed interval [0, 1]."""
    return min(1.0, max(0.0, float(value)))


def _check_grid_config(ppq: int, division: int) -> None:
    """Reject non-positive or misaligned grid configurations."""
    if ppq <= 0:
        raise QuantizeError(f"ppq must be positive, got {ppq}")
    if division <= 0:
        raise QuantizeError(f"division must be positive, got {division}")
    if ppq % division != 0:
        raise QuantizeError(f"division {division} does not divide ppq {ppq}")


def _swing_offsets(length: int, spacing: int, swing: float) -> list[int]:
    """Per-point delays: 1-based even positions, endpoint anchored."""
    delay = round(_clamp_unit(swing) * spacing / 2)
    offsets = [0] * length
    for index in range(length):
        position = index + 1  # 1-based
        if position % 2 == 0 and index != length - 1:
            offsets[index] = delay
    return offsets


def grid_ticks(ppq: int, division: int, swing: float) -> list[int]:
    """Build one quarter-note grid in integer ticks.

    The grid contains ``division + 1`` points from 0 through ``ppq`` inclusive,
    so the final downbeat is never lost.  Straight spacing is
    ``ppq // division`` ticks.  ``ppq`` and ``division`` must be positive and
    ``division`` must evenly divide ``ppq``; otherwise ``QuantizeError`` is
    raised.

    ``swing`` is clamped to [0, 1].  Every 1-based even grid position (the
    2nd, 4th, ... point), except the final endpoint, is moved later by
    ``round(swing * spacing / 2)`` ticks.  Consequently swing never moves a
    point by more than half a cell, swing=0 leaves the grid evenly spaced,
    and the last tick remains anchored at ``ppq``.
    """
    _check_grid_config(ppq, division)
    spacing = ppq // division
    base = [index * spacing for index in range(division + 1)]
    offsets = _swing_offsets(len(base), spacing, swing)
    return [point + offset for point, offset in zip(base, offsets)]


def snap(tick: int, grid: Sequence[int], strength: float) -> int:
    """Blend ``tick`` toward the nearest point of a sorted ``grid``.

    ``strength`` is clamped to [0, 1].  The returned tick is
    ``round(tick + (nearest - tick) * strength)``.  Thus strength=0 leaves the
    note exactly where it was, while strength=1 lands exactly on the nearest
    grid point.  Ties go to the lower grid point.  An empty grid or a
    non-increasing grid raises ``QuantizeError``.  The result is an integer
    tick within the one-tick rounding tolerance described in the module
    docstring.
    """
    if len(grid) == 0:
        raise QuantizeError("grid must contain at least one point")
    for left, right in zip(grid, grid[1:]):
        if right <= left:
            raise QuantizeError("grid points must be strictly increasing")

    strength = _clamp_unit(strength)
    index = bisect.bisect_left(grid, tick)
    if index == 0:
        nearest = grid[0]
    elif index == len(grid):
        nearest = grid[-1]
    else:
        lower, upper = grid[index - 1], grid[index]
        # Ties go to the lower grid point.
        nearest = lower if tick - lower <= upper - tick else upper
    return round(tick + (nearest - tick) * strength)


def quantize_notes(
    notes: Sequence[Mapping[str, int]], grid: Sequence[int], strength: float
) -> list[dict[str, int]]:
    """Snap every note's ``tick`` and return a new tick-sorted list.

    Each note is a mapping with ``tick``, ``dur`` and ``vel``.  Only ``tick``
    changes; ``dur`` and ``vel`` are copied unchanged.  The result is sorted
    ascending by tick and the sort is stable, so notes sharing a tick keep
    their input order.  The input list and its note dicts are not mutated.
    An empty input returns an empty list.
    """
    quantized = [
        {"tick": snap(note["tick"], grid, strength),
         "dur": note["dur"],
         "vel": note["vel"]}
        for note in notes
    ]
    quantized.sort(key=lambda note: note["tick"])  # sort() is stable
    return quantized


def fix_overlaps(
    notes: Sequence[Mapping[str, int]], min_gap: int
) -> list[dict[str, int]]:
    """Trim sustained notes so they stop before the next distinct note-on.

    Notes sharing a tick form a chord and are preserved; simultaneous notes
    are not treated as overlapping each other.  For every note, the next
    strictly larger tick bounds its end:
    ``tick + dur <= next_tick - min_gap``.  A duration is shortened when
    needed but never below ``min_gap``; if the next distinct tick is too close
    to satisfy both constraints, ``QuantizeError`` is raised.  The final tick
    group keeps its duration (raised to ``min_gap`` if it is shorter).
    ``min_gap`` must be non-negative.

    Returns a new list sorted by tick, stable within each chord.  The input is
    not mutated.
    """
    if min_gap < 0:
        raise QuantizeError(f"min_gap must be non-negative, got {min_gap}")

    ordered = sorted(
        (dict(note) for note in notes), key=lambda note: note["tick"]
    )
    distinct_ticks = sorted({note["tick"] for note in ordered})

    for note in ordered:
        tick = note["tick"]
        index = bisect.bisect_right(distinct_ticks, tick)
        if index < len(distinct_ticks):
            next_tick = distinct_ticks[index]
            max_dur = next_tick - tick - min_gap
            if max_dur < min_gap:
                raise QuantizeError(
                    f"note at tick {tick} cannot satisfy min_gap {min_gap} "
                    f"before next note-on at {next_tick}"
                )
            note["dur"] = max(min_gap, min(note["dur"], max_dur))
        else:
            note["dur"] = max(min_gap, note["dur"])
    return ordered


def quantize_velocity(
    notes: Sequence[Mapping[str, int]], steps: int, curve: float
) -> list[dict[str, int]]:
    """Quantize velocities onto ``steps`` layers on a geometric curve.

    ``steps`` must be an integer >= 2 and ``curve`` a finite number > 0.
    Layer ``k`` (0-based) has velocity
    ``round(1 + 126 * (k / (steps - 1)) ** curve)``.  Each note's velocity is
    replaced by the nearest layer, with ties choosing the lower layer; tick
    and duration are preserved.  Returns a new list in input order without
    sorting.  An empty input returns an empty list.
    """
    if not isinstance(steps, int) or steps < 2:
        raise QuantizeError(f"steps must be an integer >= 2, got {steps}")
    if not math.isfinite(curve) or curve <= 0:
        raise QuantizeError(f"curve must be a finite number > 0, got {curve}")

    layers = [
        round(1 + 126 * (k / (steps - 1)) ** curve) for k in range(steps)
    ]

    quantized = []
    for note in notes:
        vel = note["vel"]
        index = bisect.bisect_left(layers, vel)
        if index == 0:
            nearest = layers[0]
        elif index == len(layers):
            nearest = layers[-1]
        else:
            lower, upper = layers[index - 1], layers[index]
            # Ties choose the lower layer.
            nearest = lower if vel - lower <= upper - vel else upper
        quantized.append(
            {"tick": note["tick"], "dur": note["dur"], "vel": nearest}
        )
    return quantized


def groove_offset(grid: Sequence[int], swing: float) -> list[int]:
    """Return per-point swing offsets for a straight grid.

    ``grid`` must be sorted, evenly spaced and contain at least two points.
    ``swing`` is clamped to [0, 1].  The result has the same length as the
    grid.  Every 1-based even position (the 2nd, 4th, ... point) receives
    ``round(swing * spacing / 2)`` ticks of delay, except the final endpoint,
    which stays anchored.  Every offset is therefore between 0 and half a
    grid cell.  The input grid is not modified.
    """
    if len(grid) < 2:
        raise QuantizeError("grid must contain at least two points")
    spacing = grid[1] - grid[0]
    if spacing <= 0:
        raise QuantizeError("grid points must be strictly increasing")
    for left, right in zip(grid, grid[1:]):
        if right - left != spacing:
            raise QuantizeError("grid must be evenly spaced")
    return _swing_offsets(len(grid), spacing, swing)


def validate(
    notes: Sequence[Mapping[str, int]], ppq: int, division: int
) -> list[str]:
    """Return a list of problems for ``notes`` and the grid configuration.

    Problem strings are appended in this order: for each note in input order,
    ``note {i}: negative tick`` when ``tick < 0`` and
    ``note {i}: non-positive duration`` when ``dur <= 0``; finally
    ``division {division} does not divide ppq {ppq}`` when the division is not
    an exact divisor.  An empty list means the request is valid.

    ``ppq <= 0`` or ``division <= 0`` raises ``QuantizeError`` before any
    division is attempted, so callers can never divide by zero.  Invalid note
    values are reported, not raised.  Inputs are not mutated.
    """
    if ppq <= 0:
        raise QuantizeError(f"ppq must be positive, got {ppq}")
    if division <= 0:
        raise QuantizeError(f"division must be positive, got {division}")

    problems: list[str] = []
    for i, note in enumerate(notes):
        if note["tick"] < 0:
            problems.append(f"note {i}: negative tick")
        if note["dur"] <= 0:
            problems.append(f"note {i}: non-positive duration")
    if ppq % division != 0:
        problems.append(f"division {division} does not divide ppq {ppq}")
    return problems


def quantize_batch(
    tracks: Mapping[str, Mapping[str, object]], config: Mapping[str, object]
) -> dict[str, list[dict[str, int]]]:
    """Quantize several independent tracks, all-or-nothing.

    ``tracks`` is an ordered mapping from track name to
    ``{"ppq": int, "division": int, "notes": [...]}``.  Every track builds its
    own grid from its own ``ppq`` and ``division``; there is no shared grid
    between tracks.  ``config`` supplies ``strength``, ``swing`` and
    ``min_gap`` for all tracks.

    Every track is validated before any result is produced.  If any track is
    invalid, ``QuantizeError`` is raised and no partial result is returned;
    inputs are never mutated, so the batch is effectively rolled back.
    Otherwise the returned ordered dict follows the input track order, and
    each track's notes are quantized, tick-sorted and overlap-fixed.
    """
    strength = config["strength"]
    swing = config["swing"]
    min_gap = config["min_gap"]

    # Validate every track up front: all-or-nothing, no partial results.
    for name, track in tracks.items():
        problems = validate(track["notes"], track["ppq"], track["division"])
        if problems:
            raise QuantizeError(
                f"track {name!r} is invalid: {'; '.join(problems)}"
            )

    result: dict[str, list[dict[str, int]]] = {}
    for name, track in tracks.items():
        grid = grid_ticks(track["ppq"], track["division"], swing)
        quantized = quantize_notes(track["notes"], grid, strength)
        result[name] = fix_overlaps(quantized, min_gap)
    return result
