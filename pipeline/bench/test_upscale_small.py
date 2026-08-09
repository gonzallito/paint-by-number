"""Should small sources be upscaled to earn more regions?

Region count is proportional to canvas area, and small sources keep their native size because
fit_long_edge never upscales - inventing detail would turn interpolation artefacts into regions.

But that reasoning depends on the source having texture to corrupt. A flat graphic (badge, logo,
cartoon) has none: upscaling it produces clean larger shapes, not noise. Texture score should
therefore predict whether upscaling is safe, and it is already measured.
"""

import sys

import cv2
import numpy as np

from pbn import color, images, numbering, preprocess, quantize, segment, subject

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"
SMALL = {"juve", "perfecttiming", "anime", "rubinho", "deniro"}
TARGETS = (None, 1200, 1900)
K = 72


def upscale(img, long_edge):
    h, w = img.shape[:2]
    if max(h, w) >= long_edge:
        return img
    scale = long_edge / max(h, w)
    # Lanczos keeps flat-graphic edges crisp; bilinear would add a soft halo that quantises into
    # thin ring regions around every boundary.
    return cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_LANCZOS4)


print(
    f"{'image':15s} {'texture':>8s}"
    + "".join(f"{('native' if t is None else f'{t}px'):>22s}" for t in TARGETS)
)
print(f"{'':15s} {'':>8s}" + "  regions colours unnum" * len(TARGETS))
print("-" * (23 + 22 * len(TARGETS)))

for p in images.list_images(CORPUS):
    if p.stem not in SMALL:
        continue
    raw = images.load(p)
    row = f"{p.stem:15s} {preprocess.texture_score(raw):8.0f}"
    for target in TARGETS:
        w = raw if target is None else upscale(raw, target)
        s = subject.detect(w, cache_dir=".cache/subject")
        mask = None if s is None else s.mask
        simp = preprocess.background_simplification(w, mask)
        flat = preprocess.flatten_texture_adaptive(w, mask, simplify_background=simp)
        q = quantize.quantize(flat, K, subject_mask=mask)
        lab = color.rgb_to_lab(flat)
        area = w.shape[0] * w.shape[1]
        tgt = int(np.clip(round(area / 3200), 100, 1600))
        # Match the pipeline's approach: bisect the floor toward the area-derived target.
        low, high, best = 0.18, 1.30, None
        for _ in range(4):
            mid = (low + high) / 2
            seg = segment.segment(
                q.labels,
                q.n_colours,
                lab,
                q.palette_lab,
                budget=5000,
                subject_mask=mask,
                min_radius_scale=mid,
            )
            if best is None or abs(seg.n_regions - tgt) < abs(best.n_regions - tgt):
                best = seg
            if seg.n_regions > tgt:
                low = mid
            else:
                high = mid
        _, pr, _, rc = quantize.prune_unused(
            q.palette_lab, q.palette_rgb, q.from_subject, best.region_colour
        )
        num = numbering.place(best.labels, rc, best.n_regions)
        row += f"{best.n_regions:9,d}{int(pr.shape[0]):8d}{num.unlabelled_fraction:7.1%}"
    print(row)
