import 'package:flutter/material.dart';

import 'theme.dart';

/// Story mode: the world map.
///
/// Not built. The blocker is content, not code — the map needs authored chapter art, and each
/// node's canvas has to be converted and reviewed through `pbn build` before it can be published.
/// The conversion half of that already exists; the art does not.
///
/// Left as a placeholder rather than a mocked map because a node graph with no canvases behind it
/// would have to be thrown away once the real chapter structure exists.
class StoryTab extends StatelessWidget {
  const StoryTab({super.key});

  @override
  Widget build(BuildContext context) {
    return const SafeArea(
      bottom: false,
      child: NotBuiltYet(
        icon: Icons.map_outlined,
        title: 'Story',
        what:
            'A map of islands and villages. Finishing paintings restores places, unlocks '
            'chapters and earns companions, so painting is progression rather than a menu.',
        blockedOn:
            'authored chapter art, each piece converted and reviewed through the content '
            'pipeline. The pipeline is ready; the artwork is not',
      ),
    );
  }
}

/// Social: shared canvases, friends, invites.
///
/// Blocked on something that genuinely does not exist yet: accounts. The conversion service uses
/// lightweight device tokens and has no notion of a user, so friends, followers and shared canvases
/// have nothing to hang off.
///
/// One useful finding recorded here so it is not rediscovered: **a shared canvas cannot diverge.**
/// Every region has exactly one correct colour and a wrong tap does nothing, so co-op painting is a
/// grow-only set — a CRDT. Any order, any duplicate, any replay converges to the identical canvas.
/// No operational transform and no vector clocks are needed. Ordering only matters for *credit*:
/// who filled a region first and therefore earned the XP.
class SocialTab extends StatelessWidget {
  const SocialTab({super.key});

  @override
  Widget build(BuildContext context) {
    return const SafeArea(
      bottom: false,
      child: NotBuiltYet(
        icon: Icons.people_outline,
        title: 'Social',
        what:
            'Paint the same canvas with a friend in real time, follow people, and share finished '
            'work by link or QR code.',
        blockedOn:
            'real accounts. The service has device tokens and no users, so there is nothing for '
            'friends or shared canvases to attach to',
      ),
    );
  }
}
