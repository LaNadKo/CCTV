import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/models.dart';

class ApiException implements Exception {
  ApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class ApiClient {
  ApiClient({required this.baseUrlProvider, http.Client? client})
    : _client = client ?? http.Client();

  static const _requestTimeout = Duration(seconds: 20);

  final String Function() baseUrlProvider;
  final http.Client _client;

  Uri uri(String path, [Map<String, String?> query = const {}]) {
    final cleanBase = baseUrlProvider().replaceAll(RegExp(r'/+$'), '');
    final cleanPath = path.startsWith('/') ? path : '/$path';
    final uri = Uri.parse('$cleanBase$cleanPath');
    final filteredQuery = <String, String>{};
    for (final entry in query.entries) {
      final value = entry.value;
      if (value != null && value.isNotEmpty) filteredQuery[entry.key] = value;
    }
    return filteredQuery.isEmpty
        ? uri
        : uri.replace(queryParameters: filteredQuery);
  }

  Future<T> get<T>(
    String path, {
    String? token,
    Map<String, String?> query = const {},
    required T Function(Object? json) decoder,
  }) {
    return _request(path, 'GET', token: token, query: query, decoder: decoder);
  }

  Future<T> post<T>(
    String path, {
    String? token,
    Object? body,
    required T Function(Object? json) decoder,
  }) {
    return _request(path, 'POST', token: token, body: body, decoder: decoder);
  }

  Future<void> postVoid(String path, {String? token, Object? body}) {
    return _request<void>(
      path,
      'POST',
      token: token,
      body: body,
      decoder: (_) {},
    );
  }

  Future<T> patch<T>(
    String path, {
    String? token,
    Object? body,
    required T Function(Object? json) decoder,
  }) {
    return _request(path, 'PATCH', token: token, body: body, decoder: decoder);
  }

  Future<void> deleteVoid(String path, {String? token}) {
    return _request<void>(path, 'DELETE', token: token, decoder: (_) {});
  }

  Future<Object?> getJson(
    String path, {
    String? token,
    Map<String, String?> query = const {},
  }) {
    return get(path, token: token, query: query, decoder: (json) => json);
  }

  Future<List<Map<String, dynamic>>> getJsonList(
    String path, {
    String? token,
    Map<String, String?> query = const {},
  }) {
    return get(
      path,
      token: token,
      query: query,
      decoder: (json) => _asMapList(json),
    );
  }

  Future<Map<String, dynamic>> postJson(
    String path, {
    String? token,
    Object? body,
  }) {
    return post(
      path,
      token: token,
      body: body,
      decoder: (json) => _asMap(json),
    );
  }

  Future<Map<String, dynamic>> patchJson(
    String path, {
    String? token,
    Object? body,
  }) {
    return patch(
      path,
      token: token,
      body: body,
      decoder: (json) => _asMap(json),
    );
  }

  Future<T> _request<T>(
    String path,
    String method, {
    String? token,
    Map<String, String?> query = const {},
    Object? body,
    required T Function(Object? json) decoder,
  }) async {
    final headers = <String, String>{
      'Accept': 'application/json',
      'Content-Type': 'application/json',
      if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
    };

    late http.Response response;
    try {
      final requestUri = uri(path, query);
      switch (method) {
        case 'GET':
          response = await _client
              .get(requestUri, headers: headers)
              .timeout(_requestTimeout);
          break;
        case 'POST':
          response = await _client
              .post(
                requestUri,
                headers: headers,
                body: body == null ? null : jsonEncode(body),
              )
              .timeout(_requestTimeout);
          break;
        case 'PATCH':
          response = await _client
              .patch(
                requestUri,
                headers: headers,
                body: body == null ? null : jsonEncode(body),
              )
              .timeout(_requestTimeout);
          break;
        case 'DELETE':
          response = await _client
              .delete(requestUri, headers: headers)
              .timeout(_requestTimeout);
          break;
        default:
          throw ApiException('Unsupported HTTP method: $method');
      }
    } catch (error) {
      if (error is ApiException) rethrow;
      throw ApiException(
        'Не удалось связаться с backend (${baseUrlProvider()})',
      );
    }

    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(_readError(response), statusCode: response.statusCode);
    }

    if (response.bodyBytes.isEmpty) {
      return decoder(null);
    }

    final text = utf8.decode(response.bodyBytes);
    if (text.trim().isEmpty) {
      return decoder(null);
    }

    final contentType = response.headers['content-type'] ?? '';
    if (!contentType.contains('application/json')) {
      return decoder(text);
    }

    return decoder(jsonDecode(text));
  }

