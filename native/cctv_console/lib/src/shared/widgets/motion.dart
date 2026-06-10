import 'package:flutter/material.dart';

class CctvMotion {
  const CctvMotion._();

  static const fast = Duration(milliseconds: 140);
  static const standard = Duration(milliseconds: 220);
  static const calm = Duration(milliseconds: 320);
  static const theme = Duration(milliseconds: 360);

  static const curve = Curves.easeOutCubic;
  static const emphasized = Cubic(0.2, 0, 0, 1);

  static Duration resolved(BuildContext context, Duration duration) {
    final media = MediaQuery.maybeOf(context);
    if (media == null) return duration;
    if (media.disableAnimations || media.accessibleNavigation) {
      return Duration.zero;
    }
    return duration;
  }
}

class FadeSlideSwitcher extends StatelessWidget {
  const FadeSlideSwitcher({
    super.key,
    required this.child,
    this.duration = CctvMotion.standard,
  });

  final Widget child;
  final Duration duration;

  @override
  Widget build(BuildContext context) {
    return AnimatedSwitcher(
      duration: CctvMotion.resolved(context, duration),
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
      child: child,
    );
  }
}

class FadeScaleSwitcher extends StatelessWidget {
  const FadeScaleSwitcher({
    super.key,
    required this.child,
    this.duration = CctvMotion.standard,
    this.scaleBegin = 0.92,
  });

  final Widget child;
  final Duration duration;
  final double scaleBegin;

  @override
  Widget build(BuildContext context) {
    return AnimatedSwitcher(
      duration: CctvMotion.resolved(context, duration),
      switchInCurve: CctvMotion.emphasized,
      switchOutCurve: Curves.easeInCubic,
      transitionBuilder: (child, animation) {
        final curved = CurvedAnimation(
          parent: animation,
          curve: CctvMotion.emphasized,
          reverseCurve: Curves.easeInCubic,
        );
        return FadeTransition(
          opacity: curved,
          child: ScaleTransition(
            scale: Tween<double>(begin: scaleBegin, end: 1).animate(curved),
            child: child,
          ),
        );
      },
      child: child,
    );
  }
}

class PressScale extends StatefulWidget {
  const PressScale({
    super.key,
    required this.child,
    this.enabled = true,
    this.scale = 0.975,
  });

  final Widget child;
  final bool enabled;
  final double scale;

  @override
  State<PressScale> createState() => _PressScaleState();
}

class _PressScaleState extends State<PressScale> {
  bool _pressed = false;
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final targetScale = !widget.enabled
        ? 1.0
        : _pressed
        ? widget.scale
        : _hovered
        ? 1.01
        : 1.0;
    return MouseRegion(
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() {
        _hovered = false;
        _pressed = false;
      }),
      child: Listener(
        onPointerDown: widget.enabled
            ? (_) => setState(() => _pressed = true)
            : null,
        onPointerCancel: (_) => setState(() => _pressed = false),
        onPointerUp: (_) => setState(() => _pressed = false),
        child: AnimatedScale(
          scale: targetScale,
          duration: CctvMotion.resolved(context, CctvMotion.fast),
          curve: CctvMotion.curve,
          child: widget.child,
        ),
      ),
    );
  }
}
