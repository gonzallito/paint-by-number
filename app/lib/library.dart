import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// On-device store of converted artworks.
///
/// Layout, under the app's documents directory:
///
///     artworks/<jobId>/manifest.json      small summary, for listing
///     artworks/<jobId>/<variant>/meta.json
///     artworks/<jobId>/<variant>/regions.png
///
/// The manifest exists so the library can be listed without touching the bundles. `meta.json`
/// is around 385KB per artwork, so parsing every one to draw a list would make the home screen
/// slower the more the user converts — exactly backwards.
///
/// Documents directory rather than a cache directory: these are the user's artworks and their
/// progress, not a cache. The OS may evict caches under storage pressure, and losing a
/// half-finished 90-minute painting that way would be indefensible.
class ArtworkLibrary {
  ArtworkLibrary(this.root);

  final Directory root;

  static Future<ArtworkLibrary> open() async {
    final documents = await getApplicationDocumentsDirectory();
    final root = Directory('${documents.path}/artworks');
    if (!await root.exists()) await root.create(recursive: true);
    return ArtworkLibrary(root);
  }

  Directory artworkDir(String jobId) => Directory('${root.path}/$jobId');

  Directory bundleDir(String jobId, String variant) =>
      Directory('${root.path}/$jobId/$variant');

  /// Newest first, since the artwork someone just made is the one they want.
  Future<List<LibraryEntry>> list() async {
    if (!await root.exists()) return const [];

    final entries = <LibraryEntry>[];
    await for (final child in root.list()) {
      if (child is! Directory) continue;
      // Skip interrupted downloads; see ConversionService.download.
      if (child.path.endsWith('.partial')) continue;

      final manifest = File('${child.path}/manifest.json');
      if (!await manifest.exists()) continue;
      try {
        final json = jsonDecode(await manifest.readAsString()) as Map<String, dynamic>;
        entries.add(LibraryEntry.fromJson(json));
      } catch (_) {
        // A corrupt manifest should hide one artwork, not break the whole library.
        continue;
      }
    }
    entries.sort((a, b) => b.createdAt.compareTo(a.createdAt));
    return entries;
  }

  Future<LibraryEntry> save({
    required String jobId,
    required String variant,
    required int regions,
    required int colours,
    required String title,
  }) async {
    final entry = LibraryEntry(
      jobId: jobId,
      variant: variant,
      regions: regions,
      colours: colours,
      title: title,
      createdAt: DateTime.now(),
    );
    final directory = artworkDir(jobId);
    if (!await directory.exists()) await directory.create(recursive: true);
    await File('${directory.path}/manifest.json')
        .writeAsString(jsonEncode(entry.toJson()));
    return entry;
  }

  Future<void> delete(String jobId) async {
    final directory = artworkDir(jobId);
    if (await directory.exists()) await directory.delete(recursive: true);
  }

  /// True when the bundle is on disk, so an artwork can be reopened without the network.
  Future<bool> hasBundle(String jobId, String variant) {
    return File('${bundleDir(jobId, variant).path}/regions.png').exists();
  }
}

class LibraryEntry {
  const LibraryEntry({
    required this.jobId,
    required this.variant,
    required this.regions,
    required this.colours,
    required this.title,
    required this.createdAt,
  });

  final String jobId;
  final String variant;
  final int regions;
  final int colours;
  final String title;
  final DateTime createdAt;

  Map<String, dynamic> toJson() => {
    'job_id': jobId,
    'variant': variant,
    'regions': regions,
    'colours': colours,
    'title': title,
    'created_at': createdAt.toIso8601String(),
  };

  static LibraryEntry fromJson(Map<String, dynamic> json) => LibraryEntry(
    jobId: json['job_id'] as String,
    variant: json['variant'] as String? ?? 'detailed',
    regions: json['regions'] as int? ?? 0,
    colours: json['colours'] as int? ?? 0,
    title: json['title'] as String? ?? 'Artwork',
    createdAt:
        DateTime.tryParse(json['created_at'] as String? ?? '') ?? DateTime(2000),
  );
}
