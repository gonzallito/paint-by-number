"""Region extraction and budget-driven merging.

This is the stage that decides what the finished canvas actually feels like to colour, and
it is the one part of the pipeline with no off-the-shelf equivalent.

Quantisation leaves anywhere from a few hundred to ~20,000 connected regions. The target
is 300-1,500. Two reasons the standard library approach does not fit:

* ``skimage.graph.merge_hierarchical`` stops on a colour-similarity **threshold**. We need
  to stop on a region **count**, because the count is what determines whether an artwork
  takes fifteen minutes or three hours. The right threshold for a given count varies
  wildly per image, so thresholding cannot hit a budget.
* ``skimage.graph.RAG`` builds adjacency through ``ndi.generic_filter`` with a Python
  callback, i.e. one interpreter call per pixel. At 1.5 megapixels that dominates
  everything else. Adjacency is computed here with array shifts instead.

The cost function encodes the core insight that tap-target size is *not* the binding
constraint (pinch-zoom makes almost anything tappable) — **tedium** is. So cost scales
colour difference by region size: micro-facets merge almost for free regardless of colour,
while substantial regions compete on colour alone.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import cv2
import numpy as np

from pbn import color

# Regions whose *effective radius* (2·area/perimeter) falls below this are treated as
# slivers or micro-facets and merge nearly free. Expressed at a 1400px long edge and scaled
# linearly with resolution — radius is a length, so it scales with the edge, not with area.
#
# An earlier version constrained region *area* instead, which failed badly: on the dev set,
# 65% of regions could not hold a digit and 100% of those failures had adequate area with a
# median inscribed radius of only 2.2-3.0px. Quantisation boundaries follow colour gradients,
# so merged regions snake into slivers with plenty of area and no interior room.
RADIUS_REF_AT_1400 = 11.0
REFERENCE_LONG_EDGE = 1400.0

# Hard floor on effective radius, as a multiple of RADIUS_REF_AT_1400. Anchored to what
# number placement actually requires: a 2-digit number at the 7px minimum digit height needs
# an inscribed radius of ~6.4px, i.e. ~0.58 of the reference.
DEFAULT_MIN_RADIUS_SCALE = 0.60

# Background-background merges are discounted, so the background simplifies first and the
# subject keeps its regions. This is where the region budget actually gets reallocated.
BACKGROUND_COST_SCALE = 0.30

# The background's minimum effective radius is this multiple of the subject's. Cost
# discounting alone left backgrounds visibly blotchy — irregular patches that read as
# artefacts rather than design — because a discount only changes merge *order*, not the
# point at which merging stops. Forcing genuinely coarser background regions is what
# produces the few large flat shapes an illustrator would use.
#
# Now kept mild, because subject prioritisation is handled properly by the explicit budget
# split (see DEFAULT_SUBJECT_BUDGET_SHARE) rather than by distorting this floor. Earlier
# values of 2.6 and 1.8 were attempts to prioritise the subject through region *size*, which
# only ever controlled it indirectly: at 2.6 canvases collapsed to 16-259 regions, and at 1.8
# a real portrait still gave the subject only 21% of regions for 36% of the frame.
BACKGROUND_MIN_RADIUS_MULTIPLIER = 1.4

# Fraction of the region budget reserved for the subject regardless of its area. Backgrounds
# are usually the least interesting part of a photo and often the most colour-varied, so they
# need an explicit cap rather than a discount.
DEFAULT_SUBJECT_BUDGET_SHARE = 0.72

# A face tier once gave faces a *finer* floor than the rest of the subject. It was removed
# deliberately: it worked as designed (face region density rose 1.44-2.67x) and produced exactly
# the wrong artwork. Region *size* is what determines whether a canvas is pleasant to paint, so
# mixing tiny face cells with large background shapes is unpleasant however faithful it is.
#
# The lesson generalises: fidelity should come from **colour depth**, and paintability from
# **uniform region size**. Those are separate axes, and detail concentration confuses them.
# Faces are still detected (see pbn/faces.py) but only to annotate contact sheets.

# Shape term in the merge cost. Pairs with little shared border are penalised so that merging
# builds compact regions rather than chains. The exponent controls how strongly shape competes
# with colour; the epsilon keeps point-contact pairs finite rather than infinitely expensive.
CONTACT_EXPONENT = 0.75
CONTACT_EPSILON = 0.02

# A region counts as "subject" if this fraction of its pixels fall inside the mask.
SUBJECT_PIXEL_MAJORITY = 0.5


@dataclass
class Segmentation:
    """A finished set of colourable regions."""

    labels: np.ndarray  # (H, W) int32, contiguous region ids from 0
    region_colour: np.ndarray  # (N,) int32, palette index per region
    region_area: np.ndarray  # (N,) int64
    region_is_subject: np.ndarray  # (N,) bool
    initial_regions: int  # count before merging, for diagnostics
    merges_blocked: bool  # True if the budget could not be reached

    @property
    def n_regions(self) -> int:
        return int(self.labels.max()) + 1 if self.labels.size else 0


def _initial_regions(
    quantised: np.ndarray, n_colours: int, subject_mask: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Connected components within each palette colour.

    Uses 8-connectivity so a diagonal sliver reads as one region rather than a dotted
    line of separate ones.

    When a subject mask is supplied, components are extracted separately inside and
    outside it. Refusing to *merge* across the silhouette is not sufficient on its own: a
    white cat against a white couch quantises to a single colour and connects, so plain
    connected components would hand back one region already spanning both and the merge
    constraint would never get a chance to fire.
    """
    out = np.zeros(quantised.shape, dtype=np.int32)
    colours: list[int] = []
    next_id = 0

    if subject_mask is None:
        sides = [np.ones(quantised.shape, dtype=bool)]
    else:
        inside = subject_mask > 127
        sides = [inside, ~inside]

    for side in sides:
        if not side.any():
            continue
        for c in range(n_colours):
            mask = ((quantised == c) & side).astype(np.uint8)
            if not mask.any():
                continue
            count, comp = cv2.connectedComponents(mask, connectivity=8)
            found = count - 1  # label 0 is "not in mask"
            if found <= 0:
                continue
            selected = comp > 0
            out[selected] = comp[selected] - 1 + next_id
            colours.extend([c] * found)
            next_id += found
    return out, np.asarray(colours, dtype=np.int32)


