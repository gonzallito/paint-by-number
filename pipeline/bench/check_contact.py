"""Does a shape term in the merge cost reduce region elongation?

Compares the shape-aware cost against colour-only by toggling CONTACT_EXPONENT to 0.
Metric: median effective radius at a fixed region count, and the unnumberable fraction.
"""

import sys

import numpy as np

from pbn import color, images, numbering, preprocess, quantize, segment, smooth, subject

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"
K, FLOOR, BUDGET = 40, 0.38, 2000
EXPONENTS = (0.0, 0.4, 0.75, 1.2)

print(f"k={K}, radius floor {FLOOR}   (exponent 0.0 = colour-only, the previous behaviour)")
print(f"{'image':15s}" + "".join(f"{f'exp {e}':>22s}" for e in EXPONENTS))
print(f"{'':15s}" + "  regions  radius  unnum" * len(EXPONENTS))
print("-" * (15 + 22 * len(EXPONENTS)))

agg = {e: {"r": [], "u": [], "n": []} for e in EXPONENTS}
for p in images.list_images(CORPUS):
    w = images.fit_long_edge(images.load(p), 1400)
    sub = subject.detect(w, cache_dir=".cache/subject")
    mask = None if sub is None else sub.mask
    flat = preprocess.flatten_differential(w, mask)
    q = quantize.quantize(flat, K, subject_mask=mask)
    lab = color.rgb_to_lab(flat)
    row = f"{p.stem:15s}"
    for e in EXPONENTS:
        original = segment.CONTACT_EXPONENT
        segment.CONTACT_EXPONENT = e
        try:
            seg = segment.segment(
                q.labels,
                q.n_colours,
                lab,
                q.palette_lab,
                budget=BUDGET,
                subject_mask=mask,
                min_radius_scale=FLOOR,
            )
        finally:
            segment.CONTACT_EXPONENT = original
        num = numbering.place(seg.labels, seg.region_colour, seg.n_regions)
        rad = float(np.median(smooth.compactness(seg.labels, seg.n_regions)))
        agg[e]["r"].append(rad)
        agg[e]["u"].append(num.unlabelled_fraction)
        agg[e]["n"].append(seg.n_regions)
        row += f"{seg.n_regions:9,d}{rad:8.2f}{num.unlabelled_fraction:7.1%}"
    print(row)

print("-" * (15 + 22 * len(EXPONENTS)))
print(
    f"{'mean':15s}"
    + "".join(
        f"{int(np.mean(agg[e]['n'])):9,d}{np.mean(agg[e]['r']):8.2f}{np.mean(agg[e]['u']):7.1%}"
        for e in EXPONENTS
    )
)
base_u = np.mean(agg[0.0]["u"])
base_r = np.mean(agg[0.0]["r"])
print()
for e in EXPONENTS[1:]:
    print(
        f"  exponent {e}: radius {np.mean(agg[e]['r']) / base_r - 1:+.0%}, "
        f"unnumbered {np.mean(agg[e]['u']) - base_u:+.1%} absolute "
        f"({np.mean(agg[e]['u']) / base_u - 1:+.0%} relative)"
    )
