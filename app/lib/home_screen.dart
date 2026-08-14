import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import 'artwork.dart';
import 'artwork_screen.dart';
import 'library.dart';
import 'service_client.dart';
import 'settings.dart';

/// Entry point of the app: convert a photo, or reopen something already converted.
///
/// Conversion runs for tens of seconds, so this screen's main job is to make waiting
/// legible — what stage it is at, and roughly how far along. A bare spinner for 40 seconds
/// reads as a hang.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final ConversionService _service = ConversionService();
  final ImagePicker _picker = ImagePicker();

  ArtworkLibrary? _library;
  List<LibraryEntry> _entries = const [];

  Settings? _settings;

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
    _openLibrary();
  }

  @override
  void dispose() {
    _service.close();
    super.dispose();
  }

  Future<void> _openLibrary() async {
    final library = await ArtworkLibrary.open();
    final entries = await library.list();
    final settings = await Settings.open();
    final saved = await settings.serviceUrl();
    if (!mounted) return;
    setState(() {
      _library = library;
      _entries = entries;
      _settings = settings;
      _savedUrl = saved;
    });
    // Find the service now rather than at upload time, so a connection problem is visible
    // before the user picks a photo instead of after.
    await _discover();
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

  Future<void> _editServiceUrl() async {
    final controller = TextEditingController(text: _savedUrl ?? '');
    final entered = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF1E1E22),
        title: const Text('Conversion service address'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Leave empty to detect automatically. Set this when the phone and computer are '
              'on the same Wi-Fi: use the computer\'s LAN address, and start the service with '
              '--host 0.0.0.0',
              style: TextStyle(fontSize: 12, color: Color(0xFF8A8A94)),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              autocorrect: false,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(
                hintText: 'http://192.168.1.20:8000',
                isDense: true,
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(controller.text),
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (entered == null) return;

    await _settings?.setServiceUrl(entered);
    if (!mounted) return;
    setState(() => _savedUrl = entered.trim().isEmpty ? null : entered.trim());
    await _discover(force: true);
  }

  Future<void> _convert(ImageSource source) async {
    final library = _library;
    if (library == null) return;

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
      // Re-check rather than trusting the launch-time result: a USB cable gets replugged, adb
      // reverse gets lost, the laptop changes network.
      final url = await _service.discover(saved: _savedUrl);
      if (mounted) {
        setState(() {
          _serviceUrl = url;
          _progress = const _Progress(0.0, 'Uploading photo');
        });
      }

      final jobId = await _service.upload(File(picked.path));

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
        library.bundleDir(ready.jobId, ready.variant),
      );

      final entry = await library.save(
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
        backgroundColor: const Color(0xFF1E1E22),
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
    final library = _library;
    if (library == null) return;

    if (!await library.hasBundle(entry.jobId, entry.variant)) {
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
          source: DirectoryBundleSource(library.bundleDir(entry.jobId, entry.variant)),
        ),
      ),
    );
  }

  void _openSample() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => const ArtworkScreen(
          title: 'Sample (bundled)',
          source: AssetBundleSource(kArtworkAsset),
        ),
      ),
    );
  }

  Future<void> _delete(LibraryEntry entry) async {
    await _library?.delete(entry.jobId);
    if (!mounted) return;
    setState(() => _entries = _entries.where((e) => e.jobId != entry.jobId).toList());
  }

  @override
  Widget build(BuildContext context) {
    final progress = _progress;

    return Scaffold(
      backgroundColor: const Color(0xFF101012),
      appBar: AppBar(
        title: const Text('Paint by Number'),
        backgroundColor: const Color(0xFF17171A),
        actions: [
          IconButton(
            tooltip: 'Conversion service address',
            icon: const Icon(Icons.settings_ethernet),
            onPressed: _editServiceUrl,
          ),
        ],
      ),
      body: SafeArea(
        child: progress != null
            ? _ConvertingView(progress: progress)
            : Column(
                children: [
                  _ServiceStatus(
                    url: _serviceUrl,
                    probing: _probing,
                    onRetry: () => _discover(force: true),
                    onEdit: _editServiceUrl,
                  ),
                  if (_error != null) _ErrorBanner(message: _error!),
                  _ConvertButtons(
                    onGallery: () => _convert(ImageSource.gallery),
                    onCamera: () => _convert(ImageSource.camera),
                  ),
                  Expanded(
                    child: _entries.isEmpty
                        ? _EmptyLibrary(onSample: _openSample)
                        : ListView.builder(
                            itemCount: _entries.length + 1,
                            itemBuilder: (context, index) {
                              if (index == _entries.length) {
                                return _SampleTile(onTap: _openSample);
                              }
                              final entry = _entries[index];
                              return _ArtworkTile(
                                entry: entry,
                                onTap: () => _open(entry),
                                onDelete: () => _delete(entry),
                              );
                            },
                          ),
                  ),
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
              style: const TextStyle(fontSize: 15, color: Color(0xFFE8E8EE)),
            ),
            const SizedBox(height: 6),
            Text(
              '${seconds}s elapsed',
              style: const TextStyle(fontSize: 12, color: Color(0xFF8A8A94)),
            ),
            const SizedBox(height: 18),
            const Text(
              'Finding regions and building a palette. This takes a while for a large '
              'photo — usually under a minute.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: Color(0xFF6E6E78), height: 1.4),
            ),
          ],
        ),
      ),
    );
  }
}

