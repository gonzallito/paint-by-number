"""How much region count is background simplification costing, on a uniform-region canvas?

The reviewer never ruled on whether the background should also be uniform. This isolates it:
same settings, background simplification fully on versus fully off.
"""

import sys

import numpy as np

from pbn import color, images, preprocess, quantize, segment, subject

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"
K, FLOOR = 150, 0.60

print(f"k={K}, uniform floor {FLOOR}")
print(f"{'image':14s} {'simp':>5s}" + f"{'bg simplify ON':>24s}{'bg simplify OFF':>24s}")
print(f"{'':14s} {'':>5s}" + "  regions palette subj%" * 2)
print("-" * 62)
on_n, off_n, on_c, off_c = [], [], [], []
for p in images.list_images(CORPUS):
    w = images.fit_long_edge(images.load(p), 1400)
    s = subject.detect(w, cache_dir=".cache/subject")
    mask = None if s is None else s.mask
    measured = preprocess.background_simplification(w, mask)
    row = f"{p.stem:14s} {measured:5.2f}"
    for simp in (measured, 0.0):
        flat = preprocess.flatten_differential(w, mask, simplify_background=simp)
        q = quantize.quantize(flat, K, subject_mask=mask)
        lab = color.rgb_to_lab(flat)
        share = float(np.interp(simp, (0.0, 1.0), (segment.DEFAULT_SUBJECT_BUDGET_SHARE, 0.93)))
        cap = int(round(float(np.interp(simp, (0.0, 1.0), (4000, 45)))))
        seg = segment.segment(
            q.labels,
            q.n_colours,
            lab,
            q.palette_lab,
            budget=4000,
            subject_mask=mask,
            min_radius_scale=FLOOR,
            subject_budget_share=share,
            background_region_cap=cap,
        )
        _, pr, _, rc = quantize.prune_unused(
            q.palette_lab, q.palette_rgb, q.from_subject, seg.region_colour
        )
        sub_share = seg.region_is_subject.mean()
        row += f"{seg.n_regions:9,d}{int(pr.shape[0]):8d}{sub_share:7.0%}"
        (on_n if simp == measured else off_n).append(seg.n_regions)
        (on_c if simp == measured else off_c).append(int(pr.shape[0]))
    print(row)
print("-" * 62)
print(
    f"{'median':14s} {'':>5s}{int(np.median(on_n)):9,d}{int(np.median(on_c)):8d}{'':7s}"
    f"{int(np.median(off_n)):9,d}{int(np.median(off_c)):8d}"
)
