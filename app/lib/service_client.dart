import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
// MediaType lives here, not in package:http. Declared explicitly in pubspec rather than
// relied on as a transitive dependency of http.
import 'package:http_parser/http_parser.dart';

/// Client for the conversion service.
///
/// The shape of this class is dictated by one fact: **conversion takes tens of seconds**, so it
/// cannot be a request/response call. Every upload becomes a job that is polled. The service
/// converts the recommended variant first, so this polls for that variant appearing rather than
/// for the whole job finishing — which is roughly a third of the wait.
class ConversionService {
  ConversionService({String? baseUrl, http.Client? client})
    : baseUrl = baseUrl ?? _fallbackBaseUrl,
      _resolved = baseUrl != null,
      _client = client ?? http.Client();

  /// Set explicitly at build time, if at all:
  ///   flutter run --dart-define=PBN_SERVICE_URL=http://192.168.1.20:8000
  ///
  /// Empty by default so [discover] can tell "the user chose this" from "nobody said".
  static const String configuredBaseUrl = String.fromEnvironment('PBN_SERVICE_URL');

  /// Used only until discovery runs, so the field is never null.
  static const String _fallbackBaseUrl = 'http://localhost:8000';

  /// Addresses to try, in order of decreasing confidence.
  ///
  /// There is no single address that works everywhere, which is what made this a recurring
  /// dead end. An emulator reaches the host at 10.0.2.2 and cannot use localhost, because
  /// inside the emulator localhost is the emulated device. A physical phone cannot use either:
  /// it needs `adb reverse tcp:8000 tcp:8000` over USB, after which localhost works — or the
  /// host's LAN address, which nothing here can guess.
  ///
  /// So rather than pick one and make the user diagnose it, try them.
  static List<String> candidates({String? saved}) {
    final ordered = <String>[
      if (saved != null && saved.trim().isNotEmpty) saved.trim(),
      if (configuredBaseUrl.isNotEmpty) configuredBaseUrl,
      // Physical device with adb reverse, and any desktop build.
      'http://localhost:8000',
      // Android emulator.
      'http://10.0.2.2:8000',
    ];
    // Preserve order while removing duplicates.
    return ordered.toSet().toList();
  }

  String baseUrl;
  bool _resolved;
  final http.Client _client;

  /// Is this address serving the conversion API?
  Future<bool> probe(String url) async {
    try {
      final response = await _client
          .get(Uri.parse('$url/healthz'))
          .timeout(const Duration(seconds: 3));
      if (response.statusCode != 200) return false;
      // Check it is actually our service and not some other thing on port 8000.
      final body = jsonDecode(response.body);
      return body is Map && body['variants'] != null;
    } catch (_) {
      return false;
    }
  }

  /// Find a reachable service, remember it, and return it.
  ///
  /// Throws [ServiceUnreachableException] naming everything tried, so a failure says what to
  /// do rather than just that it did not work.
  Future<String> discover({String? saved, bool force = false}) async {
    if (_resolved && !force) return baseUrl;
    final tried = candidates(saved: saved);
    for (final candidate in tried) {
      if (await probe(candidate)) {
        baseUrl = candidate;
        _resolved = true;
        return baseUrl;
      }
    }
    throw ServiceUnreachableException(tried.join('\n  '));
  }

  void close() => _client.close();

  /// How often to ask. Conversion runs for tens of seconds, so anything faster is just load
  /// on the server for no better answer.
  static const Duration _pollInterval = Duration(seconds: 2);

  /// Upper bound on waiting.
  ///
  /// Was 6 minutes, which real hardware exceeded: a first conversion also downloads a 176MB
  /// subject-detection model, and a modest laptop converting a 48MP photo is legitimately slow.
  /// Giving up on work that was still progressing is the worse failure, so this is now generous
  /// enough to only ever fire on a genuinely stuck worker.
  static const Duration _timeout = Duration(minutes: 25);

  /// Consecutive poll failures tolerated before giving up.
  ///
  /// Polling spans tens of seconds on a mobile connection, so a transient blip is expected
  /// rather than exceptional. Aborting on the first one would throw away a conversion that is
  /// still running perfectly well on the server.
  static const int _maxPollFailures = 5;

  /// How long a job may sit "queued" before we call it stuck. A free worker picks a job up
  /// immediately, so more than this means none will.
  static const Duration _queuedStallLimit = Duration(seconds: 90);

