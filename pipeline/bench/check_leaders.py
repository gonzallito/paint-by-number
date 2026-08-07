"""Do leader lines eliminate unnumbered regions, and at what cost in clutter?"""

import sys
import time

import numpy as np

from pbn import color, images, numbering, preprocess, quantize, segment, subject

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"
K, FLOOR, BUDGET = 48, 0.38, 2400  # the `detailed` variant

print(f"detailed variant (k={K}, floor {FLOOR})")
print(
    f"{'image':15s} {'regions':>8s} {'inside':>7s} {'leader':>7s} {'unnum':>7s} "
    f"{'leader px':>18s} {'place s':>8s}"
)
print(f"{'':15s} {'':>8s} {'':>7s} {'':>7s} {'':>7s} {'med':>8s} {'max':>9s}")
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
    t = time.perf_counter()
    num = numbering.place(seg.labels, seg.region_colour, seg.n_regions)
    elapsed = time.perf_counter() - t

    lengths = num.leader_lengths()
    med = float(np.median(lengths)) if lengths.size else 0.0
    mx = float(lengths.max()) if lengths.size else 0.0
    rows.append((num.inside.mean(), num.leader_fraction, num.unlabelled_fraction, med, mx))
    print(
        f"{p.stem:15s} {seg.n_regions:8,d} {num.inside.mean():6.1%} "
        f"{num.leader_fraction:6.1%} {num.unlabelled_fraction:6.1%} "
        f"{med:8.1f} {mx:9.1f} {elapsed:7.2f}s"
    )

a = np.array(rows)
print("-" * 78)
print(
    f"{'mean':15s} {'':>8s} {a[:, 0].mean():6.1%} {a[:, 1].mean():6.1%} {a[:, 2].mean():6.1%} "
    f"{a[:, 3].mean():8.1f} {a[:, 4].max():9.1f}"
)
print("\nBefore leader lines the detailed variant left 12.1-31.1% of regions unnumbered.")
print(
    f"Now unlabelled is {a[:, 2].mean():.1%} mean / {a[:, 2].max():.1%} worst, "
    f"with {a[:, 1].mean():.1%} of numbers on leaders."
)
