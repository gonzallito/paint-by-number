"""Artifact and upload storage.

Filesystem-backed, behind a narrow interface so the same code can sit on object storage later.
Everything the service persists goes through here, which is also what makes the retention policy
enforceable in one place rather than scattered across handlers.

Layout::

    root/
      uploads/<job_id>.<ext>          the original photo
      artifacts/<job_id>/<variant>/   display-less artifact bundle
      jobs/<job_id>.json              job record

Deliberately *not* content-addressed on disk: users delete artworks, and a shared blob would make
"delete my photo" ambiguous. Deduplication happens at the job level instead (see jobs.py).
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Storage:
    root: Path

    def __post_init__(self) -> None:
        for directory in (self.uploads, self.artifacts, self.jobs):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def uploads(self) -> Path:
        return self.root / "uploads"

    @property
    def artifacts(self) -> Path:
        return self.root / "artifacts"

    @property
    def jobs(self) -> Path:
        return self.root / "jobs"

    # --- uploads ---------------------------------------------------------------------

    def upload_path(self, job_id: str, suffix: str) -> Path:
        return self.uploads / f"{job_id}{suffix}"

    def find_upload(self, job_id: str) -> Path | None:
        for path in self.uploads.glob(f"{job_id}.*"):
            return path
        return None

    def delete_upload(self, job_id: str) -> None:
        """Remove the original photo, keeping the artwork.

        Worth having separately from full deletion: once conversion succeeds the source photo is
        no longer needed, and holding people's family photos longer than necessary is a liability
        rather than a feature.
        """
        path = self.find_upload(job_id)
        if path is not None:
            path.unlink(missing_ok=True)

    # --- artifacts -------------------------------------------------------------------

    def artifact_dir(self, job_id: str, variant: str) -> Path:
        return self.artifacts / job_id / variant

    def artifact_file(self, job_id: str, variant: str, name: str) -> Path | None:
        # Explicit allow-list rather than sanitising: these are the only files a bundle contains,
        # so anything else is either a mistake or someone probing for traversal.
        if name not in {"regions.png", "meta.json", "display.png"}:
            return None
        path = self.artifact_dir(job_id, variant) / name
        return path if path.is_file() else None

    def artifact_bytes(self, job_id: str) -> int:
        directory = self.artifacts / job_id
        if not directory.is_dir():
            return 0
        return sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())

    # --- job records -----------------------------------------------------------------

    def job_path(self, job_id: str) -> Path:
        return self.jobs / f"{job_id}.json"

    def write_job(self, record: dict) -> None:
        path = self.job_path(record["id"])
        # Write-then-rename so a reader never observes a half-written record. Cheap here and the
        # habit matters more once this is a real queue with concurrent readers.
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(record, indent=2))
        temporary.replace(path)

    def read_job(self, job_id: str) -> dict | None:
        path = self.job_path(job_id)
        if not path.is_file():
            return None
        return json.loads(path.read_text())

    def all_jobs(self) -> list[dict]:
        records = []
        for path in self.jobs.glob("*.json"):
            try:
                records.append(json.loads(path.read_text()))
            except json.JSONDecodeError:
                continue
        records.sort(key=lambda record: record.get("created_at", 0), reverse=True)
        return records

    def find_by_digest(self, digest: str) -> dict | None:
        for record in self.all_jobs():
            if record.get("digest") == digest and record.get("status") != "failed":
                return record
        return None

    # --- deletion --------------------------------------------------------------------

    def delete_job(self, job_id: str) -> None:
        """Remove everything belonging to a job: photo, artifacts and record."""
        self.delete_upload(job_id)
        shutil.rmtree(self.artifacts / job_id, ignore_errors=True)
        self.job_path(job_id).unlink(missing_ok=True)

    def purge_older_than(self, seconds: float) -> list[str]:
        """Delete jobs past their retention window. Returns the ids removed.

        Retention is implemented rather than merely documented, because a policy nobody enforces
        is not a policy — and this service holds photographs of people's families.
        """
        cutoff = time.time() - seconds
        removed = []
        for record in self.all_jobs():
            if record.get("created_at", 0) < cutoff:
                self.delete_job(record["id"])
                removed.append(record["id"])
        return removed
