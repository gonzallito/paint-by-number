import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import 'artwork.dart';
import 'canvas_view.dart';
import 'palette_tray.dart';
import 'player.dart';
import 'progress.dart';

/// The bundled sample artwork. Kept because it needs no server, so the canvas and its
/// instrumentation can be exercised even when the conversion service is not running.
const String kArtworkAsset = 'assets/artwork/martim';

/// The colouring canvas for one artwork.
///
/// Takes a [BundleSource] rather than a path, so a downloaded artwork and the bundled sample
/// open through exactly the same code.
class ArtworkScreen extends StatefulWidget {
  const ArtworkScreen({
    super.key,
    required this.source,
    required this.title,
    this.progressStore,
    this.progressKey,
    this.player,
  });

  final BundleSource source;
  final String title;

  /// Where painting progress is saved and resumed from. Both this and [progressKey] must be set
  /// for persistence to happen; either being null makes the canvas throwaway, which is what the
  /// benchmark harness wants.
  final ProgressStore? progressStore;
  final String? progressKey;

  /// Credited with XP and lifetime counters as regions are filled.
  final PlayerStore? player;

  @override
  State<ArtworkScreen> createState() => _ArtworkScreenState();
}

class _ArtworkScreenState extends State<ArtworkScreen> {
  Artwork? _artwork;
  Object? _error;
  PaletteColour? _selected;
  int _loadMillis = 0;

  ProgressWriter? _writer;

  /// True once the completion bonus has been credited, so reopening a finished canvas does not
  /// pay again.
  bool _rewarded = false;

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
    // Flushes any pending write before going away. Popping the route is the most common way a
    // session ends, and the debounce alone would lose the last few fills.
    _writer?.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final watch = Stopwatch()..start();
    try {
      final artwork = await Artwork.load(widget.source);

      final store = widget.progressStore;
      final key = widget.progressKey;
      ProgressWriter? writer;
      if (store != null && key != null) {
        final saved = await store.load(key, artwork.regionCount);
        if (saved != null) artwork.restoreFillState(saved);
        writer = ProgressWriter(
          store: store,
          key: key,
          snapshot: () => artwork.fillState,
        );
      }

      watch.stop();
      if (!mounted) {
        await writer?.dispose();
        return;
      }
      setState(() {
        _artwork = artwork;
        _writer = writer;
        _loadMillis = watch.elapsedMilliseconds;
        _rewarded = artwork.isComplete;
        // Preselect the colour with the most regions *left*, so resuming lands on something
        // still paintable rather than a colour that was finished last sitting.
        _selected = _mostRemaining(artwork);
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error);
    }
  }

  static PaletteColour? _mostRemaining(Artwork artwork) {
    PaletteColour? best;
    var bestRemaining = 0;
    for (final entry in artwork.palette) {
      final remaining = artwork.remainingFor(entry);
      if (remaining > bestRemaining) {
        bestRemaining = remaining;
        best = entry;
      }
    }
    // Fall back to the first entry so a finished canvas still shows a selection.
    return best ?? (artwork.palette.isEmpty ? null : artwork.palette.first);
  }

  void _onRegionFilled(int regionId, bool correct) {
    final artwork = _artwork;
    // Rebuild for the progress readout and tray counts. A wrong tap deliberately changes
    // nothing on the canvas.
    if (!correct || artwork == null) {
      setState(() {});
      return;
    }

    _writer?.markDirty();
    final player = widget.player;
    player?.recordRegionPainted();

    var selected = _selected;
    if (selected != null && artwork.remainingFor(selected) == 0) {
      player?.recordColourCompleted();
      selected = _mostRemaining(artwork);
    }

    if (artwork.isComplete && !_rewarded) {
      _rewarded = true;
      player?.recordCanvasCompleted(isDaily: false);
      // Flushed rather than debounced: finishing is the one event whose loss is visible.
      _writer?.flush();
      player?.flush();
    }

    setState(() => _selected = selected);
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