  /// Run a network call, converting transport failures into an explanation.
  ///
  /// This exists because `package:http` wraps socket errors in its own `ClientException`, so
  /// catching `SocketException` alone silently misses the single most common failure during
  /// development — the service not running, or bound to loopback where the emulator cannot see
  /// it. Handled here rather than in the UI so `package:http` stays behind this class.
  Future<T> _guarded<T>(Future<T> Function() call) async {
    try {
      return await call();
    } on http.ClientException catch (_) {
      throw _unreachable();
    } on SocketException catch (_) {
      throw _unreachable();
    } on TimeoutException catch (_) {
      throw _unreachable();
    }
  }

  /// Give up on the resolved address as well as failing the call.
  ///
  /// A cable gets unplugged and adb reverse dies with it, so the address that worked a minute
  /// ago may simply be gone. Clearing this makes the next attempt search again rather than
  /// stubbornly retrying somewhere nothing is listening.
  ServiceUnreachableException _unreachable() {
    _resolved = false;
    return ServiceUnreachableException(baseUrl);
  }

  /// Upload a photo and return the job id.
  ///
  /// With [deduplicate] false the service converts again even if it already holds an artwork for
  /// this photo. Rarely needed, since its cache is keyed by pipeline version as well as content.
  Future<String> upload(File photo, {bool deduplicate = true}) =>
      _guarded(() => _upload(photo, deduplicate: deduplicate));

  Future<String> _upload(File photo, {required bool deduplicate}) async {
    final request = http.MultipartRequest(
      'POST',
      Uri.parse('$baseUrl/v1/conversions?deduplicate=$deduplicate'),
    );
    final filename = photo.uri.pathSegments.last;
    request.files.add(
      await http.MultipartFile.fromPath(
        'photo',
        photo.path,
        filename: filename,
        // The service validates content type strictly and answers 415 otherwise, so this
        // cannot be left to a default of application/octet-stream.
        contentType: _mediaTypeFor(filename),
      ),
    );

    final response = await http.Response.fromStream(await _client.send(request));
    if (response.statusCode != 202) {
      throw ConversionException(_describe(response));
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return body['id'] as String;
  }

  Future<Map<String, dynamic>> status(String jobId) => _guarded(() => _status(jobId));

  Future<Map<String, dynamic>> _status(String jobId) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/v1/conversions/$jobId'),
    );
    if (response.statusCode != 200) {
      throw ConversionException(_describe(response));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  /// Poll until the variant the app will actually open is ready.
  ///
  /// Returns as soon as a variant flagged `recommended` exists, without waiting for the
  /// alternatives, which keep converting in the background.
  Future<ConversionReady> awaitRecommended(
    String jobId, {
    void Function(double progress, String stage)? onProgress,
  }) async {
    final deadline = DateTime.now().add(_timeout);
    var failures = 0;
    DateTime? queuedSince;

    while (true) {
      final Map<String, dynamic> record;
      try {
        record = await status(jobId);
        failures = 0;
      } on ServiceUnreachableException {
        // The job is server-side and unaffected by our connectivity, so a blip should cost a
        // retry rather than the whole conversion.
        if (++failures >= _maxPollFailures) rethrow;
        onProgress?.call(0.0, 'Reconnecting');
        await Future<void>.delayed(_pollInterval);
        continue;
      }
      final state = record['status'] as String;

      if (state == 'failed') {
        throw ConversionException(
          (record['error'] as String?) ?? 'conversion failed',
        );
      }

      final variants = (record['variants'] as Map<String, dynamic>? ?? const {});
      final ready = _pickRecommended(variants);
      if (ready != null) {
        final summary = variants[ready] as Map<String, dynamic>;
        return ConversionReady(
          jobId: jobId,
          variant: ready,
          regions: summary['regions'] as int? ?? 0,
          colours: summary['colours'] as int? ?? 0,
        );
      }

      if (state == 'succeeded') {
        // Succeeded with no usable variant means the contract was broken, not that we
        // should keep polling forever.
        throw ConversionException('conversion produced no variants');
      }

      // A job that stays queued has no worker, and waiting longer will not produce one. Worth
      // separating from a slow conversion because the causes are unrelated: a stuck queue is a
      // server problem, while "running" and slow is just a big photo.
      if (state == 'queued') {
        queuedSince ??= DateTime.now();
        if (DateTime.now().difference(queuedSince) > _queuedStallLimit) {
          throw ConversionException(
            'The service accepted the photo but never started converting it. '
            'Its worker pool may be wedged — restart the service and try again.',
          );
        }
      } else {
        queuedSince = null;
      }

      onProgress?.call(
        (record['progress'] as num?)?.toDouble() ?? 0.0,
        state == 'queued' ? 'Waiting for a worker' : 'Converting your photo',
      );

      if (DateTime.now().isAfter(deadline)) {
        throw ConversionException('conversion timed out after ${_timeout.inMinutes} minutes');
      }
      await Future<void>.delayed(_pollInterval);
    }
  }

  /// The variant the service marked recommended, else any that is present.
  static String? _pickRecommended(Map<String, dynamic> variants) {
    if (variants.isEmpty) return null;
    for (final entry in variants.entries) {
      final summary = entry.value;
      if (summary is Map<String, dynamic> && summary['recommended'] == true) {
        return entry.key;
      }
    }
    return null;
  }

  /// Download a bundle into [target].
  ///
  /// Written to a sibling `.partial` directory and renamed on success, so an interrupted
  /// download cannot leave a truncated `regions.png` behind. That failure mode would be
  /// permanent and confusing: the artwork would appear in the library and throw on every
  /// attempt to open it.
  Future<Directory> download(
    String jobId,
    String variant,
    Directory target, {
    void Function(double progress, String stage)? onProgress,
  }) {
    return _guarded(
      () => _download(jobId, variant, target, onProgress: onProgress),
    );
  }

  Future<Directory> _download(
    String jobId,
    String variant,
    Directory target, {
    void Function(double progress, String stage)? onProgress,
  }) async {
    final partial = Directory('${target.path}.partial');
    if (await partial.exists()) await partial.delete(recursive: true);
    await partial.create(recursive: true);

    // regions.png is the larger of the two and the one the canvas cannot work without.
    const files = ['meta.json', 'regions.png'];
    for (var i = 0; i < files.length; i++) {
      final name = files[i];
      onProgress?.call(i / files.length, 'Downloading artwork');
      final response = await _client.get(
        Uri.parse('$baseUrl/v1/conversions/$jobId/$variant/$name'),
      );
      if (response.statusCode != 200) {
        await partial.delete(recursive: true);
        throw ConversionException('could not download $name: ${_describe(response)}');
      }
      await File('${partial.path}/$name').writeAsBytes(response.bodyBytes);
    }

    if (await target.exists()) await target.delete(recursive: true);
    await partial.rename(target.path);
    return target;
  }

  static String _describe(http.Response response) {
    try {
      final body = jsonDecode(response.body);
      if (body is Map && body['detail'] != null) {
        return '${response.statusCode}: ${body['detail']}';
      }
    } catch (_) {
      // Not JSON; fall through to the status line.
    }
    return 'HTTP ${response.statusCode}';
  }
}

/// Map an extension to a type the service accepts.
///
/// Needed because the allowed set is explicit server-side. HEIC matters in particular: it is
/// the default capture format on iPhones, so rejecting it would reject a large share of real
/// photo libraries.
MediaType _mediaTypeFor(String filename) {
  final dot = filename.lastIndexOf('.');
  final extension = dot == -1 ? '' : filename.substring(dot + 1).toLowerCase();
  return switch (extension) {
    'png' => MediaType('image', 'png'),
    'webp' => MediaType('image', 'webp'),
    'heic' => MediaType('image', 'heic'),
    'heif' => MediaType('image', 'heif'),
    // jpg, jpeg, and anything unrecognised. The picker overwhelmingly yields JPEG, and the
    // service decodes by content rather than trusting the label.
    _ => MediaType('image', 'jpeg'),
  };
}

/// A variant that finished and can be opened.
class ConversionReady {
  const ConversionReady({
    required this.jobId,
    required this.variant,
    required this.regions,
    required this.colours,
  });

