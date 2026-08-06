"""Does a larger palette buy region count without costing numberability?"""
import numpy as np
from pbn import color, images, numbering, preprocess, quantize, segment, subject

WORK, BUDGET, SCALE = 1400, 1500, 0.60
COLOURS = (12, 16, 20, 24, 28)

print(f"Region count / unlabelled %, at {WORK}px, radius floor {SCALE}")
print(f"{'image':20s}" + "".join(f"{f'k={k}':>16s}" for k in COLOURS))
print("-" * 100)
agg = {k: {"n": [], "u": []} for k in COLOURS}
for p in images.list_images("../corpus/dev"):
    img = images.fit_long_edge(images.load(p), WORK)
    sub = subject.detect(img, cache_dir=".cache/subject")
    mask = None if sub is None else sub.mask
    flat = preprocess.flatten_differential(img, mask)
    lab = color.rgb_to_lab(flat)
    row = f"{p.stem:20s}"
    for k in COLOURS:
        q = quantize.quantize(flat, k, subject_mask=mask)
        seg = segment.segment(q.labels, q.n_colours, lab, q.palette_lab,
                              budget=BUDGET, subject_mask=mask, min_radius_scale=SCALE)
        num = numbering.place(seg.labels, seg.region_colour, seg.n_regions)
        agg[k]["n"].append(seg.n_regions); agg[k]["u"].append(num.unlabelled_fraction)
        row += f"{seg.n_regions:9,d} {num.unlabelled_fraction:5.1%}"
    print(row)
print("-" * 100)
print(f"{'median / mean':20s}" + "".join(
    f"{int(np.median(agg[k]['n'])):9,d} {np.mean(agg[k]['u']):5.1%}" for k in COLOURS))
print(f"{'palette kept':20s}", end="")
for k in COLOURS:
    kept = []
    for p in images.list_images("../corpus/dev"):
        img = images.fit_long_edge(images.load(p), WORK)
        sub = subject.detect(img, cache_dir=".cache/subject")
        mask = None if sub is None else sub.mask
        flat = preprocess.flatten_differential(img, mask)
        kept.append(quantize.quantize(flat, k, subject_mask=mask).n_colours)
    print(f"{int(np.median(kept)):9,d}      ", end="")
print()
