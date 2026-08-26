import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/widgets.dart';
import 'package:path_provider/path_provider.dart';

/// Persisted painting progress, one file per canvas.
///
/// The payload is **one byte per region**, holding the 1-based palette number the region was
/// filled with and 0 for unfilled — exactly the array the canvas already keeps in memory. For a
/// typical 1,266-region canvas that is 1,266 bytes.
///
/// Three deliberate choices, all from `docs/APP-SPEC.md`:
///
/// * **A byte array, not JSON and not a row per region.** JSON of the same data is an order of
///   magnitude larger and has to be parsed; a row per region turns one save into a thousand
///   writes.
/// * **State, not an event log.** A region-to-colour array is idempotent: writing it twice, or
///   writing a stale copy, converges to something valid. A log has to be replayed and can desync.
/// * **The documents directory, never a cache directory.** The OS evicts caches under storage
///   pressure, and sessions here run 30-90 minutes. Losing one that way would be indefensible.
///
/// Writes are debounced *and* flushed on lifecycle change — see [ProgressWriter]. A debounce
/// alone loses the tail of a session, which is precisely when sessions end.
class ProgressStore {
  ProgressStore(this.root);

  final Directory root;

  static Future<ProgressStore> open() async {
    final documents = await getApplicationDocumentsDirectory();
    final root = Directory('${documents.path}/progress');
    if (!await root.exists()) await root.create(recursive: true);
    return ProgressStore(root);
  }

  /// Canvas keys are bundle paths, so they contain separators and colons. Flattened to a safe
  /// filename rather than nesting directories, because the key is opaque to this layer.
  static String _fileName(String key) {
    final safe = key.replaceAll(RegExp(r'[^A-Za-z0-9._-]'), '_');
    return '$safe.bin';
  }

  File fileFor(String key) => File('${root.path}/${_fileName(key)}');

  /// Saved state, or null when this canvas has never been painted.
  ///
  /// Returns null on a length mismatch as well. That happens when a canvas is rebuilt with a
  /// different region count, and applying the old bytes would colour arbitrary regions — a
  /// corrupted painting is worse than a lost one.
  Future<Uint8List?> load(String key, int regionCount) async {
    final file = fileFor(key);
    try {
      if (!await file.exists()) return null;
      final bytes = await file.readAsBytes();
      if (bytes.length != regionCount) return null;
      return bytes;
    } catch (_) {
      return null;
    }
  }

  Future<void> save(String key, Uint8List state) async {
    try {
      // Written to a sibling then renamed, so an interrupted write cannot leave a truncated
      // file that would silently fail the length check and discard a finished painting.
      final target = fileFor(key);
      final temporary = File('${target.path}.partial');
      await temporary.writeAsBytes(state, flush: true);
      await temporary.rename(target.path);
    } catch (_) {
      // A failed save must not interrupt painting. The next debounce tick retries.
    }
  }

  Future<void> delete(String key) async {
    try {
      final file = fileFor(key);
      if (await file.exists()) await file.delete();
    } catch (_) {
      // Nothing useful to do; a stale progress file is harmless.
    }
  }
}

/// Debounced writer for one canvas, with a guaranteed flush on lifecycle change.
///
/// Saving on every tap would put a file write on the interaction path; saving only on dispose
/// loses everything if the process is killed while backgrounded, which is the normal way a mobile
/// app ends. So: coalesce rapid fills into one write, and flush unconditionally when the app
/// leaves the foreground or the canvas closes.
///
/// [markDirty] is called from the fill path and must stay cheap — it resets a timer and nothing
/// else. The byte array is read lazily inside [flush], not captured per tap.
class ProgressWriter with WidgetsBindingObserver {
  ProgressWriter({
    required this.store,
    required this.key,
    required this.snapshot,
    this.debounce = const Duration(seconds: 2),
  }) {
    WidgetsBinding.instance.addObserver(this);
  }

  final ProgressStore store;
  final String key;

  /// Reads current fill state at flush time.
  final Uint8List Function() snapshot;

  final Duration debounce;

  Timer? _timer;
  bool _dirty = false;
  bool _disposed = false;

  void markDirty() {
    if (_disposed) return;
    _dirty = true;
    _timer?.cancel();
    _timer = Timer(debounce, flush);
  }

  Future<void> flush() async {
    if (!_dirty) return;
    _dirty = false;
    _timer?.cancel();
    _timer = null;
    await store.save(key, snapshot());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // inactive covers the iOS app switcher and an incoming call; paused and detached cover
    // Android backgrounding. All three are moments the process may not come back from.
    if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached ||
        state == AppLifecycleState.hidden) {
      flush();
    }
  }

  /// Flushes any pending write, then stops observing. Safe to call more than once.
  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    _timer?.cancel();
    _timer = null;
    WidgetsBinding.instance.removeObserver(this);
    if (_dirty) {
      _dirty = false;
      await store.save(key, snapshot());
    }
  }
}
