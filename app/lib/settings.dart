import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// Tiny persisted settings store.
///
/// A plain file rather than a preferences package: there is exactly one value, and it is not
/// worth a dependency. It lives beside the artwork library for the same reason that does —
/// losing it would mean re-entering a service address by hand.
class Settings {
  Settings(this._file);

  final File _file;

  static Future<Settings> open() async {
    final documents = await getApplicationDocumentsDirectory();
    return Settings(File('${documents.path}/service_url.txt'));
  }

  /// The address the user set explicitly, or null.
  Future<String?> serviceUrl() async {
    try {
      if (!await _file.exists()) return null;
      final value = (await _file.readAsString()).trim();
      return value.isEmpty ? null : value;
    } catch (_) {
      return null;
    }
  }

  Future<void> setServiceUrl(String? url) async {
    try {
      if (url == null || url.trim().isEmpty) {
        if (await _file.exists()) await _file.delete();
        return;
      }
      await _file.writeAsString(url.trim());
    } catch (_) {
      // A settings write failing should not take down a conversion.
    }
  }
}
