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


# Leader lines: when a region has no interior room, its number is drawn outside and joined
# back by a thin line. This is what commercial paint-by-number kits do, and it is the only
# thing that works here — two independent attempts to make regions rounder (boundary
# smoothing, and a shape term in the merge cost) each moved the unnumberable fraction by
# under 1%, because the offending regions are thin in the *source photograph*: object edges,
# outlines and gaps. They are not artefacts of merging and cannot be merged away.
LEADER_DIRECTIONS = 16
LEADER_MAX_LENGTH_FACTOR = 16.0  # multiples of the minimum digit height
LEADER_STEP_FACTOR = 0.5  # search granularity, also in digit heights
# Padding around a label box when reserving space, so adjacent numbers do not touch.
LABEL_PADDING = 2.0
# Successive regions start their angular search offset by the golden angle, so that clusters
# of leaders fan out instead of all pointing the same direction.
GOLDEN_ANGLE = 2.399963


@dataclass
class Numbering:
    """Number placement for every region."""

    centres: np.ndarray  # (N, 2) int32, (x, y) of the most interior pixel
    radii: np.ndarray  # (N,) float32, inscribed radius in pixels
    digit_heights: np.ndarray  # (N,) float32, height to draw at (0 = no label at all)
    label_positions: np.ndarray  # (N, 2) int32, where the digit is actually drawn
    has_leader: np.ndarray  # (N,) bool, label sits outside and needs a connector line

    @property
    def fits(self) -> np.ndarray:
        """Boolean mask of regions that carry a number, whether inside or via a leader."""
        return self.digit_heights > 0

    @property
    def inside(self) -> np.ndarray:
        """Regions whose number sits within their own boundary."""
        return self.fits & ~self.has_leader

    @property
    def unlabelled_fraction(self) -> float:
        if self.digit_heights.size == 0:
            return 0.0
        return float(1.0 - self.fits.mean())

    @property
    def leader_fraction(self) -> float:
        if self.digit_heights.size == 0:
            return 0.0
        return float(self.has_leader.mean())

    def leader_lengths(self) -> np.ndarray:
        """Distance from anchor to label for each leadered region."""
        if not self.has_leader.any():
            return np.zeros(0, dtype=np.float32)
        delta = self.label_positions[self.has_leader] - self.centres[self.has_leader]
        return np.hypot(delta[:, 0], delta[:, 1]).astype(np.float32)


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

    height_map, width_map = labels.shape
    centres = np.zeros((n_regions, 2), dtype=np.int32)
    radii = np.zeros(n_regions, dtype=np.float32)
    heights = np.zeros(n_regions, dtype=np.float32)
    label_positions = np.zeros((n_regions, 2), dtype=np.int32)
    has_leader = np.zeros(n_regions, dtype=bool)

    # Reserved space, so labels never overlap one another.
    occupancy = np.zeros(labels.shape, dtype=bool)

    def label_box(x: float, y: float, digits: int, text_height: float) -> tuple[int, int, int, int]:
        half_w = digits * DIGIT_ASPECT * text_height / 2.0 + LABEL_PADDING
        half_h = text_height / 2.0 + LABEL_PADDING
        return (
            int(round(x - half_w)),
            int(round(y - half_h)),
            int(round(x + half_w)),
            int(round(y + half_h)),
        )

    def reserve(box: tuple[int, int, int, int]) -> None:
        x0, y0, x1, y1 = box
        occupancy[max(0, y0) : y1 + 1, max(0, x0) : x1 + 1] = True

    def is_free(box: tuple[int, int, int, int]) -> bool:
        x0, y0, x1, y1 = box
        if x0 < 0 or y0 < 0 or x1 >= width_map or y1 >= height_map:
            return False
        return not occupancy[y0 : y1 + 1, x0 : x1 + 1].any()

    # find_objects is 1-indexed and returns None for absent labels.
    boxes = ndi.find_objects(labels + 1)
    digits_for = [len(str(int(region_colour[r]) + 1)) for r in range(n_regions)]

    # --- Pass 1: interior placement, largest regions first ------------------------------
    # Ordering by area matters because pass 1 reserves space that pass 2 must work around;
    # letting the most prominent regions claim their natural position first keeps the common
    # case clean.
    areas = np.bincount(labels.ravel(), minlength=n_regions)
    order = np.argsort(-areas, kind="stable")

    needs_leader: list[int] = []
    for region in order:
        region = int(region)
        if region >= len(boxes) or boxes[region] is None:
            continue
        box = boxes[region]
        crop = labels[box] == region
        if not crop.any():
            continue

        local_x, local_y, radius = _interior_point(crop)
        anchor_x = box[1].start + local_x
        anchor_y = box[0].start + local_y
        centres[region] = (anchor_x, anchor_y)
        radii[region] = radius
        digits = digits_for[region]

        # Scale the digit to the room available, then verify it actually fits. A region can
        # have ample area yet no interior room if it is long and thin, which is precisely
        # the case an area-only threshold misses.
        desired = float(
            np.clip(radius * DIGIT_HEIGHT_PER_RADIUS, min_digit_height, max_digit_height)
        )
        if radius >= required_radius(digits, desired):
            text_height = desired
        elif radius >= required_radius(digits, min_digit_height):
            text_height = min_digit_height
        else:
            needs_leader.append(region)
            continue

        heights[region] = text_height
        label_positions[region] = (anchor_x, anchor_y)
        reserve(label_box(anchor_x, anchor_y, digits, text_height))

    # --- Pass 2: leader lines for everything that did not fit ---------------------------
    # Leaders always use the minimum digit height: they are a fallback, and a compact label
    # is far more likely to find free space.
    step = max(1.0, min_digit_height * LEADER_STEP_FACTOR)
    max_length = min_digit_height * LEADER_MAX_LENGTH_FACTOR
    angles = np.arange(LEADER_DIRECTIONS) * (2.0 * np.pi / LEADER_DIRECTIONS)

    # Largest first again, so the more visible small regions get the shortest leaders.
    for rank, region in enumerate(sorted(needs_leader, key=lambda r: -areas[r])):
        digits = digits_for[region]
        anchor_x, anchor_y = (int(v) for v in centres[region])
        # Start just clear of the region itself, otherwise the label lands on top of the
        # sliver it is meant to point at.
        start = max(radii[region] + min_digit_height * 0.6, step)
        offset = rank * GOLDEN_ANGLE

        placed = False
        distance = start
        while distance <= max_length and not placed:
            for angle in angles + offset:
                candidate_x = anchor_x + distance * float(np.cos(angle))
                candidate_y = anchor_y + distance * float(np.sin(angle))
                candidate = label_box(candidate_x, candidate_y, digits, min_digit_height)
                if is_free(candidate):
                    heights[region] = min_digit_height
                    label_positions[region] = (int(round(candidate_x)), int(round(candidate_y)))
                    has_leader[region] = True
                    reserve(candidate)
                    placed = True
                    break
            distance += step

        if not placed:
            # Genuinely nowhere to put it; leave unlabelled rather than overlap another
            # number, which would be worse than an absent one.
            heights[region] = 0.0
            label_positions[region] = (anchor_x, anchor_y)

    return Numbering(
        centres=centres,
        radii=radii,
        digit_heights=heights,
        label_positions=label_positions,
        has_leader=has_leader,
    )
