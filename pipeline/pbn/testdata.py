"""Assemble a development image set.

These images exist so the pipeline can be written and exercised before the real corpus
is ready. They are **not** the Phase 0 quality gate — that requires the ~50 deliberately
difficult real photos described in ``corpus/manifest.csv``. Sample photos are well shot
and well lit, which is exactly the failure mode where a pipeline looks great in
development and falls apart on real uploads.

Two sources:

* **scikit-image built-ins** — small (300-640px) but bundled, offline, cleanly licensed,
  and with *known* content. ``astronaut`` and ``chelsea`` matter most: they are the
  portrait and pet cases, so they are the only images here that meaningfully exercise
  subject segmentation.
* **picsum.photos** — fetched at realistic resolution to check that region counts and
  merge performance hold up at full size. Content is arbitrary, so these test throughput
  rather than subject handling.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from pbn import images

# scikit-image built-ins: (loader name, output stem, category, has a clear subject?)
BUILTIN_SAMPLES: list[tuple[str, str, str, bool]] = [
    ("astronaut", "builtin_portrait", "portrait", True),
    ("chelsea", "builtin_pet_cat", "pet", True),
    ("coffee", "builtin_object", "object", False),
    ("rocket", "builtin_vehicle", "object", False),
]

# Fixed seeds so the dev set is reproducible across machines and runs.
PICSUM_SEEDS: list[tuple[str, str]] = [
    ("pbn-a", "fetched_hires_a"),
    ("pbn-b", "fetched_hires_b"),
    ("pbn-c", "fetched_hires_c"),
]
PICSUM_SIZE = (1600, 1200)
FETCH_TIMEOUT_S = 20


def _write_builtins(dest: Path) -> list[tuple[str, str, bool]]:
    from skimage import data

    written = []
    for loader_name, stem, category, has_subject in BUILTIN_SAMPLES:
        try:
            arr = getattr(data, loader_name)()
        except Exception as exc:  # noqa: BLE001 - sample set is best-effort
            print(f"  skip  {stem}: {exc}")
            continue
        arr = np.asarray(arr)
        if arr.ndim == 3 and arr.shape[2] == 4:
            arr = arr[:, :, :3]
        if arr.ndim == 2:
            arr = np.dstack([arr] * 3)
        filename = f"{stem}.png"
        images.save(dest / filename, arr.astype(np.uint8))
        print(f"  ok    {filename}  {arr.shape[1]}x{arr.shape[0]}  ({category})")
        written.append((filename, category, has_subject))
    return written


def _fetch_picsum(dest: Path) -> list[tuple[str, str, bool]]:
    written = []
    w, h = PICSUM_SIZE
    for seed, stem in PICSUM_SEEDS:
        url = f"https://picsum.photos/seed/{seed}/{w}/{h}"
        filename = f"{stem}.jpg"
        target = dest / filename
        if target.exists():
            print(f"  have  {filename}  (cached)")
            written.append((filename, "unlabelled", False))
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pbn-pipeline/0.1"})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
                payload = resp.read()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            # Round-trip through the loader to confirm it actually decodes.
            arr = images.load(target)
            print(f"  ok    {filename}  {arr.shape[1]}x{arr.shape[0]}  (unlabelled, fetched)")
            written.append((filename, "unlabelled", False))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(f"  skip  {filename}: {exc}")
    return written


def build_dev_set(dest: str | Path, fetch: bool = True) -> list[tuple[str, str, bool]]:
    """Populate ``dest`` with the development image set. Returns (filename, category, subject)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    print("scikit-image built-ins:")
    written = _write_builtins(dest)

    if fetch:
        print("picsum.photos (high resolution):")
        written += _fetch_picsum(dest)
    else:
        print("skipping network fetch (--no-fetch)")

    subjects = sum(1 for _, _, has_subject in written if has_subject)
    print(f"\n{len(written)} images in {dest}  ({subjects} with a clear subject)")
    if subjects < 3:
        print(
            "NOTE: the dev set is thin on clear subjects, so subject-aware behaviour is\n"
            "      only lightly exercised here. The real corpus is what validates it."
        )
    return written
