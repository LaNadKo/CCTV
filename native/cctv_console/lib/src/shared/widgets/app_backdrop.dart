import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';

class AppBackdrop extends StatelessWidget {
  const AppBackdrop({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final textStyle = Theme.of(context).textTheme.bodyMedium?.copyWith(
      decoration: TextDecoration.none,
      decorationColor: Colors.transparent,
    );

    return Material(
      type: MaterialType.transparency,
      child: DefaultTextStyle(
        style: textStyle ?? const TextStyle(decoration: TextDecoration.none),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: colors.bg,
            gradient: isDark
                ? LinearGradient(
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                    colors: [
                      colors.bg,
                      Color.lerp(colors.bg, colors.secondaryAccent, 0.16)!,
                      Color.lerp(colors.bg, colors.primaryAccent, 0.10)!,
                    ],
                  )
                : const LinearGradient(
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                    colors: [
                      Color(0xFFF8FBFF),
                      Color(0xFFEAF3FF),
                      Color(0xFFF4F8EF),
                    ],
                  ),
          ),
          child: Stack(
            children: [
              Positioned.fill(
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      begin: Alignment.topRight,
                      end: Alignment.bottomLeft,
                      colors: [
                        colors.secondaryAccent.withValues(
                          alpha: isDark ? 0.07 : 0.10,
                        ),
                        colors.bg.withValues(alpha: 0),
                      ],
                    ),
                  ),
                ),
              ),
              Positioned.fill(
                child: CustomPaint(
                  painter: _GridPainter(
                    color: colors.textStrong.withValues(alpha: 0.025),
                  ),
                ),
              ),
              Positioned.fill(child: child),
            ],
          ),
        ),
      ),
    );
  }
}

class _GridPainter extends CustomPainter {
  const _GridPainter({required this.color});

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = 1;
    const step = 48.0;
    for (var x = 0.0; x < size.width; x += step) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
    }
    for (var y = 0.0; y < size.height; y += step) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _GridPainter oldDelegate) {
    return oldDelegate.color != color;
  }
}
