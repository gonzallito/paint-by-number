"""Separate the two background levers: flatten boost (fixes SHAPE) vs region cap (cuts COUNT).

The wavy-band problem was a shape problem, so the flatten boost may be doing all the useful
work while the region cap merely discards content the reviewer wants kept.
"""

import sys

import numpy as np

from pbn import images, pipeline, preprocess, subject

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"
CAPS = (22, 45, 80, 10_000)  # 10_000 = effectively no cap

print("standard variant. 'no cap' isolates the flatten boost's contribution.")
print(
    f"{'image':15s} {'simp':>5s}"
    + "".join(f"{f'cap {c}' if c < 9999 else 'no cap':>17s}" for c in CAPS)
)
print(f"{'':15s} {'':>5s}" + "  regions  subj%" * len(CAPS))
print("-" * (20 + 17 * len(CAPS)))

totals = {c: [] for c in CAPS}
shares = {c: [] for c in CAPS}
for p in images.list_images(CORPUS):
    img = images.load(p)
    w = images.fit_long_edge(img, 1400)
    s = subject.detect(w, cache_dir=".cache/subject")
    simp = preprocess.background_simplification(w, None if s is None else s.mask)
    row = f"{p.stem:15s} {simp:5.2f}"
    for cap in CAPS:
        original = pipeline.BACKGROUND_REGIONS_WHEN_FLAT
        pipeline.BACKGROUND_REGIONS_WHEN_FLAT = cap
        try:
            c = pipeline.convert(img, pipeline.VARIANTS["standard"], subject_cache=".cache/subject")
        finally:
            pipeline.BACKGROUND_REGIONS_WHEN_FLAT = original
        share = c.subject_region_share
        totals[cap].append(c.n_regions)
        shares[cap].append(share if share is not None else float("nan"))
        row += f"{c.n_regions:9,d}{(share if share is not None else 0):8.0%}"
    print(row)

print("-" * (20 + 17 * len(CAPS)))
print(
    f"{'median / mean':15s} {'':>5s}"
    + "".join(f"{int(np.median(totals[c])):9,d}{np.nanmean(shares[c]):8.0%}" for c in CAPS)
)
print("\nBefore any background work: median 295 regions.")
print("Pick the cap that keeps region count while still lifting subject share.")
