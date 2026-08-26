"""Command line entry point for the pipeline."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from pbn.pipeline import DEFAULT_VARIANTS

# (import name, pyproject name, required?)
_DEPS = [
    ("numpy", "numpy", True),
    ("cv2", "opencv-python-headless", True),
    ("skimage", "scikit-image", True),
    ("sklearn", "scikit-learn", True),
    ("scipy", "scipy", True),
    ("PIL", "pillow", True),
    ("matplotlib", "matplotlib", True),
    ("rembg", "rembg (extra: segmentation)", False),
]


def doctor() -> int:
    """Verify the toolchain is importable and report versions."""
    print(f"python {sys.version.split()[0]}")
    missing_required = []

    for import_name, dist_name, required in _DEPS:
        try:
            mod = importlib.import_module(import_name)
            version = getattr(mod, "__version__", "unknown")
            print(f"  ok       {dist_name} {version}")
        except ImportError:
            if required:
                missing_required.append(dist_name)
                print(f"  MISSING  {dist_name}")
            else:
                print(f"  absent   {dist_name}  (optional)")

    if missing_required:
        print(f"\n{len(missing_required)} required dependency/ies missing. Run: uv sync")
        return 1

    print("\ntoolchain ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="pbn", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="verify the toolchain is installed correctly")

    p_fetch = sub.add_parser("fetch", help="assemble the development image set")
    p_fetch.add_argument("--dest", default="../corpus/dev", help="output directory")
    p_fetch.add_argument(
        "--no-fetch", action="store_true", help="use bundled samples only, no network"
    )

    p_convert = sub.add_parser("convert", help="convert images and write contact sheets")
    p_convert.add_argument("--input", default="../corpus/dev", help="input image directory")
    p_convert.add_argument("--out", default="../out", help="directory for contact sheets")
    p_convert.add_argument(
        "--variants",
        default=",".join(DEFAULT_VARIANTS),
        help="comma-separated detail levels to render",
    )
    p_convert.add_argument("--cache", default=".cache/subject", help="subject-mask cache directory")
    p_convert.add_argument(
        "--stylise",
        action="store_true",
        help="remove thin structures (hair strands, weave) before converting",
    )
    p_convert.add_argument(
        "--artifacts",
        default=None,
        help="also write artifact bundles (display.png, regions.png, meta.json) here",
    )

    p_build = sub.add_parser(
        "build", help="convert curated source art into publishable canvas artifacts"
    )
    p_build.add_argument("--sources", default="../content/sources", help="source art directory")
    p_build.add_argument("--out", default="../content", help="where artifacts and reports go")
    p_build.add_argument(
        "--profile",
        default=None,
        help="profile for sources with no artwork.toml (default: library-medium)",
    )
    p_build.add_argument(
        "--force", action="store_true", help="reconvert even when nothing has changed"
    )
    p_build.add_argument("--only", default=None, help="build ids or collections matching this")

    sub.add_parser("profiles", help="list content profiles and their acceptance criteria")

    args = parser.parse_args()

    if args.command == "doctor":
        return doctor()

    if args.command == "fetch":
        from pbn.testdata import build_dev_set

        build_dev_set(args.dest, fetch=not args.no_fetch)
        return 0

    if args.command == "convert":
        return convert_command(
            input_dir=args.input,
            out_dir=args.out,
            variant_names=tuple(v.strip() for v in args.variants.split(",") if v.strip()),
            cache_dir=args.cache,
            artifact_dir=args.artifacts,
            stylise_input=args.stylise,
        )

    if args.command == "profiles":
        from pbn import profiles

        print(f"{'profile':16s} {'regions':>8s} {'colours':>8s} {'canvas':>7s} {'zoom':>5s}  gate")
        for name, profile in profiles.PROFILES.items():
            gate = (
                f"{profile.min_regions}-{profile.max_regions} regions, "
                f">={profile.min_colours} colours"
            )
            if not profile.zoomable:
                gate += (
                    f", every region >={profile.min_tap_radius_px:.0f}px at "
                    f"{profile.display_size[0]}x{profile.display_size[1]}"
                )
            print(
                f"{name:16s} {profile.target_regions:8d} {profile.n_colours:8d} "
                f"{profile.canvas_long_edge:7d} {'yes' if profile.zoomable else 'NO':>5s}  {gate}"
            )
            print(f"{'':16s} {profile.description}")
        return 0

    if args.command == "build":
        from pbn import build as build_module
        from pbn import profiles

        results = build_module.build(
            sources_root=args.sources,
            out_root=args.out,
            default_profile=args.profile or profiles.DEFAULT_PROFILE,
            force=args.force,
            only=args.only,
        )
        failed = sum(1 for r in results if r.status in {"rejected", "error"})
        return 1 if failed else 0

    parser.error(f"unknown command: {args.command}")
    return 2


def convert_command(
    input_dir: str,
    out_dir: str,
    variant_names: tuple[str, ...],
    cache_dir: str,
    artifact_dir: str | None = None,
    stylise_input: bool = False,
) -> int:
    """Convert every image in ``input_dir`` and write one contact sheet per image."""
    import time

    from pbn import artifact, contact, images, pipeline, render

    paths = images.list_images(input_dir)
    if not paths:
        print(f"no images found in {input_dir}")
        return 1

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    print(f"{len(paths)} images x {len(variant_names)} variants -> {out}\n")
    print(
        f"{'image':22s} {'variant':10s} {'regions':>8s} {'colours':>8s} {'unnum':>7s} {'time':>7s}"
    )
    print("-" * 70)

    summary = []
    started = time.perf_counter()
    for path in paths:
        img = images.load(path)
        conversions = pipeline.convert_all(
            img, variant_names, subject_cache=cache_dir, stylise_input=stylise_input
        )
        panels = []
        for conversion in conversions:
            elapsed = sum(conversion.timings.values())
            print(
                f"{path.stem:22s} {conversion.variant.name:10s} {conversion.n_regions:8,d} "
                f"{conversion.n_colours:8d} {conversion.unlabelled_fraction:6.1%} {elapsed:6.1f}s"
            )
            summary.append((path.stem, conversion))
            if artifact_dir is not None:
                artifact.write_bundle(
                    conversion,
                    Path(artifact_dir) / path.stem / conversion.variant.name,
                    display=render.outline_canvas(
                        conversion.labels, conversion.numbering, conversion.region_colour
                    ),
                )
            panels.append(
                contact.build_row(
                    original=conversion.working,
                    subject_mask=conversion.subject_mask,
                    labels=conversion.labels,
                    region_colour=conversion.region_colour,
                    palette_rgb=conversion.palette_rgb,
                    numbering=conversion.numbering,
                    title=f"{path.stem}\n{conversion.variant.name}",
                    caption=conversion.caption(),
                    from_subject=conversion.from_subject,
                    face_mask=conversion.face_mask,
                )
            )
        contact.write_sheet(panels, out / f"{path.stem}.png")

    total = time.perf_counter() - started
    print("-" * 70)
    regions = [c.n_regions for _, c in summary]
    unnumbered = [c.unlabelled_fraction for _, c in summary]
    print(
        f"{len(summary)} conversions in {total:.1f}s "
        f"({total / max(len(summary), 1):.1f}s each)\n"
        f"regions    min {min(regions):,}  median {int(sorted(regions)[len(regions) // 2]):,}  "
        f"max {max(regions):,}\n"
        f"unnumbered mean {sum(unnumbered) / len(unnumbered):.1%}  max {max(unnumbered):.1%}"
    )
    blocked = [name for name, c in summary if c.merges_blocked]
    if blocked:
        print(f"constraints unsatisfied on: {', '.join(sorted(set(blocked)))}")
    print(f"\ncontact sheets written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
