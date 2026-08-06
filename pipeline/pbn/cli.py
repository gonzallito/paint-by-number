"""Command line entry point for the pipeline."""

from __future__ import annotations

import argparse
import importlib
import sys

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

    args = parser.parse_args()
    if args.command == "doctor":
        return doctor()
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
