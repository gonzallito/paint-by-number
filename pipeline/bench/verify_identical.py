"""Hash conversion outputs so an optimisation can be proven to change nothing.

    uv run python bench/verify_identical.py scratch/baseline.json   # before the change
    uv run python bench/verify_identical.py scratch/after.json      # after it
    diff <(jq -S . scratch/baseline.json) <(jq -S . scratch/after.json)

This is what made the 1.7x segmentation speedup safe to ship: identical label hashes prove the
merge loop rewrite altered no artwork. Requires a deterministic pipeline, which is why the
k-means seed is fixed.

Run before a change, then after, and diff the JSON. Any difference in region count, colour
count, or the label array itself means the "optimisation" altered the artwork.
"""

from __future__ import annotations

import glob
import hashlib
import json
import sys
import time

from pbn import images, pipeline

CASES = [
    ("martim.jpg", "simple"),
    ("porto.jpg", "simple"),
    ("king.png", "simple"),
    ("praga.JPG", "detailed"),
]


def main(out_path: str) -> None:
    results = {}
    for name, variant in CASES:
        matches = glob.glob(f"../corpus/{name}")
        if not matches:
            print(f"skip {name}: not in corpus")
            continue
        img = images.load(matches[0])
        started = time.perf_counter()
        c = pipeline.convert(img, pipeline.VARIANTS[variant])
        elapsed = time.perf_counter() - started
        results[f"{name}:{variant}"] = {
            "regions": int(c.n_regions),
            "colours": int(c.n_colours),
            "labels_sha1": hashlib.sha1(c.labels.tobytes()).hexdigest(),
            "region_colour_sha1": hashlib.sha1(c.region_colour.tobytes()).hexdigest(),
            "seconds": round(elapsed, 1),
        }
        print(
            f"{name:16s} {variant:9s} {c.n_regions:5d} regions "
            f"{c.n_colours:3d} colours {elapsed:6.1f}s"
        )
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, sort_keys=True)
    total = sum(v["seconds"] for v in results.values())
    print(f"total {total:.1f}s -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "scratch/baseline.json")
