import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import 'app_shell.dart';
import 'artwork.dart';
import 'artwork_screen.dart';
import 'library.dart';
import 'service_client.dart';
import 'theme.dart';

/// Stable progress key for a converted artwork.
///
/// Built from the job id and variant rather than the bundle's path on disk. The documents
/// directory has a different absolute path after an iOS reinstall or a restore, so a path-based
/// key would silently orphan every in-progress painting.
String artworkProgressKey(LibraryEntry entry) =>
    'artwork-${entry.jobId}-${entry.variant}';

/// The library: convert a photo, or reopen something already converted.
///
/// **The photo converter is pinned at the top, above everything else.** Photo conversion is the
/// product bet, not a feature buried in a browser, and "Library" is otherwise a word that means
/// "things that already exist" — which is exactly the wrong frame for the one screen where the
/// player makes something.
///
/// This tab is a browser. Opening an artwork *pushes* [ArtworkScreen] rather than hosting the
/// canvas here, because a zoomable canvas costs roughly 78MB and tabs are never disposed.
class LibraryTab extends StatefulWidget {
  const LibraryTab({super.key, required this.services});

  final AppServices services;

  @override
  State<LibraryTab> createState() => _LibraryTabState();
}

class _LibraryTabState extends State<LibraryTab> {
  final ConversionService _service = ConversionService();
  final ImagePicker _picker = ImagePicker();

  List<LibraryEntry> _entries = const [];

  /// Filled regions per artwork, read from saved progress so the list can show resume state.
  final Map<String, int> _filled = <String, int>{};

  /// Address the user set by hand, if any. Tried first during discovery.
  String? _savedUrl;

  /// The address discovery settled on, or null if nothing answered.
  String? _serviceUrl;
  bool _probing = true;

  /// Non-null while a conversion is in flight.
  _Progress? _progress;
  String? _error;

  @override
  void initState() {
    super.initState();
    _savedUrl = widget.services.settings.serviceUrl;
    _refresh();
    // Found now rather than at upload time, so a connection problem is visible before the user
    // picks a photo instead of after.
    _discover();
  }

  @override
  void dispose() {
    _service.close();
    super.dispose();
  }

  Future<void> _refresh() async {
    final entries = await widget.services.library.list();
    final filled = <String, int>{};
    for (final entry in entries) {
      final bytes = await widget.services.progress.load(
        artworkProgressKey(entry),
        entry.regions,
      );
      if (bytes == null) continue;
      var count = 0;
      for (final value in bytes) {
        if (value != 0) count++;
      }
      filled[entry.jobId] = count;
    }
    if (!mounted) return;
    setState(() {
      _entries = entries;
      _filled
        ..clear()
        ..addAll(filled);
    });
  }

  Future<void> _discover({bool force = false}) async {
    if (!mounted) return;
    setState(() => _probing = true);
    try {
      final url = await _service.discover(saved: _savedUrl, force: force);
      if (!mounted) return;
      setState(() {
        _probing = false;
        _serviceUrl = url;
        _error = null;
      });
    } on ConversionException catch (error) {
      if (!mounted) return;
      setState(() {
        _probing = false;
        _serviceUrl = null;
        _error = error.message;
      });
    }
  }

  Future<void> _convert(ImageSource source) async {
    final services = widget.services;
    setState(() => _error = null);

    final XFile? picked;
    try {
      picked = await _picker.pickImage(source: source);
    } catch (error) {
      setState(() => _error = 'Could not open the picker: $error');
      return;
    }
    if (picked == null) return;

    setState(() => _progress = const _Progress(0.0, 'Finding the service'));

    try {
      // Re-checked rather than trusting the launch-time result: a USB cable gets replugged, adb
      // reverse gets lost, the laptop changes network.
      final url = await _service.discover(saved: _savedUrl);
      if (mounted) {
        setState(() {
          _serviceUrl = url;
          _progress = const _Progress(0.0, 'Uploading photo');
        });
      }

      final jobId = await _service.upload(
        File(picked.path),
        deduplicate: !services.settings.alwaysReconvert,
      );

      final ready = await _service.awaitRecommended(
        jobId,
        onProgress: (progress, stage) {
          if (mounted) setState(() => _progress = _Progress(progress, stage));
        },
      );

      if (mounted) {
        setState(() => _progress = const _Progress(0.9, 'Downloading artwork'));
      }
      await _service.download(
        ready.jobId,
        ready.variant,
        services.library.bundleDir(ready.jobId, ready.variant),
      );

      final entry = await services.library.save(
        jobId: ready.jobId,
        variant: ready.variant,
        regions: ready.regions,
        colours: ready.colours,
        title: _titleFor(picked.name),
      );

      if (!mounted) return;
      setState(() {
        _progress = null;
        _entries = [entry, ..._entries];
      });
      await _open(entry);
    } catch (error) {
      if (!mounted) return;
      final message = _explain(error);
      setState(() {
        _progress = null;
        _error = message;
      });
      // A dialog, not just the banner. A conversion can fail in under a second — an unsupported
      // format fails immediately — and the banner was quiet enough that a fast failure looked
      // like nothing happening at all.
      await _showFailure(message);
    }
  }

