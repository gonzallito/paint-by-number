import 'package:flutter/material.dart';

import 'app_shell.dart';
import 'artwork.dart';
import 'canvas_view.dart';
import 'daily.dart';
import 'palette_tray.dart';
import 'player.dart';
import 'progress.dart';
import 'store_sheet.dart';
import 'theme.dart';

/// The daily hub. The painting *is* the screen — the player paints here, in place.
///
/// Three constraints shape this layout, and all three come from the daily canvas being
/// non-zoomable:
///
/// 1. **Nothing paintable may sit under permanent chrome.** The canvas occupies the space between
///    the header and the palette tray, never behind them. On a zoomable canvas an occluded region
///    is reachable by panning; here it would simply be unpaintable, and the streak depends on the
///    canvas being finishable.
/// 2. **Floating cards must be dismissible.** Quest cards overlay the top of the artwork, which is
///    what makes the screen feel like a hub rather than a canvas, so they collapse on the first
///    tap and can be brought back.
/// 3. **It is kept alive.** This widget lives inside the shell's [IndexedStack] and is never
///    disposed, because reloading the bundle costs a visible pause on every return to Home.
class HomeTab extends StatefulWidget {
  const HomeTab({super.key, required this.services});

  final AppServices services;

  @override
  State<HomeTab> createState() => _HomeTabState();
}

class _HomeTabState extends State<HomeTab> with WidgetsBindingObserver {
  Artwork? _artwork;
  Object? _error;
  PaletteColour? _selected;

  ProgressWriter? _writer;

  /// The day this canvas and its progress belong to.
  String _day = currentDay();

  /// Floating quest cards. Hidden after the first tap on the artwork.
  bool _hudExpanded = true;

  /// True once the completion reward has been recorded for this canvas, so reopening a finished
  /// daily neither pays twice nor shows the celebration again.
  bool _rewarded = false;

  /// Set when this session is the one that finished it, so the celebration shows once.
  int? _coinsAwarded;

  final CanvasStats _stats = CanvasStats();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _load();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _writer?.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) return;
    // An app left open across midnight would otherwise keep yesterday's canvas and quest
    // counters, and the streak could not advance.
    widget.services.player.rollOverIfNewDay();
    if (currentDay() != _day) {
      _reload();
    } else if (mounted) {
      setState(() {});
    }
  }

  Future<void> _reload() async {
    await _writer?.dispose();
    _writer = null;
    if (!mounted) return;
    setState(() {
      _artwork = null;
      _rewarded = false;
      _coinsAwarded = null;
      _hudExpanded = true;
    });
    await _load();
  }

  Future<void> _load() async {
    final day = currentDay();
    final services = widget.services;
    try {
      final artwork = await Artwork.load(kTodaysDaily.source);
      final key = kTodaysDaily.progressKeyFor(day);

      final saved = await services.progress.load(key, artwork.regionCount);
      if (saved != null) artwork.restoreFillState(saved);

      final writer = ProgressWriter(
        store: services.progress,
        key: key,
        snapshot: () => artwork.fillState,
      );

      if (!mounted) {
        await writer.dispose();
        return;
      }
      setState(() {
        _day = day;
        _artwork = artwork;
        _writer = writer;
        _selected = _nextUnfinishedColour(artwork);
        // A daily reopened after being finished must not re-award. The streak itself is also
        // guarded by date inside PlayerStore, but XP and the completion count are not.
        _rewarded = artwork.isComplete;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error);
    }
  }

  /// The colour with the most regions left, or null when the canvas is finished.
  ///
  /// Most-remaining rather than lowest-numbered so the first thing the player is offered is the
  /// easiest to find, and auto-advance never lands on a colour with a single sliver left.
  PaletteColour? _nextUnfinishedColour(Artwork artwork) {
    PaletteColour? best;
    var bestRemaining = 0;
    for (final entry in artwork.palette) {
      final remaining = artwork.remainingFor(entry);
      if (remaining > bestRemaining) {
        bestRemaining = remaining;
        best = entry;
      }
    }
    return best;
  }

  void _onRegionFilled(int regionId, bool correct) {
    final artwork = _artwork;
    if (artwork == null) return;

    final player = widget.services.player;

    // Any tap on the artwork clears the floating cards, including a wrong one: the player has
    // started painting either way, and a card sitting over the region they just missed is the
    // most likely reason they missed it.
    final collapsing = _hudExpanded;

    if (!correct) {
      if (collapsing) setState(() => _hudExpanded = false);
      return;
    }

    player.recordRegionPainted();
    _writer?.markDirty();

    var selected = _selected;
    if (selected != null && artwork.remainingFor(selected) == 0) {
      player.recordColourCompleted();
      // Auto-advance, so finishing a colour does not leave the player tapping a dead swatch.
      selected = _nextUnfinishedColour(artwork);
    }

    int? awarded;
    if (artwork.isComplete && !_rewarded) {
      _rewarded = true;
      awarded = player.recordCanvasCompleted(isDaily: true);
      // Flushed immediately rather than on the debounce. This is the one write whose loss the
      // player would actually notice, because it carries the streak.
      _writer?.flush();
      player.flush();
    }

    setState(() {
      _selected = selected;
      if (collapsing) _hudExpanded = false;
      if (awarded != null) _coinsAwarded = awarded;
    });
  }

  @override
  Widget build(BuildContext context) {
    final artwork = _artwork;
    final player = widget.services.player;

    return SafeArea(
      // The navigation bar already handles the bottom inset.
      bottom: false,
      child: Column(
        children: [
          _Header(player: player, onStore: () => showStoreSheet(context)),
          Expanded(
            child: _error != null
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Text(
                        "Today's canvas could not be loaded:\n$_error",
                        textAlign: TextAlign.center,
                        style: const TextStyle(fontSize: 13, color: AppColours.muted),
                      ),
                    ),
                  )
                : artwork == null
                ? const Center(child: CircularProgressIndicator())
                : Stack(
                    children: [
                      // The canvas fills this box and nothing permanent overlaps it.
                      Positioned.fill(
                        child: CanvasView(
                          artwork: artwork,
                          selectedColour: _selected,
                          onRegionFilled: _onRegionFilled,
                          stats: _stats,
                          // The whole point of the daily format.
                          zoomable: false,
                        ),
                      ),
                      Positioned(
                        left: 12,
                        top: 12,
                        right: 12,
                        child: _QuestOverlay(
                          expanded: _hudExpanded,
                          quests: player.dailyQuests,
                          filled: artwork.filledCount,
                          total: artwork.regionCount,
                          title: kTodaysDaily.title,
                          onToggle: () => setState(() => _hudExpanded = !_hudExpanded),
                        ),
                      ),
                      if (_coinsAwarded != null)
                        Positioned.fill(
                          child: _CompletionCard(
                            coins: _coinsAwarded!,
                            streak: player.streak,
                            onDismiss: () => setState(() => _coinsAwarded = null),
                          ),
                        ),
                    ],
                  ),
          ),
          if (artwork != null)
            PaletteTray(
              artwork: artwork,
              selected: _selected,
              onSelected: (entry) => setState(() => _selected = entry),
            ),
        ],
      ),
    );
  }
}

