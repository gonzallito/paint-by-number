import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/services.dart';

/// One palette entry, as presented in the tray.
class PaletteColour {
  PaletteColour({
    required this.number,
    required this.red,
    required this.green,
    required this.blue,
    required this.regionIds,
  }) : colour = ui.Color.fromARGB(255, red, green, blue),
       // Word order for PixelFormat.rgba8888 on a little-endian host is 0xAABBGGRR.
       // Kept as raw channels from meta.json rather than read back off ui.Color, whose
       // component accessors have churned across Flutter versions.
       rgbaWord = 0xFF000000 | (blue << 16) | (green << 8) | red;

  /// 1-based, exactly what is printed on the canvas.
  final int number;
  final int red;
  final int green;
  final int blue;

  /// For painting widgets.
  final ui.Color colour;

  /// For writing directly into a pixel buffer.
  final int rgbaWord;

  /// Every region wearing this number. Comes straight from the artifact's
  /// `regions_by_colour` index, so selecting a colour never scans the region map.
  final List<int> regionIds;
}

/// Per-region geometry needed for numbering.
class RegionInfo {
  RegionInfo({
    required this.id,
    required this.colourNumber,
    required this.centre,
    required this.revealZoom,
  });

  final int id;
  final int colourNumber;

  /// The most interior point, where the number sits.
  final ui.Offset centre;

  /// Zoom at which this region's number becomes legible, where 1.0 means the whole
  /// canvas fits the screen. Small regions carry a higher value and stay unlabelled
  /// until the user zooms in, which is why leader lines proved unnecessary.
  final double revealZoom;
}

/// A loaded artifact bundle plus the user's progress against it.
///
/// The central idea is the **region-ID map**: `regions.png` encodes each pixel's region
/// index directly in its 24-bit RGB value. Hit-testing a tap is therefore a single array
/// lookup rather than a geometric query, at any region count. Nothing here does polygon
/// maths, which is why the pipeline never needed to emit vectors.
class Artwork {
  Artwork._({
    required this.width,
    required this.height,
    required this.regionIds,
    required this.regions,
    required this.palette,
    required this.outlineImage,
    required Uint32List regionBounds,
  }) : _regionBounds = regionBounds,
       _filledColour = Uint8List(regions.length);

  final int width;
  final int height;

  /// Region index per pixel, row-major. Uint16 rather than Int32 because region counts
  /// are in the hundreds — that halves this from ~17MB to ~8.6MB at 1800x2400, which
  /// matters on the low-end devices this prototype exists to test.
  final Uint16List regionIds;

  final List<RegionInfo> regions;
  final List<PaletteColour> palette;

  /// Outlines rendered from the region map at load, **not** loaded from `display.png`.
  /// The shipped display image has numbers baked in, which would fight the zoom-based
  /// reveal. Deriving outlines also tests whether `display.png` needs shipping at all —
  /// it is 3.4MB of a 4.1MB bundle.
  final ui.Image outlineImage;

  /// Tight bounds per region, packed as [minX, minY, maxX, maxY] per entry.
  ///
  /// Computed here because the artifact does not carry them, and filling a region must
  /// touch only its own pixels. Without bounds every tap would rescan all 4.3M pixels.
  final Uint32List _regionBounds;

  /// 0 = unfilled, otherwise the 1-based colour number it was filled with. Storing the
  /// colour rather than a flag lets the UI show a wrong fill distinctly from a right one.
  final Uint8List _filledColour;

  int get regionCount => regions.length;

  bool isFilled(int regionId) => _filledColour[regionId] != 0;

  int filledColourOf(int regionId) => _filledColour[regionId];

  void fill(int regionId, int colourNumber) {
    _filledColour[regionId] = colourNumber;
  }

  /// Bounds of a region as (minX, minY, maxX, maxY), inclusive.
  (int, int, int, int) boundsOf(int regionId) {
    final base = regionId * 4;
    return (
      _regionBounds[base],
      _regionBounds[base + 1],
      _regionBounds[base + 2],
      _regionBounds[base + 3],
    );
  }

  /// Region at a canvas pixel, or -1 outside the canvas.
  int regionAt(int x, int y) {
    if (x < 0 || y < 0 || x >= width || y >= height) return -1;
    return regionIds[y * width + x];
  }

  /// How many of this colour's regions are still unfilled.
  int remainingFor(PaletteColour colour) {
    var remaining = 0;
    for (final id in colour.regionIds) {
      if (_filledColour[id] == 0) remaining++;
    }
    return remaining;
  }

  int get filledCount {
    var count = 0;
    for (var i = 0; i < _filledColour.length; i++) {
      if (_filledColour[i] != 0) count++;
    }
    return count;
  }

