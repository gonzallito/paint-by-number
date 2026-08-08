"""Which actually improves the filled result: more colours, or more regions?

Each region is flooded with one flat colour, so error has two sources: palette quantisation and
within-region variation. Whichever dominates is the real lever.
"""

import sys

from pbn import color, images, pipeline

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"


def filled_error(c):
    """Mean CIE76 between the ORIGINAL canvas and what the user ends up looking at."""
    filled = c.palette_rgb[c.region_colour[c.labels]]
    return float(color.delta_e(color.rgb_to_lab(c.working), color.rgb_to_lab(filled)).mean())


print(
    f"{'image':14s} {'variant':10s} {'regions':>8s} {'colours':>8s} {'err':>7s} {'vs simple':>10s}"
)
print("-" * 62)
for p in images.list_images(CORPUS):
    img = images.load(p)
    base = None
    for v in ("simple", "standard", "detailed"):
        c = pipeline.convert(
            img, pipeline.VARIANTS[v], subject_cache=".cache/subject", model_cache=".cache/models"
        )
        err = filled_error(c)
        if base is None:
            base = err
            delta = "-"
        else:
            delta = f"{err / base - 1:+.0%}"
        print(f"{p.stem:14s} {v:10s} {c.n_regions:8,d} {c.n_colours:8d} {err:7.2f} {delta:>10s}")
    print()
