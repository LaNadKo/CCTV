import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';

class AppBackdrop extends StatelessWidget {
  const AppBackdrop({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final mobile = MediaQuery.sizeOf(context).width < 700;
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
                      Color(0xFFF2F6FC),
                    ],
              ),
          ),
          child: Stack(
            children: [
              Positioned.fill(
                child: RepaintBoundary(
                  child: CustomPaint(
                    isComplex: true,
                    willChange: false,
                    painter: _AuroraPainter(
                      primary: colors.primaryAccent,
                      secondary: colors.secondaryAccent,
                      dark: isDark,
                      mobile: mobile,
                    ),
                  ),
                ),
              ),
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
                child: RepaintBoundary(
                  child: CustomPaint(
                    isComplex: true,
                    willChange: false,
                    painter: _GridPainter(
                      color: colors.textStrong.withValues(alpha: 0.025),
                    ),
                  ),
                ),
              ),
              Positioned.fill(
                child: RepaintBoundary(
                  child: CustomPaint(
                    isComplex: false,
                    willChange: false,
                    painter: _SignalPainter(
                      primary: colors.primaryAccent,
                      border: colors.borderStrong,
                      dark: isDark,
                    ),
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

class _AuroraPainter extends CustomPainter {
  const _AuroraPainter({
    required this.primary,
    required this.secondary,
    required this.dark,
    required this.mobile,
  });

  final Color primary;
  final Color secondary;
  final bool dark;
  final bool mobile;

  @override
  void paint(Canvas canvas, Size size) {
    final alpha = dark ? 0.24 : 0.34;
    final topBand = Paint()
      ..shader = LinearGradient(
        colors: [
          primary.withValues(alpha: alpha),
          secondary.withValues(alpha: alpha * 0.82),
          Colors.transparent,
        ],
      ).createShader(Offset.zero & size)
      ..maskFilter = MaskFilter.blur(BlurStyle.normal, mobile ? 16 : 28);

    final topPath = Path()
      ..moveTo(-size.width * 0.08, size.height * 0.18)
      ..cubicTo(
        size.width * 0.22,
        size.height * 0.05,
        size.width * 0.56,
        size.height * 0.15,
        size.width * 1.08,
        size.height * 0.02,
      )
      ..lineTo(size.width * 1.08, size.height * 0.2)
      ..cubicTo(
        size.width * 0.68,
        size.height * 0.34,
        size.width * 0.24,
        size.height * 0.27,
        -size.width * 0.08,
        size.height * 0.46,
      )
      ..close();
    canvas.drawPath(topPath, topBand);

    final bottomBand = Paint()
      ..shader = LinearGradient(
        begin: Alignment.bottomLeft,
        end: Alignment.topRight,
        colors: [
          secondary.withValues(alpha: alpha * 0.72),
          primary.withValues(alpha: alpha * 0.62),
          Colors.transparent,
        ],
      ).createShader(Offset.zero & size)
      ..maskFilter = MaskFilter.blur(BlurStyle.normal, mobile ? 20 : 34);

    final bottomPath = Path()
      ..moveTo(-size.width * 0.12, size.height * 0.86)
      ..cubicTo(
        size.width * 0.24,
        size.height * 0.7,
        size.width * 0.56,
        size.height * 0.94,
        size.width * 1.1,
        size.height * 0.72,
      )
      ..lineTo(size.width * 1.1, size.height * 1.08)
      ..lineTo(-size.width * 0.12, size.height * 1.08)
      ..close();
    canvas.drawPath(bottomPath, bottomBand);
  }

  @override
  bool shouldRepaint(covariant _AuroraPainter oldDelegate) {
    return oldDelegate.primary != primary ||
        oldDelegate.secondary != secondary ||
        oldDelegate.dark != dark ||
        oldDelegate.mobile != mobile;
  }
}

class _SignalPainter extends CustomPainter {
  const _SignalPainter({
    required this.primary,
    required this.border,
    required this.dark,
  });

  final Color primary;
  final Color border;
  final bool dark;

  @override
  void paint(Canvas canvas, Size size) {
    final line = Paint()
      ..color = primary.withValues(alpha: dark ? 0.10 : 0.08)
      ..strokeWidth = 1.2
      ..style = PaintingStyle.stroke;
    final soft = Paint()
      ..color = border.withValues(alpha: dark ? 0.16 : 0.10)
      ..strokeWidth = 1
      ..style = PaintingStyle.stroke;

    const inset = 22.0;
    const length = 54.0;
    canvas.drawLine(
      Offset(size.width - inset - length, inset),
      Offset(size.width - inset, inset),
      line,
    );
    canvas.drawLine(
      Offset(size.width - inset, inset),
      Offset(size.width - inset, inset + length),
      line,
    );
    canvas.drawLine(
      Offset(inset, size.height - inset - length),
      Offset(inset, size.height - inset),
      soft,
    );
    canvas.drawLine(
      Offset(inset, size.height - inset),
      Offset(inset + length, size.height - inset),
      soft,
    );

    final center = Offset(size.width * 0.86, size.height * 0.18);
    canvas.drawCircle(center, 32, soft);
    canvas.drawCircle(center, 52, line);
    canvas.drawLine(center.translate(-62, 0), center.translate(-38, 0), soft);
    canvas.drawLine(center.translate(38, 0), center.translate(62, 0), soft);
    canvas.drawLine(center.translate(0, -62), center.translate(0, -38), soft);
    canvas.drawLine(center.translate(0, 38), center.translate(0, 62), soft);
  }

  @override
  bool shouldRepaint(covariant _SignalPainter oldDelegate) {
    return oldDelegate.primary != primary ||
        oldDelegate.border != border ||
        oldDelegate.dark != dark;
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
