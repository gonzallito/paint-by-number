"""Content build: source art in, publishable canvas artifacts out.

This is the studio half of the project. Player photos are converted on demand by the service; the
daily, story and library canvases are converted *here*, reviewed by a person, and published as
finished artifacts. That is how the genre works, and the reasons are practical: every player gets a
byte-identical canvas so a QA pass means something, a bad conversion is rejected before anyone sees
it, an old phone does not get a worse canvas, and a region can be hand-corrected without shipping
an app update.

Layout::

    content/
      sources/
        whispering-woods/          <- collection
          cottage-at-dusk/         <- artwork id
            source.png             <- AI-generated colour illustration
            artwork.toml           <- optional metadata
      build/                       <- artifacts, one directory per artwork
      manifest.json                <- static index for the CDN
      report.html                  <- open in a browser to review
      report.json

Run::

    uv run pbn build --sources ../content/sources --out ../content

Rebuilds are skipped when the source bytes, the profile and CONVERSION_VERSION all match what was
built before. That is what makes a thousand-canvas library practical, and it is also the "pin"
behaviour curated content needs: a published artifact is not silently replaced because the pipeline
changed. Use ``--force`` to deliberately reconvert, then re-review.
"""

from __future__ import annotations

import hashlib
import json
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from pbn import ARTIFACT_FORMAT_VERSION, CONVERSION_VERSION, artifact, images, profiles

SIDECAR = "artwork.toml"

# Written inside each artifact directory so a rebuild can tell whether anything actually changed.
STAMP = "build.json"


@dataclass
class Source:
    """One piece of source art and the metadata that travels with it."""

    id: str
    image: Path
    profile: str
    title: str = ""
    collection: str = ""
    tags: list[str] = field(default_factory=list)
    credit: str = ""

    @property
    def display_title(self) -> str:
        # A filename is a poor title but an honest default, and better than "Artwork 7".
        return self.title or self.id.replace("-", " ").replace("_", " ").title()


@dataclass
class Result:
    """What happened to one source in this build."""

    source: Source
    status: str  # "built" | "skipped" | "rejected" | "error"
    report: profiles.GateReport | None = None
    seconds: float = 0.0
    message: str = ""
    fingerprint: str = ""


def _fingerprint(image: Path, profile_name: str) -> str:
    """Identity of a *built artifact*: the art, the recipe, and the algorithm.

    CONVERSION_VERSION belongs in here. Without it, improving the pipeline leaves every previously
    built canvas stale with nothing to detect it.
    """
    digest = hashlib.sha256()
    digest.update(image.read_bytes())
    digest.update(profile_name.encode())
    digest.update(str(CONVERSION_VERSION).encode())
    return digest.hexdigest()[:16]


def _output_hash(conversion) -> str:
    """Hash of the canvas itself: which pixel belongs to which region, and its colour."""
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(conversion.labels).tobytes())
    digest.update(np.ascontiguousarray(conversion.region_colour).tobytes())
    return digest.hexdigest()[:16]


def discover(root: str | Path, default_profile: str = profiles.DEFAULT_PROFILE) -> list[Source]:
    """Find every artwork under ``root``.

    An artwork is any directory holding exactly one image with a supported suffix. The collection is
    the path from ``root`` down to that directory's parent, so nesting is free-form.
    """
    root = Path(root)
    found: list[Source] = []
    for directory in sorted(p for p in root.rglob("*") if p.is_dir()):
        candidates = [
            p
            for p in sorted(directory.iterdir())
            if p.is_file() and p.suffix.lower() in images.SUPPORTED_SUFFIXES
        ]
        if not candidates:
            continue
        if len(candidates) > 1:
            raise ValueError(
                f"{directory} holds {len(candidates)} images; an artwork directory must hold one"
            )

        meta: dict = {}
        sidecar = directory / SIDECAR
        if sidecar.is_file():
            meta = tomllib.loads(sidecar.read_text())

        relative = directory.relative_to(root)
        profile_name = str(meta.get("profile", default_profile))
        if profile_name not in profiles.PROFILES:
            raise ValueError(
                f"{sidecar}: unknown profile {profile_name!r}; "
                f"choose from {', '.join(sorted(profiles.PROFILES))}"
            )

        found.append(
            Source(
                id=str(meta.get("id", directory.name)),
                image=candidates[0],
                profile=profile_name,
                title=str(meta.get("title", "")),
                collection=str(meta.get("collection", str(relative.parent).replace(".", ""))),
                tags=[str(t) for t in meta.get("tags", [])],
                credit=str(meta.get("credit", "")),
            )
        )

    ids = [s.id for s in found]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate artwork ids: {', '.join(sorted(duplicates))}")
    return found


