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
    expect(config['poll_interval'], 1);
    expect(config['heartbeat_interval'], 10);
    expect(config['processor_accel'], 'auto');
    expect(config['theme_primary_color'], '#49C8E8');
  });

  test('sanitizes noisy processor output', () {
    const noisy =
        '\u001b[0;93mW:onnxruntime execution_frame.cc VerifyOutputSizes '
        'Expected shape from model of {3200,10} does not match actual shape '
        'of {8192,10} for output 477\u001b[m\n'
        'N\u0000o\u0000 \u0000s\u0000o\u0000u\u0000r\u0000c\u0000e\u0000 '
        '\u0000f\u0000o\u0000r\u0000 \u0000c\u0000a\u0000m\u0000e\u0000r\u0000a\u0000 '
        '\u00001\u0000\n';

    expect(sanitizeProcessOutput(noisy), 'No source for camera 1\n');
  });

  test('decodes json after noisy process prefix', () {
    const output =
        '\u001b[0;93monnxruntime execution_frame.cc VerifyOutputSizes\u001b[m\n'
        '{"assignments_count":1,"assignments":[{"camera_id":1,"name":"C200"}]}';

    final decoded = decodeLooseJson(output);

    expect(_asMapForTest(decoded)['assignments_count'], 1);
  });
}

Map<String, dynamic> _asMapForTest(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return value.map((key, val) => MapEntry('$key', val));
  return <String, dynamic>{};
}
