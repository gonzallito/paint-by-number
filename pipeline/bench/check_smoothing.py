"""Does boundary smoothing make regions rounder, and does that reduce unnumbered regions?

Hypothesis: smoothing raises median effective radius at a fixed region count, which should
directly lower the unnumberable fraction and visually de-noise the page.
"""

import sys

import numpy as np

from pbn import color, images, numbering, preprocess, quantize, segment, smooth, subject

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"
K, FLOOR, BUDGET = 40, 0.38, 2000

print(f"k={K}, radius floor {FLOOR}")
print(f"{'image':16s} {'regions':>8s} {'radius med':>21s} {'unnumbered':>21s} {'split':>6s}")
print(f"{'':16s} {'':>8s} {'raw':>9s} {'smoothed':>11s} {'raw':>9s} {'smoothed':>11s}")
print("-" * 78)
rows = []
for p in images.list_images(CORPUS):
    w = images.fit_long_edge(images.load(p), 1400)
    sub = subject.detect(w, cache_dir=".cache/subject")
    mask = None if sub is None else sub.mask
    flat = preprocess.flatten_differential(w, mask)
    q = quantize.quantize(flat, K, subject_mask=mask)
    lab = color.rgb_to_lab(flat)
    seg = segment.segment(
        q.labels,
        q.n_colours,
        lab,
        q.palette_lab,
        budget=BUDGET,
        subject_mask=mask,
        min_radius_scale=FLOOR,
    )

    n0 = numbering.place(seg.labels, seg.region_colour, seg.n_regions)
    c0 = smooth.compactness(seg.labels, seg.n_regions)

    sm = smooth.smooth_labels(seg.labels)
    n1 = numbering.place(sm, seg.region_colour, seg.n_regions)
    c1 = smooth.compactness(sm, seg.n_regions)

    # did smoothing fragment any region?
    import cv2

    split = 0
    for r in np.unique(sm):
        cnt, _ = cv2.connectedComponents((sm == r).astype(np.uint8), 8)
        if cnt - 1 > 1:
            split += 1

    rows.append(
        (np.median(c0), np.median(c1), n0.unlabelled_fraction, n1.unlabelled_fraction, split)
    )
    print(
        f"{p.stem:16s} {seg.n_regions:8,d} {np.median(c0):9.2f} {np.median(c1):11.2f} "
        f"{n0.unlabelled_fraction:8.1%} {n1.unlabelled_fraction:10.1%} {split:6d}"
    )
print("-" * 78)
a = np.array(rows)
print(
    f"{'mean':16s} {'':>8s} {a[:, 0].mean():9.2f} {a[:, 1].mean():11.2f} "
    f"{a[:, 2].mean():8.1%} {a[:, 3].mean():10.1%} {a[:, 4].mean():6.1f}"
)
print(
    f"\nradius {a[:, 1].mean() / a[:, 0].mean() - 1:+.0%}   "
    f"unnumbered {a[:, 3].mean() - a[:, 2].mean():+.1%} absolute"
)