def _adjacency(labels: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Region adjacency with shared-border lengths and per-region perimeters.

    Returns ``(pairs, shared_lengths, perimeters)``. Border length is counted in adjacent
    pixel pairs, which is what makes perimeter cheap to maintain across merges.

    4-connectivity: diagonal-only contact is not a real shared border, and treating it as
    one produces adjacencies with no boundary to draw.
    """
    keys = []
    for left, right in (
        (labels[:, :-1], labels[:, 1:]),
        (labels[:-1, :], labels[1:, :]),
    ):
        a = left.ravel()
        b = right.ravel()
        differing = a != b
        if not differing.any():
            continue
        a = a[differing].astype(np.int64)
        b = b[differing].astype(np.int64)
        # Encode the unordered pair as one integer so counting is a fast 1-D bincount
        # instead of np.unique(axis=0) over millions of rows.
        keys.append(np.minimum(a, b) * n + np.maximum(a, b))

    if not keys:
        # A single region covering the frame: perimeter is the image border.
        perimeters = np.zeros(n, dtype=np.float64)
        if n > 0:
            h, w = labels.shape
            perimeters[labels[0, 0]] = 2.0 * (h + w)
        return np.zeros((0, 2), dtype=np.int64), np.zeros(0, dtype=np.float64), perimeters

    all_keys = np.concatenate(keys)
    unique, counts = np.unique(all_keys, return_counts=True)
    pairs = np.stack([unique // n, unique % n], axis=1)
    shared = counts.astype(np.float64)

    # Perimeter = every shared border, plus the stretch of image edge each region touches
    # (an unbounded region would otherwise look more compact than it is).
    perimeters = np.zeros(n, dtype=np.float64)
    np.add.at(perimeters, pairs[:, 0], shared)
    np.add.at(perimeters, pairs[:, 1], shared)
    for edge in (labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]):
        np.add.at(perimeters, edge.ravel(), 1.0)

    return pairs, shared, perimeters


def _region_stats(
    labels: np.ndarray, lab: np.ndarray, n: int, subject_mask: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-region area, summed LAB, and subject flag. All vectorised via bincount."""
    flat = labels.ravel()
    area = np.bincount(flat, minlength=n).astype(np.int64)
    sums = np.empty((n, 3), dtype=np.float64)
    for channel in range(3):
        sums[:, channel] = np.bincount(
            flat, weights=lab[:, :, channel].ravel().astype(np.float64), minlength=n
        )
    if subject_mask is None:
        is_subject = np.zeros(n, dtype=bool)
    else:
        inside = np.bincount(
            flat, weights=(subject_mask > 127).ravel().astype(np.float64), minlength=n
        )
        with np.errstate(invalid="ignore", divide="ignore"):
            is_subject = (inside / np.maximum(area, 1)) >= SUBJECT_PIXEL_MAJORITY
    return area, sums, is_subject


class _Merger:
    """Greedy region merging against two independent constraints.

    The constraints are enforced in **separate passes**, and that separation is essential
    rather than cosmetic:

    1. *Absorb undersized regions.* Only edges with at least one undersized endpoint are
       eligible. This bounds the pass — it can only consume regions that need consuming.
    2. *Reduce to the count ceiling.* Any edge is eligible.

    A single combined loop ("keep going while count > budget **or** anything is
    undersized") looks equivalent and is catastrophically wrong. It pops the globally
    cheapest edge, which usually does not involve an undersized region, so when a few
    specks are silhouette-isolated and can never legally merge, the condition stays true
    and the loop merges the entire rest of the image trying to satisfy it. Measured: whole
    photos collapsing to 1-24 regions.

    Uses a lazy-deletion heap. Rather than removing stale entries when a node changes, each
    entry records the generation counter of both endpoints and is discarded on pop if
    either has moved on. Cheaper than an indexed priority queue, at the cost of some dead
    entries.
    """

    def __init__(
        self,
        pairs: np.ndarray,
        shared: np.ndarray,
        perimeter: np.ndarray,
        area: np.ndarray,
        sums: np.ndarray,
        is_subject: np.ndarray,
        radius_ref: float,
        min_radius: float,
        preserve_silhouette: bool,
    ) -> None:
        self.n = int(area.shape[0])
        self.area = area.astype(np.float64).copy()
        self.perimeter = perimeter.astype(np.float64).copy()
        self.sums = sums.astype(np.float64).copy()
        self.is_subject = is_subject.copy()
        # With no subject detected there is no foreground to protect, so the coarse
        # background floor must not apply — otherwise every region on a subject-less image
        # gets treated as background and the whole frame over-merges.
        self.has_subject = bool(is_subject.any())
        self.radius_ref = max(radius_ref, 1e-6)
        self.min_radius = min_radius
        self.preserve_silhouette = preserve_silhouette

        self.parent = np.arange(self.n, dtype=np.int64)
        self.alive = np.ones(self.n, dtype=bool)
        self.generation = np.zeros(self.n, dtype=np.int64)
        self.remaining = self.n

        # neighbour -> shared border length, so perimeter stays exact across merges.
        self.neighbours: list[dict[int, float]] = [{} for _ in range(self.n)]
        for (a, b), length in zip(pairs, shared, strict=True):
            a, b = int(a), int(b)
            self.neighbours[a][b] = float(length)
            self.neighbours[b][a] = float(length)

    # --- geometry / cost -------------------------------------------------------------

    def _mean_lab(self, i: int) -> np.ndarray:
        return self.sums[i] / max(self.area[i], 1.0)

    def effective_radius(self, i: int) -> float:
        """``2 * area / perimeter``: the radius of a disc with the same area:perimeter ratio.

        Exact for a disc, and degrades gracefully — a 50x2 sliver of area 100 scores 1.9
        against a same-area disc's 5.65. This is what area alone could not see: measured on
        the dev set, every single region that failed number placement had sufficient area
        and insufficient interior room.
        """
        return 2.0 * self.area[i] / max(self.perimeter[i], 1.0)

    def _contact(self, i: int, j: int) -> float:
        """Shared border as a fraction of the smaller region's perimeter, in 0..1.

        A proxy for how compact the merged region will be. Two regions sharing most of a
        perimeter fuse into a blob; two touching along a sliver of their outlines fuse into a
        dumbbell or a snake. Discouraging the latter is the only lever that addresses region
        *elongation*, which is the real reason regions cannot hold numbers — boundary smoothing
        was measured and only improved effective radius by 2%, because smoothing a snake leaves
        a smooth snake.
        """
        shared = self.neighbours[i].get(j, 0.0)
        smaller_perimeter = max(1.0, min(self.perimeter[i], self.perimeter[j]))
        return min(1.0, shared / smaller_perimeter)

    def _cost(self, i: int, j: int) -> float:
        """Colour difference, adjusted for sliver size, shape outcome and background priority."""
        difference = float(np.sqrt(np.sum((self._mean_lab(i) - self._mean_lab(j)) ** 2)))
        smaller = min(self.effective_radius(i), self.effective_radius(j))
        # Slivers and micro-facets merge nearly free; full colour cost applies only once a
        # region is round enough and big enough to work as its own tap target.
        size_factor = min(1.0, smaller / self.radius_ref)
        scale = 1.0 if (self.is_subject[i] or self.is_subject[j]) else BACKGROUND_COST_SCALE
        # Dividing by contact makes well-joined pairs cheap and barely-touching pairs
        # expensive, so the merger builds blobs instead of chains.
        shape_factor = 1.0 / (self._contact(i, j) + CONTACT_EPSILON) ** CONTACT_EXPONENT
        return difference * size_factor * scale * shape_factor

    def _legal(self, i: int, j: int) -> bool:
        if self.preserve_silhouette and self.is_subject[i] != self.is_subject[j]:
            return False
        return True

    def _min_radius_for(self, i: int) -> float:
        """Per-region floor. Uniform for the subject; only the background is coarser."""
        if self.is_subject[i] or not self.has_subject:
            return self.min_radius
        return self.min_radius * BACKGROUND_MIN_RADIUS_MULTIPLIER

    def _undersized(self, i: int) -> bool:
        return self.effective_radius(i) < self._min_radius_for(i)

    # --- merging ---------------------------------------------------------------------

    def _merge(self, a: int, b: int) -> int:
        """Merge ``b`` into ``a`` (larger survives). Returns the survivor."""
        if self.area[a] < self.area[b]:
            a, b = b, a

        # The shared border stops being a border, so it leaves both perimeters.
        border = self.neighbours[a].pop(b, 0.0)
        self.neighbours[b].pop(a, None)
        self.perimeter[a] = self.perimeter[a] + self.perimeter[b] - 2.0 * border

        self.area[a] += self.area[b]
        self.sums[a] += self.sums[b]
        self.is_subject[a] = bool(self.is_subject[a] or self.is_subject[b])
        self.alive[b] = False
        self.parent[b] = a
        self.generation[a] += 1
        self.remaining -= 1

        for other, length in self.neighbours[b].items():
            if other == a or not self.alive[other]:
                continue
            self.neighbours[other].pop(b, None)
            # A neighbour of both a and b now shares the sum of the two borders.
            combined = self.neighbours[a].get(other, 0.0) + length
            self.neighbours[a][other] = combined
            self.neighbours[other][a] = combined
        self.neighbours[b].clear()
        self.neighbours[a].pop(a, None)
        return a

    def _pop_valid(self, heap: list) -> tuple[int, int] | None:
        while heap:
            _, a, b, gen_a, gen_b = heapq.heappop(heap)
            if not (self.alive[a] and self.alive[b]):
                continue
            if self.generation[a] != gen_a or self.generation[b] != gen_b:
                continue  # superseded by a later merge
            return a, b
        return None

    def _push(self, heap: list, a: int, b: int) -> None:
        heapq.heappush(
            heap, (self._cost(a, b), a, b, int(self.generation[a]), int(self.generation[b]))
        )

    # --- passes ----------------------------------------------------------------------

    def absorb_undersized(self) -> None:
        """Pass 1: fold every region below ``min_area`` into a neighbour."""
        heap: list = []
        for a in range(self.n):
            if not self.alive[a]:
                continue
            for b in self.neighbours[a]:
                if b <= a or not self.alive[b] or not self._legal(a, b):
                    continue
                if self._undersized(a) or self._undersized(b):
                    self._push(heap, a, b)

        while True:
            popped = self._pop_valid(heap)
            if popped is None:
                break
            a, b = popped
            # The pair may have grown out of eligibility since it was queued.
            if not (self._undersized(a) or self._undersized(b)):
                continue
            survivor = self._merge(a, b)
            for other in self.neighbours[survivor]:
                if not self.alive[other] or not self._legal(survivor, other):
                    continue
                if self._undersized(survivor) or self._undersized(other):
                    self._push(heap, survivor, other)

    def count_side(self, subject_side: bool) -> int:
        """Living regions on one side of the silhouette."""
        return int(
            sum(
                1
                for i in range(self.n)
                if self.alive[i] and bool(self.is_subject[i]) == subject_side
            )
        )

    def reduce_to(self, budget: int, subject_side: bool | None = None) -> None:
        """Pass 2: merge the cheapest legal pair until at most ``budget`` regions remain.

        ``subject_side`` restricts the pass to one side of the silhouette. Because no edge
        ever crosses the silhouette, the two sides are genuinely independent sub-problems,
        which is what lets the caller give each an explicit budget instead of letting them
        compete on colour cost alone.
        """
        current = self.remaining if subject_side is None else self.count_side(subject_side)
        if current <= budget:
            return

        heap: list = []
        for a in range(self.n):
            if not self.alive[a]:
                continue
            if subject_side is not None and bool(self.is_subject[a]) != subject_side:
                continue
            for b in self.neighbours[a]:
                if b <= a or not self.alive[b] or not self._legal(a, b):
                    continue
                self._push(heap, a, b)

        while current > budget:
            popped = self._pop_valid(heap)
            if popped is None:
                break
            survivor = self._merge(*popped)
            current -= 1
            for other in self.neighbours[survivor]:
                if self.alive[other] and self._legal(survivor, other):
                    self._push(heap, survivor, other)

    # --- result ----------------------------------------------------------------------

    def parent_map(self) -> np.ndarray:
        """Path-compressed map from every original region id to its survivor."""
        parent = self.parent
        for i in range(self.n):
            root = i
            while parent[root] != root:
                root = parent[root]
            parent[i] = root
        return parent

    def unsatisfied(self, budget: int) -> bool:
        """True if either constraint could not be met.

        Happens when the only remaining neighbours sit across a silhouette we refuse to
        cross. Reported rather than raised: a canvas with a few stubborn slivers is still
        usable, but it signals the constraints were mutually unsatisfiable.
        """
        if self.remaining > budget:
            return True
        return any(self._undersized(i) for i in range(self.n) if self.alive[i])


def segment(
    quantised: np.ndarray,
    n_colours: int,
    lab: np.ndarray,
    palette_lab: np.ndarray,
    budget: int = 900,
    subject_mask: np.ndarray | None = None,
    preserve_silhouette: bool = True,
    min_radius_scale: float = DEFAULT_MIN_RADIUS_SCALE,
    subject_budget_share: float = DEFAULT_SUBJECT_BUDGET_SHARE,
    background_region_cap: int | None = None,
) -> Segmentation:
    """Extract regions from a quantised image and merge them.

    ``budget`` is a ceiling on region count, not a target. ``min_radius_scale`` multiplies
    the resolution-derived minimum effective radius, so a variant can trade comfortable tap
    targets against detail. ``subject_budget_share`` is the fraction of the region budget
    reserved for the subject, independent of how much of the frame it occupies.
    """
    labels, region_colour = _initial_regions(
        quantised, n_colours, subject_mask if preserve_silhouette else None
    )
    initial = int(region_colour.shape[0])
    if initial == 0:
        raise ValueError("quantised image produced no regions")

    area, sums, is_subject = _region_stats(labels, lab, initial, subject_mask)

    # Thresholds scale linearly with the canvas long edge (radius is a length), which keeps the
    # *proportion* of regions below them constant across canvas sizes.
    #
    # An absolute floor was tried, on the reasoning that comfortable region size is a property of
    # the screen rather than the canvas. It behaves exactly as that argument predicts and is still
    # a net loss on real input: it raises region count only for high-resolution sources (a 17.9MP
    # photo went 281 -> 844 regions and 115 -> 132 usable colours) while *reducing* it for ordinary
    # web-sized images, which lose the proportionally finer floor they were getting. Since most
    # real uploads are 0.4-2.6MP, relative wins on the mix.
    #
    # The insight still stands for later: to get 300-600+ regions and a 100+ colour palette, the
    # canvas must be large relative to comfortable region size, and only a high-resolution source
    # can supply that. Region count is ultimately bounded by detail present in the original photo.
    long_edge = max(labels.shape)
    resolution_scale = long_edge / REFERENCE_LONG_EDGE
    radius_ref = RADIUS_REF_AT_1400 * resolution_scale
    min_radius = RADIUS_REF_AT_1400 * min_radius_scale * resolution_scale

    # Always run the merge. Even when the initial count is already under the ceiling,
    # slivers still need absorbing.
    pairs, shared, perimeter = _adjacency(labels, initial)
    merger = _Merger(
        pairs=pairs,
        shared=shared,
        perimeter=perimeter,
        area=area,
        sums=sums,
        is_subject=is_subject,
        radius_ref=radius_ref,
        min_radius=min_radius,
        preserve_silhouette=preserve_silhouette,
    )
    merger.absorb_undersized()

    if merger.has_subject:
        # Give each side of the silhouette its own budget rather than letting them compete
        # on colour cost. Cost-based competition allocates budget to colour *variation*, and
        # perceptual importance is not colour variation: a subject in a flat black suit has
        # few boundaries and all the importance, while the blurred bokeh behind it has strong
        # colour variation and none. Left to compete, the budget flows exactly backwards —
        # measured on a real portrait, the subject took 21% of regions for 36% of the frame
        # while the out-of-focus background absorbed the rest as long wavy bands.
        subject_target = max(1, int(round(budget * subject_budget_share)))
        background_target = max(1, budget - subject_target)

        # An absolute ceiling, when the caller knows the background deserves very few shapes.
        # A share alone is not enough: 7% of a 1200 budget is still 84 regions, which is far
        # more than a defocused backdrop should ever get, and it scales the wrong way — a more
        # detailed variant would give the *background* more regions too.
        if background_region_cap is not None:
            background_target = max(1, min(background_target, background_region_cap))

        # Headroom transfers in one direction only. An unused *background* allowance may go
        # to the subject, but never the reverse: the background share is a hard ceiling, not
        # an entitlement. Donating a flat subject's unused allowance to the background undoes
        # the whole point — measured on a portrait in a black suit, it let the out-of-focus
        # backdrop keep 80% of the regions because the subject could not use its own share.
        background_have = merger.count_side(False)
        if background_have < background_target:
            subject_target += background_target - background_have

        merger.reduce_to(subject_target, subject_side=True)
        merger.reduce_to(background_target, subject_side=False)
    else:
        merger.reduce_to(budget)

    blocked = merger.unsatisfied(budget)
    labels = merger.parent_map()[labels]

    # Relabel to a contiguous 0..N-1 range.
    unique, labels = np.unique(labels, return_inverse=True)
    labels = labels.reshape(quantised.shape).astype(np.int32)
    n_final = int(unique.shape[0])

    # Recompute statistics on the merged regions and snap each to its nearest palette
    # entry. A merged region's mean colour is generally not any of its constituents'
    # colours, so re-snapping is what keeps the canvas consistent with the palette tray.
    area, sums, is_subject = _region_stats(labels, lab, n_final, subject_mask)
    means = sums / np.maximum(area, 1)[:, None]
    distances = color.delta_e(means[:, None, :], palette_lab[None, :, :])
    region_colour = np.argmin(distances, axis=1).astype(np.int32)

    return Segmentation(
        labels=labels,
        region_colour=region_colour,
        region_area=area,
        region_is_subject=is_subject,
        initial_regions=initial,
        merges_blocked=blocked,
    )
