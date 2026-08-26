import 'package:flutter/material.dart';

import 'app_shell.dart';
import 'theme.dart';

/// Paint by Number.
///
/// Opens on the Today tab — the centre of five — where the day's canvas is already on screen and
/// can be painted without navigating anywhere. Everything else (photo conversion, the library,
/// story, social, profile) is a tab away and none of it is required to paint.
///
/// The canvas screen keeps its instrumentation strip. The Phase 2 performance question — does this
/// hold 60fps on a low-end device? — is still open, and can only be answered on hardware in profile
/// mode. An emulator runs on the host CPU and GPU, so a "Pixel 8" emulator is not a Pixel 8 and
/// cannot answer it either way.
void main() {
  runApp(const PaintByNumberApp());
}

class PaintByNumberApp extends StatelessWidget {
  const PaintByNumberApp({super.key});

  @override
  Widget build(BuildContext context) {
    final base = ThemeData.dark(useMaterial3: true);
    return MaterialApp(
      title: 'Paint by Number',
      debugShowCheckedModeBanner: false,
      theme: base.copyWith(
        scaffoldBackgroundColor: AppColours.background,
        colorScheme: base.colorScheme.copyWith(
          primary: AppColours.accent,
          secondary: AppColours.accent,
          surface: AppColours.surface,
        ),
      ),
      home: const AppShell(),
    );
  }
}
