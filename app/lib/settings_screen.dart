import 'package:flutter/material.dart';

import 'app_shell.dart';
import 'daily.dart';
import 'theme.dart';

/// Global settings, reached from the gear in the Profile header.
///
/// Split into player-facing options and a **developer** section. The two are not the same thing:
/// the conversion service address and the re-convert override exist to work on the pipeline from a
/// phone on the same Wi-Fi, and putting them beside a player's display name would present internal
/// plumbing as a normal preference.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, required this.services});

  final AppServices services;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  @override
  Widget build(BuildContext context) {
    final services = widget.services;
    final player = services.player;
    final settings = services.settings;

    return Scaffold(
      backgroundColor: AppColours.background,
      appBar: AppBar(
        title: const Text('Settings'),
        backgroundColor: AppColours.surface,
        toolbarHeight: 48,
      ),
      body: ListView(
        padding: const EdgeInsets.only(bottom: 32),
        children: [
          const SectionHeader(title: 'PLAYER'),
          ListTile(
            leading: const Icon(Icons.badge_outlined, color: AppColours.muted),
            title: const Text(
              'Display name',
              style: TextStyle(fontSize: 14, color: AppColours.text),
            ),
            subtitle: Text(
              player.name,
              style: const TextStyle(fontSize: 12, color: AppColours.muted),
            ),
            onTap: _editName,
          ),

          const SectionHeader(title: 'ACCESSIBILITY'),
          const ListTile(
            leading: Icon(Icons.contrast, color: AppColours.faint),
            title: Text(
              'High-contrast numbering',
              style: TextStyle(fontSize: 14, color: AppColours.muted),
            ),
            subtitle: Text(
              'Not built. Needed for colour vision deficiency, where two palette entries can '
              'look identical and only the printed number distinguishes them.',
              style: TextStyle(fontSize: 11.5, height: 1.4, color: AppColours.faint),
            ),
            enabled: false,
          ),

          const SectionHeader(title: 'TODAY'),
          ListTile(
            leading: const Icon(Icons.restart_alt, color: AppColours.muted),
            title: const Text(
              "Reset today's canvas",
              style: TextStyle(fontSize: 14, color: AppColours.text),
            ),
            subtitle: const Text(
              'Clears your painting on the daily so you can start it again. Your streak and '
              'coins are not affected.',
              style: TextStyle(fontSize: 11.5, height: 1.4, color: AppColours.muted),
            ),
            onTap: _resetDaily,
          ),

          const SectionHeader(
            title: 'DEVELOPER',
            subtitle: 'Pipeline plumbing, not player options',
          ),
          ListTile(
            leading: const Icon(Icons.lan_outlined, color: AppColours.muted),
            title: const Text(
              'Conversion service address',
              style: TextStyle(fontSize: 14, color: AppColours.text),
            ),
            subtitle: Text(
              settings.serviceUrl ?? 'Detected automatically',
              style: const TextStyle(fontSize: 12, color: AppColours.muted),
            ),
            onTap: _editServiceUrl,
          ),
          SwitchListTile(
            value: settings.alwaysReconvert,
            onChanged: (value) async {
              await settings.setAlwaysReconvert(value);
              if (mounted) setState(() {});
            },
            title: const Text(
              'Always re-convert',
              style: TextStyle(fontSize: 14, color: AppColours.text),
            ),
            subtitle: const Text(
              'Skip the service\'s deduplication and convert from scratch. For comparing runs '
              'while the pipeline is being changed.',
              style: TextStyle(fontSize: 11.5, height: 1.4, color: AppColours.muted),
            ),
          ),

          const SectionHeader(title: 'ABOUT'),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 16),
            child: Text(
              'Paint by Number, development build.\n'
              'Artifact format version 2. Progress is stored on this device only — there is no '
              'account and no cloud backup yet, so clearing app data loses your paintings.',
              style: TextStyle(fontSize: 11.5, height: 1.5, color: AppColours.faint),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _editName() async {
    final controller = TextEditingController(
      text: widget.services.player.name,
    );
    final entered = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AppColours.raised,
        title: const Text('Display name'),
        content: TextField(
          controller: controller,
          autofocus: true,
          maxLength: 24,
          decoration: const InputDecoration(isDense: true),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(controller.text),
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (entered == null || entered.trim().isEmpty) return;
    await widget.services.player.setName(entered);
    if (mounted) setState(() {});
  }

  Future<void> _resetDaily() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AppColours.raised,
        title: const Text("Reset today's canvas?"),
        content: const Text(
          'Your painting on it will be cleared. Reopen the Today tab to see the blank canvas.',
          style: TextStyle(fontSize: 13, height: 1.4),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Reset'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    await widget.services.progress.delete(
      kTodaysDaily.progressKeyFor(currentDay()),
    );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text(
          "Today's canvas has been reset. It reloads next time the app starts.",
        ),
      ),
    );
  }

  Future<void> _editServiceUrl() async {
    final settings = widget.services.settings;
    final controller = TextEditingController(text: settings.serviceUrl ?? '');
    final entered = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AppColours.raised,
        title: const Text('Conversion service address'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Leave empty to detect automatically. Set this when the phone and computer are '
              'on the same Wi-Fi: use the computer\'s LAN address, and start the service with '
              '--host 0.0.0.0',
              style: TextStyle(fontSize: 12, color: AppColours.muted),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              autocorrect: false,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(
                hintText: 'http://192.168.1.20:8000',
                isDense: true,
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(controller.text),
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (entered == null) return;
    await settings.setServiceUrl(entered);
    if (mounted) setState(() {});
  }
}