def build_one(source: Source, out_root: Path, force: bool = False) -> Result:
    """Convert, grade, and publish one artwork."""
    directory = out_root / source.id
    fingerprint = _fingerprint(source.image, source.profile)

    stamp = directory / STAMP
    if not force and stamp.is_file():
        try:
            previous = json.loads(stamp.read_text())
            if previous.get("fingerprint") == fingerprint:
                return Result(source, "skipped", seconds=0.0, fingerprint=fingerprint)
        except json.JSONDecodeError:
            pass  # unreadable stamp means rebuild

    profile = profiles.PROFILES[source.profile]
    started = time.perf_counter()
    try:
        img = images.load(source.image)
        conversion, report = profiles.convert_with_profile(img, profile)
    except Exception as error:  # noqa: BLE001 - one bad source must not stop the batch
        return Result(
            source,
            "error",
            seconds=time.perf_counter() - started,
            message=f"{type(error).__name__}: {error}",
            fingerprint=fingerprint,
        )
    elapsed = time.perf_counter() - started

    if not report.passed:
        # Deliberately still written, so the review page can show *why* it failed. Publishing reads
        # the manifest, not the directory, so a rejected artifact is never served.
        directory.mkdir(parents=True, exist_ok=True)
        artifact.write_preview(conversion, directory)
        return Result(source, "rejected", report=report, seconds=elapsed, fingerprint=fingerprint)

    # Reproducibility check. The whole skip mechanism rests on identical inputs producing an
    # identical canvas, so a rebuild that contradicts that must be loud rather than silent — it
    # means published artwork and freshly built artwork have quietly diverged.
    output = _output_hash(conversion)
    drift = ""
    if stamp.is_file():
        try:
            previous = json.loads(stamp.read_text())
            if previous.get("fingerprint") == fingerprint and previous.get("output") not in (
                None,
                output,
            ):
                drift = (
                    f"NOT REPRODUCIBLE: identical source, profile and conversion version "
                    f"produced a different canvas ({previous['output']} -> {output})"
                )
        except json.JSONDecodeError:
            pass

    directory.mkdir(parents=True, exist_ok=True)
    images.save(directory / "regions.png", artifact.encode_region_map(conversion.labels))
    (directory / "meta.json").write_text(json.dumps(artifact.build_meta(conversion), indent=2))
    artifact.write_preview(conversion, directory)
    stamp.write_text(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "output": output,
                "profile": source.profile,
                "conversion_version": CONVERSION_VERSION,
                "format_version": ARTIFACT_FORMAT_VERSION,
                "built_at": time.time(),
            },
            indent=2,
        )
    )
    return Result(
        source,
        "built",
        report=report,
        seconds=elapsed,
        message=drift,
        fingerprint=fingerprint,
    )


