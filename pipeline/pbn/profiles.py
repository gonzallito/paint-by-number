"""Content profiles: a named parameter set plus the acceptance criteria that go with it.

A *variant* is a detail level offered to the player for their own photo. A *profile* is a
production recipe for curated content, and the difference matters: a variant derives its region
count from how much detail the photo happens to contain, while a profile states the count as a
product decision and must hit it.

Each profile carries its own gate, because the profiles do not agree on what "good" means. A
zoomable library canvas may contain regions too small to tap at fit-to-screen — the player zooms
in. The daily canvas cannot zoom, so the same region makes the painting impossible to finish. One
global quality bar would either fail acceptable library art or pass unusable daily art.

Usage::

    conversion, report = convert_with_profile(img, PROFILES["daily"])
    if report.passed:
        artifact.write_bundle(conversion, out_dir)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from pbn import pipeline

# Comfortable inscribed radius for a tap target, in screen pixels, on a canvas that cannot zoom.
#
# Not the 22px that Material's 44px minimum touch target implies. That figure is for controls which
# must be hit first time and where a miss does something wrong. Painting is more forgiving: a miss
# does nothing at all, and the player is deliberately aiming. Measured across illustration art, the
# 22px bar caps the daily canvas at roughly 17-38 regions, which is too short a session on some
# art; 14px keeps 24-47.
#
# PROVISIONAL. This wants a real-device read before it is treated as settled.
DEFAULT_MIN_TAP_RADIUS_PX = 14.0

# Safe paintable area on a portrait phone, after the top HUD and the bottom navigation bar. Used to
# convert a canvas-space radius into a screen-space one for the tappability check.
DEFAULT_DISPLAY_SIZE = (1080, 1400)


@dataclass(frozen=True)
class Profile:
    """A production recipe and its acceptance criteria."""

    name: str
    description: str

    # --- conversion -------------------------------------------------------------------
    target_regions: int
    n_colours: int
    canvas_long_edge: int
    zoomable: bool
    # None means use the pipeline default. The daily canvas needs a much higher floor because
    # nothing is revealed by zooming.
    radius_floor: float | None = None
    guarantee_min_radius: bool = False

    # --- acceptance gate --------------------------------------------------------------
    min_regions: int = 1
    max_regions: int = pipeline.TARGET_REGIONS_MAX
    min_colours: int = 1
    max_unnumbered: float = 0.0
    # Only meaningful when the canvas cannot zoom.
    display_size: tuple[int, int] = DEFAULT_DISPLAY_SIZE
    min_tap_radius_px: float = DEFAULT_MIN_TAP_RADIUS_PX
    require_all_numbers_at_fit: bool = False

    def variant(self) -> pipeline.Variant:
        """The Variant the pipeline needs. ``region_area_scale`` is unused here, because the
        region count is stated explicitly rather than derived from canvas area."""
        return pipeline.Variant(
            name=self.name,
            n_colours=self.n_colours,
            region_area_scale=1.0,
            canvas_cap=self.canvas_long_edge,
            description=self.description,
        )


# Region counts and floors below are measured, not guessed. See the daily floor sweep in
# docs/APP-SPEC.md: at floor 1.8 with the forced merge, illustration art lands at 24-47 regions with
# 0% of regions under 14 screen pixels and 100% of numbers visible without zooming.
#
# Library tiers pair a region count with a canvas sized for it. Matching the two is not cosmetic: a
# low region count on a large canvas is *slower*, because the second merge pass has to reduce tens
# of thousands of initial regions rather than hundreds. Measured at 52.3s for 100 regions on a
# 1900px canvas against roughly 2s for the same count at 1400px.
PROFILES: dict[str, Profile] = {
    "daily": Profile(
        name="daily",
        description="fixed canvas, 3-5 minutes, everything tappable without zooming",
        target_regions=110,
        n_colours=12,
        canvas_long_edge=1400,
        zoomable=False,
        radius_floor=1.8,
        guarantee_min_radius=True,
        min_regions=20,
        max_regions=130,
        min_colours=8,
        require_all_numbers_at_fit=True,
    ),
    "library-easy": Profile(
        name="library-easy",
        description="10-15 minutes",
        target_regions=250,
        n_colours=28,
        canvas_long_edge=1400,
        zoomable=True,
        min_regions=180,
        max_regions=320,
        min_colours=18,
    ),
    "library-medium": Profile(
        name="library-medium",
        description="25-40 minutes",
        target_regions=550,
        n_colours=48,
        canvas_long_edge=1900,
        zoomable=True,
        min_regions=420,
        max_regions=700,
        min_colours=32,
    ),
    "library-hard": Profile(
        name="library-hard",
        description="60-90 minutes",
        target_regions=1200,
        n_colours=88,
        canvas_long_edge=2400,
        zoomable=True,
        min_regions=900,
        max_regions=1600,
        min_colours=60,
    ),
}

DEFAULT_PROFILE = "library-medium"


@dataclass
class GateReport:
    """Whether a conversion is fit to publish, and the numbers behind that."""

    profile: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    metrics: dict[str, float | int | bool] = field(default_factory=dict)

    def summary(self) -> str:
        state = "PASS" if self.passed else "FAIL"
        detail = "" if self.passed else "  " + "; ".join(self.failures)
        return (
            f"{state}  {self.profile:15s} "
            f"{self.metrics.get('regions', 0):5d} regions "
            f"{self.metrics.get('colours', 0):3d} colours "
            f"min_tap {self.metrics.get('min_tap_radius_px', 0):5.1f}px{detail}"
        )


def screen_radii(conversion, display_size: tuple[int, int]) -> np.ndarray:
    """Per-region inscribed radius in *screen* pixels at fit-to-screen.

    Tappability is a property of the display, not the canvas, so a canvas-space radius says
    nothing on its own.
    """
    height, width = conversion.labels.shape[:2]
    display_w, display_h = display_size
    scale = min(display_w / max(width, 1), display_h / max(height, 1))
    return np.asarray(conversion.numbering.radii, dtype=np.float64) * scale


def evaluate(conversion, profile: Profile) -> GateReport:
    """Check a conversion against a profile's acceptance criteria."""
    radii = screen_radii(conversion, profile.display_size)
    visible_at_fit = float(conversion.numbering.visible_fraction(1.0))

    metrics: dict[str, float | int | bool] = {
        "regions": int(conversion.n_regions),
        "target_regions": int(conversion.target_regions),
        "colours": int(conversion.n_colours),
        "unnumbered": float(conversion.unlabelled_fraction),
        "numbers_at_fit": visible_at_fit,
        "min_tap_radius_px": float(radii.min()) if radii.size else 0.0,
        "median_tap_radius_px": float(np.median(radii)) if radii.size else 0.0,
        "untappable_regions": int((radii < profile.min_tap_radius_px).sum()),
        "merges_blocked": bool(conversion.merges_blocked),
    }

    failures: list[str] = []

    if not profile.min_regions <= conversion.n_regions <= profile.max_regions:
        failures.append(
            f"regions {conversion.n_regions} outside {profile.min_regions}-{profile.max_regions}"
        )
    if conversion.n_colours < profile.min_colours:
        failures.append(f"colours {conversion.n_colours} below {profile.min_colours}")
    if conversion.unlabelled_fraction > profile.max_unnumbered:
        failures.append(
            f"unnumbered {conversion.unlabelled_fraction:.1%} above {profile.max_unnumbered:.1%}"
        )

    # Tappability and full number visibility only bind when the player cannot zoom. On a zoomable
    # canvas a small region is reached by zooming, which is what reveal_zoom exists for.
    if not profile.zoomable:
        untappable = int(metrics["untappable_regions"])
        if untappable:
            failures.append(
                f"{untappable} region(s) below {profile.min_tap_radius_px:.0f}px "
                f"(smallest {metrics['min_tap_radius_px']:.1f}px)"
            )
        if profile.require_all_numbers_at_fit and visible_at_fit < 1.0:
            failures.append(f"only {visible_at_fit:.0%} of numbers visible without zooming")

    return GateReport(profile=profile.name, passed=not failures, failures=failures, metrics=metrics)


def convert_with_profile(img: np.ndarray, profile: Profile, **kwargs):
    """Convert to a profile's recipe and grade the result.

    Returns ``(conversion, report)``. A failing report is not an exception: a content build wants
    to convert everything, then show which pieces need different art or a different profile.
    """
    conversion = pipeline.convert(
        img,
        profile.variant(),
        target_regions=profile.target_regions,
        guarantee_min_radius=profile.guarantee_min_radius,
        radius_floor=profile.radius_floor,
        **kwargs,
    )
    return conversion, evaluate(conversion, profile)
