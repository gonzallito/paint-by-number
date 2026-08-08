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

from pbn import color, faces, images, numbering, preprocess, quantize, segment, subject

# Canvas size for segmentation. Raised from 1400 once the radius floor became absolute rather
# than canvas-relative (see pbn/segment.py): with an absolute floor, a larger canvas genuinely
# yields more regions and therefore more usable palette entries, whereas before it did not.
#
# The gain only materialises for high-resolution sources — a 0.8MP web image has no further
# detail to resolve and is never upscaled. Region count is ultimately bounded by the source photo.
WORKING_LONG_EDGE = 1400

# Subject budget share when the background is fully defocused. A bokeh backdrop needs only a
# handful of shapes, so nearly the whole budget should go to the subject.
MAX_SUBJECT_SHARE = 0.82

# Absolute ceiling on background regions at full simplification. Expressed as a count rather
# than a share because "how many shapes does an out-of-focus backdrop deserve" does not depend
# on how detailed the user asked the subject to be.
BACKGROUND_REGIONS_WHEN_FLAT = 120


@dataclass(frozen=True)
class Variant:
    """A detail level offered to the user."""

    name: str
    n_colours: int
    budget: int
    min_radius_scale: float
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
VARIANTS: dict[str, Variant] = {
    "simple": Variant("simple", 48, 1500, 0.75, "larger regions, quicker to finish"),
    "standard": Variant("standard", 96, 3000, 0.60, "comfortable regions, rich colour"),
    "detailed": Variant("detailed", 150, 4000, 0.60, "same region size, deepest colour"),
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
            f"regions       {self.n_regions:,} of {self.initial_regions:,} initial\n"
            f"palette       {self.n_colours} colours (asked {self.variant.n_colours})\n"
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


def convert(
    img: np.ndarray,
    variant: Variant,
    subject_cache: str | Path | None = None,
    working_long_edge: int = WORKING_LONG_EDGE,
    model_cache: str | Path = ".cache/models",
    detect_faces: bool = True,
) -> Conversion:
    """Convert one image at one detail level."""
    timings: dict[str, float] = {}

    t = time.perf_counter()
    working = images.fit_long_edge(img, working_long_edge)
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
    flat = preprocess.flatten_differential(working, mask, simplify_background=simplify)
    timings["flatten"] = time.perf_counter() - t

    t = time.perf_counter()
    quantised = quantize.quantize(flat, variant.n_colours, subject_mask=mask)
    lab = color.rgb_to_lab(flat)
    timings["quantize"] = time.perf_counter() - t

    # A defocused background loses region budget as well as detail. Flattening alone is not
    # enough: even a heavily flattened bokeh backdrop still has enough residual variation to
    # absorb hundreds of regions if the budget allows it.
    subject_share = float(
        np.interp(simplify, (0.0, 1.0), (segment.DEFAULT_SUBJECT_BUDGET_SHARE, MAX_SUBJECT_SHARE))
    )
    background_cap = int(
        round(
            float(np.interp(simplify, (0.0, 1.0), (variant.budget, BACKGROUND_REGIONS_WHEN_FLAT)))
        )
    )

    t = time.perf_counter()
    seg = segment.segment(
        quantised.labels,
        quantised.n_colours,
        lab,
        quantised.palette_lab,
        budget=variant.budget,
        subject_mask=mask,
        min_radius_scale=variant.min_radius_scale,
        subject_budget_share=subject_share,
        background_region_cap=background_cap,
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
) -> list[Conversion]:
    """Convert one image at several detail levels, for the user to choose between."""
    results = []
    for name in variant_names:
        if name not in VARIANTS:
            raise ValueError(f"unknown variant {name!r}; expected one of {sorted(VARIANTS)}")
        results.append(
            convert(img, VARIANTS[name], subject_cache=subject_cache, model_cache=model_cache)
        )
    return results
