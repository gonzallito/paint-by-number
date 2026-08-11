import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import 'artwork.dart';
import 'canvas_view.dart';
import 'palette_tray.dart';

/// Phase 2 canvas prototype.
///
/// Its purpose is to answer one question with numbers: **does the colouring canvas hold
/// 60fps on a low-end physical Android device?** Everything on screen serves either the
/// interaction being tested or the measurement of it.
///
/// Profile on hardware, in profile mode. An emulator runs on the host CPU and GPU, so it
/// cannot answer this either way — a "Pixel 6" emulator is not a Pixel 6.
void main() {
  runApp(const PaintByNumberApp());
}

const String kArtworkAsset = 'assets/artwork/martim';

class PaintByNumberApp extends StatelessWidget {
  const PaintByNumberApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Paint by Number',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark(useMaterial3: true),
      home: const ArtworkScreen(),
    );
  }
}

class ArtworkScreen extends StatefulWidget {
  const ArtworkScreen({super.key});

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
      final artwork = await Artwork.load(kArtworkAsset);
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
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text('Failed to load artwork:\n$_error'),
          ),
        ),
      );
    }

    if (artwork == null) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }

    return Scaffold(
      backgroundColor: const Color(0xFF101012),
      body: SafeArea(
        child: Column(
          children: [
            _StatsStrip(
              artwork: artwork,
              stats: _stats,
              frames: _frames,
              loadMillis: _loadMillis,
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
class _FrameMonitor {
  static const int _window = 120;
  final List<double> _buildMs = <double>[];
  final List<double> _rasterMs = <double>[];

  void start() {
    SchedulerBinding.instance.addTimingsCallback(_onTimings);
  }

  void stop() {
    SchedulerBinding.instance.removeTimingsCallback(_onTimings);
  }

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

  double get worstBuild => _buildMs.isEmpty ? 0 : _buildMs.reduce((a, b) => a > b ? a : b);
  double get worstRaster => _rasterMs.isEmpty ? 0 : _rasterMs.reduce((a, b) => a > b ? a : b);

  /// Share of recent frames that missed the 16ms budget. This is the gate.
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
  });

  final Artwork artwork;
  final CanvasStats stats;
  final _FrameMonitor frames;
  final int loadMillis;

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
              'worst build ${frames.worstBuild.toStringAsFixed(1)}ms   '
              'worst raster ${frames.worstRaster.toStringAsFixed(1)}ms   '
              'over 16ms ${frames.jankPercent.toStringAsFixed(0)}%',
            ),
          ],
        ),
      ),
    );
  }
}
