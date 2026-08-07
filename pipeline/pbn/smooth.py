"""Boundary smoothing.

Two complaints share one cause. The colourable page "reads as a contour map" because region
boundaries trace colour gradients into nested wavy lines, and regions fail number placement
because those same wavy boundaries make them slivers with no interior room.

Rounder regions fix both at once, and rounder regions are also what let the palette grow: the
binding constraint on adding colours is that finer quantisation produces more slivers.

The method is iterative boundary relaxation — each boundary pixel adopts the majority label of
its 8-neighbourhood. That is discrete curvature flow: it shortens boundaries, so wiggles
straighten and thin necks pinch off, while large-scale shape is preserved. Only boundary pixels
are considered, which is a few percent of the image, so the cost is small.
"""

from __future__ import annotations

import numpy as np
from skimage import segmentation as skseg

# A boundary pixel flips only when this many of its 8 neighbours agree on another label.
# 5 of 8 is a genuine majority; lower values erode regions rather than smoothing them.
DEFAULT_MIN_AGREEMENT = 5
DEFAULT_ITERATIONS = 3


def _neighbour_stack(labels: np.ndarray) -> np.ndarray:
    """(8, H, W) array of the eight neighbouring labels, edge-replicated."""
    padded = np.pad(labels, 1, mode="edge")
    h, w = labels.shape
    offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    return np.stack([padded[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w] for dy, dx in offsets])


def _row_mode(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Most frequent value per row of an (N, 8) integer array, with its count.

    Sorting each row groups equal values together, so the longest run is the mode. Fully
    vectorised, which matters because this runs on every boundary pixel of every iteration.
    """
    ordered = np.sort(values, axis=1)
    # A run starts wherever the value differs from its predecessor.
    starts = np.ones_like(ordered, dtype=bool)
    starts[:, 1:] = ordered[:, 1:] != ordered[:, :-1]

    n_rows, n_cols = ordered.shape
    # Index of the run each element belongs to, then run lengths via the start positions.
    run_index = np.cumsum(starts, axis=1) - 1
    counts = np.zeros_like(ordered)
    flat_rows = np.repeat(np.arange(n_rows), n_cols)
    np.add.at(counts, (flat_rows, run_index.ravel()), 1)

    best_run = np.argmax(counts, axis=1)
    best_count = counts[np.arange(n_rows), best_run]
    # The first element of a run carries its value; find it by counting starts.
    start_positions = np.cumsum(starts, axis=1) - 1
    mode = np.take_along_axis(
        ordered, np.argmax(start_positions == best_run[:, None], axis=1)[:, None], axis=1
    ).ravel()
    return mode, best_count


def smooth_labels(
    labels: np.ndarray,
    iterations: int = DEFAULT_ITERATIONS,
    min_agreement: int = DEFAULT_MIN_AGREEMENT,
) -> np.ndarray:
    """Round off region boundaries without changing which labels exist.

    Labels are never created or destroyed here, only reassigned, so palette associations stay
    valid. A region *can* be split into disconnected pieces, which callers must repair by
    relabelling connected components and re-absorbing fragments.
    """
    result = labels.copy()
    for _ in range(iterations):
        boundary = skseg.find_boundaries(result, mode="inner")
        if not boundary.any():
            break

        stack = _neighbour_stack(result)
        candidates = stack[:, boundary].T  # (n_boundary, 8)
        mode, count = _row_mode(candidates)

        current = result[boundary]
        flip = (count >= min_agreement) & (mode != current)
        if not flip.any():
            break

        updated = current.copy()
        updated[flip] = mode[flip]
        result[boundary] = updated
    return result


def compactness(labels: np.ndarray, n_regions: int) -> np.ndarray:
    """Per-region ``2*area/perimeter``, the same measure the merge stage constrains.

    Useful for verifying that smoothing actually made regions rounder rather than merely
    different.
    """
    flat = labels.ravel()
    area = np.bincount(flat, minlength=n_regions).astype(np.float64)

    perimeter = np.zeros(n_regions, dtype=np.float64)
    for left, right in ((labels[:, :-1], labels[:, 1:]), (labels[:-1, :], labels[1:, :])):
        a = left.ravel()
        b = right.ravel()
        differing = a != b
        np.add.at(perimeter, a[differing], 1.0)
        np.add.at(perimeter, b[differing], 1.0)
    for edge in (labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]):
        np.add.at(perimeter, edge.ravel(), 1.0)

    return 2.0 * area / np.maximum(perimeter, 1.0)
