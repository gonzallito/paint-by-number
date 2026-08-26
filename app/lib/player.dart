import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/widgets.dart';
import 'package:path_provider/path_provider.dart';

/// A day key in the player's own timezone, `yyyy-mm-dd`.
///
/// Local rather than UTC on purpose: a streak is about the player's day. A UTC boundary would
/// break the streak at 1am for anyone east of Greenwich, which reads as a bug and is one.
String dayKey(DateTime when) {
  final local = when.toLocal();
  final month = local.month.toString().padLeft(2, '0');
  final day = local.day.toString().padLeft(2, '0');
  return '${local.year}-$month-$day';
}

/// One quest, always an **aggregate counter**.
///
/// Never colour-specific. "Colour 5 green regions" breaks silently when today's art has no green,
/// cannot be rebuilt from saved progress after a crash, and needs the palette stored beside it.
/// "Paint 20 regions" has none of those problems.
class Quest {
  const Quest({
    required this.id,
    required this.title,
    required this.target,
    required this.progress,
    required this.reward,
  });

  final String id;
  final String title;
  final int target;
  final int progress;

  /// Coins paid on completion.
  final int reward;

  bool get done => progress >= target;
  double get fraction => target == 0 ? 1.0 : (progress / target).clamp(0.0, 1.0);
}

/// Persisted meta-game state: streak, level, currency and the counters quests read from.
///
/// Deliberately **not** on the canvas hot path. A fill calls [recordRegionPainted], which
/// increments integers in memory and arms a debounce; nothing here touches a widget rebuild or a
/// file write per tap. Routing per-tap state through a state layer previously cost 119ms per tap
/// on the test device, and that must not come back.
class PlayerStore with WidgetsBindingObserver {
  PlayerStore(this._file, this._values) {
    WidgetsBinding.instance.addObserver(this);
  }

  final File _file;
  final Map<String, dynamic> _values;

  Timer? _timer;
  bool _dirty = false;

  static const Duration _debounce = Duration(seconds: 2);

  /// Coins for finishing the daily canvas.
  static const int dailyCoinReward = 50;

  /// XP per region filled, and the bonus for finishing a canvas.
  static const int xpPerRegion = 2;
  static const int xpPerCanvas = 40;

  static Future<PlayerStore> open() async {
    final documents = await getApplicationDocumentsDirectory();
    final file = File('${documents.path}/player.json');
    Map<String, dynamic> values = {};
    try {
      if (await file.exists()) {
        final decoded = jsonDecode(await file.readAsString());
        if (decoded is Map<String, dynamic>) values = decoded;
      }
    } catch (_) {
      // Corrupt player state means a fresh start, not a broken app.
    }
    final store = PlayerStore(file, values);
    store.rollOverIfNewDay();
    return store;
  }

  int _int(String key) {
    final value = _values[key];
    return value is int ? value : 0;
  }

  String? _string(String key) {
    final value = _values[key];
    return value is String && value.isNotEmpty ? value : null;
  }

  // --- identity ---------------------------------------------------------------------------

  String get name => _string('name') ?? 'Painter';
  Future<void> setName(String value) => _write('name', value.trim());

  /// Index into the avatar set. Customisation is a placeholder: one seed value, no wardrobe.
  int get avatar => _int('avatar');
  Future<void> setAvatar(int index) => _write('avatar', index);

  // --- progression ------------------------------------------------------------------------

  int get xp => _int('xp');
  int get coins => _int('coins');
  int get gems => _int('gems');

  int get regionsPaintedTotal => _int('regions_painted_total');
  int get paintingsCompleted => _int('paintings_completed');

  int get streak => _int('streak');
  int get longestStreak => _int('longest_streak');
  String? get lastDailyCompleted => _string('last_daily_completed');

  bool get dailyCompletedToday => lastDailyCompleted == dayKey(DateTime.now());

  /// XP needed to go from [level] to the next one. Grows linearly, so early levels come quickly
  /// and later ones do not become absurd.
  static int xpForLevelUp(int level) => 200 * level;

