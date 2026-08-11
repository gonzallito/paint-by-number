"""Should flattening follow LOCAL TEXTURE rather than subject membership?

Current behaviour flattens the subject LESS, to preserve detail that carries likeness. On hair
that is actively harmful: it keeps thousands of individual strands as thin snaking regions and
gives the page a contour-map look. Hair does not want 500 strand regions, it wants ~20 tonal masses.

Foliage, fur and fabric weave are the same problem. The hypothesis is that flatten strength should
track LOCAL texture — hair and leaves flattened hard, smooth gradients (faces, skies) preserved —
independently of whether the pixels belong to the subject.
"""

import sys

import cv2
import numpy as np

from pbn import color, images, preprocess, quantize, segment, subject

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"
WORK, K = 1900, 72


def local_texture(img: np.ndarray, window: int = 25) -> np.ndarray:
    """Per-pixel local texture: standard deviation of the Laplacian in a window, 0..1."""
    grey = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)
    lap = np.abs(cv2.Laplacian(grey, cv2.CV_32F))
    k = window | 1
    mean = cv2.blur(lap, (k, k))
    # Normalise robustly; the top percentile is hair/foliage.
    high = np.percentile(mean, 97)
    return np.clip(mean / max(high, 1e-6), 0.0, 1.0)


def flatten_texture_adaptive(img, mask, base, simp, high=3.2):
    """Escalate flattening in high-texture areas only, on top of current behaviour.

    Purely additive: smooth areas keep exactly the flattening they get today, and only hair,
    foliage and weave are pushed harder. This is the correct comparison - an earlier version
    also lowered the baseline, which conflated two changes.
    """
    light = preprocess.flatten_differential(img, mask, simplify_background=simp)
    heavy = preprocess.flatten(img, strength=base * high)
    weight = local_texture(img)[:, :, None]
    return np.clip(light * (1.0 - weight) + heavy * weight, 0, 255).astype(np.uint8)


print(f"canvas {WORK}px, k={K}   initial regions = merge workload; lower is a cleaner page")
print(
    f"{'image':16s} {'texture':>8s} {'initial now':>12s} {'initial adaptive':>17s} {'change':>8s}"
)
print("-" * 68)
for p in images.list_images(CORPUS):
    if p.stem not in {"leonorGoncalo", "martim", "porto", "arouca", "tese", "deniro"}:
        continue
    w = images.fit_long_edge(images.load(p), WORK)
    s = subject.detect(w, cache_dir=".cache/subject")
    mask = None if s is None else s.mask
    base = preprocess.suggest_strength(w)
    simp = preprocess.background_simplification(w, mask)

    now = preprocess.flatten_differential(w, mask, simplify_background=simp)
    adaptive = flatten_texture_adaptive(w, mask, base, simp)

    counts = []
    for variant in (now, adaptive):
        q = quantize.quantize(variant, K, subject_mask=mask)
        lab = color.rgb_to_lab(variant)
        seg = segment.segment(
            q.labels,
            q.n_colours,
            lab,
            q.palette_lab,
            budget=100000,
            subject_mask=mask,
            min_radius_scale=1.0,
        )
        counts.append(seg.initial_regions)
    print(
        f"{p.stem:16s} {preprocess.texture_score(w):8.0f} {counts[0]:12,d} {counts[1]:17,d} "
        f"{counts[1] / counts[0] - 1:7.0%}"
    )
