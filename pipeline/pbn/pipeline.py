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

from pbn import color, images, numbering, preprocess, quantize, segment, subject

# Segmentation runs at this long edge regardless of the input size. Measured: raising it to
# 2000 or 2800px does not increase region count (131 -> 129 -> 124 median) because the
# thresholds and the image content scale together, while cost rises 3.1s -> 4.3s. The
# eventual high-resolution artifact should come from upscaling the label map, not from
# segmenting at full size.
WORKING_LONG_EDGE = 1400


@dataclass(frozen=True)
class Variant:
    """A detail level offered to the user."""

    name: str
    n_colours: int
    budget: int
    min_radius_scale: float
    description: str


# Region count is content-determined rather than tuning-determined, so these presets vary
# the *character* of the output more than they hit specific counts. Measured on the dev set:
# a 2.3x larger palette buys only ~1.55x the regions, and dropping the radius floor to 0.40
# yields 3x the regions at 18-24% of them unnumberable.
VARIANTS: dict[str, Variant] = {
    "simple": Variant("simple", 12, 400, 0.85, "few large regions, quick to finish"),
    "standard": Variant("standard", 18, 900, 0.60, "balanced detail"),
    "detailed": Variant("detailed", 24, 1500, 0.50, "maximum detail, some regions unnumbered"),
}
DEFAULT_VARIANTS = ("simple", "standard", "detailed")


@dataclass
class Conversion:
    """Everything a contact sheet or artifact bundle needs, plus diagnostics."""

    variant: Variant
    working: np.ndarray  # resized original, RGB uint8
    subject_mask: np.ndarray | None
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
            f"unnumbered    {self.unlabelled_fraction:.1%}\n"
            f"texture       {self.texture:.0f} -> flatten {self.flatten_strength:.2f}\n"
            f"time          {total:.1f}s"
            + ("\nWARNING       constraints unsatisfied" if self.merges_blocked else "")
        )


def convert(
    img: np.ndarray,
    variant: Variant,
    subject_cache: str | Path | None = None,
    working_long_edge: int = WORKING_LONG_EDGE,
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
    texture = preprocess.texture_score(working)
    strength = preprocess.suggest_strength(working)
    flat = preprocess.flatten_differential(working, mask)
    timings["flatten"] = time.perf_counter() - t

    t = time.perf_counter()
    quantised = quantize.quantize(flat, variant.n_colours, subject_mask=mask)
    lab = color.rgb_to_lab(flat)
    timings["quantize"] = time.perf_counter() - t

    t = time.perf_counter()
    seg = segment.segment(
        quantised.labels,
        quantised.n_colours,
        lab,
        quantised.palette_lab,
        budget=variant.budget,
        subject_mask=mask,
        min_radius_scale=variant.min_radius_scale,
    )
    timings["segment"] = time.perf_counter() - t

    t = time.perf_counter()
    numbers = numbering.place(seg.labels, seg.region_colour, seg.n_regions)
    timings["numbering"] = time.perf_counter() - t

    return Conversion(
        variant=variant,
        working=working,
        subject_mask=mask,
        subject_coverage=None if found is None else found.coverage,
        labels=seg.labels,
        region_colour=seg.region_colour,
        palette_rgb=quantised.palette_rgb,
        from_subject=quantised.from_subject,
        numbering=numbers,
        n_regions=seg.n_regions,
        initial_regions=seg.initial_regions,
        n_colours=quantised.n_colours,
        texture=texture,
        flatten_strength=strength,
        merges_blocked=seg.merges_blocked,
        timings=timings,
    )


def convert_all(
    img: np.ndarray,
    variant_names: tuple[str, ...] = DEFAULT_VARIANTS,
    subject_cache: str | Path | None = None,
) -> list[Conversion]:
    """Convert one image at several detail levels, for the user to choose between."""
    results = []
    for name in variant_names:
        if name not in VARIANTS:
            raise ValueError(f"unknown variant {name!r}; expected one of {sorted(VARIANTS)}")
        results.append(convert(img, VARIANTS[name], subject_cache=subject_cache))
    return results
