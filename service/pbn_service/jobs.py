"""Conversion jobs.

Conversion takes 20-110 seconds, which is the single fact that shapes this whole module. It cannot
happen inside a request, so every upload becomes a job the client polls. That in turn is what makes
the app's upload flow "send it and get told when it's ready" rather than a spinner.

The runner here is an in-process thread pool: enough to build and test the API contract, and
deliberately simple. **Production needs real workers** (RQ or Celery) in separate processes, because
an in-process pool dies with the web server, cannot scale beyond one machine, and shares a CPU with
request handling. The API surface is the same either way, which is the point of keeping the runner
behind this interface.
"""

from __future__ import annotations

import hashlib
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pbn import artifact, images, pipeline, render

from pbn_service.storage import Storage

Status = Literal["queued", "running", "succeeded", "failed"]

# Conversion is CPU-bound, so more workers than cores makes every job slower without finishing any
# sooner. Kept low deliberately; a real deployment scales by adding worker processes, not threads.
DEFAULT_WORKERS = 2

# Variants produced per upload. All three are generated so the user picks, which turns an imperfect
# conversion from a gamble into a choice they own.
VARIANTS = pipeline.DEFAULT_VARIANTS

# Conversion order, recommended variant FIRST.
#
# This is a user-visible latency decision, not tidying. Each variant costs roughly a third of the
# job, and the client opens the recommended one — so producing it last made every user wait for two
# variants they were not about to paint. Recommended-first lets the app open the artwork after about
# a third of the total wait, while the alternatives finish in the background.
CONVERSION_ORDER = tuple(
    sorted(VARIANTS, key=lambda name: name != pipeline.RECOMMENDED_VARIANT)
)

# display.png is NOT written. The canvas prototype proved the app never reads it — it derives
# outlines from the region map at load — and dropping it takes a bundle from 4.1MB to 760KB, a 5.5x
# saving in storage and download per artwork.
WRITE_DISPLAY_IMAGE = False


@dataclass
class JobRunner:
    """Owns the worker pool and the lifecycle of every conversion."""

    storage: Storage
    workers: int = DEFAULT_WORKERS

    def __post_init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="convert")

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # --- submission ------------------------------------------------------------------

    def submit(self, data: bytes, filename: str, deduplicate: bool = True) -> dict:
        """Store an upload and queue its conversion. Returns the job record.

        Identical uploads reuse the existing job by content digest. Re-converting the same photo
        costs a minute of CPU and produces byte-identical output, and users retry uploads far more
        often than one would guess.
        """
        digest = hashlib.sha256(data).hexdigest()

        if deduplicate:
            existing = self.storage.find_by_digest(digest)
            if existing is not None:
                return existing

        job_id = uuid.uuid4().hex[:16]
        suffix = Path(filename).suffix.lower() or ".jpg"
        upload = self.storage.upload_path(job_id, suffix)
        upload.write_bytes(data)

        record = {
            "id": job_id,
            "status": "queued",
            "digest": digest,
            "original_filename": filename,
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "variants": {},
            "error": None,
        }
        self.storage.write_job(record)
        self._pool.submit(self._run, job_id)
        return record

    # --- execution -------------------------------------------------------------------

    def _run(self, job_id: str) -> None:
        record = self.storage.read_job(job_id)
        if record is None:
            return

        record["status"] = "running"
        record["started_at"] = time.time()
        self.storage.write_job(record)

        try:
            upload = self.storage.find_upload(job_id)
            if upload is None:
                raise FileNotFoundError("upload missing")

            source = images.load(upload)
            for name in CONVERSION_ORDER:
                variant = pipeline.VARIANTS[name]
                started = time.perf_counter()
                conversion = pipeline.convert(source, variant)

                directory = self.storage.artifact_dir(job_id, name)
                display = (
                    render.outline_canvas(
                        conversion.labels, conversion.numbering, conversion.region_colour
                    )
                    if WRITE_DISPLAY_IMAGE
                    # A 1x1 placeholder keeps write_bundle's signature honest without paying for
                    # a 3.4MB image the client never reads.
                    else conversion.working[:1, :1]
                )
                artifact.write_bundle(conversion, directory, display=display)
                if not WRITE_DISPLAY_IMAGE:
                    (directory / "display.png").unlink(missing_ok=True)

                record["variants"][name] = {
                    "regions": conversion.n_regions,
                    "colours": conversion.n_colours,
                    "recommended": name == pipeline.RECOMMENDED_VARIANT,
                    "seconds": round(time.perf_counter() - started, 1),
                    "bytes": sum(p.stat().st_size for p in directory.iterdir() if p.is_file()),
                }
                # Persisted per variant rather than at the end, so a client polling mid-conversion
                # can start on the first variant instead of waiting for all three.
                self.storage.write_job(record)

            record["status"] = "succeeded"
            # The photo has served its purpose once artifacts exist. Keeping it would mean holding
            # someone's family photo indefinitely for no benefit.
            self.storage.delete_upload(job_id)

        except Exception as error:  # noqa: BLE001 - a failed job must be reported, not raised
            record["status"] = "failed"
            record["error"] = f"{type(error).__name__}: {error}"
            record["traceback"] = traceback.format_exc(limit=6)

        finally:
            record["finished_at"] = time.time()
            self.storage.write_job(record)

    # --- reporting -------------------------------------------------------------------

    def progress(self, record: dict) -> float:
        """Rough completion fraction, for a progress indicator during the wait."""
        if record["status"] == "succeeded":
            return 1.0
        if record["status"] in {"queued", "failed"}:
            return 0.0
        return len(record.get("variants", {})) / max(len(VARIANTS), 1)
