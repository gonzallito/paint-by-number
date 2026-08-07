"""Pre-quantisation flattening.

Quantisation is only as good as what you feed it. Sensor noise, JPEG blocking and fine
texture all survive k-means and reappear as thousands of speckle regions that the merge
stage then has to clean up. Flattening first removes that at the source, which is far
cheaper and produces better boundaries than merging afterwards.

The goal is *flat areas with intact edges*, which is a different objective from ordinary
denoising — we actively want to destroy gradients that a photograph legitimately
contains, because a gradient cannot be represented as a numbered region.
"""

from __future__ import annotations

import cv2
import numpy as np

FlattenMode = str  # "bilateral" | "edgepreserve" | "meanshift" | "hybrid"

MODES: tuple[str, ...] = ("bilateral", "edgepreserve", "meanshift", "hybrid")

# Measured on the dev set: bilateral gives a 0.50x region reduction in 0.03s, versus
# 0.64x/2.33s for mean-shift and 0.49x/2.16s for hybrid. Mean-shift was the expected
# winner (it clusters in joint colour+space, which is the posterisation we want) and lost
# on both axes. Bilateral is the default on measured evidence, not intuition.
DEFAULT_MODE: FlattenMode = "bilateral"

# Beyond ~4.0 bilateral stops helping and starts introducing its own banding, which
# fragments back into new regions. Measured: a portrait's region density bottoms out at
# strength 4.0 and rises again at 6.0.
MAX_USEFUL_STRENGTH = 4.0
MIN_USEFUL_STRENGTH = 0.6

# Empirical map from log10(Laplacian variance) to flatten strength, calibrated on the
# dev set where texture correlated with post-quantisation region density at Pearson
# 0.965 / Spearman 0.893.
#
# CALIBRATION WARNING: fitted on 7 development images, 3 of them arbitrary stock photos.
# Recalibrate against the real corpus before trusting these numbers.
_TEXTURE_LOG = (1.3, 2.4, 2.9, 3.2, 3.6)
_TEXTURE_STRENGTH = (0.7, 1.0, 1.5, 2.0, 3.5)


def texture_score(img: np.ndarray) -> float:
    """Laplacian variance: a cheap proxy for how much fine detail an image carries.

    High for foliage, crowds, fabric and sensor noise; low for smooth studio portraits.
    Predicts how badly the image will fragment under quantisation.
    """
    grey = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


