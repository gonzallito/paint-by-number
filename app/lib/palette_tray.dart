import 'package:flutter/material.dart';

import 'artwork.dart';

/// Horizontally scrolling colour tray.
///
/// Scrolling is not a detail: palettes reach 70-95 entries, and a linear strip stops being
/// legible past roughly 48. A fixed-width row would compress the numbers into an unreadable
/// smear, which is exactly what happened when the pipeline's own contact sheets tried it.
class PaletteTray extends StatelessWidget {
  const PaletteTray({
    super.key,
    required this.artwork,
    required this.selected,
    required this.onSelected,
  });

  final Artwork artwork;
  final PaletteColour? selected;
  final ValueChanged<PaletteColour> onSelected;

  static const double _swatch = 54;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: _swatch + 26,
      color: const Color(0xFF1C1C1E),
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        itemCount: artwork.palette.length,
        separatorBuilder: (context, index) => const SizedBox(width: 8),
        itemBuilder: (context, index) {
          final entry = artwork.palette[index];
          final remaining = artwork.remainingFor(entry);
          final isSelected = selected?.number == entry.number;
          return _Swatch(
            entry: entry,
            remaining: remaining,
            isSelected: isSelected,
            size: _swatch,
            onTap: () => onSelected(entry),
          );
        },
      ),
    );
  }
}

class _Swatch extends StatelessWidget {
  const _Swatch({
    required this.entry,
    required this.remaining,
    required this.isSelected,
    required this.size,
    required this.onTap,
  });

  final PaletteColour entry;
  final int remaining;
  final bool isSelected;
  final double size;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    // A colour with nothing left to fill is dimmed rather than removed: removing entries
    // would reshuffle the tray under the user's finger mid-session.
    final done = remaining == 0;
    final luma = 0.299 * entry.red + 0.587 * entry.green + 0.114 * entry.blue;
    final label = luma > 140 ? const Color(0xFF141414) : const Color(0xFFF5F5F5);

    return GestureDetector(
      onTap: done ? null : onTap,
      child: Opacity(
        opacity: done ? 0.32 : 1.0,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: size,
              height: size,
              decoration: BoxDecoration(
                color: entry.colour,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(
                  color: isSelected ? const Color(0xFFFFFFFF) : const Color(0x33FFFFFF),
                  width: isSelected ? 3 : 1,
                ),
              ),
              alignment: Alignment.center,
              child: Text(
                '${entry.number}',
                style: TextStyle(
                  color: label,
                  fontSize: 17,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            const SizedBox(height: 4),
            Text(
              done ? '✓' : '$remaining',
              style: const TextStyle(color: Color(0xFF9A9AA0), fontSize: 11),
            ),
          ],
        ),
      ),
    );
  }
}
