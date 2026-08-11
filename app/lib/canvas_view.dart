import 'dart:async';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import 'artwork.dart';

/// Timings captured so the performance gate is answered with numbers rather than
/// impressions. Surfaced on screen rather than only logged, because the point of this
/// prototype is measuring on a real device.
class CanvasStats {
  int lastFillMillis = 0;
  int lastHighlightMillis = 0;
  int visibleNumbers = 0;
  double zoom = 1.0;
}

/// The colourable canvas: pan, zoom, tap-to-fill, zoom-revealed numbers.
///
/// Zoom and pan go through [InteractiveViewer] rather than hand-rolled gesture maths,
/// which also gives sensible fling and boundary behaviour for free. The transform is kept
/// in a controller so the number layer can read it: numbers are painted *outside* the
/// transformed subtree so they stay a constant size on screen while the artwork scales.
/// That is what makes small regions numberable at all, and why the pipeline was able to
/// drop leader lines entirely.
class CanvasView extends StatefulWidget {
  const CanvasView({
    super.key,
    required this.artwork,
    required this.selectedColour,
    required this.onRegionFilled,
    required this.stats,
  });

  final Artwork artwork;
  final PaletteColour? selectedColour;

  /// Reports (regionId, wasCorrect) so the shell can update progress and give feedback.
  final void Function(int regionId, bool correct) onRegionFilled;
  final CanvasStats stats;

  @override
  State<CanvasView> createState() => _CanvasViewState();
}

class _CanvasViewState extends State<CanvasView> {
  final TransformationController _controller = TransformationController();

  /// Fill layer: transparent where unfilled, palette colour where filled. Held as a CPU
  /// buffer and re-uploaded after each fill.
  late Uint32List _fillPixels;
  ui.Image? _fillImage;

  /// Grey/white pattern over the selected colour's unfilled regions.
  ui.Image? _highlightImage;
  int? _highlightedColour;

  Size _viewport = Size.zero;
  bool _fitted = false;

  @override
  void initState() {
    super.initState();
    _fillPixels = Uint32List(widget.artwork.width * widget.artwork.height);
  }

