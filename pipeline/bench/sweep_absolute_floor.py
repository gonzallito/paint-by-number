"""Is canvas size the missing lever for region count AND palette size?

The minimum region radius is currently expressed relative to the canvas long edge, so enlarging
the canvas enlarges the floor too and region count stays flat -- which is why an earlier sweep
concluded "resolution is not a lever". But comfortable region size is a property of the SCREEN,
not the canvas. Holding the floor ABSOLUTE and growing the canvas should raise region count with
area, and with it the number of usable colours.
"""

import sys

import numpy as np

from pbn import color, images, numbering, preprocess, quantize, segment, subject

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"
RESOLUTIONS = (1400, 2100, 2800)
BASE_SCALE = 0.60  # comfortable floor, quoted at 1400px
K = 150

print("Floor held ABSOLUTE (same on-screen comfort) while the canvas grows.")
print(f"{'image':14s}" + "".join(f"{f'{r}px':>24s}" for r in RESOLUTIONS))
print(f"{'':14s}" + "  regions palette vis@1x" * len(RESOLUTIONS))
print("-" * (14 + 24 * len(RESOLUTIONS)))

agg = {r: {"n": [], "c": [], "v": []} for r in RESOLUTIONS}
for p in images.list_images(CORPUS):
    raw = images.load(p)
    row = f"{p.stem:14s}"
    for res in RESOLUTIONS:
        w = images.fit_long_edge(raw, res)
        long_edge = max(w.shape[:2])
        # Cancel the resolution term so the floor is the same absolute size at every canvas size.
        scale = BASE_SCALE * (1400.0 / long_edge)
        s = subject.detect(w, cache_dir=".cache/subject")
        mask = None if s is None else s.mask
        simp = preprocess.background_simplification(w, mask)
        flat = preprocess.flatten_differential(w, mask, simplify_background=simp)
        q = quantize.quantize(flat, K, subject_mask=mask)
        lab = color.rgb_to_lab(flat)
        seg = segment.segment(
            q.labels,
            q.n_colours,
            lab,
            q.palette_lab,
            budget=20000,
            subject_mask=mask,
            min_radius_scale=scale,
        )
        pl, pr, fs, rc = quantize.prune_unused(
            q.palette_lab, q.palette_rgb, q.from_subject, seg.region_colour
        )
        num = numbering.place(seg.labels, rc, seg.n_regions)
        agg[res]["n"].append(seg.n_regions)
        agg[res]["c"].append(int(pr.shape[0]))
        agg[res]["v"].append(num.visible_fraction(1.0))
        row += f"{seg.n_regions:9,d}{int(pr.shape[0]):8d}{num.visible_fraction(1.0):7.0%}"
    print(row)

print("-" * (14 + 24 * len(RESOLUTIONS)))
print(
    f"{'median':14s}"
    + "".join(
        f"{int(np.median(agg[r]['n'])):9,d}{int(np.median(agg[r]['c'])):8d}"
        f"{np.mean(agg[r]['v']):7.0%}"
        for r in RESOLUTIONS
    )
)
base_n = np.median(agg[RESOLUTIONS[0]]["n"])
print()
for r in RESOLUTIONS:
    print(
        f"  {r}px: regions {np.median(agg[r]['n']) / base_n:.2f}x baseline, "
        f"median palette {int(np.median(agg[r]['c']))} of {K} requested"
    )
