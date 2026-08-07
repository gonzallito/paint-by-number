"""What does the background blur ratio actually look like on real photos?

Measure before designing the mapping. Also reports the effect of erosion, since the
silhouette edge would otherwise dominate the background measurement.
"""

import sys

from pbn import images, preprocess, subject

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"

print(
    f"{'image':15s} {'cov':>5s} {'subj tex':>9s} {'bg tex':>8s} {'ratio':>7s} "
    f"{'ratio no-erode':>15s} {'reading':>22s}"
)
print("-" * 88)
for p in images.list_images(CORPUS):
    w = images.fit_long_edge(images.load(p), 1400)
    s = subject.detect(w, cache_dir=".cache/subject")
    if s is None:
        print(f"{p.stem:15s} {'-':>5s}  (no subject)")
        continue
    inside = s.mask > 127
    st = preprocess.masked_texture(w, inside)
    bt = preprocess.masked_texture(w, ~inside)
    ratio = preprocess.background_blur_ratio(w, s.mask)
    # Same ratio with erosion disabled, to show why erosion matters.
    st0 = preprocess.masked_texture(w, inside, erode_fraction=0.0)
    bt0 = preprocess.masked_texture(w, ~inside, erode_fraction=0.0)
    raw = st0 / bt0 if bt0 > 0 else float("nan")

    if ratio is None:
        reading = "n/a"
    elif ratio >= 2.5:
        reading = "background defocused"
    elif ratio >= 1.4:
        reading = "background softer"
    elif ratio >= 0.7:
        reading = "comparable"
    else:
        reading = "background SHARPER"
    print(
        f"{p.stem:15s} {s.coverage:5.0%} {st:9.0f} {bt:8.0f} {ratio:7.2f} "
        f"{raw:15.2f} {reading:>22s}"
    )
