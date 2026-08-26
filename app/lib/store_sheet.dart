import 'package:flutter/material.dart';

import 'theme.dart';

/// The store, as an explicit placeholder.
///
/// Currency is displayed and earned locally, which is fine for a single-player loop, but a store
/// cannot ship on top of that. Two dependencies are missing and neither is small:
///
/// * **Real purchases** need RevenueCat (or hand-rolled receipt validation on both stores).
/// * **Server-authoritative balances.** A coin count kept in a local JSON file is editable by
///   anyone with a rooted device or a file manager. Selling anything against it means selling
///   something a player can mint for free, and once purchases are involved that is a refund
///   problem rather than a cheating problem.
///
/// Showing an empty, honest sheet beats showing a grid of items that cannot be bought.
void showStoreSheet(BuildContext context) {
  showModalBottomSheet<void>(
    context: context,
    backgroundColor: AppColours.raised,
    showDragHandle: true,
    builder: (context) => const SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(24, 4, 24, 28),
        child: NotBuiltYet(
          icon: Icons.storefront_outlined,
          title: 'Store',
          what:
              'Cosmetic packs, hint consumables and premium story chapters, bought with coins, '
              'gems or real money.',
          blockedOn:
              'purchases through RevenueCat, and balances held on a server rather than in a '
              'local file a player can edit',
        ),
      ),
    ),
  );
}
