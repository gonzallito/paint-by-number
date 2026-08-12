# Conversion service

Wraps the pipeline in an HTTP API. Its entire shape follows from one fact: **conversion takes
20-110 seconds**, so it cannot happen inside a request. Every upload becomes a job the client polls,
which is also why the app's upload flow is "send it and get told when it's ready" rather than a
spinner someone watches for two minutes.

## Running

```bash
cd service
uv sync
PBN_STORAGE=.data uv run uvicorn pbn_service.app:app --reload --port 8000
```

`uv run pytest` exercises the whole loop in-process, running genuine conversions — roughly 85
seconds. A mocked pipeline would test the plumbing and miss the thing most likely to break, which is
the pipeline and the API disagreeing about what an artifact contains.

## API

| | |
|---|---|
| `POST /v1/conversions` | upload a photo, returns **202** and a job |
| `GET /v1/conversions/{id}` | status and progress |
| `GET /v1/conversions/{id}/{variant}/{file}` | fetch `meta.json` or `regions.png` |
| `DELETE /v1/conversions/{id}` | remove photo, artifacts and record |
| `GET /v1/conversions` | list jobs (development aid) |
| `POST /v1/maintenance/purge` | enforce the retention window |
| `GET /healthz` | liveness |

202 rather than 201 on upload, because the artwork does not exist yet — only the promise of one.

## Decisions worth knowing

**`display.png` is not written.** The canvas prototype proved the app never reads it: outlines are
derived from the region map at load. Dropping it takes a bundle from 4.1MB to **760KB**, a 5.5x
saving in storage and egress per artwork. The endpoint returns 404 for it, and a test asserts that,
so it cannot quietly come back.

**Uploads are deleted as soon as conversion succeeds.** The artifacts are the product; the source
photo has no further use, and holding people's family photos longer than necessary is a liability
rather than a feature. The retention window therefore only bounds how long a *failed* job's photo
can linger.

**Retention is implemented, not just documented.** `POST /v1/maintenance/purge` is an endpoint so a
scheduler can drive it, rather than a background timer that silently stops when a worker restarts.

**Identical uploads reuse the existing job**, matched on content digest. Re-converting the same
photo costs a minute of CPU for byte-identical output, and people retry uploads far more often than
one would guess.

**Artifacts are served `immutable` with a one-year max-age.** They never change once written, and a
client re-opening an artwork should not re-download its region map.

**Per-variant progress is persisted as it completes**, so a polling client can start on the first
variant instead of waiting for all three.

**The segmentation extra is a hard dependency.** Without `rembg` the pipeline silently falls back to
whole-frame treatment and produces visibly worse artwork than the version that was reviewed and
accepted. Silent quality regressions are worse than missing dependencies.

## What this is not yet

**The worker is an in-process thread pool.** Fine for building and testing the API contract, and
deliberately simple. Production needs real workers (RQ or Celery) in separate processes: an
in-process pool dies with the web server, cannot scale past one machine, and shares CPU with request
handling. The API surface is identical either way, which is the point of keeping it behind
`JobRunner`.

**Storage is the local filesystem**, behind a narrow `Storage` interface so object storage can be
swapped in without touching handlers.

**There is no authentication.** Every endpoint is open, so this must not be exposed publicly as-is.
Device tokens are the intended next step.

**Nothing validates photo suitability.** The pipeline already measures subject presence and texture,
which is enough to warn someone before spending a minute converting a photo that will convert badly.
Worth adding before real users meet it.
