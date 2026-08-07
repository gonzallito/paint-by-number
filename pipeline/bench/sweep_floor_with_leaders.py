"""Leader lines change the economics of the radius floor.

Before leaders, lowering the floor produced regions that could not be numbered, so the floor
had to stay high. Now those regions get a leader instead, so the floor can drop and recover
detail. The cost is no longer unnumbered regions but leader clutter.
"""

import sys

import numpy as np

from pbn import color, images, numbering, preprocess, quantize, segment, subject

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"
K, BUDGET = 48, 2400
FLOORS = (0.38, 0.30, 0.24, 0.18)

print(f"detailed variant (k={K}). Cost of a lower floor is now leader %, not unnumbered %.")
print(f"{'image':15s}" + "".join(f"{f'floor {f}':>21s}" for f in FLOORS))
print(f"{'':15s}" + "  regions leader unnum" * len(FLOORS))
print("-" * (15 + 21 * len(FLOORS)))

agg = {f: {"n": [], "l": [], "u": []} for f in FLOORS}
for p in images.list_images(CORPUS):
    w = images.fit_long_edge(images.load(p), 1400)
    s = subject.detect(w, cache_dir=".cache/subject")
    mask = None if s is None else s.mask
    simp = preprocess.background_simplification(w, mask)
    flat = preprocess.flatten_differential(w, mask, simplify_background=simp)
    q = quantize.quantize(flat, K, subject_mask=mask)
    lab = color.rgb_to_lab(flat)
    row = f"{p.stem:15s}"
    for fl in FLOORS:
        seg = segment.segment(
            q.labels,
            q.n_colours,
            lab,
            q.palette_lab,
            budget=BUDGET,
            subject_mask=mask,
            min_radius_scale=fl,
        )
        num = numbering.place(seg.labels, seg.region_colour, seg.n_regions)
        agg[fl]["n"].append(seg.n_regions)
        agg[fl]["l"].append(num.leader_fraction)
        agg[fl]["u"].append(num.unlabelled_fraction)
        row += f"{seg.n_regions:9,d}{num.leader_fraction:7.0%}{num.unlabelled_fraction:6.1%}"
    print(row)

print("-" * (15 + 21 * len(FLOORS)))
print(
    f"{'median / mean':15s}"
    + "".join(
        f"{int(np.median(agg[f]['n'])):9,d}{np.mean(agg[f]['l']):7.0%}{np.mean(agg[f]['u']):6.1%}"
        for f in FLOORS
    )
)
