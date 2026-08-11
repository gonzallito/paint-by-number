"""Joint sweep of working resolution and the minimum-effective-radius floor.

Region count and numberability pull against each other at fixed resolution. Higher
resolution should relieve the tension by resolving more genuine detail above a
proportionally scaled floor.
"""

import time

import numpy as np

from pbn import color, images, numbering, preprocess, quantize, segment, subject

N_COLOURS = 16
BUDGET = 1500
RESOLUTIONS = (1400, 2000, 2800)
SCALES = (0.40, 0.60)

# Only the fetched images are large enough to actually vary; builtins cap at 640px.
PATHS = [p for p in images.list_images("../corpus/dev") if "hires" in p.stem]

print("Region count / unlabelled %% / seconds, by working resolution and radius floor")
print(f"{'image':18s} {'scale':>6s}" + "".join(f"{f'{r}px':>22s}" for r in RESOLUTIONS))
print("-" * 90)

for p in PATHS:
    raw = images.load(p)
    for scale in SCALES:
        row = f"{p.stem:18s} {scale:6.2f}"
        for res in RESOLUTIONS:
            img = images.fit_long_edge(raw, res)
            sub = subject.detect(img, cache_dir=".cache/subject")
            mask = None if sub is None else sub.mask
            t = time.time()
            flat = preprocess.flatten_differential(img, mask)
            q = quantize.quantize(flat, N_COLOURS, subject_mask=mask)
            lab = color.rgb_to_lab(flat)
            seg = segment.segment(
                q.labels,
                q.n_colours,
                lab,
                q.palette_lab,
                budget=BUDGET,
                subject_mask=mask,
                min_radius_scale=scale,
            )
            num = numbering.place(seg.labels, seg.region_colour, seg.n_regions)
            elapsed = time.time() - t
            row += f"{seg.n_regions:9,d} {num.unlabelled_fraction:6.1%} {elapsed:5.1f}s"
        print(row)

print("\n" + "=" * 90)
print("Does higher resolution buy region count without costing numberability?")
print(f"{'resolution':>12s} {'median regions':>16s} {'mean unlabelled':>17s} {'mean seconds':>14s}")
print("-" * 90)
for res in RESOLUTIONS:
    counts, unlab, times = [], [], []
    for p in PATHS:
        img = images.fit_long_edge(images.load(p), res)
        sub = subject.detect(img, cache_dir=".cache/subject")
        mask = None if sub is None else sub.mask
        t = time.time()
        flat = preprocess.flatten_differential(img, mask)
        q = quantize.quantize(flat, N_COLOURS, subject_mask=mask)
        lab = color.rgb_to_lab(flat)
        seg = segment.segment(
            q.labels,
            q.n_colours,
            lab,
            q.palette_lab,
            budget=BUDGET,
            subject_mask=mask,
            min_radius_scale=0.60,
        )
        num = numbering.place(seg.labels, seg.region_colour, seg.n_regions)
        times.append(time.time() - t)
        counts.append(seg.n_regions)
        unlab.append(num.unlabelled_fraction)
    print(
        f"{res:11d}px {int(np.median(counts)):16,d} {np.mean(unlab):16.1%} {np.mean(times):13.1f}s"
    )
