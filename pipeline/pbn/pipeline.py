"""End-to-end conversion: photo in, colourable canvas out.

Variants exist because conversion quality is not fully predictable from the input. Offering
the user two or three renditions turns a quality gamble into a choice they own, which buys
a great deal of forgiveness for an imperfect pipeline — and it is load-bearing given that
photo upload is the core feature rather than a premium add-on.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from pbn import color, faces, images, numbering, preprocess, quantize, segment, stylise, subject

# --- Adaptive sizing -----------------------------------------------------------------------
#
# Canvas size follows the source. A camera-roll photo (12-48MP on any recent phone) supports a
# large canvas with many regions and a deep palette; a saved web image or screenshot does not, and
# cannot be upscaled into detail it never had.
#
# Region count is then derived from canvas *area* rather than chosen by hand, so both input classes
# get regions of the same comfortable size and simply differ in how many there are. This is what
# makes one set of settings work for both.
MAX_WORKING_LONG_EDGE = 2400
# Small sources are enlarged to this before conversion. Region count is proportional to canvas
# area, so without it a 0.4MP download yields ~120 regions against ~1,350 for a 6MP phone photo.
# Measured: enlarging such an image to 1900px took it from 119 regions / 36 colours to 852 / 93,
# with no visible interpolation artefacts and a markedly better filled result.
# See images.ensure_long_edge for why Lanczos specifically.
MIN_WORKING_LONG_EDGE = 1800

# Target area per region, in canvas pixels — the painting grain. ~3,200px is roughly 57x57,
# comfortable to tap and fill.
#
# 6,400px was tried first and was too coarse: it drove ordinary web-sized images down to ~120
# regions, which both lost fidelity and collapsed all three variants into the same output because
# every one of them hit TARGET_REGIONS_MIN.
TARGET_REGION_AREA_PX = 3200.0
TARGET_REGIONS_MIN = 100
TARGET_REGIONS_MAX = 1600

# Palette size is capped by region count (measured correlation 0.849, roughly one usable colour per
# 2-4 regions), so requesting more colours than the regions can host just returns fewer. Requests
# are clamped to what is actually hostable, which keeps the palette honest and avoids paying for
# k-means clusters that get pruned immediately afterwards.
COLOURS_PER_REGION_CEILING = 0.40

# Bounds for the adaptive floor search.
FLOOR_SEARCH_LOW = 0.18
FLOOR_SEARCH_HIGH = 1.30
FLOOR_SEARCH_STEPS = 4


# Subject budget share when the background is fully defocused. A bokeh backdrop needs only a
# handful of shapes, so nearly the whole budget should go to the subject.
MAX_SUBJECT_SHARE = 0.82

# Absolute ceiling on background regions at full simplification. Expressed as a count rather
# than a share because "how many shapes does an out-of-focus backdrop deserve" does not depend
# on how detailed the user asked the subject to be.
BACKGROUND_REGIONS_WHEN_FLAT = 120


@dataclass(frozen=True)
class Variant:
    """A detail level offered to the user.

    ``region_area_scale`` multiplies the target area per region, so it sets the painting *grain*.
    Note that no variant goes below 1.0: the reviewer's comfortable grain is the finest offered, and
    richer variants add colour depth rather than smaller regions. Buying detail by shrinking regions
    is what produced cells too small to paint.
    """

    name: str
    n_colours: int
    region_area_scale: float
    canvas_cap: int
    description: str


# Region count is content-determined rather than tuning-determined, so these presets vary the
# *character* of the output more than they hit specific counts: a 2.3x larger palette buys
# only ~1.55x the regions.
#
# Radius floors recalibrated against the real corpus (`bench/recalibrate.py`). The earlier
# dev-set values produced 16-259 region canvases — too quick to be satisfying — because dev
# subjects were large and high-texture while real ones are smaller and often flat.
#
# The floor trades region count directly against unnumberable regions. Measured medians at
# background multiplier 1.8: floor 0.60 -> 121 regions / 1% unnumbered; 0.50 -> 158 / 3%;
# 0.40 -> 215 / 10%; 0.30 -> 339 / 22%. There is no setting that gives both, which is why
# leader lines for small regions are on the Phase 1 list.
# Colour counts follow the tiers that commercial custom photo-to-paint-by-number services
# actually sell — 24 / 36 / 48 — which the earlier 12 / 18 / 24 undershot by a full tier (12 is
# the children's range). Measured on the real corpus, raising the palette cuts subject
# reconstruction error by 27% and it plateaus at 48, landing on the same ceiling the industry
# settled on independently.
#
# An earlier sweep judged palette size by region count and wrongly concluded it barely mattered.
# Palette size buys colour *fidelity*, which is what "it does not look like the photo" means.
# Variants now differ mainly by **palette size**, not by region size.
#
# This is a reversal. Earlier variants bought detail by shrinking regions (floors 0.60 / 0.40 /
# 0.30), which produced canvases mixing large background shapes with cells too small to paint
# comfortably even zoomed in. Region size determines paintability, so it is held at one
# comfortable value and colour depth carries fidelity instead.
#
# Measured on the real corpus at a fixed comfortable floor, going 36 -> 150 colours:
#   mean error  6.49 -> 5.90  (only -9%, so the *metric* gain is small)
#   regions      205 -> 310   (+50% at the SAME region size, from extra colour boundaries)
# plus markedly less visible banding in gradients, which mean error averages away and which is
# most of what "looks like the photo" means perceptually.
# Variants differ by **canvas size**, i.e. how many comfortable-sized regions the artwork has, and
# therefore how long it takes. Grain is identical across all three.
#
# This replaced two earlier models, both measured and both wrong:
#
# 1. Varying region *size* — produced cells too small to paint comfortably.
# 2. Varying palette *depth* — measured to buy almost nothing. Isolating colour from region count
#    (89 -> 128 colours at near-constant regions) changed reconstruction error by 0 to -2.5%, and on
#    two images made it *worse*. Doubling region count changed it by -7% to -19%.
#
# Colour saturates early; region count is the real lever. Palettes are capped at 96 accordingly —
# beyond that the palette tray gets harder to use for no visible gain.
VARIANTS: dict[str, Variant] = {
    "simple": Variant("simple", 48, 1.0, 1400, "shorter artwork"),
    "standard": Variant("standard", 72, 1.0, 1900, "medium artwork"),
    "detailed": Variant("detailed", 96, 1.0, 2400, "longest artwork, most regions"),
}
DEFAULT_VARIANTS = ("simple", "standard", "detailed")


@dataclass
class Conversion:
    """Everything a contact sheet or artifact bundle needs, plus diagnostics."""

    variant: Variant
    working: np.ndarray  # resized original, RGB uint8
    subject_mask: np.ndarray | None
    face_mask: np.ndarray | None
    subject_coverage: float | None
    labels: np.ndarray
    region_colour: np.ndarray
    palette_rgb: np.ndarray
    from_subject: np.ndarray
    numbering: numbering.Numbering
    n_regions: int
    initial_regions: int
    n_colours: int
    texture: float
    flatten_strength: float
    target_regions: int
    radius_floor: float
    requested_colours: int
    background_simplify: float
    subject_budget_share: float
    face_count: int
    merges_blocked: bool
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def unlabelled_fraction(self) -> float:
        return self.numbering.unlabelled_fraction

    @property
    def subject_region_share(self) -> float | None:
        if self.subject_mask is None:
            return None
        inside = (self.subject_mask > 127).ravel()
        flat = self.labels.ravel()
        area = np.bincount(flat, minlength=self.n_regions)
        inside_count = np.bincount(
            flat, weights=inside.astype(np.float64), minlength=self.n_regions
        )
        is_subject = (inside_count / np.maximum(area, 1)) >= 0.5
        return float(is_subject.mean())

    def caption(self) -> str:
        """Compact diagnostics block for contact sheets."""
        coverage = "none" if self.subject_coverage is None else f"{self.subject_coverage:.0%}"
        share = self.subject_region_share
        share_text = "n/a" if share is None else f"{share:.0%}"
        total = sum(self.timings.values())
        return (
            f"variant       {self.variant.name} ({self.variant.description})\n"
            f"regions       {self.n_regions:,} (target {self.target_regions:,}) "
            f"of {self.initial_regions:,} initial\n"
            f"canvas        {self.working.shape[1]}x{self.working.shape[0]}"
            f"   floor {self.radius_floor:.2f}\n"
            f"palette       {self.n_colours} colours"
            f" (asked {self.requested_colours} of {self.variant.n_colours} offered)\n"
            f"subject       {coverage} of frame -> {share_text} of regions\n"
            f"numbers       {self.numbering.visible_fraction(1.0):.0%} shown at fit-to-screen,"
            f" {self.numbering.visible_fraction(2.0):.0%} at 2x\n"
            f"unnumbered    {self.unlabelled_fraction:.1%}"
            f"   on leaders {self.numbering.leader_fraction:.1%}\n"
            f"texture       {self.texture:.0f} -> flatten {self.flatten_strength:.2f}\n"
            f"faces         {self.face_count}\n"
            f"bg simplify   {self.background_simplify:.2f}"
            f" -> subject gets {self.subject_budget_share:.0%} of budget\n"
            f"time          {total:.1f}s"
            + ("\nWARNING       constraints unsatisfied" if self.merges_blocked else "")
        )


def canvas_long_edge(img: np.ndarray, variant: Variant | None = None) -> int:
    """Canvas size for this source and variant. Never upscales — absent detail cannot be invented.

    The variant's ``canvas_cap`` is what makes one artwork longer than another: at a fixed
    comfortable grain, more canvas means more regions. A low-resolution source cannot reach the
    larger caps, so its variants converge — which is honest, since a 0.4MP image genuinely supports
    only one rendition.
    """
    cap = (
        MAX_WORKING_LONG_EDGE if variant is None else min(MAX_WORKING_LONG_EDGE, variant.canvas_cap)
    )
    return int(np.clip(max(img.shape[:2]), MIN_WORKING_LONG_EDGE, cap))


def target_region_count(canvas_shape: tuple[int, int], variant: Variant) -> int:
    """Region count implied by canvas area at this variant's grain."""
    height, width = canvas_shape[:2]
    area_per_region = TARGET_REGION_AREA_PX * variant.region_area_scale
    return int(
        np.clip(round(height * width / area_per_region), TARGET_REGIONS_MIN, TARGET_REGIONS_MAX)
    )