  /// Total XP required to have reached [level]. Closed form of the sum above.
  static int xpToReachLevel(int level) => 100 * level * (level - 1);

  int get level {
    var candidate = 1;
    // Bounded rather than while(true): a corrupt XP value should not spin forever.
    while (candidate < 999 && xp >= xpToReachLevel(candidate + 1)) {
      candidate++;
    }
    return candidate;
  }

  int get xpIntoLevel => xp - xpToReachLevel(level);
  int get xpForNextLevel => xpForLevelUp(level);

  // --- today's counters -------------------------------------------------------------------

  int get regionsPaintedToday => _int('regions_today');
  int get coloursCompletedToday => _int('colours_today');

  /// Zero today's counters when the calendar day has changed.
  ///
  /// Called on open and again whenever the daily is inspected, because an app left running
  /// overnight would otherwise keep yesterday's counters and show completed quests all day.
  void rollOverIfNewDay() {
    final today = dayKey(DateTime.now());
    if (_string('counter_day') == today) return;
    _values['counter_day'] = today;
    _values['regions_today'] = 0;
    _values['colours_today'] = 0;
    markDirty();
  }

  // --- quests -----------------------------------------------------------------------------

  /// Evaluated from counters on read, never accumulated per tap.
  List<Quest> get dailyQuests => [
    Quest(
      id: 'paint-30',
      title: 'Paint 30 regions',
      target: 30,
      progress: regionsPaintedToday,
      reward: 15,
    ),
    Quest(
      id: 'colours-3',
      title: 'Finish 3 colours',
      target: 3,
      progress: coloursCompletedToday,
      reward: 20,
    ),
    Quest(
      id: 'daily',
      title: "Complete today's canvas",
      target: 1,
      progress: dailyCompletedToday ? 1 : 0,
      reward: dailyCoinReward,
    ),
  ];

  // --- recording --------------------------------------------------------------------------

  /// One region filled. Cheap by design; see the class doc.
  void recordRegionPainted() {
    _values['regions_painted_total'] = regionsPaintedTotal + 1;
    _values['regions_today'] = regionsPaintedToday + 1;
    _values['xp'] = xp + xpPerRegion;
    markDirty();
  }

  void recordColourCompleted() {
    _values['colours_today'] = coloursCompletedToday + 1;
    markDirty();
  }

  /// A canvas finished. Returns the coins awarded, so the caller can show them.
  int recordCanvasCompleted({required bool isDaily}) {
    _values['paintings_completed'] = paintingsCompleted + 1;
    _values['xp'] = xp + xpPerCanvas;
    var awarded = 0;
    if (isDaily) awarded = _advanceStreak();
    markDirty();
    return awarded;
  }

  /// Extend, restart or leave the streak, and pay the daily reward once per day.
  int _advanceStreak() {
    final today = dayKey(DateTime.now());
    if (lastDailyCompleted == today) return 0; // already counted; never pay twice

    final yesterday = dayKey(DateTime.now().subtract(const Duration(days: 1)));
    final next = lastDailyCompleted == yesterday ? streak + 1 : 1;

    _values['streak'] = next;
    _values['longest_streak'] = next > longestStreak ? next : longestStreak;
    _values['last_daily_completed'] = today;
    _values['coins'] = coins + dailyCoinReward;
    return dailyCoinReward;
  }

  Future<void> addCoins(int amount) => _write('coins', coins + amount);

  // --- persistence ------------------------------------------------------------------------

  void markDirty() {
    _dirty = true;
    _timer?.cancel();
    _timer = Timer(_debounce, flush);
  }

  Future<void> flush() async {
    if (!_dirty) return;
    _dirty = false;
    _timer?.cancel();
    _timer = null;
    try {
      await _file.writeAsString(jsonEncode(_values), flush: true);
    } catch (_) {
      // A failed write must not interrupt painting; the next debounce retries.
    }
  }

  Future<void> _write(String key, Object? value) async {
    if (value == null) {
      _values.remove(key);
    } else {
      _values[key] = value;
    }
    _dirty = true;
    await flush();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) flush();
  }

  void dispose() {
    _timer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    flush();
  }
}
