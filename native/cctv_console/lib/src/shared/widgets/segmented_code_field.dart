import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/theme/app_theme.dart';

class UpperCaseTextFormatter extends TextInputFormatter {
  const UpperCaseTextFormatter();

  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    return newValue.copyWith(text: newValue.text.toUpperCase());
  }
}

class SegmentedCodeField extends StatefulWidget {
  const SegmentedCodeField({
    super.key,
    required this.controller,
    required this.length,
    this.autofocus = false,
    this.enabled = true,
    this.keyboardType = TextInputType.text,
    this.inputFormatters = const [],
    this.obscure = false,
    this.onCompleted,
  });

  final TextEditingController controller;
  final int length;
  final bool autofocus;
  final bool enabled;
  final TextInputType keyboardType;
  final List<TextInputFormatter> inputFormatters;
  final bool obscure;
  final ValueChanged<String>? onCompleted;

  @override
  State<SegmentedCodeField> createState() => _SegmentedCodeFieldState();
}

class _SegmentedCodeFieldState extends State<SegmentedCodeField> {
  late final FocusNode _focusNode;
  var _lastCompletedValue = '';

  @override
  void initState() {
    super.initState();
    _focusNode = FocusNode()..addListener(_handleFocusChanged);
    widget.controller.addListener(_handleTextChanged);
  }

  @override
  void didUpdateWidget(covariant SegmentedCodeField oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.removeListener(_handleTextChanged);
      widget.controller.addListener(_handleTextChanged);
      _lastCompletedValue = '';
    }
  }

  @override
  void dispose() {
    widget.controller.removeListener(_handleTextChanged);
    _focusNode
      ..removeListener(_handleFocusChanged)
      ..dispose();
    super.dispose();
  }

  void _handleFocusChanged() {
    if (mounted) setState(() {});
  }

  void _handleTextChanged() {
    if (!mounted) return;
    final value = widget.controller.text;
    if (value.length == widget.length && value != _lastCompletedValue) {
      _lastCompletedValue = value;
      widget.onCompleted?.call(value);
    }
    if (value.length < widget.length) _lastCompletedValue = '';
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final formatters = <TextInputFormatter>[
      ...widget.inputFormatters,
      LengthLimitingTextInputFormatter(widget.length),
    ];
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: widget.enabled ? () => _focusNode.requestFocus() : null,
      child: Stack(
        alignment: Alignment.center,
        children: [
          SegmentedCodeDisplay(
            value: widget.controller.text,
            length: widget.length,
            focused: _focusNode.hasFocus,
            activeIndex: math.min(widget.controller.text.length, widget.length),
            obscure: widget.obscure,
            enabled: widget.enabled,
          ),
          Positioned.fill(
            child: Opacity(
              opacity: 0.01,
              child: TextField(
                controller: widget.controller,
                focusNode: _focusNode,
                autofocus: widget.autofocus,
                enabled: widget.enabled,
                keyboardType: widget.keyboardType,
                textCapitalization: TextCapitalization.characters,
                inputFormatters: formatters,
                maxLength: widget.length,
                autocorrect: false,
                enableSuggestions: false,
                showCursor: false,
                decoration: const InputDecoration(
                  border: InputBorder.none,
                  counterText: '',
                  contentPadding: EdgeInsets.zero,
                ),
                onSubmitted: widget.onCompleted,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class SegmentedCodeDisplay extends StatelessWidget {
  const SegmentedCodeDisplay({
    super.key,
    required this.value,
    required this.length,
    this.focused = false,
    this.activeIndex,
    this.obscure = false,
    this.enabled = true,
  });

  final String value;
  final int length;
  final bool focused;
  final int? activeIndex;
  final bool obscure;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return LayoutBuilder(
      builder: (context, constraints) {
        const gap = 8.0;
        final width = constraints.maxWidth.isFinite
            ? constraints.maxWidth
            : length * 52.0 + (length - 1) * gap;
        final cellWidth = ((width - (length - 1) * gap) / length).clamp(
          34.0,
          54.0,
        );
        final cellHeight = (cellWidth * 1.18).clamp(46.0, 62.0);
        final fontSize = (cellWidth * 0.48).clamp(17.0, 24.0);
        return Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            for (var i = 0; i < length; i++) ...[
              _CodeCell(
                char: i < value.length ? (obscure ? '•' : value[i]) : '',
                width: cellWidth,
                height: cellHeight,
                fontSize: fontSize,
                active: focused && enabled && i == (activeIndex ?? 0),
                filled: i < value.length,
                colors: colors,
                enabled: enabled,
              ),
              if (i != length - 1) const SizedBox(width: gap),
            ],
          ],
        );
      },
    );
  }
}

class _CodeCell extends StatelessWidget {
  const _CodeCell({
    required this.char,
    required this.width,
    required this.height,
    required this.fontSize,
    required this.active,
    required this.filled,
    required this.colors,
    required this.enabled,
  });

  final String char;
  final double width;
  final double height;
  final double fontSize;
  final bool active;
  final bool filled;
  final AppColors colors;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final fillColor = Color.alphaBlend(
      colors.primaryAccent.withValues(alpha: filled ? 0.11 : 0.035),
      colors.surfaceElevated,
    );
    final borderColor = active
        ? colors.primaryAccent
        : (filled
              ? colors.primaryAccent.withValues(alpha: 0.55)
              : colors.border);
    return AnimatedContainer(
      duration: const Duration(milliseconds: 120),
      width: width,
      height: height,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: enabled
            ? fillColor
            : Color.alphaBlend(
                colors.muted.withValues(alpha: 0.05),
                colors.surface,
              ),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: borderColor, width: active ? 1.8 : 1.1),
        boxShadow: active
            ? [
                BoxShadow(
                  color: colors.primaryAccent.withValues(alpha: 0.18),
                  blurRadius: 18,
                  spreadRadius: 1,
                ),
              ]
            : null,
      ),
      child: Text(
        char,
        style: TextStyle(
          color: enabled ? colors.textStrong : colors.muted,
          fontSize: fontSize,
          fontWeight: FontWeight.w900,
          height: 1,
        ),
      ),
    );
  }
}
