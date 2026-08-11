"""Can morphological simplification remove thin structures that flattening only smooths?

Four attempts so far (boundary smoothing, shape-aware merge cost, background simplification,
texture-adaptive flattening) all *smoothed* hair without removing it: flattening reduces the number
of tonal bands but not their directionality, so strands survive as ribbons.

Morphological opening-closing is categorically different — it DELETES structures narrower than the
kernel instead of blurring them. A disc kernel sized to the minimum region radius should turn hair
strands into tonal masses, which is what an illustrator draws.
"""

import sys

import cv2
import numpy as np

from pbn import color, images, preprocess, quantize, segment, subject

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"
WORK, K = 1800, 72
KERNELS = (0, 5, 9, 15)


def morph_simplify(img: np.ndarray, size: int) -> np.ndarray:
    """Remove structures thinner than ``size`` while preserving larger shapes.

    Opening then closing with the same disc: opening deletes thin light structures, closing deletes
    thin dark ones. Applied per channel, which is adequate here because the following quantisation
    re-unifies colour anyway.
    """
    if size <= 1:
        return img
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size | 1, size | 1))
    opened = cv2.morphologyEx(img, cv2.MORPH_OPEN, kernel)
    return cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel)


print(f"canvas {WORK}px, k={K}. 'initial' is merge workload; 'elong' is mean region elongation")
print(f"{'image':15s}" + "".join(f"{f'kernel {k}':>26s}" for k in KERNELS))
print(f"{'':15s}" + "   initial regions elong" * len(KERNELS))
print("-" * (15 + 26 * len(KERNELS)))

for p in images.list_images(CORPUS):
    if p.stem not in {"leonorGoncalo", "martim", "tese", "juve"}:
        continue
    raw = images.ensure_long_edge(images.load(p), WORK)
    w = images.fit_long_edge(raw, WORK)
    s = subject.detect(w, cache_dir=".cache/subject")
    mask = None if s is None else s.mask
    simp = preprocess.background_simplification(w, mask)
    row = f"{p.stem:15s}"
    for kernel_size in KERNELS:
        styled = morph_simplify(w, kernel_size)
        flat = preprocess.flatten_texture_adaptive(styled, mask, simplify_background=simp)
        q = quantize.quantize(flat, K, subject_mask=mask)
        lab = color.rgb_to_lab(flat)
        target = int(np.clip(round(w.shape[0] * w.shape[1] / 3200), 100, 1600))
        low, high, best = 0.18, 1.30, None
        for _ in range(4):
            mid = (low + high) / 2
            seg = segment.segment(
                q.labels,
                q.n_colours,
                lab,
                q.palette_lab,
                budget=6000,
                subject_mask=mask,
                min_radius_scale=mid,
            )
            if best is None or abs(seg.n_regions - target) < abs(best.n_regions - target):
                best = seg
            if seg.n_regions > target:
                low = mid
            else:
                high = mid
        # Elongation: perimeter relative to that of a disc of equal area. 1.0 = perfectly round.
        from pbn.smooth import compactness

        eff_r = compactness(best.labels, best.n_regions)
        areas = np.bincount(best.labels.ravel(), minlength=best.n_regions).astype(np.float64)
        disc_r = np.sqrt(np.maximum(areas, 1) / np.pi)
        elong = float(np.median(disc_r / np.maximum(eff_r, 1e-6)))
        row += f"{best.initial_regions:10,d}{best.n_regions:8,d}{elong:6.2f}"
    print(row)
