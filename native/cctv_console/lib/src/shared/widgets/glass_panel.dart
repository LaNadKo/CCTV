import 'dart:ui';

import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';

class GlassPanel extends StatelessWidget {
  const GlassPanel({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(20),
    this.margin,
    this.radius = AppTheme.radiusLg,
    this.onTap,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final EdgeInsetsGeometry? margin;
  final double radius;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final dark = Theme.of(context).brightness == Brightness.dark;
    final platform = Theme.of(context).platform;
    final mobileWidth = MediaQuery.sizeOf(context).width < 700;
    final useBlur =
        !mobileWidth &&
        platform != TargetPlatform.android &&
        platform != TargetPlatform.iOS;
    final panel = Container(
      padding: padding,
      margin: margin,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(radius),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            colors.surfaceElevated.withValues(alpha: dark ? 0.56 : 0.68),
            colors.surface.withValues(alpha: dark ? 0.42 : 0.54),
          ],
        ),
        border: Border.all(color: colors.border),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: dark ? 0.2 : 0.08),
            blurRadius: mobileWidth ? 16 : 32,
            offset: Offset(0, mobileWidth ? 8 : 18),
          ),
          BoxShadow(
            color: colors.primaryAccent.withValues(alpha: dark ? 0.05 : 0.08),
            blurRadius: mobileWidth ? 18 : 40,
            offset: const Offset(0, 0),
          ),
        ],
      ),
      foregroundDecoration: BoxDecoration(
        borderRadius: BorderRadius.circular(radius),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            Colors.white.withValues(alpha: dark ? 0.08 : 0.18),
            Colors.white.withValues(alpha: 0),
            colors.primaryAccent.withValues(alpha: dark ? 0.025 : 0.04),
          ],
          stops: const [0, 0.42, 1],
        ),
      ),
      child: child,
    );
    final content = ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: useBlur
          ? BackdropFilter(
              filter: ImageFilter.blur(sigmaX: 16, sigmaY: 16),
              child: panel,
            )
          : panel,
    );

    if (onTap == null) return content;
    return InkWell(
      borderRadius: BorderRadius.circular(radius),
      onTap: onTap,
      child: content,
    );
  }
}

class StatCard extends StatelessWidget {
  const StatCard({
    super.key,
    required this.label,
    required this.value,
    required this.icon,
    this.accent,
    this.compact = false,
  });

  final String label;
  final String value;
  final IconData icon;
  final Color? accent;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final resolvedAccent = accent ?? colors.primaryAccent;
    return GlassPanel(
      padding: EdgeInsets.all(compact ? 12 : 18),
      child: Row(
        children: [
          Container(
            width: compact ? 38 : 48,
            height: compact ? 38 : 48,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(compact ? 12 : 16),
              gradient: LinearGradient(
                colors: [
                  resolvedAccent.withValues(alpha: 0.2),
                  colors.secondaryAccent.withValues(alpha: 0.16),
                ],
              ),
              border: Border.all(color: colors.borderStrong),
            ),
            child: Icon(
              icon,
              color: colors.textStrong,
              size: compact ? 20 : 24,
            ),
          ),
          SizedBox(width: compact ? 10 : 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  value,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style:
                      (compact
                              ? Theme.of(context).textTheme.titleLarge
                              : Theme.of(context).textTheme.headlineSmall)
                          ?.copyWith(
                            color: colors.textStrong,
                            fontWeight: FontWeight.w800,
                          ),
                ),
                Text(
                  label,
                  maxLines: compact ? 2 : 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: colors.muted,
                    fontSize: compact ? 12 : null,
                    height: 1.15,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