  Future<LoginResponse> login({
    required String login,
    required String password,
    String? totpCode,
  }) {
    return post(
      '/auth/login',
      body: {
        'login': login,
        'password': password,
        if (totpCode != null && totpCode.isNotEmpty) 'totp_code': totpCode,
      },
      decoder: (json) => LoginResponse.fromJson(json as Map<String, dynamic>),
    );
  }

  Future<CurrentUser> me(String token) {
    return get(
      '/auth/me',
      token: token,
      decoder: (json) => CurrentUser.fromJson(json as Map<String, dynamic>),
    );
  }

  Future<MediaTokenResponse> createMediaToken(String token) {
    return post(
      '/auth/media-token',
      token: token,
      decoder: (json) =>
          MediaTokenResponse.fromJson(json as Map<String, dynamic>),
    );
  }

  Future<List<CameraSummary>> listCameras(String token) {
    return get(
      '/cameras',
      token: token,
      decoder: (json) => (json as List<dynamic>)
          .whereType<Map<String, dynamic>>()
          .map(CameraSummary.fromJson)
          .toList(),
    );
  }

  Future<List<ProcessorOut>> listProcessors(String token) {
    return get(
      '/processors',
      token: token,
      decoder: (json) => (json as List<dynamic>)
          .whereType<Map<String, dynamic>>()
          .map(ProcessorOut.fromJson)
          .toList(),
    );
  }

  Future<List<PendingEvent>> listPendingEvents(String token) {
    return get(
      '/detections/pending',
      token: token,
      decoder: (json) => (json as List<dynamic>)
          .whereType<Map<String, dynamic>>()
          .map(PendingEvent.fromJson)
          .toList(),
    );
  }

  Future<void> ptzRelative(
    String token,
    int cameraId, {
    double pan = 0,
    double tilt = 0,
    double zoom = 0,
  }) {
    return postVoid(
      '/admin/cameras/$cameraId/onvif/ptz/relative',
      token: token,
      body: {'pan': pan, 'tilt': tilt, 'zoom': zoom},
    );
  }

  Future<void> ptzStop(String token, int cameraId) {
    return postVoid('/admin/cameras/$cameraId/onvif/ptz/stop', token: token);
  }

  Future<void> ptzHome(String token, int cameraId) {
    return postVoid('/admin/cameras/$cameraId/onvif/ptz/home', token: token);
  }

  Future<void> reviewEvent(String token, int eventId, String status) {
    return postVoid(
      '/detections/events/$eventId/review',
      token: token,
      body: {'status': status},
    );
  }

  Future<void> rejectAllPendingReviews(String token) {
    return postVoid('/detections/review/reject-all', token: token);
  }

  Uri cameraStreamUri(int cameraId) => uri('/cameras/$cameraId/stream');

  static Map<String, dynamic> _asMap(Object? json) {
    if (json == null) return <String, dynamic>{};
    if (json is Map<String, dynamic>) return json;
    if (json is Map) {
      return json.map((key, value) => MapEntry('$key', value));
    }
    return {'value': json};
  }

  static List<Map<String, dynamic>> _asMapList(Object? json) {
    if (json == null) return const [];
    if (json is List) {
      return json.map(_asMap).toList();
    }
    return [_asMap(json)];
  }

  static String _readError(http.Response response) {
    final text = utf8.decode(response.bodyBytes);
    if (text.trim().isEmpty) return response.reasonPhrase ?? 'Request failed';
    try {
      final json = jsonDecode(text);
      final detail = json is Map<String, dynamic> ? json['detail'] : null;
      if (detail is String && detail.trim().isNotEmpty) {
        return _safeErrorText(detail, response.statusCode);
      }
    } catch (_) {
      return _safeErrorText(text, response.statusCode);
    }
    return _safeErrorText(text, response.statusCode);
  }

  static String _safeErrorText(String text, int statusCode) {
    final normalized = text.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (normalized.isEmpty) return 'Backend вернул ошибку HTTP $statusCode';
    final lower = normalized.toLowerCase();
    final looksInternal =
        normalized.length > 320 ||
        lower.contains('<html') ||
        lower.contains('traceback') ||
        lower.contains('stack trace') ||
        lower.contains('exception at') ||
        lower.contains('file "') ||
        lower.contains('sqlalchemy') ||
        lower.contains('postgres');
    if (looksInternal) return 'Backend вернул ошибку HTTP $statusCode';
    return normalized;
  }
}