  /// Load a bundle from bundled assets. [directory] is an asset path such as
  /// `assets/artwork/martim`.
  static Future<Artwork> load(String directory) async {
    final metaJson = await rootBundle.loadString('$directory/meta.json');
    final meta = jsonDecode(metaJson) as Map<String, dynamic>;

    final canvas = meta['canvas'] as Map<String, dynamic>;
    final width = canvas['width'] as int;
    final height = canvas['height'] as int;

    final regionIds = await _decodeRegionMap('$directory/regions.png', width, height);

    final regionList = (meta['regions'] as List).cast<Map<String, dynamic>>();
    final regions = regionList.map((entry) {
      final centre = (entry['centroid'] as List).cast<num>();
      return RegionInfo(
        id: entry['id'] as int,
        colourNumber: entry['colour'] as int,
        centre: ui.Offset(centre[0].toDouble(), centre[1].toDouble()),
        revealZoom: (entry['reveal_zoom'] as num).toDouble(),
      );
    }).toList(growable: false);

    final byColour = (meta['regions_by_colour'] as Map<String, dynamic>);
    final palette = (meta['palette'] as List)
        .cast<Map<String, dynamic>>()
        .map((entry) {
          final number = entry['number'] as int;
          final rgb = (entry['rgb'] as List).cast<int>();
          return PaletteColour(
            number: number,
            red: rgb[0],
            green: rgb[1],
            blue: rgb[2],
            regionIds: ((byColour['$number'] as List?) ?? const []).cast<int>(),
          );
        })
        .toList(growable: false);

    // Bounds and outlines are derived in a single pass. Two separate walks over 4.3M pixels
    // showed up directly in a measured 2615ms load time.
    final derived = _derive(regionIds, width, height, regions.length);
    final outline = await _decodePixels(derived.outlinePixels, width, height);

    return Artwork._(
      width: width,
      height: height,
      regionIds: regionIds,
      regions: regions,
      palette: palette,
      outlineImage: outline,
      regionBounds: derived.bounds,
    );
  }

  /// Decode `regions.png` into region indices.
  ///
  /// The encoding is `id = r + g*256 + b*65536`, little-endian by channel, which keeps
  /// green and blue near zero for the region counts we produce and so compresses well —
  /// this file is 372KB where the display image is 3.4MB.
  static Future<Uint16List> _decodeRegionMap(String asset, int width, int height) async {
    final data = await rootBundle.load(asset);
    final codec = await ui.instantiateImageCodec(data.buffer.asUint8List());
    final frame = await codec.getNextFrame();
    final image = frame.image;

    final raw = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
    image.dispose();
    if (raw == null) {
      throw StateError('could not read pixels from $asset');
    }

    final bytes = raw.buffer.asUint8List();
    final ids = Uint16List(width * height);
    for (var i = 0, p = 0; i < ids.length; i++, p += 4) {
      final id = bytes[p] | (bytes[p + 1] << 8) | (bytes[p + 2] << 16);
      // Uint16 is a deliberate memory saving; a bundle with more regions than this would
      // need a wider list, so fail loudly rather than silently wrapping around.
      if (id > 0xFFFF) {
        throw StateError('region id $id exceeds the 16-bit region map assumption');
      }
      ids[i] = id;
    }
    return ids;
  }

  /// Per-region bounds and the outline layer, from a single walk of the region map.
  ///
  /// Both were separate passes over 4.3M pixels, which showed up directly in a measured
  /// 2615ms load. Combining them halves the work for identical output.
  ///
  /// The outline layer is **transparent** with grey boundary pixels, not white, so it can be
  /// drawn over the fill layer — an opaque background would hide every colour the user has
  /// laid down. Only right and down neighbours are compared, giving a single-pixel line per
  /// boundary rather than the doubled line that checking all four would produce.
  static ({Uint32List bounds, Uint32List outlinePixels}) _derive(
    Uint16List ids,
    int width,
    int height,
    int regionCount,
  ) {
    // A Uint32List word for PixelFormat.rgba8888 on a little-endian host reads 0xAABBGGRR,
    // so this is R=0x58 G=0x5C B=0x60 at full alpha — the grey the pipeline draws with.
    const line = 0xFF605C58;

    final bounds = Uint32List(regionCount * 4);
    for (var i = 0; i < regionCount; i++) {
      bounds[i * 4] = width; // minX seeded high so the first pixel seen wins
      bounds[i * 4 + 1] = height;
    }
    final outline = Uint32List(width * height);

    for (var y = 0; y < height; y++) {
      final row = y * width;
      for (var x = 0; x < width; x++) {
        final index = row + x;
        final id = ids[index];

        final base = id * 4;
        if (x < bounds[base]) bounds[base] = x;
        if (y < bounds[base + 1]) bounds[base + 1] = y;
        if (x > bounds[base + 2]) bounds[base + 2] = x;
        if (y > bounds[base + 3]) bounds[base + 3] = y;

        final rightDiffers = x + 1 < width && ids[index + 1] != id;
        final downDiffers = y + 1 < height && ids[index + width] != id;
        if (rightDiffers || downDiffers) {
          outline[index] = line;
        }
      }
    }
    return (bounds: bounds, outlinePixels: outline);
  }

  static Future<ui.Image> _decodePixels(Uint32List pixels, int width, int height) {
    final completer = Completer<ui.Image>();
    ui.decodeImageFromPixels(
      pixels.buffer.asUint8List(),
      width,
      height,
      ui.PixelFormat.rgba8888,
      completer.complete,
    );
    return completer.future;
  }
}
