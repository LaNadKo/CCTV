import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

class MjpegStreamView extends StatefulWidget {
  const MjpegStreamView({
    super.key,
    required this.uri,
    this.headers = const {},
    this.fit = BoxFit.cover,
    this.placeholder,
    this.errorBuilder,
    this.onError,
  });

  final Uri uri;
  final Map<String, String> headers;
  final BoxFit fit;
  final Widget? placeholder;
  final Widget Function(BuildContext context, Object error)? errorBuilder;
  final ValueChanged<Object>? onError;

  @override
  State<MjpegStreamView> createState() => _MjpegStreamViewState();
}

class _MjpegStreamViewState extends State<MjpegStreamView> {
  static const _responseTimeout = Duration(seconds: 8);
  static const _idleTimeout = Duration(seconds: 10);

  http.Client? _client;
  StreamSubscription<List<int>>? _subscription;
  Timer? _retryTimer;
  Uint8List? _frame;
  Object? _error;
  var _generation = 0;
  var _retryCount = 0;

  @override
  void initState() {
    super.initState();
    _start();
  }

  @override
  void didUpdateWidget(covariant MjpegStreamView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.uri != widget.uri ||
        !_sameHeaders(oldWidget.headers, widget.headers)) {
      _restart();
    }
  }

  @override
  void dispose() {
    _generation += 1;
    _retryTimer?.cancel();
    unawaited(_subscription?.cancel());
    _client?.close();
    super.dispose();
  }

  void _restart() {
    _generation += 1;
    _retryTimer?.cancel();
    unawaited(_subscription?.cancel());
    _client?.close();
    _frame = null;
    _error = null;
    _retryCount = 0;
    _start();
  }

  void _start() {
    final generation = _generation;
    final client = http.Client();
    _client = client;
    final request = http.Request('GET', widget.uri);
    request.headers.addAll(widget.headers);
    request.headers.putIfAbsent(
      'Accept',
      () => 'multipart/x-mixed-replace,image/jpeg,*/*',
    );

    unawaited(
      client
          .send(request)
          .timeout(_responseTimeout)
          .then<void>((response) async {
            if (!mounted || generation != _generation) return;
            if (response.statusCode < 200 || response.statusCode >= 300) {
              final body = await response.stream.bytesToString();
              throw MjpegStreamException(
                _friendlyHttpError(response.statusCode, body),
              );
            }
            final buffer = <int>[];
            _subscription = response.stream.timeout(
              _idleTimeout,
              onTimeout: (sink) {
                sink.addError(
                  const MjpegStreamException(
                    'Поток перестал отдавать кадры. Выполняется повторное подключение.',
                  ),
                );
                sink.close();
              },
            ).listen(
              (chunk) {
                if (!mounted || generation != _generation) return;
                buffer.addAll(chunk);
                Uint8List? latestFrame;
                while (true) {
                  final frame = _takeNextJpeg(buffer);
                  if (frame == null) break;
                  latestFrame = frame;
                }
                if (latestFrame != null) {
                  setState(() {
                    _frame = latestFrame;
                    _error = null;
                    _retryCount = 0;
                  });
                }
                if (buffer.length > 8 * 1024 * 1024) {
                  buffer.removeRange(0, buffer.length - 1024);
                }
              },
              onError: (Object error) => _scheduleRetry(error, generation),
              onDone: () => _scheduleRetry('stream closed', generation),
              cancelOnError: true,
            );
          })
          .catchError((Object error) => _scheduleRetry(error, generation)),
    );
  }

  void _scheduleRetry(Object error, int generation) {
    if (!mounted || generation != _generation) return;
    final visibleError = error is TimeoutException
        ? const MjpegStreamException(
            'Поток не ответил за 8 секунд. Проверьте камеру или Процессор.',
          )
        : error;
    setState(() => _error = visibleError);
    widget.onError?.call(visibleError);
    _retryTimer?.cancel();
    _retryCount += 1;
    final delaySeconds = _retryCount <= 1
        ? 3
        : (_retryCount <= 3 ? 10 : 30);
    _retryTimer = Timer(Duration(seconds: delaySeconds), () {
      if (!mounted || generation != _generation) return;
      unawaited(_subscription?.cancel());
      _client?.close();
      _start();
    });
  }

  @override
  Widget build(BuildContext context) {
    final frame = _frame;
    if (frame != null) {
      return RepaintBoundary(
        child: Image.memory(
          frame,
          fit: widget.fit,
          gaplessPlayback: true,
          filterQuality: FilterQuality.low,
          width: double.infinity,
          height: double.infinity,
        ),
      );
    }
    final error = _error;
    if (error != null && widget.errorBuilder != null) {
      return widget.errorBuilder!(context, error);
    }
    return widget.placeholder ??
        const Center(child: CircularProgressIndicator(strokeWidth: 2));
  }
}

class MjpegStreamException implements Exception {
  const MjpegStreamException(this.message);

  final String message;

  @override
  String toString() => message;
}

Uint8List? _takeNextJpeg(List<int> buffer) {
  var start = -1;
  for (var index = 0; index < buffer.length - 1; index++) {
    if (buffer[index] == 0xFF && buffer[index + 1] == 0xD8) {
      start = index;
      break;
    }
  }
  if (start < 0) {
    if (buffer.length > 1024) buffer.removeRange(0, buffer.length - 1024);
    return null;
  }
  for (var index = start + 2; index < buffer.length - 1; index++) {
    if (buffer[index] == 0xFF && buffer[index + 1] == 0xD9) {
      final end = index + 2;
      final frame = Uint8List.fromList(buffer.sublist(start, end));
      buffer.removeRange(0, end);
      return frame;
    }
  }
  if (start > 0) buffer.removeRange(0, start);
  return null;
}

bool _sameHeaders(Map<String, String> left, Map<String, String> right) {
  if (left.length != right.length) return false;
  for (final entry in left.entries) {
    if (right[entry.key] != entry.value) return false;
  }
  return true;
}

String _compactErrorBody(String body) {
  try {
    final decoded = jsonDecode(body);
    if (decoded is Map && decoded['detail'] != null) {
      return '${decoded['detail']}';
    }
  } catch (_) {
    // Plain text body.
  }
  final compact = body.replaceAll(RegExp(r'\s+'), ' ').trim();
  return compact.length > 240 ? '${compact.substring(0, 240)}...' : compact;
}

String _friendlyHttpError(int statusCode, String body) {
  final compact = _compactErrorBody(body);
  if (statusCode == 503) {
    return 'Поток сейчас недоступен. Проверьте камеру, назначение Процессора и URL потока.';
  }
  if (statusCode == 401 || statusCode == 403) {
    return 'Нет доступа к потоку. Войдите заново или проверьте права роли.';
  }
  if (compact.isEmpty) {
    return 'Поток вернул HTTP $statusCode.';
  }
  return 'Поток вернул HTTP $statusCode: $compact';
}
