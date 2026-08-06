"""Where to put each region's number.

The textbook answer is the *pole of inaccessibility* — the point furthest from a polygon's
boundary — usually computed with a polygon algorithm such as Mapbox's ``polylabel``. But
our regions are already rasters, so a distance transform gives the same answer far more
directly: the pixel with the maximum distance-to-boundary *is* the most interior point, and
its distance value *is* the inscribed radius, which tells us whether a digit even fits.
Two useful numbers from one cheap call, and no polygon library.

This is a concrete payoff from having dropped vectorisation: on a polygon representation
this stage would need real computational geometry.

The transform runs on each region's bounding-box crop rather than the full frame. Doing it
full-frame per region would be O(regions x pixels) — for 900 regions on a 2-megapixel image
that is 1.8 billion pixel visits for information confined to a small box.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import scipy.ndimage as ndi

# Digit geometry for Noto Sans: a numeral's advance width is a little over half its height.
DIGIT_ASPECT = 0.62

# Inscribed radius must exceed the text's half-diagonal by this factor for the number to
# sit comfortably rather than touching the region's edges.
FIT_SAFETY = 1.15

# Digit height limits, quoted at a 1400px long edge and scaled linearly with the canvas.
#
# These MUST scale with resolution to stay consistent with the merge stage's minimum
# effective radius, which also scales. Holding digit height at a fixed pixel value while the
# radius floor scaled produced exactly the mismatch it sounds like: on a 451px canvas the
# merge guaranteed 2.1px of interior room while numbering demanded 6.4px, leaving 67% of
# regions unlabelled despite the merge having done its job correctly.
MIN_DIGIT_HEIGHT_AT_1400 = 7.0
# Deliberately close to the minimum. Digits scale with the room available so that small
# regions get numbers that fit, but there is no reason for a large region to carry a large
# number, and letting the range run wide (34px was tried) reads as unpolished next to the
# near-uniform numbering commercial paint-by-number products use.
MAX_DIGIT_HEIGHT_AT_1400 = 13.0
REFERENCE_LONG_EDGE = 1400.0

# Digit height as a fraction of the region's inscribed radius, so numbers scale with the
# space available instead of being uniformly tiny or uniformly huge.
DIGIT_HEIGHT_PER_RADIUS = 0.95


@dataclass
class Numbering:
    """Number placement for every region."""

    centres: np.ndarray  # (N, 2) int32, (x, y) of the most interior pixel
    radii: np.ndarray  # (N,) float32, inscribed radius in pixels
    digit_heights: np.ndarray  # (N,) float32, height to draw at (0 where it will not fit)

    @property
    def fits(self) -> np.ndarray:
        """Boolean mask of regions whose number can actually be drawn."""
        return self.digit_heights > 0

    @property
    def unlabelled_fraction(self) -> float:
        if self.digit_heights.size == 0:
            return 0.0
        return float(1.0 - self.fits.mean())


def text_half_diagonal(digits: int, height: float) -> float:
    """Half-diagonal of the bounding box of ``digits`` numerals at ``height`` pixels."""
    width = digits * DIGIT_ASPECT * height
    return float(np.hypot(width, height) / 2.0)


def required_radius(digits: int, height: float) -> float:
    """Inscribed radius needed to comfortably hold ``digits`` numerals at ``height``."""
    return text_half_diagonal(digits, height) * FIT_SAFETY


def _interior_point(mask: np.ndarray) -> tuple[int, int, float]:
    """Most interior pixel of a boolean crop, plus its distance to the boundary.

    The crop is zero-padded first. Without padding, a region touching the crop edge would
    have its distance measured only against boundaries inside the crop, overstating how much
    room it has — OpenCV does not treat off-image as background.
    """
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    distance = cv2.distanceTransform(padded.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    flat_index = int(np.argmax(distance))
    y, x = np.unravel_index(flat_index, distance.shape)
    # Subtract the pad offset to return to crop coordinates.
    return int(x) - 1, int(y) - 1, float(distance[y, x])


def digit_height_limits(long_edge: int) -> tuple[float, float]:
    """Minimum and maximum digit height for a canvas with this long edge."""
    scale = long_edge / REFERENCE_LONG_EDGE
    return MIN_DIGIT_HEIGHT_AT_1400 * scale, MAX_DIGIT_HEIGHT_AT_1400 * scale


def place(
    labels: np.ndarray,
    region_colour: np.ndarray,
    n_regions: int,
    min_digit_height: float | None = None,
    max_digit_height: float | None = None,
) -> Numbering:
    """Compute a number position, inscribed radius and digit size for every region.

    ``region_colour`` supplies the palette index per region, because the number of digits
    changes the space required — "12" needs noticeably more room than "3".

    Digit height limits default to values scaled from the canvas's own long edge, keeping
    them consistent with the merge stage's resolution-scaled radius floor.
    """
    default_min, default_max = digit_height_limits(max(labels.shape))
    if min_digit_height is None:
        min_digit_height = default_min
    if max_digit_height is None:
        max_digit_height = default_max

    centres = np.zeros((n_regions, 2), dtype=np.int32)
    radii = np.zeros(n_regions, dtype=np.float32)
    heights = np.zeros(n_regions, dtype=np.float32)

    # find_objects is 1-indexed and returns None for absent labels.
    boxes = ndi.find_objects(labels + 1)

    for region in range(n_regions):
        if region >= len(boxes) or boxes[region] is None:
            continue
        box = boxes[region]
        crop = labels[box] == region
        if not crop.any():
            continue

        local_x, local_y, radius = _interior_point(crop)
        centres[region] = (box[1].start + local_x, box[0].start + local_y)
        radii[region] = radius

        # Numbers are 1-based for the user; palette index 0 is displayed as "1".
        digits = len(str(int(region_colour[region]) + 1))

        # Scale the digit to the room available, then verify it actually fits. A region can
        # have ample area yet no interior room if it is long and thin, which is precisely
        # the case an area-only threshold misses.
        desired = float(
            np.clip(radius * DIGIT_HEIGHT_PER_RADIUS, min_digit_height, max_digit_height)
        )
        if radius >= required_radius(digits, desired):
            heights[region] = desired
        elif radius >= required_radius(digits, min_digit_height):
            heights[region] = min_digit_height
        else:
            heights[region] = 0.0  # no legible number possible

    return Numbering(centres=centres, radii=radii, digit_heights=heights)