/// Avatar, level and XP on the left; currency on the right. A real bar, not an overlay, so the
/// canvas below it is never occluded.
class _Header extends StatelessWidget {
  const _Header({required this.player, required this.onStore});

  final PlayerStore player;
  final VoidCallback onStore;

  @override
  Widget build(BuildContext context) {
    final into = player.xpIntoLevel;
    final needed = player.xpForNextLevel;

    return Container(
      color: AppColours.surface,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      child: Row(
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: AppColours.accent.withValues(alpha: 0.22),
              shape: BoxShape.circle,
              border: Border.all(color: AppColours.accent, width: 1.5),
            ),
            alignment: Alignment.center,
            child: const Icon(Icons.brush, size: 19, color: AppColours.accent),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  children: [
                    Text(
                      player.name,
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: AppColours.text,
                      ),
                    ),
                    const SizedBox(width: 6),
                    Text(
                      'Lv ${player.level}',
                      style: const TextStyle(fontSize: 11, color: AppColours.muted),
                    ),
                  ],
                ),
                const SizedBox(height: 5),
                ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: LinearProgressIndicator(
                    value: needed == 0 ? 0 : (into / needed).clamp(0.0, 1.0),
                    minHeight: 5,
                    backgroundColor: const Color(0xFF2A2A30),
                    valueColor: const AlwaysStoppedAnimation(AppColours.accent),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          _StreakPill(streak: player.streak, doneToday: player.dailyCompletedToday),
          const SizedBox(width: 6),
          GestureDetector(
            onTap: onStore,
            child: Row(
              children: [
                _CurrencyPill(
                  icon: Icons.monetization_on,
                  colour: AppColours.coin,
                  value: player.coins,
                ),
                const SizedBox(width: 6),
                _CurrencyPill(
                  icon: Icons.diamond,
                  colour: AppColours.gem,
                  value: player.gems,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CurrencyPill extends StatelessWidget {
  const _CurrencyPill({required this.icon, required this.colour, required this.value});

  final IconData icon;
  final Color colour;
  final int value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
      decoration: BoxDecoration(
        color: AppColours.raised,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        children: [
          Icon(icon, size: 13, color: colour),
          const SizedBox(width: 4),
          Text(
            '$value',
            style: const TextStyle(
              fontSize: 11.5,
              fontWeight: FontWeight.w600,
              color: AppColours.text,
            ),
          ),
        ],
      ),
    );
  }
}

class _StreakPill extends StatelessWidget {
  const _StreakPill({required this.streak, required this.doneToday});

  final int streak;
  final bool doneToday;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
      decoration: BoxDecoration(
        color: AppColours.raised,
        borderRadius: BorderRadius.circular(999),
        // Outlined only once today's canvas is done, so the pill answers "am I safe today?"
        // rather than just showing a number.
        border: doneToday ? Border.all(color: AppColours.streak, width: 1) : null,
      ),
      child: Row(
        children: [
          Icon(
            Icons.local_fire_department,
            size: 13,
            color: doneToday ? AppColours.streak : AppColours.faint,
          ),
          const SizedBox(width: 4),
          Text(
            '$streak',
            style: const TextStyle(
              fontSize: 11.5,
              fontWeight: FontWeight.w600,
              color: AppColours.text,
            ),
          ),
        ],
      ),
    );
  }
}

/// Quest cards over the artwork, collapsible to a single chip.
class _QuestOverlay extends StatelessWidget {
  const _QuestOverlay({
    required this.expanded,
    required this.quests,
    required this.filled,
    required this.total,
    required this.title,
    required this.onToggle,
  });

  final bool expanded;
  final List<Quest> quests;
  final int filled;
  final int total;
  final String title;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    if (!expanded) {
      return Align(
        alignment: Alignment.topLeft,
        child: GestureDetector(
          onTap: onToggle,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: AppColours.surface.withValues(alpha: 0.92),
              borderRadius: BorderRadius.circular(999),
              border: Border.all(color: const Color(0x22FFFFFF)),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.checklist, size: 13, color: AppColours.muted),
                const SizedBox(width: 6),
                Text(
                  '$filled/$total',
                  style: const TextStyle(
                    fontSize: 11.5,
                    fontFeatures: [FontFeature.tabularFigures()],
                    color: AppColours.muted,
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    }

    return Align(
      alignment: Alignment.topLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 260),
        decoration: BoxDecoration(
          color: AppColours.surface.withValues(alpha: 0.94),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0x22FFFFFF)),
        ),
        padding: const EdgeInsets.fromLTRB(12, 10, 8, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    title,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColours.text,
                    ),
                  ),
                ),
                GestureDetector(
                  onTap: onToggle,
                  child: const Padding(
                    padding: EdgeInsets.all(4),
                    child: Icon(Icons.close, size: 15, color: AppColours.faint),
                  ),
                ),
              ],
            ),
            Text(
              '$filled of $total regions',
              style: const TextStyle(fontSize: 11, color: AppColours.faint),
            ),
            const SizedBox(height: 10),
            for (final quest in quests) ...[
              _QuestRow(quest: quest),
              const SizedBox(height: 6),
            ],
            const SizedBox(height: 2),
            const Text(
              'Tap the artwork to start. Cards get out of the way.',
              style: TextStyle(fontSize: 10.5, height: 1.3, color: AppColours.faint),
            ),
          ],
        ),
      ),
    );
  }
}

