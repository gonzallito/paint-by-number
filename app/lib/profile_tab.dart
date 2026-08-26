import 'package:flutter/material.dart';

import 'app_shell.dart';
import 'library.dart';
import 'library_tab.dart';
import 'player.dart';
import 'settings_screen.dart';
import 'theme.dart';

/// One achievement, derived from a lifetime counter.
///
/// Computed on read from counters the player store already keeps, never stored as an unlocked
/// list. That means a badge cannot end up out of step with the stats beside it, and adding a new
/// badge retroactively credits players who already earned it.
class Badge {
  const Badge({
    required this.icon,
    required this.title,
    required this.detail,
    required this.earned,
  });

  final IconData icon;
  final String title;
  final String detail;
  final bool earned;
}

/// Profile: who the player is, what they have done, and where settings live.
///
/// Settings sits here as a gear in the header rather than as a sixth tab. Bottom navigation is the
/// most valuable space in the app and a settings screen is opened rarely; giving it a tab would
/// cost a gameplay mode its place.
class ProfileTab extends StatefulWidget {
  const ProfileTab({super.key, required this.services, required this.onBrowseLibrary});

  final AppServices services;

  /// Sends the player to the Library tab from the empty gallery state.
  final VoidCallback onBrowseLibrary;

  @override
  State<ProfileTab> createState() => _ProfileTabState();
}

class _ProfileTabState extends State<ProfileTab> {
  List<LibraryEntry> _completed = const [];
  int _inProgress = 0;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  /// Completion is read from saved progress, not from a flag on the artwork.
  ///
  /// There is no "finished" bit to keep in sync: an artwork is complete when every region in its
  /// progress bytes is non-zero, which is derivable and cannot disagree with the canvas.
  Future<void> _refresh() async {
    final entries = await widget.services.library.list();
    final completed = <LibraryEntry>[];
    var started = 0;
    for (final entry in entries) {
      final bytes = await widget.services.progress.load(
        artworkProgressKey(entry),
        entry.regions,
      );
      if (bytes == null) continue;
      var filled = 0;
      for (final value in bytes) {
        if (value != 0) filled++;
      }
      if (filled == 0) continue;
      if (filled >= entry.regions) {
        completed.add(entry);
      } else {
        started++;
      }
    }
    if (!mounted) return;
    setState(() {
      _completed = completed;
      _inProgress = started;
    });
  }