  Future<void> _showFailure(String message) async {
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AppColours.raised,
        title: const Text('Conversion failed'),
        content: SingleChildScrollView(
          child: SelectableText(
            message,
            style: const TextStyle(fontSize: 13, height: 1.4),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  /// ConversionException already carries a message written to be read by a person, including
  /// the unreachable-service guidance, so there is nothing to add here.
  String _explain(Object error) =>
      error is ConversionException ? error.message : '$error';

  /// A filename is a poor title but an honest one, and better than "Artwork 3".
  static String _titleFor(String filename) {
    final dot = filename.lastIndexOf('.');
    final stem = dot == -1 ? filename : filename.substring(0, dot);
    return stem.isEmpty ? 'Artwork' : stem;
  }

  Future<void> _open(LibraryEntry entry) async {
    final services = widget.services;
    if (!await services.library.hasBundle(entry.jobId, entry.variant)) {
      if (mounted) {
        setState(() => _error = 'That artwork is missing its files. Convert it again.');
      }
      return;
    }
    if (!mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ArtworkScreen(
          title: entry.title,
          source: DirectoryBundleSource(
            services.library.bundleDir(entry.jobId, entry.variant),
          ),
          progressStore: services.progress,
          progressKey: artworkProgressKey(entry),
          player: services.player,
        ),
      ),
    );
    // Progress may have changed while the canvas was open.
    await _refresh();
  }

  Future<void> _openSample() async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ArtworkScreen(
          title: 'Sample (bundled)',
          source: const AssetBundleSource(kArtworkAsset),
          progressStore: widget.services.progress,
          progressKey: 'sample-$kArtworkAsset',
          player: widget.services.player,
        ),
      ),
    );
  }

  Future<void> _delete(LibraryEntry entry) async {
    await widget.services.library.delete(entry.jobId);
    await widget.services.progress.delete(artworkProgressKey(entry));
    if (!mounted) return;
    setState(() => _entries = _entries.where((e) => e.jobId != entry.jobId).toList());
  }

  @override
  Widget build(BuildContext context) {
    final progress = _progress;
    if (progress != null) {
      return SafeArea(bottom: false, child: _ConvertingView(progress: progress));
    }

    return SafeArea(
      bottom: false,
      child: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          padding: const EdgeInsets.only(bottom: 24),
          children: [
            // Pinned at the top: this is the product, not an entry in a list.
            _ConverterCard(
              onGallery: () => _convert(ImageSource.gallery),
              onCamera: () => _convert(ImageSource.camera),
            ),
            _ServiceStatus(
              url: _serviceUrl,
              probing: _probing,
              onRetry: () => _discover(force: true),
            ),
            if (_error != null) _ErrorBanner(message: _error!),

            SectionHeader(
              title: 'YOUR PAINTINGS',
              subtitle: _entries.isEmpty
                  ? null
                  : '${_entries.length} converted from your photos',
            ),
            if (_entries.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: Text(
                  'Nothing yet. Pick a photo above and it will appear here, with your progress '
                  'saved between sittings.',
                  style: TextStyle(fontSize: 12, height: 1.45, color: AppColours.faint),
                ),
              )
            else
              for (final entry in _entries)
                _ArtworkTile(
                  entry: entry,
                  filled: _filled[entry.jobId] ?? 0,
                  onTap: () => _open(entry),
                  onDelete: () => _delete(entry),
                ),

            const SectionHeader(
              title: 'CURATED CATALOGUE',
              subtitle: 'Browse by theme and difficulty',
            ),
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 16),
              child: Text(
                'Empty for now. Curated canvases are converted and reviewed offline, then '
                'published as finished artifacts — the build tool for that exists, but no art has '
                'been published through it yet.\n\n'
                'The Rare, Blend and Mystery types are not filters over this list: Blend needs '
                'gradient fills and Mystery needs a colour hidden until it is filled, and both '
                'require new fields in the artifact format.',
                style: TextStyle(fontSize: 12, height: 1.5, color: AppColours.faint),
              ),
            ),

            const SectionHeader(title: 'DEVELOPMENT'),
            _SampleTile(onTap: _openSample),
          ],
        ),
      ),
    );
  }
}

class _Progress {
  const _Progress(this.fraction, this.stage);
  final double fraction;
  final String stage;
}

/// The photo converter, at the top of the tab.
class _ConverterCard extends StatelessWidget {
  const _ConverterCard({required this.onGallery, required this.onCamera});