  final String jobId;
  final String variant;
  final int regions;
  final int colours;
}

class ConversionException implements Exception {
  const ConversionException(this.message);
  final String message;

  @override
  String toString() => message;
}

/// The service could not be contacted at all.
///
/// Separate from a general failure because the fix is specific, and because the underlying
/// transport errors name no address — which makes them read as a bug in the app rather than as a
/// service that cannot be reached.
class ServiceUnreachableException extends ConversionException {
  ServiceUnreachableException(this.addresses) : super(_describeUnreachable(addresses));

  /// One address, or several separated by newlines when discovery tried a list.
  final String addresses;
}

String _describeUnreachable(String addresses) =>
    'Could not reach the conversion service.\n\n'
    'Tried:\n  $addresses\n\n'
    'ON A PHONE CONNECTED BY USB — run this on your computer, then retry:\n'
    '  adb reverse tcp:8000 tcp:8000\n'
    'That forwards the phone\'s localhost:8000 to your computer. It has to be re-run whenever '
    'the phone reconnects.\n\n'
    'ON THE SAME WI-FI INSTEAD — start the service with --host 0.0.0.0 and set the address '
    'manually from the menu, using your computer\'s LAN address, e.g. http://192.168.1.20:8000\n\n'
    'ON AN EMULATOR — 10.0.2.2 is the host, never localhost, and is tried automatically.\n\n'
    'Also check the service is actually running.';
