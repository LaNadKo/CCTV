import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'theme_controller.dart';

class AppColors extends ThemeExtension<AppColors> {
  const AppColors({
    required this.bg,
    required this.bgElevated,
    required this.surface,
    required this.surfaceElevated,
    required this.surfaceMuted,
    required this.text,
    required this.textStrong,
    required this.muted,
    required this.border,
    required this.borderStrong,
    required this.success,
    required this.warning,
    required this.danger,
    required this.primaryAccent,
    required this.secondaryAccent,
  });

  final Color bg;
  final Color bgElevated;
  final Color surface;
  final Color surfaceElevated;
  final Color surfaceMuted;
  final Color text;
  final Color textStrong;
  final Color muted;
  final Color border;
  final Color borderStrong;
  final Color success;
  final Color warning;
  final Color danger;
  final Color primaryAccent;
  final Color secondaryAccent;

  @override
  AppColors copyWith({
    Color? bg,
    Color? bgElevated,
    Color? surface,
    Color? surfaceElevated,
    Color? surfaceMuted,
    Color? text,
    Color? textStrong,
    Color? muted,
    Color? border,
    Color? borderStrong,
    Color? success,
    Color? warning,
    Color? danger,
    Color? primaryAccent,
    Color? secondaryAccent,
  }) {
    return AppColors(
      bg: bg ?? this.bg,
      bgElevated: bgElevated ?? this.bgElevated,
      surface: surface ?? this.surface,
      surfaceElevated: surfaceElevated ?? this.surfaceElevated,
      surfaceMuted: surfaceMuted ?? this.surfaceMuted,
      text: text ?? this.text,
      textStrong: textStrong ?? this.textStrong,
      muted: muted ?? this.muted,
      border: border ?? this.border,
      borderStrong: borderStrong ?? this.borderStrong,
      success: success ?? this.success,
      warning: warning ?? this.warning,
      danger: danger ?? this.danger,
      primaryAccent: primaryAccent ?? this.primaryAccent,
      secondaryAccent: secondaryAccent ?? this.secondaryAccent,
    );
  }

