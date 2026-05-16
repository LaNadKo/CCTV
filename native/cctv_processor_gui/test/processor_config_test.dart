import 'package:flutter_test/flutter_test.dart';

import 'package:cctv_processor_gui/main.dart';

void main() {
  test('normalizes processor runtime config', () {
    final config = normalizeProcessorConfig({
      'recording_segment_seconds': 300,
      'max_workers': 0,
      'processor_accel': 'bad',
      'theme_primary_color': '49c8e8',
    }, r'C:\runtime');

    expect(config['recording_segment_seconds'], 60);
    expect(config['max_workers'], 1);
    expect(config['processor_accel'], 'auto');
    expect(config['theme_primary_color'], '#49C8E8');
  });
}
