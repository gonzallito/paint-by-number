# Flutter app

Phase 2: canvas prototype. Its single purpose is to answer one question with numbers —
**does the colouring canvas hold 60fps on a low-end physical Android device?** — because that is
the largest unvalidated risk in the project and no amount of pipeline work discharges it.

## Running it

```bash
cd app
flutter pub get
flutter run                 # correctness, emulator is fine
flutter run --profile       # performance, physical device only
```

An emulator runs on the host CPU and GPU, so it **cannot** answer the performance question in
either direction — a "Pixel 6" emulator is a screen size and a system image, not a Pixel 6. Use it
to confirm behaviour, and a real device for the gate.

Never measure in debug mode; it is misleadingly slow.

## What it does

| | |
|---|---|
| Tap a region | fills it if it matches the selected colour, otherwise nothing happens |
| Pinch / drag | zoom and pan via `InteractiveViewer` |
| Numbers | appear only once zoom passes each region's `reveal_zoom` |
| Palette tray | horizontally scrolling, shows regions remaining per colour, dims when done |
| Selected colour | its unfilled regions get a grey/white checkerboard |

A wrong tap deliberately does nothing. Filling the wrong colour would be unrecoverable without
undo, and mis-taps are the most frequent interaction after correct ones.

## Structure

| file | role |
|---|---|
| `lib/artwork.dart` | loads the artifact bundle, decodes the region-ID map, derives outlines and per-region bounds, holds fill state |
| `lib/canvas_view.dart` | interactive canvas — layers, fills, highlight, zoom-revealed numbers |
| `lib/palette_tray.dart` | scrolling colour tray |
| `lib/main.dart` | app shell and the on-screen stats strip |

Numbers are painted **outside** the transformed subtree, so they keep a constant on-screen size
while the artwork scales. That is what makes small regions numberable at all, and why the pipeline
was able to drop leader lines entirely.

Outlines are derived from the region map at load rather than loaded from `display.png`, because the
shipped display image has numbers baked in, which would fight the zoom reveal. It also tests whether
`display.png` needs shipping at all — it is 3.4MB of a 4.1MB bundle.

## The stats strip

Reports live: regions filled, palette size, load time, current zoom, numbers currently drawn, last
fill and highlight times, worst frame build and raster times, and the percentage of recent frames
over 16ms. **That last figure is the gate.**

## Known concerns to measure, not assume

These are the specific things this prototype exists to find out. All are deliberate prototype
choices with a known better alternative if the numbers demand it.

**Fill cost.** A fill rewrites only the region's bounding box, but then re-uploads the whole
1800x2400 RGBA buffer as a new texture. That is ~17MB per tap. If `fill Nms` is bad, the fix is to
composite small per-region images and periodically collapse them into the full buffer.

**Memory.** Region map ~8.6MB (Uint16, halved by assuming under 65,536 regions), fill buffer 17MB,
a transient highlight buffer 17MB, plus three full-canvas GPU textures. Expect ~100MB. If that is
too much on a low-end device, the highlight can be generated at half resolution and the display
image dropped.

**Large texture draws.** Three full-canvas images are drawn per frame. This is the main suspect if
raster time is high; the answer would be tiling.

**Highlight rebuild.** Runs on colour selection and after every fill, visiting only that colour's
regions via `regions_by_colour`, never the whole map.

## What to report back

- `over 16ms %` during sustained pinch-zoom and pan — the gate
- worst build and worst raster, separately (they have different fixes)
- `fill Nms` and `highlight Nms`
- load time, and peak memory from Android Studio's profiler
- device make and model