  @override
  AppColors lerp(ThemeExtension<AppColors>? other, double t) {
    if (other is! AppColors) return this;
    return AppColors(
      bg: Color.lerp(bg, other.bg, t)!,
      bgElevated: Color.lerp(bgElevated, other.bgElevated, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      surfaceElevated: Color.lerp(surfaceElevated, other.surfaceElevated, t)!,
      surfaceMuted: Color.lerp(surfaceMuted, other.surfaceMuted, t)!,
      text: Color.lerp(text, other.text, t)!,
      textStrong: Color.lerp(textStrong, other.textStrong, t)!,
      muted: Color.lerp(muted, other.muted, t)!,
      border: Color.lerp(border, other.border, t)!,
      borderStrong: Color.lerp(borderStrong, other.borderStrong, t)!,
      success: Color.lerp(success, other.success, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
      danger: Color.lerp(danger, other.danger, t)!,
      primaryAccent: Color.lerp(primaryAccent, other.primaryAccent, t)!,
      secondaryAccent: Color.lerp(secondaryAccent, other.secondaryAccent, t)!,
    );
  }
}

extension AppThemeContext on BuildContext {
  AppColors get colors => Theme.of(this).extension<AppColors>()!;
}

class AppTheme {
  static const radiusSm = 12.0;
  static const radiusMd = 18.0;
  static const radiusLg = 24.0;

  static ThemeData build({
    required ThemeController settings,
    required Brightness brightness,
  }) {
    final isDark = brightness == Brightness.dark;
    final colors = isDark
        ? AppColors(
            bg: const Color(0xFF07111F),
            bgElevated: const Color(0xE60A1426),
            surface: const Color(0xD10B1425),
            surfaceElevated: const Color(0xEA09101F),
            surfaceMuted: Colors.white.withValues(alpha: 0.035),
            text: const Color(0xFFF3F7FF),
            textStrong: Colors.white,
            muted: const Color(0xFF94A3B8),
            border: Colors.white.withValues(alpha: 0.08),
            borderStrong: settings.primaryAccent.withValues(alpha: 0.24),
            success: const Color(0xFF22C55E),
            warning: const Color(0xFFF59E0B),
            danger: const Color(0xFFEF4444),
            primaryAccent: settings.primaryAccent,
            secondaryAccent: settings.secondaryAccent,
          )
        : AppColors(
            bg: const Color(0xFFEEF4FF),
            bgElevated: Colors.white.withValues(alpha: 0.84),
            surface: Colors.white.withValues(alpha: 0.9),
            surfaceElevated: Colors.white.withValues(alpha: 0.96),
            surfaceMuted: const Color(0x0A0F172A),
            text: const Color(0xFF10203A),
            textStrong: const Color(0xFF091220),
            muted: const Color(0xFF5F718C),
            border: const Color(0x140F172A),
            borderStrong: settings.secondaryAccent.withValues(alpha: 0.24),
            success: const Color(0xFF16A34A),
            warning: const Color(0xFFD97706),
            danger: const Color(0xFFDC2626),
            primaryAccent: settings.primaryAccent,
            secondaryAccent: settings.secondaryAccent,
          );

    final scheme = ColorScheme.fromSeed(
      seedColor: settings.primaryAccent,
      brightness: brightness,
      primary: settings.primaryAccent,
      secondary: settings.secondaryAccent,
      surface: colors.surface,
      error: colors.danger,
    );

    final base = ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: scheme,
      scaffoldBackgroundColor: colors.bg,
      extensions: [colors],
    );

    final textTheme = GoogleFonts.spaceGroteskTextTheme(base.textTheme)
        .apply(bodyColor: colors.text, displayColor: colors.textStrong)
        .copyWith(
          displaySmall: GoogleFonts.spaceGrotesk(
            fontSize: 30,
            height: 1.04,
            fontWeight: FontWeight.w800,
            color: colors.textStrong,
            letterSpacing: -1.2,
          ),
          headlineLarge: GoogleFonts.spaceGrotesk(
            fontSize: 26,
            height: 1.06,
            fontWeight: FontWeight.w800,
            color: colors.textStrong,
            letterSpacing: -0.8,
          ),
          headlineMedium: GoogleFonts.spaceGrotesk(
            fontSize: 22,
            height: 1.12,
            fontWeight: FontWeight.w800,
            color: colors.textStrong,
          ),
          headlineSmall: GoogleFonts.spaceGrotesk(
            fontSize: 19,
            height: 1.18,
            fontWeight: FontWeight.w800,
            color: colors.textStrong,
          ),
          titleLarge: GoogleFonts.spaceGrotesk(
            fontSize: 18,
            height: 1.2,
            fontWeight: FontWeight.w700,
            color: colors.textStrong,
          ),
          titleMedium: GoogleFonts.spaceGrotesk(
            fontSize: 14,
            height: 1.45,
            fontWeight: FontWeight.w500,
            color: colors.text,
          ),
          bodyLarge: GoogleFonts.spaceGrotesk(
            fontSize: 14,
            height: 1.45,
            color: colors.text,
          ),
          bodyMedium: GoogleFonts.spaceGrotesk(
            fontSize: 13,
            height: 1.45,
            color: colors.text,
          ),
          labelLarge: GoogleFonts.spaceGrotesk(
            fontSize: 13,
            fontWeight: FontWeight.w700,
          ),
        );

    return base.copyWith(
      textTheme: textTheme,
      appBarTheme: AppBarTheme(
        elevation: 0,
        centerTitle: false,
        backgroundColor: Colors.transparent,
        foregroundColor: colors.textStrong,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: colors.surfaceMuted,
        labelStyle: TextStyle(color: colors.muted, fontSize: 13),
        hintStyle: TextStyle(color: colors.muted, fontSize: 14),
        errorStyle: TextStyle(color: colors.danger, fontSize: 12, height: 1.2),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 14,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(radiusMd),
          borderSide: BorderSide(color: colors.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(radiusMd),
          borderSide: BorderSide(color: colors.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(radiusMd),
          borderSide: BorderSide(color: colors.primaryAccent),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          elevation: 0,
          backgroundColor: colors.primaryAccent,
          foregroundColor: const Color(0xFF07111F),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
          textStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: colors.textStrong,
          side: BorderSide(color: colors.border),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
        ),
      ),
    );
  }
}
