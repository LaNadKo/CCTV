import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';
import 'motion.dart';

class PageHeader extends StatelessWidget {
  const PageHeader({
    super.key,
    required this.title,
    required this.icon,
    this.trailing,
    this.compactBreakpoint = 600,
    this.maxTrailingWidth = 560,
  });

  final String title;
  final IconData icon;
  final Widget? trailing;
  final double compactBreakpoint;
  final double maxTrailingWidth;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < compactBreakpoint;
        final titleBlock = Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            _HeaderMark(icon: icon, compact: compact),
            SizedBox(width: compact ? 10 : 14),
            Expanded(
              child: Text(
                title,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  color: colors.textStrong,
                  fontWeight: FontWeight.w900,
                  fontSize: compact ? 24 : null,
                  height: 1.05,
                ),
              ),
            ),
          ],
        );

        if (compact) {
          return _HeaderEntrance(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                titleBlock,
                if (trailing != null) ...[
                  const SizedBox(height: 12),
                  SizedBox(width: double.infinity, child: trailing!),
                ],
              ],
            ),
          );
        }

        return _HeaderEntrance(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(child: titleBlock),
              if (trailing != null) ...[
                const SizedBox(width: 12),
                Flexible(
                  flex: 0,
                  child: ConstrainedBox(
                    constraints: BoxConstraints(maxWidth: maxTrailingWidth),
                    child: trailing!,
                  ),
                ),
              ],
            ],
          ),
        );
      },
    );
  }
}

class _HeaderEntrance extends StatelessWidget {
  const _HeaderEntrance({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: CctvMotion.standard,
      curve: CctvMotion.emphasized,
      builder: (context, value, child) {
        return Opacity(
          opacity: value,
          child: Transform.translate(
            offset: Offset(0, 8 * (1 - value)),
            child: child,
          ),
        );
      },
      child: child,
    );
  }
}

class _HeaderMark extends StatelessWidget {
  const _HeaderMark({required this.icon, required this.compact});

  final IconData icon;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final size = compact ? 40.0 : 46.0;
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(compact ? 14 : 16),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Stack(
        alignment: Alignment.center,
        children: [
          Icon(icon, color: colors.primaryAccent, size: compact ? 20 : 22),
          Positioned(
            right: compact ? 7 : 8,
            bottom: compact ? 7 : 8,
            child: Container(
              width: compact ? 12 : 14,
              height: 2,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(99),
                gradient: LinearGradient(
                  colors: [colors.primaryAccent, colors.secondaryAccent],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class PageActions extends StatelessWidget {
  const PageActions({super.key, required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 600;
        return Wrap(
          spacing: 8,
          runSpacing: 8,
          alignment: compact ? WrapAlignment.start : WrapAlignment.end,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: children,
        );
      },
    );
  }
}
