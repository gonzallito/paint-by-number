"""The artifact bundle: what the app actually consumes.

This is the single interface between pipeline and app, so changes here are breaking changes and
``ARTIFACT_FORMAT_VERSION`` must be bumped alongside them. Users will have artworks in progress
against older bundles, so old versions have to stay readable.

Three files:

``display.png``
    Outlines and numbers, for reference and for the finished-artwork preview.

``regions.png``
    The **region ID map** — each pixel's 24-bit RGB value is the index of the region that pixel
    belongs to. Tapping is then one pixel read: no point-in-polygon test, no spatial index, no
    geometry at all. This is why the pipeline never needed vectorisation.

``meta.json``
    Palette, per-region geometry, and a palette-to-regions index.

Two fields exist for behaviour the app needs but cannot cheaply derive:

* ``reveal_zoom`` — the zoom at which a region's number becomes legible. Numbers render at
  constant screen size, so small regions should have their numbers appear only as the user zooms
  in, rather than being crammed onto the first view.
* ``regions_by_colour`` — so selecting a colour can highlight all of its unfilled regions without
  scanning the whole ID map. With a 150-colour palette each colour owns few regions, which makes
  "where does colour 87 go?" genuinely hard and the highlight essential rather than decorative.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from pbn import ARTIFACT_FORMAT_VERSION, images

# Region ids are encoded across three 8-bit channels, so this is the ceiling. Region counts are
# in the hundreds, so the headroom is ample.
MAX_ENCODABLE_REGIONS = 256**3


def encode_region_map(labels: np.ndarray) -> np.ndarray:
    """Encode region ids into RGB. ``id = r + g*256 + b*65536``.

    Little-endian byte order by channel is deliberate: the low byte lands in red, so the common
    case of a few hundred regions leaves green and blue near zero, which compresses well.
    """
    if labels.size and int(labels.max()) >= MAX_ENCODABLE_REGIONS:
        raise ValueError(f"too many regions to encode: {int(labels.max()) + 1}")
    ids = labels.astype(np.uint32)
    return np.stack(
        [
            (ids & 0xFF).astype(np.uint8),
            ((ids >> 8) & 0xFF).astype(np.uint8),
            ((ids >> 16) & 0xFF).astype(np.uint8),
        ],
        axis=-1,
    )


def decode_region_map(rgb: np.ndarray) -> np.ndarray:
    """Inverse of :func:`encode_region_map`, for verification and tests."""
    values = rgb.astype(np.uint32)
    return (values[..., 0] | (values[..., 1] << 8) | (values[..., 2] << 16)).astype(np.int32)


def build_meta(conversion) -> dict:
    """Assemble ``meta.json`` content from a conversion."""
    numbering = conversion.numbering
    height, width = conversion.labels.shape
    region_colour = conversion.region_colour

    areas = np.bincount(conversion.labels.ravel(), minlength=conversion.n_regions)

    regions = []
    for index in range(conversion.n_regions):
        regions.append(
            {
                "id": index,
                # 1-based, matching what the user sees on the canvas and in the tray.
                "colour": int(region_colour[index]) + 1,
                "centroid": [int(numbering.centres[index][0]), int(numbering.centres[index][1])],
                "label": [
                    int(numbering.label_positions[index][0]),
                    int(numbering.label_positions[index][1]),
                ],
                "inscribed_radius": round(float(numbering.radii[index]), 2),
                "digit_height": round(float(numbering.digit_heights[index]), 2),
                "reveal_zoom": round(float(numbering.reveal_zoom[index]), 3),
                "leader": bool(numbering.has_leader[index]),
                "area": int(areas[index]),
            }
        )

    # Palette-to-regions index, 1-based to match the displayed numbers.
    by_colour: dict[str, list[int]] = {}
    for index in range(conversion.n_regions):
        by_colour.setdefault(str(int(region_colour[index]) + 1), []).append(index)

    palette = [
        {
            "number": position + 1,
            "rgb": [int(channel) for channel in conversion.palette_rgb[position]],
            "hex": "#{:02x}{:02x}{:02x}".format(
                *(int(c) for c in conversion.palette_rgb[position])
            ),
            "from_subject": bool(conversion.from_subject[position]),
            "region_count": len(by_colour.get(str(position + 1), [])),
        }
        for position in range(len(conversion.palette_rgb))
    ]

    return {
        "format_version": ARTIFACT_FORMAT_VERSION,
        "canvas": {"width": width, "height": height},
        "variant": {
            "name": conversion.variant.name,
            "offered_colours": conversion.variant.n_colours,
            "requested_colours": conversion.requested_colours,
            "region_area_scale": conversion.variant.region_area_scale,
            "target_regions": conversion.target_regions,
            "radius_floor": round(conversion.radius_floor, 3),
        },
        "counts": {
            "regions": conversion.n_regions,
            "colours": len(palette),
            "leaders": int(numbering.has_leader.sum()),
            "unlabelled": int((~numbering.fits).sum()),
        },
        # Ordered light to dark, which is how the tray presents it.
        "palette": palette,
        "regions": regions,
        "regions_by_colour": by_colour,
        "diagnostics": {
            "subject_coverage": conversion.subject_coverage,
            "background_simplify": round(conversion.background_simplify, 3),
            "texture": round(conversion.texture, 1),
            "faces_detected": conversion.face_count,
        },
    }


def write_bundle(conversion, directory: str | Path, display: np.ndarray) -> Path:
    """Write ``display.png``, ``regions.png`` and ``meta.json`` into ``directory``."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    images.save(directory / "display.png", display)
    images.save(directory / "regions.png", encode_region_map(conversion.labels))
    (directory / "meta.json").write_text(json.dumps(build_meta(conversion), indent=2))
    return directory