class _QuestRow extends StatelessWidget {
  const _QuestRow({required this.quest});

  final Quest quest;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(
          quest.done ? Icons.check_circle : Icons.radio_button_unchecked,
          size: 14,
          color: quest.done ? AppColours.good : AppColours.faint,
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            quest.title,
            style: TextStyle(
              fontSize: 11.5,
              color: quest.done ? AppColours.muted : AppColours.text,
              decoration: quest.done ? TextDecoration.lineThrough : null,
              decorationColor: AppColours.muted,
            ),
          ),
        ),
        Text(
          quest.done ? '+${quest.reward}' : '${quest.progress}/${quest.target}',
          style: TextStyle(
            fontSize: 11,
            fontFeatures: const [FontFeature.tabularFigures()],
            color: quest.done ? AppColours.coin : AppColours.faint,
          ),
        ),
      ],
    );
  }
}

/// Shown once, when the daily is finished.
class _CompletionCard extends StatelessWidget {
  const _CompletionCard({
    required this.coins,
    required this.streak,
    required this.onDismiss,
  });

  final int coins;
  final int streak;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onDismiss,
      child: ColoredBox(
        color: const Color(0xCC000000),
        child: Center(
          child: Container(
            margin: const EdgeInsets.symmetric(horizontal: 36),
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 26),
            decoration: BoxDecoration(
              color: AppColours.raised,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: const Color(0x33FFFFFF)),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.local_fire_department, size: 40, color: AppColours.streak),
                const SizedBox(height: 12),
                Text(
                  streak == 1 ? 'Streak started' : '$streak day streak',
                  style: const TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w600,
                    color: AppColours.text,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  "Today's canvas is finished.",
                  style: const TextStyle(fontSize: 13, color: AppColours.muted),
                ),
                const SizedBox(height: 16),
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.monetization_on, size: 17, color: AppColours.coin),
                    const SizedBox(width: 6),
                    Text(
                      '+$coins',
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: AppColours.coin,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 18),
                Text(
                  'Tap to close',
                  style: const TextStyle(fontSize: 11, color: AppColours.faint),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