def _segment_to_target(
    quantised,
    boundary_labels: np.ndarray,
    lab: np.ndarray,
    mask: np.ndarray | None,
    target: int,
    subject_share: float,
    background_cap: int,
):
    """Find the radius floor that lands closest to ``target`` regions, by bisection.

    Region count falls monotonically as the floor rises, so bisection converges quickly. Searching
    for the *count* rather than fixing the floor is what makes one configuration work for both a
    48MP camera-roll photo and a 0.4MP screenshot: each gets regions of the same comfortable size,
    and simply differs in how many there are.
    """
    low, high = FLOOR_SEARCH_LOW, FLOOR_SEARCH_HIGH
    best = None
    for _ in range(FLOOR_SEARCH_STEPS):
        middle = (low + high) / 2.0
        candidate = segment.segment(
            boundary_labels,
            quantised.n_colours,
            lab,
            quantised.palette_lab,
            budget=TARGET_REGIONS_MAX * 3,
            subject_mask=mask,
            min_radius_scale=middle,
            subject_budget_share=subject_share,
            background_region_cap=background_cap,
        )
        if best is None or abs(candidate.n_regions - target) < abs(best[1].n_regions - target):
            best = (middle, candidate)
        if candidate.n_regions > target:
            low = middle  # too many regions: raise the floor
        else:
            high = middle  # too few: lower it
    return best


