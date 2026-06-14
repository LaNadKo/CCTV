import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:cctv_console/src/core/network/api_client.dart';
import 'package:cctv_console/src/core/theme/theme_controller.dart';

void main() {
  test('formats theme color as css-like hex', () {
    expect(ThemeController.colorToHex(const Color(0xFF5EF0FF)), '#5ef0ff');
  });

  test('sends bearer token only to backend origin', () {
    final api = ApiClient(baseUrlProvider: () => 'http://127.0.0.1:8001');

    expect(
      api.authorizationHeadersFor(
        Uri.parse('http://127.0.0.1:8001/cameras/1/stream'),
        'secret-token',
      ),
      {'Authorization': 'Bearer secret-token'},
    );
    expect(
      api.authorizationHeadersFor(
        Uri.parse('http://192.168.88.10:8777/cameras/1/stream.mjpeg'),
        'secret-token',
      ),
      isEmpty,
    );
  });
}