  List<Badge> _badges(PlayerStore player) => [
    Badge(
      icon: Icons.brush,
      title: 'First strokes',
      detail: 'Fill your first region',
      earned: player.regionsPaintedTotal >= 1,
    ),
    Badge(
      icon: Icons.grid_on,
      title: 'Hundred',
      detail: 'Fill 100 regions',
      earned: player.regionsPaintedTotal >= 100,
    ),
    Badge(
      icon: Icons.workspace_premium,
      title: 'Thousand',
      detail: 'Fill 1,000 regions',
      earned: player.regionsPaintedTotal >= 1000,
    ),
    Badge(
      icon: Icons.check_circle,
      title: 'Finisher',
      detail: 'Complete a painting',
      earned: player.paintingsCompleted >= 1,
    ),
    Badge(
      icon: Icons.local_fire_department,
      title: 'Three in a row',
      detail: '3 day streak',
      earned: player.longestStreak >= 3,
    ),
    Badge(
      icon: Icons.calendar_month,
      title: 'A full week',
      detail: '7 day streak',
      earned: player.longestStreak >= 7,
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final player = widget.services.player;
    final badges = _badges(player);
    final earned = badges.where((b) => b.earned).length;

    return Scaffold(
      backgroundColor: AppColours.background,
      appBar: AppBar(
        title: const Text('Profile'),
        backgroundColor: AppColours.surface,
        toolbarHeight: 48,
        actions: [
          IconButton(
            tooltip: 'Settings',
            icon: const Icon(Icons.settings_outlined),
            onPressed: () async {
              await Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => SettingsScreen(services: widget.services),
                ),
              );
              if (mounted) setState(() {});
            },
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          padding: const EdgeInsets.only(bottom: 24),
          children: [
            _IdentityCard(player: player),
            _StatRow(player: player, completed: _completed.length, inProgress: _inProgress),

            const SectionHeader(
              title: 'FOLLOWERS',
              subtitle: 'Needs accounts before it can mean anything',
            ),
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 16),
              child: Text(
                'Following and followers stay at zero until the service has real users. It '
                'currently issues device tokens, which cannot identify a person across two '
                'phones or survive a reinstall.',
                style: TextStyle(fontSize: 12, height: 1.5, color: AppColours.faint),
              ),
            ),

            SectionHeader(title: 'ACHIEVEMENTS', subtitle: '$earned of ${badges.length} earned'),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [for (final badge in badges) _BadgeChip(badge: badge)],
              ),
            ),

            SectionHeader(
              title: 'FINISHED',
              subtitle: _completed.isEmpty ? null : '${_completed.length} paintings',
            ),
            if (_completed.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Nothing finished yet. Completed paintings are collected here.',
                      style: TextStyle(fontSize: 12, height: 1.45, color: AppColours.faint),
                    ),
                    const SizedBox(height: 10),
                    OutlinedButton(
                      onPressed: widget.onBrowseLibrary,
                      child: const Text('Go to the library'),
                    ),
                  ],
                ),
              )
            else
              for (final entry in _completed)
                ListTile(
                  leading: const Icon(Icons.check_circle, color: AppColours.good),
                  title: Text(
                    entry.title,
                    style: const TextStyle(fontSize: 14, color: AppColours.text),
                  ),
                  subtitle: Text(
                    '${entry.regions} regions   ${entry.colours} colours',
                    style: const TextStyle(fontSize: 11, color: AppColours.faint),
                  ),
                ),
            if (_completed.isNotEmpty)
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 8, 16, 0),
                child: Text(
                  'Shown as a list rather than a thumbnail grid: the pipeline renders a preview '
                  'image for curated content, but the upload path does not download one yet.',
                  style: TextStyle(fontSize: 11, height: 1.45, color: AppColours.faint),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _IdentityCard extends StatelessWidget {
  const _IdentityCard({required this.player});

  final PlayerStore player;

  @override
  Widget build(BuildContext context) {
    final into = player.xpIntoLevel;
    final needed = player.xpForNextLevel;

    return Container(
      margin: const EdgeInsets.fromLTRB(12, 12, 12, 0),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColours.surface,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        children: [
          Container(
            width: 58,
            height: 58,
            decoration: BoxDecoration(
              color: AppColours.accent.withValues(alpha: 0.22),
              shape: BoxShape.circle,
              border: Border.all(color: AppColours.accent, width: 2),
            ),
            alignment: Alignment.center,
            child: const Icon(Icons.brush, size: 28, color: AppColours.accent),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  player.name,
                  style: const TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w600,
                    color: AppColours.text,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  'Level ${player.level}   $into / $needed XP',
                  style: const TextStyle(fontSize: 12, color: AppColours.muted),
                ),
                const SizedBox(height: 8),
                ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: LinearProgressIndicator(
                    value: needed == 0 ? 0 : (into / needed).clamp(0.0, 1.0),
                    minHeight: 6,
                    backgroundColor: const Color(0xFF2A2A30),
                    valueColor: const AlwaysStoppedAnimation(AppColours.accent),
                  ),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Avatar customisation is not built. One placeholder mark for now.',
                  style: TextStyle(fontSize: 10.5, color: AppColours.faint),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _StatRow extends StatelessWidget {
  const _StatRow({
    required this.player,
    required this.completed,
    required this.inProgress,
  });

  final PlayerStore player;
  final int completed;
  final int inProgress;

  @override
  Widget build(BuildContext context) {
    final cells = <(IconData, Color, String, String)>[
      (
        Icons.local_fire_department,
        AppColours.streak,
        '${player.streak}',
        'streak',
      ),
      (
        Icons.emoji_events_outlined,
        AppColours.warn,
        '${player.longestStreak}',
        'longest',
      ),
      (Icons.grid_on, AppColours.accent, '${player.regionsPaintedTotal}', 'regions'),
      (Icons.check_circle_outline, AppColours.good, '$completed', 'finished'),
      (Icons.timelapse, AppColours.warn, '$inProgress', 'in progress'),
    ];

    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
      child: Row(
        children: [
          for (final (icon, colour, value, label) in cells)
            Expanded(
              child: Container(
                margin: const EdgeInsets.symmetric(horizontal: 2),
                padding: const EdgeInsets.symmetric(vertical: 10),
                decoration: BoxDecoration(
                  color: AppColours.surface,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Column(
                  children: [
                    Icon(icon, size: 16, color: colour),
                    const SizedBox(height: 5),
                    Text(
                      value,
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        color: AppColours.text,
                      ),
                    ),
                    const SizedBox(height: 1),
                    Text(
                      label,
                      textAlign: TextAlign.center,
                      style: const TextStyle(fontSize: 9.5, color: AppColours.faint),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _BadgeChip extends StatelessWidget {
  const _BadgeChip({required this.badge});

  final Badge badge;

  @override
  Widget build(BuildContext context) {
    final colour = badge.earned ? AppColours.coin : AppColours.faint;
    return Container(
      width: 108,
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
      decoration: BoxDecoration(
        color: AppColours.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: badge.earned ? colour.withValues(alpha: 0.55) : const Color(0x18FFFFFF),
        ),
      ),
      child: Column(
        children: [
          Icon(badge.earned ? badge.icon : Icons.lock_outline, size: 18, color: colour),
          const SizedBox(height: 6),
          Text(
            badge.title,
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: badge.earned ? AppColours.text : AppColours.muted,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            badge.detail,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 9.5, height: 1.3, color: AppColours.faint),
          ),
        ],
      ),
    );
  }
}
