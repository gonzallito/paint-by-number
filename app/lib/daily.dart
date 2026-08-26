import 'artwork.dart';
import 'player.dart';

/// The daily canvas: a small, fixed, non-zoomable painting that drives the streak.
///
/// This is a **different format** from a library or photo canvas, not the same canvas with
/// different settings. Because it cannot zoom, every region must be tappable and every number
/// legible at fit-to-screen. The pipeline's `daily` content profile enforces exactly that at build
/// time — region count, colour count, and every region's on-screen radius at 1080x1400 — and
/// rejects art that misses it. Pointing this at a bundle built for any other profile would produce
/// a painting that cannot be finished.
class DailyCanvas {
  const DailyCanvas({
    required this.id,
    required this.title,
    required this.assetDirectory,
  });

  final String id;
  final String title;

  /// Asset path of the artifact bundle, holding `regions.png` and `meta.json`.
  final String assetDirectory;

  BundleSource get source => AssetBundleSource(assetDirectory);

  /// Progress key, scoped to the calendar day.
  ///
  /// The day is part of the key on purpose. Only one piece of daily art is bundled today, so
  /// without the day every subsequent daily would open already finished and the streak could
  /// never advance past one. Keying by day makes each day a fresh canvas, which is the real
  /// behaviour once the art actually rotates.
  String progressKeyFor(String day) => 'daily-$day-$id';
}

/// Today's canvas.
///
/// A single bundled asset, so the same art appears every day. That is a placeholder, not the
/// design: the real source is a static daily manifest on the CDN, which does not exist yet.
/// Everything downstream of here — streak, quests, rewards, progress scoping — already behaves
/// as though the art rotates.
const DailyCanvas kTodaysDaily = DailyCanvas(
  id: 'green-uniform',
  title: 'Green Uniform',
  assetDirectory: 'assets/daily/green-uniform',
);

/// Today's key, recomputed rather than cached so a session spanning midnight is handled.
String currentDay() => dayKey(DateTime.now());
