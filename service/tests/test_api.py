"""End-to-end exercise of the conversion API.

Runs the app in-process via TestClient, so no server needs starting. Conversion is genuinely
executed — a mocked pipeline would test the plumbing and miss the thing most likely to break, which
is the pipeline and the API disagreeing about what an artifact contains.

Only one variant is produced here. Three would triple an already slow test for no extra coverage;
the per-variant loop is trivial and the same code path either way.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from pbn_service import app as app_module
from pbn_service import jobs as jobs_module

PHOTO = "../corpus/juve.png"
TIMEOUT_SECONDS = 300


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A client with isolated storage and a single-variant pipeline."""
    from pbn_service.storage import Storage

    storage = Storage(tmp_path)
    runner = jobs_module.JobRunner(storage, workers=1)
    monkeypatch.setattr(jobs_module, "VARIANTS", ("simple",))
    monkeypatch.setattr(app_module, "_storage", storage)
    monkeypatch.setattr(app_module, "_runner", runner)
    monkeypatch.setattr(app_module, "VARIANTS", ("simple",))
    with TestClient(app_module.app) as test_client:
        yield test_client
    runner.shutdown()


def _upload(client, path=PHOTO, content_type="image/jpeg"):
    with open(path, "rb") as handle:
        return client.post(
            "/v1/conversions",
            files={"photo": ("photo.jpg", handle.read(), content_type)},
        )


def _wait(client, job_id):
    deadline = time.time() + TIMEOUT_SECONDS
    while time.time() < deadline:
        body = client.get(f"/v1/conversions/{job_id}").json()
        if body["status"] in {"succeeded", "failed"}:
            return body
        time.sleep(1.0)
    raise AssertionError("conversion did not finish in time")


def test_healthz(client):
    assert client.get("/healthz").json()["ok"] is True


def test_rejects_non_image(client):
    response = _upload(client, content_type="application/pdf")
    assert response.status_code == 415


def test_rejects_empty_upload(client):
    response = client.post(
        "/v1/conversions",
        files={"photo": ("empty.jpg", b"", "image/jpeg")},
    )
    assert response.status_code == 400


def test_full_conversion_loop(client):
    created = _upload(client)
    # 202, not 201: the artwork does not exist yet, only the promise of one.
    assert created.status_code == 202
    job_id = created.json()["id"]
    assert created.json()["status"] == "queued"

    finished = _wait(client, job_id)
    assert finished["status"] == "succeeded", finished.get("error")
    assert finished["progress"] == 1.0

    summary = finished["variants"]["simple"]
    assert summary["regions"] > 100
    assert summary["colours"] > 10

    # The app derives outlines from the region map, so display.png must not be shipped.
    assert client.get(f"/v1/conversions/{job_id}/simple/display.png").status_code == 404

    meta_response = client.get(f"/v1/conversions/{job_id}/simple/meta.json")
    assert meta_response.status_code == 200
    assert "immutable" in meta_response.headers.get("cache-control", "")

    meta = json.loads(meta_response.content)
    assert meta["format_version"] == 2
    assert meta["counts"]["unlabelled"] == 0
    # Everything the canvas needs must be present, since the app has no other source for it.
    assert meta["regions_by_colour"]
    assert all("reveal_zoom" in region for region in meta["regions"][:5])

    regions = client.get(f"/v1/conversions/{job_id}/simple/regions.png")
    assert regions.status_code == 200
    assert regions.content[:8] == b"\x89PNG\r\n\x1a\n"

    # The source photo is deleted once artifacts exist; holding someone's photo longer than
    # necessary is a liability rather than a feature.
    assert app_module._storage.find_upload(job_id) is None


def test_deduplicates_identical_uploads(client):
    first = _upload(client).json()
    _wait(client, first["id"])
    second = _upload(client).json()
    # Re-uploading costs a minute of CPU for byte-identical output, and users retry often.
    assert second["id"] == first["id"]


def test_unknown_variant_and_file_are_rejected(client):
    created = _upload(client).json()
    _wait(client, created["id"])
    job_id = created["id"]
    assert client.get(f"/v1/conversions/{job_id}/nonsense/meta.json").status_code == 404
    # Only known filenames are served, so traversal attempts get the same flat refusal.
    assert client.get(f"/v1/conversions/{job_id}/simple/..%2Fmeta.json").status_code == 404


def test_delete_removes_everything(client):
    created = _upload(client).json()
    _wait(client, created["id"])
    job_id = created["id"]

    assert client.delete(f"/v1/conversions/{job_id}").status_code == 204
    assert client.get(f"/v1/conversions/{job_id}").status_code == 404
    assert app_module._storage.artifact_bytes(job_id) == 0


def test_purge_enforces_retention(client):
    created = _upload(client).json()
    _wait(client, created["id"])

    # Retention is implemented rather than merely documented: a policy nobody enforces is not one.
    purged = client.post("/v1/maintenance/purge", params={"retention_days": 1e-9}).json()
    assert created["id"] in purged["removed"]
    assert client.get(f"/v1/conversions/{created['id']}").status_code == 404
