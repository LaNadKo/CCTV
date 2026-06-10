import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';

import 'core/theme/app_theme.dart';
import 'core/theme/theme_controller.dart';
import 'features/auth/auth_controller.dart';
import 'features/auth/login_screen.dart';
import 'features/shell/app_shell.dart';
import 'shared/widgets/motion.dart';

class CctvConsoleApp extends StatelessWidget {
  const CctvConsoleApp({super.key});

  @override
  Widget build(BuildContext context) {
    final settings = context.watch<ThemeController>();
    final auth = context.watch<AuthController>();

    return MaterialApp(
      title: 'CCTV Консоль',
      debugShowCheckedModeBanner: false,
      locale: const Locale('ru', 'RU'),
      supportedLocales: const [Locale('ru', 'RU'), Locale('en', 'US')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ],
      themeAnimationDuration: Duration.zero,
      themeAnimationCurve: CctvMotion.emphasized,
      themeMode: settings.materialThemeMode,
      theme: AppTheme.build(settings: settings, brightness: Brightness.light),
      darkTheme: AppTheme.build(
        settings: settings,
        brightness: Brightness.dark,
      ),
      builder: (context, child) {
        final media = MediaQuery.of(context);
        final safeScale = media.textScaler.scale(1).clamp(0.92, 1.0).toDouble();
        final baseStyle = Theme.of(context).textTheme.bodyMedium?.copyWith(
          decoration: TextDecoration.none,
          decorationColor: Colors.transparent,
        );
        return MediaQuery(
          data: media.copyWith(textScaler: TextScaler.linear(safeScale)),
          child: DefaultTextStyle(
            style:
                baseStyle ?? const TextStyle(decoration: TextDecoration.none),
            child: child ?? const SizedBox.shrink(),
          ),
        );
      },
      home: AnimatedSwitcher(
        duration: CctvMotion.resolved(context, CctvMotion.calm),
        switchInCurve: CctvMotion.emphasized,
        switchOutCurve: Curves.easeInCubic,
        transitionBuilder: (child, animation) {
          final offset = Tween<Offset>(
            begin: const Offset(0, 0.018),
            end: Offset.zero,
          ).animate(animation);
          return FadeTransition(
            opacity: animation,
            child: SlideTransition(position: offset, child: child),
          );
        },
        child: auth.isAuthenticated ? const AppShell() : const LoginScreen(),
      ),
    );
  }
}