def _manifest_entry(source: Source, out_root: Path, fingerprint: str) -> dict:
    """One manifest row, read back from what was actually written.

    Counts come from the artifact's own meta.json rather than from a gate report, so the manifest
    describes the published file even when this run only skipped it.
    """
    profile = profiles.PROFILES[source.profile]
    directory = out_root / source.id
    meta = json.loads((directory / "meta.json").read_text())
    counts = meta.get("counts", {})
    return {
        "id": source.id,
        "title": source.display_title,
        "collection": source.collection,
        "tags": source.tags,
        "credit": source.credit,
        "profile": source.profile,
        "zoomable": profile.zoomable,
        "regions": counts.get("regions"),
        "colours": counts.get("colours"),
        "canvas": meta.get("canvas"),
        "files": {
            "regions": f"{source.id}/regions.png",
            "meta": f"{source.id}/meta.json",
            "preview": f"{source.id}/preview.webp",
        },
        "bytes": {
            name: (directory / name).stat().st_size
            for name in ("regions.png", "meta.json", "preview.webp")
            if (directory / name).is_file()
        },
        "conversion_version": CONVERSION_VERSION,
        "format_version": ARTIFACT_FORMAT_VERSION,
        "fingerprint": fingerprint,
    }


def write_manifest(sources: list[Source], out_root: Path) -> Path:
    """Static index of everything publishable.

    A file on the CDN rather than an API response: it is identical for every player, changes only
    when content changes, and caches at the edge forever. An endpoint that computes this per request
    would be pure cost.

    Built from **every known source and what is on disk**, never from one run's results. Deriving it
    from the results of a filtered run empties it: ``--only busy-photo`` took a six-artwork manifest
    to zero, which in production would unpublish the whole library to rebuild one piece.

    A source that now fails its gate does not lose its existing artifact. Un-publishing live
    content because someone edited a source file is the more damaging mistake; the report says it
    failed, and the previous build keeps serving until it is deliberately replaced.
    """
    entries = []
    for source in sources:
        directory = out_root / source.id
        if not (directory / "meta.json").is_file() or not (directory / STAMP).is_file():
            continue
        try:
            stamp = json.loads((directory / STAMP).read_text())
        except json.JSONDecodeError:
            continue
        entries.append(_manifest_entry(source, out_root, stamp.get("fingerprint", "")))

    path = out_root / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": time.time(),
                "conversion_version": CONVERSION_VERSION,
                "format_version": ARTIFACT_FORMAT_VERSION,
                "count": len(entries),
                "artworks": entries,
            },
            indent=2,
        )
    )
    return path