def convert(
    img: np.ndarray,
    variant: Variant,
    subject_cache: str | Path | None = None,
    working_long_edge: int | None = None,
    model_cache: str | Path = ".cache/models",
    detect_faces: bool = True,
    stylise_input: bool = False,
) -> Conversion:
    """Convert one image at one detail level.

    ``stylise_input`` enables the optional morphological stylisation stage (see pbn/stylise.py),
    which removes thin structures such as hair strands before conversion.
    """
    timings: dict[str, float] = {}

    t = time.perf_counter()
    requested_edge = (
        working_long_edge if working_long_edge is not None else canvas_long_edge(img, variant)
    )
    # Enlarge first if the source is small, then fit down. Both are needed: a tiny source must grow
    # to earn a reasonable region count, and a 48MP source must shrink to stay tractable.
    working = images.fit_long_edge(images.ensure_long_edge(img, requested_edge), requested_edge)
    timings["resize"] = time.perf_counter() - t

    t = time.perf_counter()
    found = subject.detect(working, cache_dir=subject_cache) if subject.is_available() else None
    timings["subject"] = time.perf_counter() - t
    mask = None if found is None else found.mask

    t = time.perf_counter()
    detected_faces = faces.detect(working, cache_dir=model_cache) if detect_faces else None
    timings["faces"] = time.perf_counter() - t
    face_mask = detected_faces.mask if detected_faces is not None and detected_faces.found else None

    t = time.perf_counter()
    texture = preprocess.texture_score(working)
    strength = preprocess.suggest_strength(working)
    simplify = preprocess.background_simplification(working, mask)
    # Stylisation runs *after* subject and face detection, never before. Detecting on the stylised
    # image degrades both: measured, face count on a two-person photo fell from 3 to 1 because the
    # morphology had removed the features the detector relies on.
    styled = stylise.stylise(working) if stylise_input else working
    if stylise_input:
        timings["stylise"] = 0.0  # folded into the flatten timing below

    flat = preprocess.flatten_texture_adaptive(styled, mask, simplify_background=simplify)
    # Region *shapes* come from the quantised (possibly stylised) image, but region *colours* are
    # averaged from this array. Sampling the unstylised image therefore gives clean blobby
    # boundaries with colour faithful to the original photo, instead of paying for the shapes with
    # washed-out fill.
    colour_source = (
        preprocess.flatten_texture_adaptive(working, mask, simplify_background=simplify)
        if stylise_input
        else flat
    )
    timings["flatten"] = time.perf_counter() - t

    target = target_region_count(working.shape[:2], variant)
    # Requesting more colours than the regions can host just returns fewer after pruning, so the
    # request is clamped to what is hostable. Keeps the palette honest and avoids computing k-means
    # clusters that are discarded immediately.
    hostable = max(quantize.MIN_COLOURS, int(round(target * COLOURS_PER_REGION_CEILING)))
    requested_colours = min(variant.n_colours, hostable)

    t = time.perf_counter()
    # The palette is built from the colour source (the unstylised image when stylising), so that
    # palette, region colours and the final fill all agree. Boundaries are then taken from the
    # stylised image quantised against that same palette — one k-means, one colour space.
    quantised = quantize.quantize(colour_source, requested_colours, subject_mask=mask)
    if stylise_input:
        boundary_labels = quantize.despeckle(
            color.nearest_palette_index(color.rgb_to_lab(flat), quantised.palette_lab)
        )
    else:
        boundary_labels = quantised.labels
    lab = color.rgb_to_lab(colour_source)
    timings["quantize"] = time.perf_counter() - t

    # A defocused background loses region budget as well as detail. Flattening alone is not
    # enough: even a heavily flattened bokeh backdrop still has enough residual variation to
    # absorb hundreds of regions if the budget allows it.
    subject_share = float(
        np.interp(simplify, (0.0, 1.0), (segment.DEFAULT_SUBJECT_BUDGET_SHARE, MAX_SUBJECT_SHARE))
    )
    background_cap = int(
        round(
            float(
                np.interp(
                    simplify, (0.0, 1.0), (TARGET_REGIONS_MAX * 3, BACKGROUND_REGIONS_WHEN_FLAT)
                )
            )
        )
    )

    t = time.perf_counter()
    floor, seg = _segment_to_target(
        quantised, boundary_labels, lab, mask, target, subject_share, background_cap
    )
    timings["segment"] = time.perf_counter() - t

    # Drop palette entries that no surviving region uses. Must happen before numbering, because
    # renumbering changes how many digits a label needs and therefore whether it fits.
    palette_lab, palette_rgb, from_subject, region_colour = quantize.prune_unused(
        quantised.palette_lab, quantised.palette_rgb, quantised.from_subject, seg.region_colour
    )

    t = time.perf_counter()
    numbers = numbering.place(seg.labels, region_colour, seg.n_regions)
    timings["numbering"] = time.perf_counter() - t

    return Conversion(
        variant=variant,
        working=working,
        subject_mask=mask,
        face_mask=face_mask,
        subject_coverage=None if found is None else found.coverage,
        labels=seg.labels,
        region_colour=region_colour,
        palette_rgb=palette_rgb,
        from_subject=from_subject,
        numbering=numbers,
        n_regions=seg.n_regions,
        initial_regions=seg.initial_regions,
        n_colours=int(palette_rgb.shape[0]),
        texture=texture,
        flatten_strength=strength,
        target_regions=target,
        radius_floor=floor,
        requested_colours=requested_colours,
        background_simplify=simplify,
        subject_budget_share=subject_share,
        face_count=0 if detected_faces is None else detected_faces.count,
        merges_blocked=seg.merges_blocked,
        timings=timings,
    )


def convert_all(
    img: np.ndarray,
    variant_names: tuple[str, ...] = DEFAULT_VARIANTS,
    subject_cache: str | Path | None = None,
    model_cache: str | Path = ".cache/models",
    stylise_input: bool = False,
) -> list[Conversion]:
    """Convert one image at several detail levels, for the user to choose between."""
    results = []
    for name in variant_names:
        if name not in VARIANTS:
            raise ValueError(f"unknown variant {name!r}; expected one of {sorted(VARIANTS)}")
        results.append(
            convert(
                img,
                VARIANTS[name],
                subject_cache=subject_cache,
                model_cache=model_cache,
                stylise_input=stylise_input,
            )
        )
    return results
