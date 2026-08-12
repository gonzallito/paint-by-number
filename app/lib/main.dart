import 'package:flutter/material.dart';

import 'home_screen.dart';

/// Paint by Number.
///
/// The app opens on the library, where a photo becomes a paintable canvas. That conversion is
/// the core feature, not a premium hook, so it is the first thing on screen.
///
/// The canvas screen keeps its instrumentation strip. The Phase 2 performance question — does
/// this hold 60fps on a low-end device? — is still open, and can only be answered on hardware
/// in profile mode. An emulator runs on the host CPU and GPU, so a "Pixel 6" emulator is not a
/// Pixel 6 and cannot answer it either way.
void main() {
  runApp(const PaintByNumberApp());
}

class PaintByNumberApp extends StatelessWidget {
  const PaintByNumberApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Paint by Number',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark(useMaterial3: true),
      home: const HomeScreen(),
    );
  }
}
