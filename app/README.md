# Flutter app

Turns a photo into a paintable canvas. That conversion is the core feature, not a premium hook, so
the app opens on it.

## Running it

The app needs the conversion service running on your computer.

```bash
# terminal 1 — the service
cd service
uv sync
# Windows PowerShell:  $env:PBN_STORAGE=".data"
# macOS / Linux:       export PBN_STORAGE=.data
uv run uvicorn pbn_service.app:app --port 8000
```

```bash
# terminal 2 — the app
cd app
flutter pub get
flutter run                 # correctness, emulator is fine
flutter run --profile       # performance, physical device only
```

### Reaching the service

The app **finds the service itself**, probing `/healthz` on each candidate in turn and remembering
what answered. A status bar at the top of the library shows the result, so a connection problem is
visible before you pick a photo rather than after.

| running on | works via | you must |
|---|---|---|
| Android emulator | `http://10.0.2.2:8000` | nothing |
| **USB phone** | `http://localhost:8000` | **`adb reverse tcp:8000 tcp:8000`** |
| phone on same Wi-Fi | `http://<LAN-ip>:8000` | bind `--host 0.0.0.0`, set the address in-app |

There is no address that works everywhere, which is what made this a repeated dead end:

- An emulator reaches the host at `10.0.2.2` and **cannot** use `localhost` — inside the emulator
  that is the emulated device. `10.0.2.2` is an alias for the host loopback, so a service bound to
  `127.0.0.1` is fine.
- A **physical phone** can use neither. `10.0.2.2` is meaningless to it. Run
  `adb reverse tcp:8000 tcp:8000` over USB, which forwards the phone's `localhost:8000` to your
  computer; re-run it whenever the phone reconnects. Or use the LAN address, which nothing in the
  app can guess — set it from the toolbar button.

To pin an address at build time instead:

```bash
flutter run --dart-define=PBN_SERVICE_URL=http://192.168.1.20:8000
```

Cleartext HTTP is allowed in the **debug** manifest only, since Android blocks it from API 28 on and
the failure is otherwise an opaque connection error. Release builds keep it blocked.

## What it does

| | |
|---|---|
| Convert | pick from gallery or camera, upload, poll, download, open |
| Library | converted artworks persist on device and reopen with no network |
| Tap a region | fills it if it matches the selected colour, otherwise nothing happens |
| Pinch / drag | zoom and pan via `InteractiveViewer` |
| Numbers | appear only once zoom passes each region's `reveal_zoom` |
| Palette tray | horizontally scrolling, shows regions remaining per colour, dims when done |
| Selected colour | its unfilled regions get a grey/white checkerboard |

A wrong tap deliberately does nothing. Filling the wrong colour would be unrecoverable without undo,
and mis-taps are the most frequent interaction after correct ones.

The app polls for the **recommended** variant rather than for the whole job, and the service converts
that one first, so the wait is about a third of full conversion. The alternatives finish in the
background.

## Structure

| file | role |
|---|---|
| `lib/main.dart` | app shell |
| `lib/home_screen.dart` | library and conversion flow |
| `lib/service_client.dart` | upload, poll, download |
| `lib/library.dart` | on-device store of converted artworks |
| `lib/artwork_screen.dart` | canvas screen and the stats strip |
| `lib/artwork.dart` | loads a bundle, decodes the region-ID map, derives outlines and bounds, holds fill state |
| `lib/canvas_view.dart` | interactive canvas — layers, fills, highlight, zoom-revealed numbers |
| `lib/palette_tray.dart` | scrolling colour tray |

`Artwork.load` takes a `BundleSource`, so a downloaded artwork and the bundled sample open through
identical code — only byte access differs.

### Why a raster region map and not vectors

`regions.png` encodes each pixel's region index in its RGB value, so hit-testing a tap is a single
array lookup regardless of region count. Nothing here does polygon maths, which is why the pipeline
never needed to emit vectors.

Numbers are painted **outside** the transformed subtree, so they keep a constant on-screen size while
the artwork scales. That is what makes small regions numberable at all, and why the pipeline dropped
leader lines entirely.

Outlines are derived from the region map at load rather than from `display.png` — the shipped display
image has numbers baked in, which would fight the zoom reveal. The service therefore does not write
it at all, taking a bundle from 4.1MB to 760KB.

### Storage

Artworks live in the **documents** directory, not a cache directory: the OS evicts caches under
storage pressure, and these will hold progress on paintings that take 30 to 90 minutes.

A small `manifest.json` per artwork makes the library listable without touching the bundles, because
`meta.json` is around 385KB and parsing every one to draw a list would make the home screen slower
the more the user converts.

Downloads land in a `.partial` directory and are renamed on success, so an interrupted download
cannot leave a truncated `regions.png` that appears in the library and throws on every attempt to
open it.

## Performance

Measured and fixed:

| | before | after |
|---|---|---|
| `fill`, per tap | 174ms | **7ms** |
| `highlight`, per swatch tap | full-canvas decode | per-region patches |
| `load` | two passes over 4.3M pixels | one |

Filling re-uploaded the entire ~17MB canvas as a texture on every tap. It now uploads one small
patch per filled region and collapses to a full canvas only past 32 patches. The highlight had the
same problem, building a full-canvas image when a colour owns roughly 14 of 1,266 regions.

Both painters key off a `_revision` counter. The patch lists are mutated in place, so comparing them
meant comparing a list against itself — which length comparison masked until two colours happened to
own the same number of regions.

### Still unmeasured: the gate

**`over 16ms %` during sustained pinch-zoom on a physical device, in profile mode.**

An emulator runs on the host CPU and GPU, so it cannot answer this in either direction — a
"Pixel 6" emulator is a screen size and a system image, not a Pixel 6. An emulator reading of
`raster p50 40.9ms` says nothing about hardware. Never measure in debug mode either; it is
misleadingly slow.

Remaining suspects if raster time is high on real hardware:

- **Large texture draws.** Three full-canvas images per frame. The answer would be tiling.
- **Memory.** Region map ~8.6MB (Uint16, halved by assuming under 65,536 regions), fill buffer 17MB,
  plus full-canvas GPU textures. Expect ~100MB. If that is too much, the highlight can be generated
  at half resolution.

### What to report back

Tap `reset` first — the sample window otherwise includes startup, whose first frame is enormous and
drags every percentile with it. Then do one sustained interaction and read:

- `over 16ms %` — the gate
- build and raster, p50 and p95 separately (they have different fixes)
- `fill` and `highlight`
- load time, and peak memory from Android Studio's profiler
- device make and model

## Known gaps

- **Progress is not persisted.** Closing the app loses a session. Highest-priority gap.
- No undo, fill animation, haptics, or colour-complete detection.
- No thumbnails in the library, since `display.png` is not downloaded.
