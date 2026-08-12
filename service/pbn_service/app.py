"""Conversion service HTTP API.

Shaped entirely by one constraint: conversion takes 20-110 seconds, so it cannot happen inside a
request. Every upload creates a job, the client polls it, and artifacts are fetched per variant.

Endpoints::

    POST   /v1/conversions                                   upload a photo, get a job
    GET    /v1/conversions/{id}                              poll status and progress
    GET    /v1/conversions/{id}/{variant}/{file}             fetch an artifact file
    DELETE /v1/conversions/{id}                              delete photo, artifacts and record
    GET    /v1/conversions                                   list jobs (development aid)
    POST   /v1/maintenance/purge                             enforce the retention window
    GET    /healthz
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from pbn_service.jobs import VARIANTS, JobRunner
from pbn_service.storage import Storage

# Reject oversized uploads before reading them into memory. 48MP phone photos land around 15-25MB,
# so this leaves headroom without inviting someone to post a gigabyte.
MAX_UPLOAD_BYTES = 40 * 1024 * 1024

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

# Retention default. Artifacts are the product and are kept; the source photo is already deleted as
# soon as conversion succeeds. This window bounds how long a *failed* job's photo can linger.
DEFAULT_RETENTION_DAYS = 30

_storage = Storage(Path(os.environ.get("PBN_STORAGE", ".data")).resolve())
_runner = JobRunner(_storage, workers=int(os.environ.get("PBN_WORKERS", "2")))


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    _runner.shutdown()


app = FastAPI(title="Paint by Number conversion service", version="1", lifespan=lifespan)


def _public(record: dict) -> dict:
    """Job record as clients should see it.

    The stored record carries a traceback on failure, which is useful in logs and has no business
    being sent to a phone.
    """
    return {
        "id": record["id"],
        "status": record["status"],
        "progress": _runner.progress(record),
        "created_at": record.get("created_at"),
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "variants": record.get("variants", {}),
        "error": record.get("error"),
    }


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "variants": list(VARIANTS)}


@app.post("/v1/conversions", status_code=202)
async def create_conversion(
    photo: UploadFile = File(...),
    deduplicate: bool = Query(
        default=True,
        description="Reuse an existing job when the same image has already been uploaded.",
    ),
) -> JSONResponse:
    if photo.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported content type {photo.content_type!r}",
        )

    data = await photo.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
        )

    record = _runner.submit(data, photo.filename or "upload.jpg", deduplicate=deduplicate)
    # 202 rather than 201: the artwork does not exist yet, only the promise of one.
    return JSONResponse(status_code=202, content=_public(record))


@app.get("/v1/conversions/{job_id}")
def get_conversion(job_id: str) -> dict:
    record = _storage.read_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="no such conversion")
    return _public(record)


@app.get("/v1/conversions")
def list_conversions(limit: int = Query(default=50, ge=1, le=500)) -> dict:
    records = _storage.all_jobs()[:limit]
    return {"conversions": [_public(record) for record in records]}


@app.get("/v1/conversions/{job_id}/{variant}/{filename}")
def get_artifact(job_id: str, variant: str, filename: str) -> FileResponse:
    if variant not in VARIANTS:
        raise HTTPException(status_code=404, detail=f"no such variant {variant!r}")

    path = _storage.artifact_file(job_id, variant, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="no such artifact file")

    # Artifacts are immutable once written, so they can be cached hard. That matters: a client
    # re-opening an artwork should never re-download its region map.
    return FileResponse(
        path,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.delete("/v1/conversions/{job_id}", status_code=204)
def delete_conversion(job_id: str) -> None:
    if _storage.read_job(job_id) is None:
        raise HTTPException(status_code=404, detail="no such conversion")
    _storage.delete_job(job_id)


@app.post("/v1/maintenance/purge")
def purge(
    retention_days: float = Query(default=DEFAULT_RETENTION_DAYS, gt=0),
) -> dict:
    """Delete jobs past the retention window.

    Exposed as an endpoint so a scheduler can call it, rather than relying on a background timer
    that silently stops when a worker restarts.
    """
    removed = _storage.purge_older_than(retention_days * 86400)
    return {"removed": removed, "count": len(removed)}
