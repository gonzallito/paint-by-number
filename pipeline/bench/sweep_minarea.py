"""How does the minimum-region-area floor trade against final region count?

min_area is expressed as a fraction of total canvas area, which is the resolution-
independent way to say "big enough to carry a digit". 400px on a 1400px-long-edge canvas
is ~0.020% of it.
"""

import numpy as np

from pbn import color, images, preprocess, quantize, segment, subject

WORK = 1400
N_COLOURS = 16
BUDGET = 1500

SCALES = (0.15, 0.25, 0.4, 0.6, 1.0)

prepared = []
for p in images.list_images("../corpus/dev"):
    img = images.fit_long_edge(images.load(p), WORK)
    sub = subject.detect(img, cache_dir=".cache/subject")
    mask = None if sub is None else sub.mask
    flat = preprocess.flatten_differential(img, mask)
    q = quantize.quantize(flat, N_COLOURS, subject_mask=mask)
    prepared.append((p.stem, q, color.rgb_to_lab(flat), mask))

px = WORK  # long edge; area floor in px for scale 1.0 at this resolution
print(
    f"min_area at {WORK}px long edge, scale 1.0 = {segment.RADIUS_REF_AT_1400:.0f}px "
    f"(radius ~{np.sqrt(segment.RADIUS_REF_AT_1400 / np.pi):.0f}px)"
)
print()
header = f"{'image':20s}" + "".join(f"{f'x{s}':>10s}" for s in SCALES)
print(header)
print("-" * len(header))

counts = {s: [] for s in SCALES}
for stem, q, lab, mask in prepared:
    row = f"{stem:20s}"
    for s in SCALES:
        seg = segment.segment(
            q.labels,
            q.n_colours,
            lab,
            q.palette_lab,
            budget=BUDGET,
            subject_mask=mask,
            min_radius_scale=s,
        )
        counts[s].append(seg.n_regions)
        row += f"{seg.n_regions:10,d}"
    print(row)

print("-" * len(header))
print(f"{'median':20s}" + "".join(f"{int(np.median(counts[s])):10,d}" for s in SCALES))
print(f"{'min':20s}" + "".join(f"{min(counts[s]):10,d}" for s in SCALES))
print(
    f"{'in 300-1500':20s}"
    + "".join(f"{sum(1 for c in counts[s] if 300 <= c <= 1500):9d}/7" for s in SCALES)
)

for s in SCALES:
    area_px = segment.RADIUS_REF_AT_1400 * s
    print(
        f"  scale {s:4.2f} -> {area_px:6.0f}px  radius ~{np.sqrt(area_px / np.pi):4.1f}px  "
        f"= {area_px / (WORK * WORK * 0.75) * 100:.4f}% of canvas"
    )
