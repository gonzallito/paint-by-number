import 'package:flutter/material.dart';

import 'library.dart';
import 'library_tab.dart';
import 'home_tab.dart';
import 'placeholders.dart';
import 'player.dart';
import 'profile_tab.dart';
import 'progress.dart';
import 'settings.dart';
import 'theme.dart';

/// The stores every tab needs, opened once at startup.
///
/// Passed down explicitly rather than through an inherited widget or a provider. There are four of
/// them, they are created once and never replaced, and the canvas hot path must not acquire a
/// dependency on a state framework — routing per-tap work through one previously cost 119ms per
/// tap on the test device.
class AppServices {
  const AppServices({
    required this.player,
    required this.progress,
    required this.library,
    required this.settings,
  });

  final PlayerStore player;
  final ProgressStore progress;
  final ArtworkLibrary library;
  final Settings settings;
}

/// Five tabs with a persistent bottom bar, Home in the centre.
///
/// **Tabs hold browsers; a canvas is a route you push.** That is a memory constraint, not a
/// preference: a zoomable canvas costs roughly 78MB, so three tabs each holding one would reach
/// ~233MB and be killed on older Android. Library, Story, Social and Profile therefore hold lists
/// and push [ArtworkScreen] when something is opened.
///
/// Home is the single deliberate exception. Its daily canvas is non-zoomable and small — about
/// 26MB — and it is kept alive permanently because disposing it would put a ~900ms reload in front
/// of every return to Home. [IndexedStack] is what keeps it alive.
class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  /// Home sits at index 2 of 5, so it is the centre destination.
  static const int _homeIndex = 2;

  int _index = _homeIndex;
  AppServices? _services;
  String? _error;

  @override
  void initState() {
    super.initState();
    _open();
  }

  @override
  void dispose() {
    _services?.player.dispose();
    super.dispose();
  }

  Future<void> _open() async {
    try {
      // Independent stores, so opened concurrently. Each is a directory create plus at most one
      // small file read; serialising them would add latency to a cold start for no reason.
      final results = await (
        PlayerStore.open(),
        ProgressStore.open(),
        ArtworkLibrary.open(),
        Settings.open(),
      ).wait;
      if (!mounted) return;
      setState(() {
        _services = AppServices(
          player: results.$1,
          progress: results.$2,
          library: results.$3,
          settings: results.$4,
        );
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = '$error');
    }
  }

  @override
  Widget build(BuildContext context) {
    final services = _services;

    if (_error != null) {
      return Scaffold(
        backgroundColor: AppColours.background,
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text('Could not open local storage:\n$_error'),
          ),
        ),
      );
    }
    if (services == null) {
      return const Scaffold(
        backgroundColor: AppColours.background,
        body: Center(child: CircularProgressIndicator()),
      );
    }

    return Scaffold(
      backgroundColor: AppColours.background,
      // No app bar. Home draws its own header over the canvas, and the other tabs draw theirs,
      // because a shared bar would sit above the daily canvas and eat paintable height.
      body: IndexedStack(
        index: _index,
        children: [
          const StoryTab(),
          LibraryTab(services: services),
          HomeTab(services: services),
          const SocialTab(),
          ProfileTab(services: services, onBrowseLibrary: () => _select(1)),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: _select,
        backgroundColor: AppColours.surface,
        indicatorColor: AppColours.accent.withValues(alpha: 0.22),
        height: 64,
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.map_outlined),
            selectedIcon: Icon(Icons.map),
            label: 'Story',
          ),
          NavigationDestination(
            icon: Icon(Icons.photo_library_outlined),
            selectedIcon: Icon(Icons.photo_library),
            label: 'Library',
          ),
          NavigationDestination(
            icon: Icon(Icons.palette_outlined),
            selectedIcon: Icon(Icons.palette),
            label: 'Today',
          ),
          NavigationDestination(
            icon: Icon(Icons.people_outline),
            selectedIcon: Icon(Icons.people),
            label: 'Social',
          ),
          NavigationDestination(
            icon: Icon(Icons.person_outline),
            selectedIcon: Icon(Icons.person),
            label: 'Profile',
          ),
        ],
      ),
    );
  }

  void _select(int index) {
    if (index == _index) return;
    setState(() => _index = index);
  }
}
