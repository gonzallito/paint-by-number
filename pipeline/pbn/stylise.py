"""Optional stylisation: turn a photograph into flatter, more illustration-like input.

Opt-in and off by default, so existing output is unaffected. Enable with ``pbn convert --stylise``
and send it to a separate output directory.

**Why this stage exists.** Four earlier attempts to make the colourable page look designed rather
than like a contour map — boundary smoothing, a shape-aware merge cost, background simplification,
and texture-adaptive flattening — each helped a few percent and none solved it. What they share is
that they all *smooth* the photograph. Smoothing reduces how many tonal bands hair breaks into
without changing their **directionality**, so strands survive as thin ribbons either way.

Morphological opening-closing is categorically different: it **deletes** structures narrower than
its kernel instead of blurring them. That is the operation the pipeline was missing.

Measured at an 1800px canvas with a 15px kernel, against no stylisation:

| image         | initial regions   | median elongation |
|---------------|-------------------|-------------------|
| leonorGoncalo | 30,445 -> 7,768   | 2.49 -> 2.14      |
| martim        | 27,087 -> 9,448   | 2.14 -> 1.82      |
| tese          | 21,959 -> 8,462   | 2.30 -> 1.86      |

Final region count is unchanged, because it is pinned to canvas area — the gain is that the same
number of regions are rounder and cost far less merging to obtain.

Note this is deliberately a *classical* styliser. A learned photo-to-illustration model would very
likely do better, and remains the more promising direction; the ONNX hosts tried were unreachable
from this sandbox (404 / auth required), so this establishes whether the *idea* is sound before
anyone invests in model plumbing.
"""

from __future__ import annotations

import cv2
import numpy as np

# Kernel diameter at a 1800px long edge, scaled with the canvas. 15px removes hair strands and
# fabric weave while leaving facial features and clothing boundaries intact. Larger kernels keep
# rounding regions but start swallowing features worth keeping — eyes go first.
KERNEL_AT_1800 = 15
REFERENCE_LONG_EDGE = 1800.0

# Edges to protect from the morphology, as a fraction of the strongest gradients present. Without
# this, opening-closing rounds off genuine silhouettes as readily as it removes hair.
EDGE_PROTECT_PERCENTILE = 96.0
# Edges are only protected where the surrounding neighbourhood is below this local-texture level.
# Above it the "edge" is one strand among thousands and simplifying it is the whole point.
TEXTURE_GATE = 0.35


def kernel_size_for(long_edge: int, scale: float = 1.0) -> int:
    """Odd kernel diameter for a canvas with this long edge."""
    size = int(round(KERNEL_AT_1800 * scale * (long_edge / REFERENCE_LONG_EDGE)))
    return max(3, size | 1)


def _strong_edges(img: np.ndarray, dilate: int) -> np.ndarray:
    """Mask of *isolated* strong edges — silhouettes and features, not dense texture.

    Gating on local texture is essential, not a refinement. A first version protected simply the
    strongest gradients, which defeated the entire stage: in hair almost every pixel is a strong
    gradient, so the protection covered exactly the texture the morphology was meant to remove.
    Measured, it left initial regions unchanged (65,500 vs 67,861) where the unprotected version
    cut them by 74%.

    An isolated boundary — a jawline against a wall — has a strong local gradient inside a
    low-texture neighbourhood. Hair has strong gradients inside a high-texture neighbourhood. Only
    the former is worth preserving.
    """
    grey = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    gradient = cv2.magnitude(
        cv2.Sobel(grey, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(grey, cv2.CV_32F, 0, 1, ksize=3)
    )
    threshold = float(np.percentile(gradient, EDGE_PROTECT_PERCENTILE))
    strong = gradient >= threshold

    from pbn.preprocess import local_texture

    quiet_neighbourhood = local_texture(img) <= TEXTURE_GATE
    mask = (strong & quiet_neighbourhood).astype(np.uint8)

    if dilate > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate | 1, dilate | 1))
        mask = cv2.dilate(mask, kernel)
    return mask.astype(bool)


def morph_simplify(img: np.ndarray, size: int) -> np.ndarray:
    """Remove structures thinner than ``size`` while preserving larger shapes.

    Opening then closing with the same disc: opening deletes thin *light* structures and closing
    deletes thin *dark* ones. Both are needed — hair contains highlights and shadows alike.
    """
    if size <= 1:
        return img.copy()
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    opened = cv2.morphologyEx(img, cv2.MORPH_OPEN, kernel)
    return cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel)


def stylise(img: np.ndarray, scale: float = 1.0, protect_edges: bool = True) -> np.ndarray:
    """Flatten ``img`` (RGB uint8) toward illustration by removing thin structures.

    ``protect_edges`` keeps the original pixels along the strongest gradients, so silhouettes and
    facial features stay sharp while hair and weave are simplified. Without it the morphology rounds
    off real boundaries just as happily as it removes texture.
    """
    size = kernel_size_for(max(img.shape[:2]), scale)
    simplified = morph_simplify(img, size)
    if not protect_edges:
        return simplified
    keep = _strong_edges(img, dilate=max(3, size // 3))[:, :, None]
    return np.where(keep, img, simplified)