def write_report(results: list[Result], out_root: Path) -> tuple[Path, Path]:
    """A machine-readable report and a page a person can actually review.

    The HTML exists because the gate can only check what is measurable. Nothing automatic can tell
    whether a canvas is *pleasant* to paint, so the last step is always a human looking at
    thumbnails — and looking at 200 of them needs to take a minute, not an hour.
    """
    payload = {
        "generated_at": time.time(),
        "conversion_version": CONVERSION_VERSION,
        "results": [
            {
                "id": r.source.id,
                "collection": r.source.collection,
                "profile": r.source.profile,
                "status": r.status,
                "seconds": round(r.seconds, 1),
                "message": r.message,
                "failures": r.report.failures if r.report else [],
                "metrics": r.report.metrics if r.report else {},
            }
            for r in results
        ],
    }
    json_path = out_root / "report.json"
    json_path.write_text(json.dumps(payload, indent=2))

    cards = []
    for r in sorted(
        results, key=lambda r: (r.status != "rejected", r.source.collection, r.source.id)
    ):
        metrics = r.report.metrics if r.report else {}
        preview = f"build/{r.source.id}/preview.webp"
        colour = {
            "built": "#6BDF8A",
            "skipped": "#8A8A94",
            "rejected": "#FF6B7A",
            "error": "#FF6B7A",
        }[r.status]
        detail = ""
        if r.report and r.report.failures:
            detail = "<br>".join(f"&#9888; {f}" for f in r.report.failures)
        elif r.message:
            detail = f"&#9888; {r.message}"
        cards.append(
            f"""<div class="card">
  <img src="{preview}" loading="lazy" alt="{r.source.id}">
  <div class="body">
    <div class="title">{r.source.display_title}</div>
    <div class="meta">{r.source.collection or "-"} &middot; {r.source.profile}</div>
    <div class="status" style="color:{colour}">{r.status.upper()}</div>
    <div class="metrics">{metrics.get("regions", "-")} regions &middot;
      {metrics.get("colours", "-")} colours &middot;
      min tap {metrics.get("min_tap_radius_px", 0):.0f}px</div>
    <div class="fail">{detail}</div>
  </div>
</div>"""
        )

    counts = {
        s: sum(1 for r in results if r.status == s)
        for s in ("built", "skipped", "rejected", "error")
    }
    html_path = out_root / "report.html"
    html_path.write_text(
        f"""<!doctype html>
<meta charset="utf-8">
<title>Content build review</title>
<style>
  body {{ background:#101012; color:#E8E8EE; font:14px/1.4 system-ui, sans-serif; margin:24px; }}
  h1 {{ font-size:18px; font-weight:600; }}
  .summary {{ color:#8A8A94; margin-bottom:20px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:16px; }}
  .card {{ background:#17171A; border-radius:10px; overflow:hidden; }}
  .card img {{ width:100%; display:block; background:#000; }}
  .body {{ padding:10px 12px 12px; }}
  .title {{ font-weight:600; margin-bottom:2px; }}
  .meta, .metrics {{ color:#8A8A94; font-size:12px; }}
  .status {{ font-size:11px; font-weight:700; letter-spacing:.06em; margin:6px 0 4px; }}
  .fail {{ color:#FFC9CF; font-size:12px; margin-top:6px; }}
</style>
<h1>Content build review</h1>
<div class="summary">
  {counts["built"]} built &middot; {counts["skipped"]} unchanged &middot;
  {counts["rejected"]} rejected &middot; {counts["error"]} errored
  &mdash; conversion version {CONVERSION_VERSION}
</div>
<div class="grid">
{chr(10).join(cards)}
</div>
"""
    )
    return json_path, html_path


def build(
    sources_root: str | Path,
    out_root: str | Path,
    default_profile: str = profiles.DEFAULT_PROFILE,
    force: bool = False,
    only: str | None = None,
) -> list[Result]:
    """Convert every source, grade it, publish what passes, and write the review artefacts."""
    all_sources = discover(sources_root, default_profile)
    sources = all_sources
    if only:
        sources = [s for s in all_sources if only in s.id or only in s.collection]
    if not sources:
        print(f"no artwork found under {sources_root}")
        return []

    out_root = Path(out_root)
    build_root = out_root / "build"
    build_root.mkdir(parents=True, exist_ok=True)

    results: list[Result] = []
    for index, source in enumerate(sources, start=1):
        result = build_one(source, build_root, force=force)
        results.append(result)
        note = ""
        if result.report and result.report.failures:
            note = "  " + "; ".join(result.report.failures)
        elif result.message:
            note = "  " + result.message
        print(
            f"[{index:4d}/{len(sources)}] {result.status:8s} {source.profile:15s} "
            f"{source.id:32s} {result.seconds:5.1f}s{note}"
        )

    # Every source, not just this run's, or a filtered build empties the index.
    write_manifest(all_sources, build_root)

    # The review page covers the whole library too. Its job is to let someone eyeball everything
    # quickly, and a page showing only the one artwork a filtered run touched cannot do that.
    touched = {r.source.id for r in results}
    untouched = [
        Result(source=s, status="skipped", fingerprint="")
        for s in all_sources
        if s.id not in touched and (build_root / s.id / "meta.json").is_file()
    ]
    write_report(results + untouched, out_root)

    counts = {
        s: sum(1 for r in results if r.status == s)
        for s in ("built", "skipped", "rejected", "error")
    }
    total = sum(r.seconds for r in results)
    print(
        f"\n{counts['built']} built, {counts['skipped']} unchanged, "
        f"{counts['rejected']} rejected, {counts['error']} errored in {total:.0f}s"
    )
    print(f"review: {out_root / 'report.html'}")
    return results