  @override
  void didUpdateWidget(CanvasView old) {
    super.didUpdateWidget(old);
    if (widget.selectedColour?.number != _highlightedColour) {
      _rebuildHighlight();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    _fillImage?.dispose();
    _highlightImage?.dispose();
    super.dispose();
  }

  /// Scale at which the whole canvas just fits the viewport. This is zoom 1.0 — the same
  /// reference the pipeline used when computing each region's `reveal_zoom`.
  double get _fitScale {
    if (_viewport.isEmpty) return 1.0;
    final byWidth = _viewport.width / widget.artwork.width;
    final byHeight = _viewport.height / widget.artwork.height;
    return byWidth < byHeight ? byWidth : byHeight;
  }

  double get _scale => _controller.value.getMaxScaleOnAxis();

  /// Current zoom in the pipeline's terms: 1.0 means the canvas fits the screen.
  double get _zoom => _fitScale == 0 ? 1.0 : _scale / _fitScale;

  void _fitToViewport() {
    final scale = _fitScale;
    final dx = (_viewport.width - widget.artwork.width * scale) / 2;
    final dy = (_viewport.height - widget.artwork.height * scale) / 2;
    _controller.value = Matrix4.identity()
      ..translate(dx, dy)
      ..scale(scale);
  }

  Future<void> _onTapUp(TapUpDetails details) async {
    final selected = widget.selectedColour;
    if (selected == null) return;

    // InteractiveViewer maps child (canvas) coordinates to viewport coordinates, so the
    // inverse takes a tap straight back to a canvas pixel.
    final canvasPoint = MatrixUtils.transformPoint(
      Matrix4.inverted(_controller.value),
      details.localPosition,
    );
    final regionId = widget.artwork.regionAt(
      canvasPoint.dx.floor(),
      canvasPoint.dy.floor(),
    );
    if (regionId < 0) return;

    final region = widget.artwork.regions[regionId];
    final correct = region.colourNumber == selected.number;

    // A wrong tap is reported but never fills. Filling the wrong colour would be
    // unrecoverable without undo, and mis-taps are the most common interaction after
    // correct ones, so they must be harmless.
    if (!correct || widget.artwork.isFilled(regionId)) {
      widget.onRegionFilled(regionId, false);
      return;
    }

    final watch = Stopwatch()..start();
    widget.artwork.fill(regionId, selected.number);
    _paintRegion(_fillPixels, regionId, selected.rgbaWord);
    await _uploadFillLayer();
    // The highlight shows only *unfilled* regions of this colour, so it is now stale by
    // exactly the region just filled.
    await _rebuildHighlight(force: true);
    watch.stop();

    widget.stats.lastFillMillis = watch.elapsedMilliseconds;
    widget.onRegionFilled(regionId, true);
  }

  /// Write a region's pixels into an RGBA buffer, touching only its bounding box.
  ///
  /// The bounds are why a fill is cheap: rescanning all 4.3M pixels per tap would be
  /// wasteful when the region occupies a few thousand.
  void _paintRegion(Uint32List target, int regionId, int rgbaWord) {
    final artwork = widget.artwork;
    final (minX, minY, maxX, maxY) = artwork.boundsOf(regionId);
    for (var y = minY; y <= maxY; y++) {
      final row = y * artwork.width;
      for (var x = minX; x <= maxX; x++) {
        if (artwork.regionIds[row + x] == regionId) {
          target[row + x] = rgbaWord;
        }
      }
    }
  }

  Future<void> _uploadFillLayer() async {
    final image = await _decode(_fillPixels);
    if (!mounted) {
      image.dispose();
      return;
    }
    setState(() {
      _fillImage?.dispose();
      _fillImage = image;
    });
  }

  /// Build the grey/white pattern over unfilled regions of the selected colour.
  ///
  /// Not decoration: with ~88 colours each one owns only a handful of regions, so "where
  /// does colour 43 go?" is genuinely hard to answer by eye without it.
  Future<void> _rebuildHighlight({bool force = false}) async {
    final selected = widget.selectedColour;
    if (!force && selected?.number == _highlightedColour) return;
    _highlightedColour = selected?.number;

    if (selected == null) {
      if (mounted) setState(() => _highlightImage = null);
      return;
    }

    final watch = Stopwatch()..start();
    final artwork = widget.artwork;
    final pixels = Uint32List(artwork.width * artwork.height);

    // Only this colour's regions are visited, via the artifact's regions_by_colour index —
    // never a scan of the whole map.
    for (final id in selected.regionIds) {
      if (artwork.isFilled(id)) continue;
      _paintRegionCheckered(pixels, id);
    }

    final image = await _decode(pixels);
    watch.stop();
    if (!mounted) {
      image.dispose();
      return;
    }
    setState(() {
      _highlightImage?.dispose();
      _highlightImage = image;
      widget.stats.lastHighlightMillis = watch.elapsedMilliseconds;
    });
  }

  /// Checkerboard within a region, so a highlighted area reads as "to do" rather than as
  /// colour already laid down.
  void _paintRegionCheckered(Uint32List target, int regionId) {
    // Greys, so channel order does not matter for these words.
    const light = 0xFFF2F2F2;
    const dark = 0xFF9A9A9A;
    const cell = 8;

    final artwork = widget.artwork;
    final (minX, minY, maxX, maxY) = artwork.boundsOf(regionId);
    for (var y = minY; y <= maxY; y++) {
      final row = y * artwork.width;
      final band = (y ~/ cell) & 1;
      for (var x = minX; x <= maxX; x++) {
        if (artwork.regionIds[row + x] != regionId) continue;
        final checker = ((x ~/ cell) & 1) ^ band;
        target[row + x] = checker == 0 ? light : dark;
      }
    }
  }

  Future<ui.Image> _decode(Uint32List pixels) {
    final completer = Completer<ui.Image>();
    ui.decodeImageFromPixels(
      pixels.buffer.asUint8List(),
      widget.artwork.width,
      widget.artwork.height,
      ui.PixelFormat.rgba8888,
      completer.complete,
    );
    return completer.future;
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final size = Size(constraints.maxWidth, constraints.maxHeight);
        if (size != _viewport) {
          _viewport = size;
          if (!_fitted && !size.isEmpty) {
            _fitted = true;
            // Deferred: setting the controller during layout would mutate state mid-build.
            WidgetsBinding.instance.addPostFrameCallback((_) {
              if (mounted) _fitToViewport();
            });
          }
        }

        final artwork = widget.artwork;
        return GestureDetector(
          onTapUp: _onTapUp,
          child: ClipRect(
            child: Stack(
              children: [
                InteractiveViewer(
                  transformationController: _controller,
                  // The child is sized in canvas pixels, so it is larger than the viewport
                  // and must not be constrained to it.
                  constrained: false,
                  boundaryMargin: const EdgeInsets.all(double.infinity),
                  minScale: _fitScale * 0.8,
                  // The pipeline assumes numbers become legible by roughly 8x zoom; a
                  // little headroom beyond that is comfortable, much more is pointless.
                  maxScale: _fitScale * 16.0,
                  child: SizedBox(
                    width: artwork.width.toDouble(),
                    height: artwork.height.toDouble(),
                    child: CustomPaint(
                      painter: _LayersPainter(
                        artwork: artwork,
                        fillImage: _fillImage,
                        highlightImage: _highlightImage,
                      ),
                    ),
                  ),
                ),
                // Numbers live outside the transformed subtree so they keep a constant
                // on-screen size. Rebuilt from the controller, so panning and zooming
                // move them without rebuilding the artwork layers.
                Positioned.fill(
                  child: IgnorePointer(
                    child: AnimatedBuilder(
                      animation: _controller,
                      builder: (context, _) {
                        widget.stats.zoom = _zoom;
                        return CustomPaint(
                          painter: _NumbersPainter(
                            artwork: artwork,
                            transform: _controller.value,
                            zoom: _zoom,
                            stats: widget.stats,
                          ),
                        );
                      },
                    ),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// Artwork layers, painted in canvas coordinates inside the transformed subtree.
class _LayersPainter extends CustomPainter {
  _LayersPainter({
    required this.artwork,
    required this.fillImage,
    required this.highlightImage,
  });

  final Artwork artwork;
  final ui.Image? fillImage;
  final ui.Image? highlightImage;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..filterQuality = FilterQuality.low;

    // Order matters. Fills sit under the outlines so lines stay visible; the highlight
    // sits above the fills but under the lines so it does not swallow them.
    canvas.drawRect(Offset.zero & size, Paint()..color = const Color(0xFFFFFFFF));
    if (fillImage != null) canvas.drawImage(fillImage!, Offset.zero, paint);
    if (highlightImage != null) canvas.drawImage(highlightImage!, Offset.zero, paint);
    canvas.drawImage(artwork.outlineImage, Offset.zero, paint);
  }

  @override
  bool shouldRepaint(_LayersPainter old) =>
      old.fillImage != fillImage || old.highlightImage != highlightImage;
}

/// Region numbers, painted in screen coordinates at constant size.
class _NumbersPainter extends CustomPainter {
  _NumbersPainter({
    required this.artwork,
    required this.transform,
    required this.zoom,
    required this.stats,
  });

  final Artwork artwork;
  final Matrix4 transform;
  final double zoom;
  final CanvasStats stats;

  static const TextStyle _style = TextStyle(
    color: Color(0xFF4A4A52),
    fontSize: 11,
    fontWeight: FontWeight.w500,
  );

  /// Laid-out text is cached per number. There are only as many distinct labels as there
  /// are palette colours (~88), while a frame can show hundreds of regions, so building a
  /// TextPainter per region per frame would be pure waste on the hot path.
  static final Map<int, TextPainter> _labels = <int, TextPainter>{};

  static TextPainter _label(int number) {
    return _labels.putIfAbsent(number, () {
      return TextPainter(
        text: TextSpan(text: '$number', style: _style),
        textDirection: TextDirection.ltr,
      )..layout();
    });
  }

  @override
  void paint(Canvas canvas, Size size) {
    var visible = 0;
    final viewport = Offset.zero & size;

    for (final region in artwork.regions) {
      // The reveal threshold is the whole mechanism: a region too small to hold a legible
      // digit at this zoom simply has no number yet.
      if (region.revealZoom > zoom) continue;
      if (artwork.isFilled(region.id)) continue;

      final point = MatrixUtils.transformPoint(transform, region.centre);
      if (!viewport.contains(point)) continue;

      visible++;
      final painter = _label(region.colourNumber);
      painter.paint(canvas, point - Offset(painter.width / 2, painter.height / 2));
    }
    stats.visibleNumbers = visible;
  }

  @override
  bool shouldRepaint(_NumbersPainter old) =>
      old.transform != transform || old.zoom != zoom;
}
