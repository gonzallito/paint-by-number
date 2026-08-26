import 'package:flutter/material.dart';

/// Shared palette for app chrome.
///
/// Collected here because the same greys were hardcoded in five widgets, and the canvas is the one
/// place where an exact value matters: the region outline colour and the checkerboard greys are
/// chosen to read correctly against arbitrary fill colours, so they live with the canvas rather
/// than here.
///
/// Dark by default. The artwork is a bright white page and it should be the brightest thing on
/// screen — chrome that competes with it makes the canvas look grey.
abstract final class AppColours {
  static const Color background = Color(0xFF101012);
  static const Color surface = Color(0xFF17171A);
  static const Color raised = Color(0xFF1E1E22);
  static const Color tray = Color(0xFF1C1C1E);

  static const Color text = Color(0xFFE8E8EE);
  static const Color muted = Color(0xFF8A8A94);
  static const Color faint = Color(0xFF6E6E78);

  static const Color accent = Color(0xFF9A9AF0);
  static const Color good = Color(0xFF6BDF8A);
  static const Color warn = Color(0xFFFFC08A);
  static const Color bad = Color(0xFFFF6B7A);

  static const Color coin = Color(0xFFF2C14E);
  static const Color gem = Color(0xFF6FD3E8);
  static const Color streak = Color(0xFFFF9A5C);
}

/// A section heading used across the browser tabs.
class SectionHeader extends StatelessWidget {
  const SectionHeader({super.key, required this.title, this.trailing, this.subtitle});

  final String title;
  final String? subtitle;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 16, right: 8, top: 18, bottom: 8),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 0.4,
                    color: AppColours.muted,
                  ),
                ),
                if (subtitle != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(
                      subtitle!,
                      style: const TextStyle(fontSize: 11, color: AppColours.faint),
                    ),
                  ),
              ],
            ),
          ),
          ?trailing,
        ],
      ),
    );
  }
}

/// Explains a feature that is not built yet, and says what it is waiting on.
///
/// Deliberately not fake UI. A mocked friends list or a store full of unbuyable items reads as
/// broken and, worse, hides the fact that the feature has an unmet dependency.
class NotBuiltYet extends StatelessWidget {
  const NotBuiltYet({
    super.key,
    required this.icon,
    required this.title,
    required this.what,
    required this.blockedOn,
  });

  final IconData icon;
  final String title;

  /// What the feature will do, in the player's terms.
  final String what;

  /// The dependency that has to exist first, in the builder's terms.
  final String blockedOn;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, size: 44, color: AppColours.faint),
            const SizedBox(height: 16),
            Text(
              title,
              style: const TextStyle(
                fontSize: 17,
                fontWeight: FontWeight.w600,
                color: AppColours.text,
              ),
            ),
            const SizedBox(height: 10),
            Text(
              what,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 13, height: 1.45, color: AppColours.muted),
            ),
            const SizedBox(height: 20),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: AppColours.surface,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: const Color(0x22FFFFFF)),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(Icons.link_off, size: 14, color: AppColours.warn),
                  const SizedBox(width: 8),
                  Flexible(
                    child: Text(
                      'Needs first: $blockedOn',
                      style: const TextStyle(
                        fontSize: 11.5,
                        height: 1.4,
                        color: AppColours.warn,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