  final VoidCallback onGallery;
  final VoidCallback onCamera;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 12, 12, 4),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColours.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColours.accent.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.auto_awesome, size: 18, color: AppColours.accent),
              const SizedBox(width: 8),
              const Text(
                'Turn a photo into a canvas',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                  color: AppColours.text,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          const Text(
            'Your dog, your family, a place you went. Pick a photo and it becomes a painting '
            'you can fill in.',
            style: TextStyle(fontSize: 12, height: 1.45, color: AppColours.muted),
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: onGallery,
                  icon: const Icon(Icons.photo_library_outlined, size: 18),
                  label: const Text('From gallery'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: onCamera,
                  icon: const Icon(Icons.photo_camera_outlined, size: 18),
                  label: const Text('Take photo'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Waiting UI.
///
/// Shows elapsed time alongside the stage, because the honest answer to "how long?" is "it
/// depends on the photo" and a stalled-looking bar with no clock invites force-quitting.
class _ConvertingView extends StatefulWidget {
  const _ConvertingView({required this.progress});
  final _Progress progress;

  @override
  State<_ConvertingView> createState() => _ConvertingViewState();
}

class _ConvertingViewState extends State<_ConvertingView> {
  final Stopwatch _elapsed = Stopwatch()..start();
  late final Timer _ticker;

  @override
  void initState() {
    super.initState();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _ticker.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final seconds = _elapsed.elapsed.inSeconds;
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            SizedBox(
              width: 220,
              child: LinearProgressIndicator(
                value: widget.progress.fraction > 0 ? widget.progress.fraction : null,
                backgroundColor: const Color(0xFF2A2A30),
                minHeight: 6,
              ),
            ),
            const SizedBox(height: 20),
            Text(
              widget.progress.stage,
              style: const TextStyle(fontSize: 15, color: AppColours.text),
            ),
            const SizedBox(height: 6),
            Text(
              '${seconds}s elapsed',
              style: const TextStyle(fontSize: 12, color: AppColours.muted),
            ),
            const SizedBox(height: 18),
            const Text(
              'Finding regions and building a palette. This takes a while for a large '
              'photo — usually under a minute.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: AppColours.faint, height: 1.4),
            ),
          ],
        ),
      ),
    );
  }
}

/// Always-visible connection state.
///
/// Present because "nothing happens when I upload" was, twice, a connection problem that the UI
/// gave no hint about until after a photo had been picked. Showing it up front turns an
/// invisible precondition into something checkable at a glance.
class _ServiceStatus extends StatelessWidget {
  const _ServiceStatus({
    required this.url,
    required this.probing,
    required this.onRetry,
  });

  final String? url;
  final bool probing;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final (Color dot, String text, bool retry) = probing
        ? (AppColours.muted, 'Looking for the conversion service...', false)
        : url == null
        ? (AppColours.bad, 'No conversion service found', true)
        : (AppColours.good, 'Connected to $url', false);

    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 2, 8, 2),
      child: Row(
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(color: dot, shape: BoxShape.circle),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 11, color: AppColours.faint),
            ),
          ),
          if (retry)
            TextButton(
              onPressed: onRetry,
              child: const Text('Retry', style: TextStyle(fontSize: 11)),
            ),
        ],
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message});
  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(12, 6, 12, 0),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF3A1F22),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        message,
        style: const TextStyle(fontSize: 12, color: Color(0xFFFFC9CF)),
      ),
    );
  }
}

class _SampleTile extends StatelessWidget {
  const _SampleTile({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: const Icon(Icons.science_outlined, color: AppColours.muted),
      title: const Text(
        'Sample (bundled)',
        style: TextStyle(fontSize: 14, color: AppColours.text),
      ),
      subtitle: const Text(
        '1,266 regions, zoomable. For benchmarking, needs no server',
        style: TextStyle(fontSize: 11, color: AppColours.faint),
      ),
      onTap: onTap,
    );
  }
}

class _ArtworkTile extends StatelessWidget {
  const _ArtworkTile({
    required this.entry,
    required this.filled,
    required this.onTap,
    required this.onDelete,
  });

  final LibraryEntry entry;
  final int filled;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final total = entry.regions;
    final complete = total > 0 && filled >= total;
    final started = filled > 0;

    return ListTile(
      leading: Icon(
        complete
            ? Icons.check_circle
            : started
            ? Icons.timelapse
            : Icons.palette_outlined,
        color: complete
            ? AppColours.good
            : started
            ? AppColours.warn
            : AppColours.accent,
      ),
      title: Text(
        entry.title,
        style: const TextStyle(fontSize: 15, color: AppColours.text),
      ),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '$total regions   ${entry.colours} colours   ${entry.variant}',
            style: const TextStyle(fontSize: 11, color: AppColours.muted),
          ),
          if (started && !complete) ...[
            const SizedBox(height: 5),
            ClipRRect(
              borderRadius: BorderRadius.circular(3),
              child: LinearProgressIndicator(
                value: total == 0 ? 0 : filled / total,
                minHeight: 4,
                backgroundColor: const Color(0xFF2A2A30),
                valueColor: const AlwaysStoppedAnimation(AppColours.warn),
              ),
            ),
            const SizedBox(height: 3),
            Text(
              '$filled of $total filled',
              style: const TextStyle(fontSize: 10.5, color: AppColours.faint),
            ),
          ],
        ],
      ),
      isThreeLine: started && !complete,
      trailing: IconButton(
        icon: const Icon(Icons.delete_outline, color: AppColours.faint),
        onPressed: onDelete,
      ),
      onTap: onTap,
    );
  }
}