def masked_texture(img: np.ndarray, mask: np.ndarray, erode_fraction: float = 0.02) -> float:
    """Laplacian variance restricted to ``mask``, with the mask boundary excluded.

    Erosion is essential rather than tidy. The silhouette is one of the strongest edges in the
    image, so measuring right up to it would register a huge Laplacian response on *both*
    sides and make even a heavily blurred background look sharp — exactly inverting the signal
    we are trying to read.
    """
    selected = mask.astype(bool)
    if not selected.any():
        return 0.0

    long_edge = max(img.shape[:2])
    k = max(3, int(round(long_edge * erode_fraction)) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    core = cv2.erode(selected.astype(np.uint8), kernel).astype(bool)
    # A thin region can erode away entirely; fall back to the uneroded mask rather than
    # reporting zero texture, which would read as "perfectly blurred".
    if not core.any():
        core = selected

    grey = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    laplacian = cv2.Laplacian(grey, cv2.CV_64F)
    return float(laplacian[core].var())


def background_blur_ratio(img: np.ndarray, subject_mask: np.ndarray | None) -> float | None:
    """How much blurrier the background is than the subject. ``None`` without a subject.

    Values near 1 mean both are equally sharp (a subject against a detailed scene). Large
    values mean the background is out of focus — bokeh, which carries nothing worth colouring.

    Deliberately a *ratio* rather than an absolute measure, so that a uniformly soft or
    low-light photo is not mistaken for one with a deliberately defocused background.
    """
    if subject_mask is None:
        return None
    inside = subject_mask > 127
    subject_texture = masked_texture(img, inside)
    outside_texture = masked_texture(img, ~inside)
    if outside_texture <= 1e-6:
        return None if subject_texture <= 1e-6 else float("inf")
    return float(subject_texture / outside_texture)


# Background texture below this reads as "nothing worth colouring"; above the upper bound the
# background has real structure that must survive. Interpolated on a log scale between.
# Measured across the real corpus: bokeh backdrops land at 6-20, a moderately busy backdrop at
# 104-144, and genuinely detailed scenes at 805-1191.
BACKGROUND_TEXTURE_FLAT = 25.0
BACKGROUND_TEXTURE_STRUCTURED = 400.0

# A background this much blurrier than the subject is unambiguously defocused, whatever its
# absolute texture, so it earns at least this much simplification.
BACKGROUND_RATIO_STRONG = 3.0
BACKGROUND_RATIO_FLOOR = 0.75

# At full simplification the background's flatten strength is multiplied by 1 + this.
BACKGROUND_SIMPLIFY_BOOST = 1.5


def background_simplification(img: np.ndarray, subject_mask: np.ndarray | None) -> float:
    """How aggressively to simplify the background, from 0 (leave alone) to 1 (collapse).

    Driven primarily by the background's *absolute* texture rather than by its ratio to the
    subject. The ratio alone under-reads the most common portrait failure: a person in flat
    clothing against a defocused backdrop scores only ~2.4 because the flat subject shrinks the
    numerator, even though the background is plainly bokeh. Absolute texture reads that case
    correctly, and the ratio is kept as a booster for backgrounds that are moderately textured
    yet clearly softer than a sharp subject.
    """
    if subject_mask is None:
        return 0.0

    outside = ~(subject_mask > 127)
    if not outside.any():
        return 0.0

    texture = masked_texture(img, outside)
    factor = float(
        np.interp(
            np.log10(max(texture, 1.0)),
            (np.log10(BACKGROUND_TEXTURE_FLAT), np.log10(BACKGROUND_TEXTURE_STRUCTURED)),
            (1.0, 0.0),
        )
    )

    ratio = background_blur_ratio(img, subject_mask)
    if ratio is not None and ratio >= BACKGROUND_RATIO_STRONG:
        factor = max(factor, BACKGROUND_RATIO_FLOOR)
    return float(np.clip(factor, 0.0, 1.0))


def suggest_strength(img: np.ndarray) -> float:
    """Pick a flatten strength from the image's own texture.

    A fixed strength cannot work: on the dev set, post-quantisation region density
    spanned 1,900 to 160,000 per megapixel — an 84x range. The strength that preserves a
    portrait's facial detail leaves a foliage photo with a quarter of a million regions.
    """
    score = max(texture_score(img), 1.0)
    strength = float(np.interp(np.log10(score), _TEXTURE_LOG, _TEXTURE_STRENGTH))
    return float(np.clip(strength, MIN_USEFUL_STRENGTH, MAX_USEFUL_STRENGTH))


def _bilateral_cascade(img: np.ndarray, strength: float) -> np.ndarray:
    """Repeated moderate bilateral passes.

    Two or three moderate passes flatten more thoroughly than one aggressive pass while
    holding edges better: a very large sigmaColor starts bleeding across genuine
    boundaries, whereas iterating a moderate kernel converges toward piecewise-flat.
    """
    passes = 2 if strength <= 1.0 else 3
    sigma_color = float(np.clip(28.0 * strength, 10.0, 110.0))
    sigma_space = float(np.clip(9.0 * strength, 5.0, 25.0))
    out = img
    for _ in range(passes):
        out = cv2.bilateralFilter(out, d=7, sigmaColor=sigma_color, sigmaSpace=sigma_space)
    return out


def _edge_preserving(img: np.ndarray, strength: float) -> np.ndarray:
    """OpenCV's recursive edge-preserving filter. Fast and quite flat."""
    sigma_s = float(np.clip(40.0 * strength, 10.0, 200.0))
    sigma_r = float(np.clip(0.25 * strength, 0.05, 0.9))
    # cv2.photo functions expect BGR; convert explicitly both ways.
    bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    out = cv2.edgePreservingFilter(bgr, flags=cv2.RECURS_FILTER, sigma_s=sigma_s, sigma_r=sigma_r)
    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)


