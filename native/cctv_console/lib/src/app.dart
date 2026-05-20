import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'core/theme/app_theme.dart';
import 'core/theme/theme_controller.dart';
import 'features/auth/auth_controller.dart';
import 'features/auth/login_screen.dart';
import 'features/shell/app_shell.dart';

class CctvConsoleApp extends StatelessWidget {
  const CctvConsoleApp({super.key});

  @override
  Widget build(BuildContext context) {
    final settings = context.watch<ThemeController>();
    final auth = context.watch<AuthController>();

    return MaterialApp(
      title: 'CCTV Console',
      debugShowCheckedModeBanner: false,
      themeMode: settings.materialThemeMode,
      theme: AppTheme.build(settings: settings, brightness: Brightness.light),
      darkTheme: AppTheme.build(
        settings: settings,
        brightness: Brightness.dark,
      ),
      builder: (context, child) {
        final media = MediaQuery.of(context);
        final safeScale = media.textScaler.scale(1).clamp(0.9, 1.08).toDouble();
        return MediaQuery(
          data: media.copyWith(textScaler: TextScaler.linear(safeScale)),
          child: child ?? const SizedBox.shrink(),
        );
      },
      home: AnimatedSwitcher(
        duration: const Duration(milliseconds: 220),
        child: auth.isAuthenticated ? const AppShell() : const LoginScreen(),
      ),
    );
  }
}