class _ConvertButtons extends StatelessWidget {
  const _ConvertButtons({required this.onGallery, required this.onCamera});
  final VoidCallback onGallery;
  final VoidCallback onCamera;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Expanded(
            child: FilledButton.icon(
              onPressed: onGallery,
              icon: const Icon(Icons.photo_library_outlined),
              label: const Text('From gallery'),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: OutlinedButton.icon(
              onPressed: onCamera,
              icon: const Icon(Icons.photo_camera_outlined),
              label: const Text('Take photo'),
            ),
          ),
        ],
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
    required this.onEdit,
  });

  final String? url;
  final bool probing;
  final VoidCallback onRetry;
  final VoidCallback onEdit;

  @override
  Widget build(BuildContext context) {
    if (probing) {
      return const _StatusBar(
        colour: Color(0xFF23232A),
        dot: Color(0xFF8A8A94),
        text: 'Looking for the conversion service...',
      );
    }
    if (url == null) {
      return _StatusBar(
        colour: const Color(0xFF3A1F22),
        dot: const Color(0xFFFF6B7A),
        text: 'No conversion service found',
        action: TextButton(onPressed: onRetry, child: const Text('Retry')),
        secondary: TextButton(onPressed: onEdit, child: const Text('Set address')),
      );
    }
    return _StatusBar(
      colour: const Color(0xFF1B2A1F),
      dot: const Color(0xFF6BDF8A),
      text: 'Connected to $url',
    );
  }
}

class _StatusBar extends StatelessWidget {
  const _StatusBar({
    required this.colour,
    required this.dot,
    required this.text,
    this.action,
    this.secondary,
  });

  final Color colour;
  final Color dot;
  final String text;
  final Widget? action;
  final Widget? secondary;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: colour,
      padding: const EdgeInsets.only(left: 12, right: 4, top: 6, bottom: 6),
      child: Row(
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: dot, shape: BoxShape.circle),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              text,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 11, color: Color(0xFFB8B8C0)),
            ),
          ),
          ?secondary,
          ?action,
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
      color: const Color(0xFF3A1F22),
      padding: const EdgeInsets.all(12),
      child: Text(
        message,
        style: const TextStyle(fontSize: 12, color: Color(0xFFFFC9CF)),
      ),
    );
  }
}

class _EmptyLibrary extends StatelessWidget {
  const _EmptyLibrary({required this.onSample});
  final VoidCallback onSample;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Text(
              'No artworks yet',
              style: TextStyle(fontSize: 16, color: Color(0xFFE8E8EE)),
            ),
            const SizedBox(height: 8),
            const Text(
              'Pick a photo above to turn it into a paintable canvas.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: Color(0xFF8A8A94)),
            ),
            const SizedBox(height: 24),
            TextButton(
              onPressed: onSample,
              child: const Text('Open the bundled sample'),
            ),
          ],
        ),
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
      leading: const Icon(Icons.science_outlined, color: Color(0xFF8A8A94)),
      title: const Text(
        'Sample (bundled)',
        style: TextStyle(fontSize: 14, color: Color(0xFFB8B8C0)),
      ),
      subtitle: const Text(
        'For benchmarking, needs no server',
        style: TextStyle(fontSize: 11, color: Color(0xFF6E6E78)),
      ),
      onTap: onTap,
    );
  }
}

class _ArtworkTile extends StatelessWidget {
  const _ArtworkTile({
    required this.entry,
    required this.onTap,
    required this.onDelete,
  });

  final LibraryEntry entry;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: const Icon(Icons.palette_outlined, color: Color(0xFF9A9AF0)),
      title: Text(
        entry.title,
        style: const TextStyle(fontSize: 15, color: Color(0xFFE8E8EE)),
      ),
      subtitle: Text(
        '${entry.regions} regions   ${entry.colours} colours   ${entry.variant}',
        style: const TextStyle(fontSize: 11, color: Color(0xFF8A8A94)),
      ),
      trailing: IconButton(
        icon: const Icon(Icons.delete_outline, color: Color(0xFF6E6E78)),
        onPressed: onDelete,
      ),
      onTap: onTap,
    );
  }
}