def _mean_shift(img: np.ndarray, strength: float) -> np.ndarray:
    """Pyramidal mean-shift. Slowest, but produces genuinely flat plateaus.

    Mean-shift clusters in joint colour+space, which is essentially the posterisation we
    want, so it tends to give the cleanest region boundaries. Cost scales badly with
    resolution, hence the timing check before making it a default.
    """
    sp = float(np.clip(12.0 * strength, 4.0, 40.0))
    sr = float(np.clip(20.0 * strength, 8.0, 60.0))
    bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    out = cv2.pyrMeanShiftFiltering(bgr, sp=sp, sr=sr, maxLevel=1)
    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)


def flatten(
    img: np.ndarray, strength: float | None = None, mode: FlattenMode = DEFAULT_MODE
) -> np.ndarray:
    """Flatten ``img`` (RGB uint8) ahead of quantisation.

    ``strength`` scales filter parameters; 0 is a no-op passthrough, and ``None`` derives
    a strength from the image's own texture via :func:`suggest_strength`.
    """
    if strength is None:
        strength = suggest_strength(img)
    if strength <= 0:
        return img.copy()
    if mode == "bilateral":
        return _bilateral_cascade(img, strength)
    if mode == "edgepreserve":
        return _edge_preserving(img, strength)
    if mode == "meanshift":
        return _mean_shift(img, strength)
    if mode == "hybrid":
        # Bilateral first to kill noise cheaply, then mean-shift to consolidate plateaus.
        return _mean_shift(_bilateral_cascade(img, strength * 0.6), strength)
    raise ValueError(f"unknown flatten mode: {mode!r} (expected one of {MODES})")


def flatten_differential(
    img: np.ndarray,
    subject_mask: np.ndarray | None,
    subject_scale: float = 0.6,
    background_scale: float = 1.8,
    mode: FlattenMode = DEFAULT_MODE,
    simplify_background: float = 0.0,
) -> np.ndarray:
    """Flatten background harder than subject, then composite along the silhouette.

    This is the core of the subject-aware idea: preserve the detail that carries
    likeness, and aggressively simplify everything that does not. It is what an
    illustrator reducing a photo to flat colour would do.

    The composite seam is deliberately hard rather than feathered. The silhouette is a
    real edge we want to survive into the final segmentation, and the merge stage
    explicitly refuses to merge across it, so softening it here would only reintroduce
    intermediate colours along the most important boundary in the image.

    The ``*_scale`` arguments multiply the texture-derived base strength rather than
    setting it absolutely, so a busy photo and a smooth one both get the same *relative*
    subject/background contrast.

    ``simplify_background`` in 0..1 (see :func:`background_simplification`) escalates the
    background further when it is defocused. A bokeh backdrop contains no structure worth
    colouring, and left alone it fragments into long parallel bands that are faithful to the
    photo and unpleasant to colour — the point at which faithfulness and appeal diverge, and
    appeal should win.
    """
    base = suggest_strength(img)
    background_scale = background_scale * (1.0 + simplify_background * BACKGROUND_SIMPLIFY_BOOST)

    if subject_mask is None:
        return flatten(img, strength=base * background_scale, mode=mode)

    subject = flatten(img, strength=base * subject_scale, mode=mode)
    background = flatten(img, strength=base * background_scale, mode=mode)
    keep_subject = (subject_mask > 127)[:, :, None]
    return np.where(keep_subject, subject, background)
