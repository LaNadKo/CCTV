import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:cctv_console/src/core/theme/theme_controller.dart';

void main() {
  test('formats theme color as css-like hex', () {
    expect(ThemeController.colorToHex(const Color(0xFF5EF0FF)), '#5ef0ff');
  });
}
