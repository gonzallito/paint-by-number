import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// Tiny persisted settings store.
///
/// A JSON file rather than a preferences package: there are two values, and neither is worth a
/// dependency. It lives beside the artwork library for the same reason that does — losing it
/// would mean re-entering a service address by hand.
class Settings {
  Settings(this._file, this._values);

  final File _file;
  final Map<String, dynamic> _values;

  static Future<Settings> open() async {
    final documents = await getApplicationDocumentsDirectory();
    final file = File('${documents.path}/settings.json');
    Map<String, dynamic> values = {};
    try {
      if (await file.exists()) {
        final decoded = jsonDecode(await file.readAsString());
        if (decoded is Map<String, dynamic>) values = decoded;
      }
    } catch (_) {
      // Corrupt settings should mean defaults, not a broken app.
    }
    return Settings(file, values);
  }

  /// The address the user set explicitly, or null to detect automatically.
  String? get serviceUrl {
    final value = _values['service_url'];
    if (value is! String || value.trim().isEmpty) return null;
    return value.trim();
  }

  /// Skip the server's deduplication and convert again from scratch.
  ///
  /// Normally unnecessary: the service reuses a previous conversion only when the pipeline that
  /// produced it still matches, so an improvement reaches an old photo on its own. This exists
  /// for comparing runs while the pipeline is being changed.
  bool get alwaysReconvert => _values['always_reconvert'] == true;

  Future<void> setServiceUrl(String? url) =>
      _write('service_url', (url == null || url.trim().isEmpty) ? null : url.trim());

  Future<void> setAlwaysReconvert(bool value) => _write('always_reconvert', value);

  Future<void> _write(String key, Object? value) async {
    if (value == null) {
      _values.remove(key);
    } else {
      _values[key] = value;
    }
    try {
      await _file.writeAsString(jsonEncode(_values));
    } catch (_) {
      // A settings write failing should not take down a conversion.
    }
  }
}
