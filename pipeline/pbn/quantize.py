"""Palette construction and pixel assignment.

The important idea here is **where the colour budget gets spent**. A single k-means over
the whole image allocates clusters by pixel frequency, so a dog occupying 25% of the
frame gets roughly a quarter of the palette and the sofa behind it gets the rest. That is
faithful, and it is exactly why naive photo conversions look muddy — the fidelity goes to
the parts nobody cares about.

Running k-means separately over subject and background pixels lets us deliberately
over-allocate colours to the subject, which is what an illustrator does when reducing a
photo to flat colour.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from pbn import color

# Fewer than this and photos stop being recognisable; more and the palette tray becomes
# unwieldy on a phone. Curated illustration works at 8-12 because an artist designed
# within that budget; photographs need more, especially for skin tones.
MIN_COLOURS = 8
MAX_COLOURS = 220

# Palette entries closer than this in CIE76 are visually near-identical. Two numbers the
# user cannot tell apart is worse than one, so they get folded together.
#
# Lowered from 6.0, which was silently capping large palettes: asking for 48 colours returned
# only 33-48 depending on the image, so the requested tier was not what the user actually got.
# At 3.0 we keep 43-48 of 48. ~3.0 is still comfortably above the just-noticeable difference
# for swatches shown side by side, which is how the palette tray presents them.
DEDUPE_DELTA_E = 3.0

# Subject colour allocation: its share of the palette is its share of the frame plus this
# boost, clamped. A subject covering 5% of the frame still earns 40% of the colours.
SUBJECT_SHARE_BOOST = 0.30
MIN_SUBJECT_SHARE = 0.40
MAX_SUBJECT_SHARE = 0.85

_KMEANS_CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
_KMEANS_ATTEMPTS = 3


@dataclass
class Quantized:
    """Result of quantisation."""

    labels: np.ndarray  # (H, W) int32, index into the palette
    palette_lab: np.ndarray  # (N, 3) float32 CIELAB, ordered light -> dark
    palette_rgb: np.ndarray  # (N, 3) uint8, same order
    from_subject: np.ndarray  # (N,) bool, which entries came from the subject k-means
    requested_colours: int  # what was asked for, before deduplication

    @property
    def subject_colours(self) -> int:
        return int(self.from_subject.sum())

    @property
    def n_colours(self) -> int:
        return int(self.palette_lab.shape[0])


def subject_colour_split(total: int, coverage: float | None) -> tuple[int, int]:
    """Split ``total`` colours between subject and background.

    Returns ``(subject_colours, background_colours)``. With no subject, everything goes
    to a single whole-frame cluster.
    """
    if coverage is None:
        return total, 0
    share = float(np.clip(coverage + SUBJECT_SHARE_BOOST, MIN_SUBJECT_SHARE, MAX_SUBJECT_SHARE))
    subject = int(round(total * share))
    # Both sides need at least 2 clusters to be worth splitting at all.
    subject = max(2, min(total - 2, subject))
    return subject, total - subject


def _kmeans_lab(lab_pixels: np.ndarray, k: int) -> np.ndarray:
    """k-means over (N,3) LAB rows. Returns (k',3) centres, k' <= k."""
    rows = np.ascontiguousarray(lab_pixels.reshape(-1, 3).astype(np.float32))
    if rows.shape[0] == 0:
        return np.zeros((0, 3), np.float32)
    # k-means cannot produce more clusters than it has distinct samples.
    k = int(min(k, rows.shape[0]))
    if k <= 1:
        return rows.mean(axis=0, keepdims=True)
    _, _, centres = cv2.kmeans(
        rows, k, None, _KMEANS_CRITERIA, _KMEANS_ATTEMPTS, cv2.KMEANS_PP_CENTERS
    )
    return centres.astype(np.float32)


def _dedupe(palette_lab: np.ndarray, protected: int) -> tuple[np.ndarray, int]:
    """Fold visually indistinguishable entries together.

    ``protected`` is the count of leading entries that came from the subject k-means; when
    a subject colour and a background colour collide the subject's survives, because
    subject fidelity is what the product is selling.

    Note this can merge across the subject/background boundary, leaving the silhouette
    without a colour change in that area. That is acceptable: the region boundary is
    preserved regardless, because the merge stage refuses to fuse across the silhouette
    and the canvas draws outlines for every region.
    """
    keep: list[int] = []
    for index in range(palette_lab.shape[0]):
        candidate = palette_lab[index]
        duplicate = False
        for kept in keep:
            if color.delta_e(candidate, palette_lab[kept]) < DEDUPE_DELTA_E:
                duplicate = True
                break
        if not duplicate:
            keep.append(index)
    kept_subject = sum(1 for i in keep if i < protected)
    return palette_lab[keep], kept_subject


def prune_unused(
    palette_lab: np.ndarray,
    palette_rgb: np.ndarray,
    from_subject: np.ndarray,
    region_colour: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Drop palette entries no region uses, and renumber the rest.

    Necessary because the palette is built *before* merging, and merging re-snaps each surviving
    region to its nearest entry — so entries can end up orphaned. Left in, they appear in the
    palette tray as numbers with nothing to paint, which is a straightforwardly broken experience.
    Measured on a real photo: 82 palette entries of which only 59 were reachable.

    Relative order is preserved, so the palette stays sorted light to dark and
    :func:`despeckle`'s assumption about neighbouring indices still holds.
    """
    used = np.unique(region_colour)
    if used.size == palette_lab.shape[0]:
        return palette_lab, palette_rgb, from_subject, region_colour

    remap = np.full(palette_lab.shape[0], -1, dtype=np.int32)
    remap[used] = np.arange(used.size, dtype=np.int32)
    return (
        palette_lab[used],
        palette_rgb[used],
        from_subject[used],
        remap[region_colour].astype(np.int32),
    )


def despeckle(labels: np.ndarray, radius: int = 1) -> np.ndarray:
    """Median-filter the label map to remove isolated single-pixel labels.

    A median filter on arbitrary label indices would be meaningless, but the palette is
    ordered by lightness before this runs, so neighbouring indices are perceptually
    neighbouring colours and the median of a neighbourhood is a sensible value. That makes
    this a single cheap ``medianBlur`` instead of a per-label morphological pass.
    """
    if labels.max() > 255:
        return labels
    ksize = 2 * radius + 1
    smoothed = cv2.medianBlur(labels.astype(np.uint8), ksize)
    return smoothed.astype(np.int32)


def quantize(
    img: np.ndarray,
    n_colours: int = 16,
    subject_mask: np.ndarray | None = None,
    despeckle_radius: int = 1,
) -> Quantized:
    """Reduce ``img`` (RGB uint8) to a palette of at most ``n_colours``."""
    n_colours = int(np.clip(n_colours, MIN_COLOURS, MAX_COLOURS))
    lab = color.rgb_to_lab(img)

    if subject_mask is not None:
        is_subject = subject_mask > 127
        coverage = float(is_subject.mean())
        k_subject, k_background = subject_colour_split(n_colours, coverage)
        subject_centres = _kmeans_lab(lab[is_subject], k_subject)
        background_centres = _kmeans_lab(lab[~is_subject], k_background)
        # Subject entries lead so deduplication can protect them.
        centres = np.vstack([subject_centres, background_centres])
        protected = subject_centres.shape[0]
    else:
        centres = _kmeans_lab(lab, n_colours)
        protected = 0

    centres, kept_subject = _dedupe(centres, protected)

    # Subject entries lead the pre-ordering array, so mark them before reordering and
    # permute the flags alongside the palette. Tracking only a *count* would be wrong:
    # luminance ordering interleaves subject and background entries.
    came_from_subject = np.zeros(centres.shape[0], dtype=bool)
    came_from_subject[:kept_subject] = True

    # Order light -> dark, which despeckle() depends on and the palette tray presents.
    order = color.luminance_order(centres)
    palette_lab = centres[order]

    labels = color.nearest_palette_index(lab, palette_lab)
    if despeckle_radius > 0:
        labels = despeckle(labels, radius=despeckle_radius)

    return Quantized(
        labels=labels.astype(np.int32),
        palette_lab=palette_lab,
        palette_rgb=color.lab_rows_to_rgb(palette_lab),
        from_subject=came_from_subject[order],
        requested_colours=n_colours,
    )
