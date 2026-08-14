import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import 'artwork.dart';
import 'canvas_view.dart';
import 'palette_tray.dart';

/// The bundled sample artwork. Kept because it needs no server, so the canvas and its
/// instrumentation can be exercised even when the conversion service is not running.
const String kArtworkAsset = 'assets/artwork/martim';

/// The colouring canvas for one artwork.
///
/// Takes a [BundleSource] rather than a path, so a downloaded artwork and the bundled sample
/// open through exactly the same code.
class ArtworkScreen extends StatefulWidget {
  const ArtworkScreen({super.key, required this.source, required this.title});

  final BundleSource source;
  final String title;

  @override
  State<ArtworkScreen> createState() => _ArtworkScreenState();
}

class _ArtworkScreenState extends State<ArtworkScreen> {
  Artwork? _artwork;
  Object? _error;
  PaletteColour? _selected;
  int _loadMillis = 0;

  final CanvasStats _stats = CanvasStats();

  /// Rolling frame timing, so jank is reported rather than guessed at.
  final _FrameMonitor _frames = _FrameMonitor();

  @override
  void initState() {
    super.initState();
    _frames.start();
    _load();
  }

  @override
  void dispose() {
    _frames.stop();
    super.dispose();
  }

  Future<void> _load() async {
    final watch = Stopwatch()..start();
    try {
      final artwork = await Artwork.load(widget.source);
      watch.stop();
      if (!mounted) return;
      setState(() {
        _artwork = artwork;
        _loadMillis = watch.elapsedMilliseconds;
        // Preselect the colour with the most regions, so a tester can start filling
        // immediately rather than hunting the tray for something that exists.
        _selected = artwork.palette.reduce(
          (a, b) => a.regionIds.length >= b.regionIds.length ? a : b,
        );
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error);
    }
  }

  void _onRegionFilled(int regionId, bool correct) {
    // Rebuild for the progress readout and tray counts. A wrong tap deliberately changes
    // nothing on the canvas.
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final artwork = _artwork;

    if (_error != null) {
      return Scaffold(
        appBar: AppBar(title: Text(widget.title)),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text('Failed to load artwork:\n$_error'),
          ),
        ),
      );
    }

    if (artwork == null) {
      return Scaffold(
        appBar: AppBar(title: Text(widget.title)),
        body: const Center(child: CircularProgressIndicator()),
      );
    }

    return Scaffold(
      backgroundColor: const Color(0xFF101012),
      appBar: AppBar(
        title: Text(widget.title),
        backgroundColor: const Color(0xFF17171A),
        toolbarHeight: 44,
      ),
      body: SafeArea(
        child: Column(
          children: [
            _StatsStrip(
              artwork: artwork,
              stats: _stats,
              frames: _frames,
              loadMillis: _loadMillis,
              onReset: () => setState(_frames.reset),
            ),
            Expanded(
              child: CanvasView(
                artwork: artwork,
                selectedColour: _selected,
                onRegionFilled: _onRegionFilled,
                stats: _stats,
              ),
            ),
            PaletteTray(
              artwork: artwork,
              selected: _selected,
              onSelected: (entry) => setState(() => _selected = entry),
            ),
          ],
        ),
      ),
    );
  }
}

/// Samples frame timings from the scheduler so the gate can be answered with data.
///
/// Reports **percentiles, not a worst value**. A single worst figure was actively misleading:
/// the sample window includes app startup, whose first frame is always enormous, so it read
/// 1837ms and said nothing about interaction. p50 and p95 describe the experience; [reset]
/// exists so a specific interaction can be measured without startup in the sample at all.
class _FrameMonitor {
  static const int _window = 240;
  final List<double> _buildMs = <double>[];
  final List<double> _rasterMs = <double>[];

  void start() => SchedulerBinding.instance.addTimingsCallback(_onTimings);
  void stop() => SchedulerBinding.instance.removeTimingsCallback(_onTimings);

  void reset() {
    _buildMs.clear();
    _rasterMs.clear();
  }

  int get sampleCount => _buildMs.length;

  void _onTimings(List<FrameTiming> timings) {
    for (final timing in timings) {
      _buildMs.add(timing.buildDuration.inMicroseconds / 1000.0);
      _rasterMs.add(timing.rasterDuration.inMicroseconds / 1000.0);
    }
    while (_buildMs.length > _window) {
      _buildMs.removeAt(0);
      _rasterMs.removeAt(0);
    }
  }

  static double _percentile(List<double> values, double fraction) {
    if (values.isEmpty) return 0;
    final sorted = List<double>.of(values)..sort();
    final index = ((sorted.length - 1) * fraction).round();
    return sorted[index];
  }

  double get buildP50 => _percentile(_buildMs, 0.50);
  double get buildP95 => _percentile(_buildMs, 0.95);
  double get rasterP50 => _percentile(_rasterMs, 0.50);
  double get rasterP95 => _percentile(_rasterMs, 0.95);

  /// Share of sampled frames that missed the 16ms budget. This is the gate.
  double get jankPercent {
    if (_buildMs.isEmpty) return 0;
    var over = 0;
    for (var i = 0; i < _buildMs.length; i++) {
      if (_buildMs[i] + _rasterMs[i] > 16.0) over++;
    }
    return 100.0 * over / _buildMs.length;
  }
}

class _StatsStrip extends StatelessWidget {
  const _StatsStrip({
    required this.artwork,
    required this.stats,
    required this.frames,
    required this.loadMillis,
    required this.onReset,
  });

  final Artwork artwork;
  final CanvasStats stats;
  final _FrameMonitor frames;
  final int loadMillis;
  final VoidCallback onReset;

  @override
  Widget build(BuildContext context) {
    final filled = artwork.filledCount;
    final total = artwork.regionCount;
    return Container(
      width: double.infinity,
      color: const Color(0xFF17171A),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: DefaultTextStyle(
        style: const TextStyle(
          color: Color(0xFFB8B8C0),
          fontSize: 11,
          fontFamily: 'monospace',
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '$filled/$total filled   ${artwork.palette.length} colours   '
                    'load ${loadMillis}ms',
                  ),
                  const SizedBox(height: 2),
                  Text(
                    'zoom ${stats.zoom.toStringAsFixed(2)}x   '
                    'numbers ${stats.visibleNumbers}   '
                    'fill ${stats.lastFillMillis}ms   '
                    'highlight ${stats.lastHighlightMillis}ms',
                  ),
                  const SizedBox(height: 2),
                  Text(
                    'build p50 ${frames.buildP50.toStringAsFixed(1)} '
                    'p95 ${frames.buildP95.toStringAsFixed(1)}ms   '
                    'raster p50 ${frames.rasterP50.toStringAsFixed(1)} '
                    'p95 ${frames.rasterP95.toStringAsFixed(1)}ms',
                  ),
                  const SizedBox(height: 2),
                  Text(
                    'over 16ms ${frames.jankPercent.toStringAsFixed(0)}%   '
                    'frames ${frames.sampleCount}',
                  ),
                ],
              ),
            ),
            // Reset, then perform one interaction, then read. Startup frames otherwise
            // dominate every percentile and make the numbers meaningless.
            TextButton(
              onPressed: onReset,
              child: const Text('reset', style: TextStyle(fontSize: 11)),
            ),
          ],
        ),
      ),
    );
  }
}
