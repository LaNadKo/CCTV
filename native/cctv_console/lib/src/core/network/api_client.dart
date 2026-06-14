import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

import '../models/models.dart';

class ApiException implements Exception {
  ApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  bool get isTotpRequired {
    final lower = message.toLowerCase();
    return lower.contains('totp code required') ||
        lower.contains('код двухфакторной') ||
        lower.contains('2fa-код');
  }

  @override
  String toString() => message;
}

class CameraStreamSource {
  const CameraStreamSource({
    required this.uri,
    required this.headers,
    required this.kind,
  });

  final Uri uri;
  final Map<String, String> headers;
  final String kind;

  bool get isDirect => kind == 'processor_direct';
}

class ApiClient {
  ApiClient({required this.baseUrlProvider, http.Client? client})
    : _client = client ?? http.Client();

  static const _requestTimeout = Duration(seconds: 20);
  static const _maxDownloadErrorBytes = 64 * 1024;

  final String Function() baseUrlProvider;
  final http.Client _client;

  bool isBackendOrigin(Uri candidate) {
    final base = Uri.tryParse(baseUrlProvider().trim());
    if (base == null || !base.hasScheme || base.host.isEmpty) return false;
    if (candidate.scheme != 'http' && candidate.scheme != 'https') return false;
    return candidate.scheme == base.scheme &&
        candidate.host.toLowerCase() == base.host.toLowerCase() &&
        candidate.port == base.port;
  }

  Map<String, String> authorizationHeadersFor(Uri candidate, String? token) {
    if (token == null || token.isEmpty || !isBackendOrigin(candidate)) {
      return const {};
    }
    return {'Authorization': 'Bearer $token'};
  }

  Map<String, String> mediaAuthorizationHeaders(String? mediaToken) {
    if (mediaToken == null || mediaToken.isEmpty) return const {};
    return {'Authorization': 'Bearer $mediaToken'};
  }

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

  Uri uriWithQuery(String path, Iterable<MapEntry<String, String?>> query) {
    final cleanBase = baseUrlProvider().replaceAll(RegExp(r'/+$'), '');
    final cleanPath = path.startsWith('/') ? path : '/$path';
    final uri = Uri.parse('$cleanBase$cleanPath');
    final parts = <String>[];
    for (final entry in query) {
      final value = entry.value;
      if (value == null || value.isEmpty) continue;
      parts.add(
        '${Uri.encodeQueryComponent(entry.key)}=${Uri.encodeQueryComponent(value)}',
      );
    }
    return parts.isEmpty ? uri : uri.replace(query: parts.join('&'));
  }

  Future<T> get<T>(
    String path, {
    String? token,
    Map<String, String?> query = const {},
    Duration? timeout,
    required T Function(Object? json) decoder,
  }) {
    return _request(
      path,
      'GET',
      token: token,
      query: query,
      timeout: timeout,
      decoder: decoder,
    );
  }

  Future<T> post<T>(
    String path, {
    String? token,
    Object? body,
    Duration? timeout,
    required T Function(Object? json) decoder,
  }) {
    return _request(
      path,
      'POST',
      token: token,
      body: body,
      timeout: timeout,
      decoder: decoder,
    );
  }

  Future<void> postVoid(
    String path, {
    String? token,
    Object? body,
    Duration? timeout,
  }) {
    return _request<void>(
      path,
      'POST',
      token: token,
      body: body,
      timeout: timeout,
      decoder: (_) {},
    );
  }

  Future<T> patch<T>(
    String path, {
    String? token,
    Object? body,
    Duration? timeout,
    required T Function(Object? json) decoder,
  }) {
    return _request(
      path,
      'PATCH',
      token: token,
      body: body,
      timeout: timeout,
      decoder: decoder,
    );
  }

  Future<void> deleteVoid(String path, {String? token, Duration? timeout}) {
    return _request<void>(
      path,
      'DELETE',
      token: token,
      timeout: timeout,
      decoder: (_) {},
    );
  }

  Future<File> downloadRecordingFile(String token, int recordingId) {
    return downloadFile(
      '/recordings/file/$recordingId',
      token: token,
      filename: 'recording-$recordingId.mp4',
    );
  }

  Future<File> downloadFile(
    String path, {
    required String token,
    Map<String, String?> query = const {},
    required String filename,
  }) async {
    late http.StreamedResponse response;
    try {
      final request = http.Request('GET', uri(path, query))
        ..headers.addAll({
          'Accept': 'application/octet-stream',
          'Authorization': 'Bearer $token',
        });
      response = await _client.send(request).timeout(const Duration(seconds: 120));
    } catch (_) {
      throw ApiException(
        'Не удалось скачать файл с backend (${baseUrlProvider()})',
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(
        await _readStreamedError(response),
        statusCode: response.statusCode,
      );
    }
    final directory = await _downloadDirectory();
    await directory.create(recursive: true);
    final safeName = filename.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_');
    final file = File('${directory.path}${Platform.pathSeparator}$safeName');
    final tempFile = File('${file.path}.part');
    try {
      await response.stream.timeout(const Duration(seconds: 120)).pipe(tempFile.openWrite());
      return await _replaceWithDownloadedFile(tempFile, file);
    } catch (_) {
      if (await tempFile.exists()) {
        await tempFile.delete();
      }
      throw ApiException('Download failed (${baseUrlProvider()})');
    }
  }

  Future<File> downloadFileWithQuery(
    String path, {
    required String token,
    Iterable<MapEntry<String, String?>> query = const [],
    required String filename,
  }) async {
    late http.StreamedResponse response;
    try {
      final request = http.Request('GET', uriWithQuery(path, query))
        ..headers.addAll({
          'Accept': 'application/octet-stream',
          'Authorization': 'Bearer $token',
        });
      response = await _client.send(request).timeout(const Duration(seconds: 120));
    } catch (_) {
      throw ApiException(
        'Не удалось скачать файл с backend (${baseUrlProvider()})',
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(
        await _readStreamedError(response),
        statusCode: response.statusCode,
      );
    }
    final directory = await _downloadDirectory();
    await directory.create(recursive: true);
    final safeName = filename.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_');
    final file = File('${directory.path}${Platform.pathSeparator}$safeName');
    final tempFile = File('${file.path}.part');
    try {
      await response.stream.timeout(const Duration(seconds: 120)).pipe(tempFile.openWrite());
      return await _replaceWithDownloadedFile(tempFile, file);
    } catch (_) {
      if (await tempFile.exists()) {
        await tempFile.delete();
      }
      throw ApiException('Download failed (${baseUrlProvider()})');
    }
  }

  Future<String> _readStreamedError(http.StreamedResponse response) async {
    final builder = BytesBuilder(copy: false);
    var total = 0;
    await for (final chunk in response.stream) {
      if (chunk.isEmpty) continue;
      final remaining = _maxDownloadErrorBytes - total;
      if (remaining <= 0) break;
      if (chunk.length <= remaining) {
        builder.add(chunk);
        total += chunk.length;
      } else {
        builder.add(chunk.sublist(0, remaining));
        total += remaining;
        break;
      }
    }
    final buffered = http.Response.bytes(
      builder.takeBytes(),
      response.statusCode,
      headers: response.headers,
      reasonPhrase: response.reasonPhrase,
    );
    return _readError(buffered);
  }

  Future<File> _replaceWithDownloadedFile(File tempFile, File file) async {
    File? backupFile;
    try {
      if (await file.exists()) {
        backupFile = File('${file.path}.${DateTime.now().microsecondsSinceEpoch}.bak');
        await file.rename(backupFile.path);
      }
      final result = await tempFile.rename(file.path);
      if (backupFile != null && await backupFile.exists()) {
        await backupFile.delete();
      }
      return result;
    } catch (_) {
      if (!await file.exists() && backupFile != null && await backupFile.exists()) {
        await backupFile.rename(file.path);
      }
      rethrow;
    }
  }

  Future<Object?> getJson(
    String path, {
    String? token,
    Map<String, String?> query = const {},
    Duration? timeout,
  }) {
    return get(
      path,
      token: token,
      query: query,
      timeout: timeout,
      decoder: (json) => json,
    );
  }

  Future<Object?> getJsonWithQuery(
    String path, {
    String? token,
    Iterable<MapEntry<String, String?>> query = const [],
    Duration? timeout,
  }) async {
    final headers = <String, String>{
      'Accept': 'application/json',
      if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
    };
    late http.Response response;
    try {
      response = await _client
          .get(uriWithQuery(path, query), headers: headers)
          .timeout(timeout ?? _requestTimeout);
    } catch (_) {
      throw ApiException(
        'Не удалось подключиться к backend (${baseUrlProvider()})',
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(_readError(response), statusCode: response.statusCode);
    }
    if (response.bodyBytes.isEmpty) return null;
    return jsonDecode(utf8.decode(response.bodyBytes));
  }

  Future<List<Map<String, dynamic>>> getJsonList(
    String path, {
    String? token,
    Map<String, String?> query = const {},
    Duration? timeout,
  }) {
    return get(
      path,
      token: token,
      query: query,
      timeout: timeout,
      decoder: (json) => _asMapList(json),
    );
  }

  Future<Map<String, dynamic>> postJson(
    String path, {
    String? token,
    Object? body,
    Duration? timeout,
  }) {
    return post(
      path,
      token: token,
      body: body,
      timeout: timeout,
      decoder: (json) => _asMap(json),
    );
  }

  Future<Map<String, dynamic>> patchJson(
    String path, {
    String? token,
    Object? body,
    Duration? timeout,
  }) {
    return patch(
      path,
      token: token,
      body: body,
      timeout: timeout,
      decoder: (json) => _asMap(json),
    );
  }

  Future<T> _request<T>(
    String path,
    String method, {
    String? token,
    Map<String, String?> query = const {},
    Object? body,
    Duration? timeout,
    required T Function(Object? json) decoder,
  }) async {
    final headers = <String, String>{
      'Accept': 'application/json',
      'Content-Type': 'application/json',
      if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
    };

    late http.Response response;
    late Uri requestUri;
    final effectiveTimeout = timeout ?? _requestTimeout;
    try {
      requestUri = uri(path, query);
      switch (method) {
        case 'GET':
          response = await _client
              .get(requestUri, headers: headers)
              .timeout(effectiveTimeout);
          break;
        case 'POST':
          response = await _client
              .post(
                requestUri,
                headers: headers,
                body: body == null ? null : jsonEncode(body),
              )
              .timeout(effectiveTimeout);
          break;
        case 'PATCH':
          response = await _client
              .patch(
                requestUri,
                headers: headers,
                body: body == null ? null : jsonEncode(body),
              )
              .timeout(effectiveTimeout);
          break;
        case 'DELETE':
          response = await _client
              .delete(requestUri, headers: headers)
              .timeout(effectiveTimeout);
          break;
        default:
          throw ApiException('Unsupported HTTP method: $method');
      }
    } catch (error) {
      if (error is ApiException) rethrow;
      if (error is TimeoutException) {
        throw ApiException(
          'Backend не ответил за ${effectiveTimeout.inSeconds} сек. (${requestUri.toString()})',
        );
      }
      throw ApiException(
        'Не удалось связаться с backend (${baseUrlProvider()}): $error',
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

  Future<CurrentUser> updateProfile(
    String token, {
    String? firstName,
    String? lastName,
    String? middleName,
  }) {
    return patch(
      '/auth/profile',
      token: token,
      body: {
        'first_name': _nullableText(firstName),
        'last_name': _nullableText(lastName),
        'middle_name': _nullableText(middleName),
      },
      decoder: (json) => CurrentUser.fromJson(json as Map<String, dynamic>),
    );
  }

  Future<LoginResponse> changePassword(
    String token, {
    required String currentPassword,
    required String newPassword,
  }) {
    return post(
      '/auth/change-password',
      token: token,
      body: {'current_password': currentPassword, 'new_password': newPassword},
      decoder: (json) =>
          LoginResponse.fromJson(json as Map<String, dynamic>),
    );
  }

  Future<bool> getTotpEnabled(String token) async {
    final status = await getJson('/auth/totp/status', token: token);
    final map = _asMap(status);
    return map['enabled'] == true;
  }

  Future<Map<String, dynamic>> setupTotp(
    String token, {
    required String currentPassword,
  }) {
    return postJson(
      '/auth/totp/setup',
      token: token,
      body: {'current_password': currentPassword},
    );
  }

  Future<bool> activateTotp(
    String token,
    String code, {
    required String currentPassword,
  }) async {
    final status = await postJson(
      '/auth/totp/activate',
      token: token,
      body: {'code': code, 'current_password': currentPassword},
    );
    return status['enabled'] == true;
  }

  Future<bool> disableTotp(
    String token, {
    required String currentPassword,
    required String code,
  }) async {
    final status = await postJson(
      '/auth/totp/disable',
      token: token,
      body: {'current_password': currentPassword, 'code': code},
    );
    return status['enabled'] == true;
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

  Future<List<Map<String, dynamic>>> listReviewCandidates(
    String token,
    int eventId, {
    int limit = 3,
  }) {
    return getJsonList(
      '/detections/events/$eventId/candidates',
      token: token,
      query: {'limit': '$limit'},
      timeout: const Duration(seconds: 8),
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

  Future<void> ptzContinuous(
    String token,
    int cameraId, {
    double pan = 0,
    double tilt = 0,
    double zoom = 0,
    double? timeoutSeconds = 0.25,
  }) {
    final body = <String, dynamic>{
      'pan': pan,
      'tilt': tilt,
      'zoom': zoom,
    };
    if (timeoutSeconds != null) {
      body['timeout_seconds'] = timeoutSeconds;
    }
    return postVoid(
      '/admin/cameras/$cameraId/onvif/ptz/continuous',
      token: token,
      body: body,
    );
  }

  Future<void> ptzAbsolute(
    String token,
    int cameraId, {
    double? pan,
    double? tilt,
    double? zoom,
    double? speed,
  }) {
    final body = <String, dynamic>{};
    if (pan != null) body['pan'] = pan;
    if (tilt != null) body['tilt'] = tilt;
    if (zoom != null) body['zoom'] = zoom;
    if (speed != null) body['speed'] = speed;
    return postVoid(
      '/admin/cameras/$cameraId/onvif/ptz/absolute',
      token: token,
      body: body,
    );
  }

  Future<void> ptzStop(String token, int cameraId) {
    return postVoid('/admin/cameras/$cameraId/onvif/ptz/stop', token: token);
  }

  Future<void> ptzHome(String token, int cameraId) {
    return postVoid('/admin/cameras/$cameraId/onvif/ptz/home', token: token);
  }

  Future<List<Map<String, dynamic>>> listCameraPresets(
    String token,
    int cameraId,
  ) {
    return getJsonList('/admin/cameras/$cameraId/presets', token: token);
  }

  Future<List<Map<String, dynamic>>> refreshCameraPresets(
    String token,
    int cameraId,
  ) {
    return post(
      '/admin/cameras/$cameraId/presets/refresh',
      token: token,
      decoder: (json) => _asMapList(json),
    );
  }

  Future<Map<String, dynamic>> createCameraPreset(
    String token,
    int cameraId, {
    required String name,
    int orderIndex = 0,
    int dwellSeconds = 10,
  }) {
    return postJson(
      '/admin/cameras/$cameraId/presets',
      token: token,
      body: {
        'name': name,
        'order_index': orderIndex,
        'dwell_seconds': dwellSeconds,
      },
    );
  }

  Future<void> gotoCameraPreset(String token, int cameraId, int presetId) {
    return postVoid(
      '/admin/cameras/$cameraId/presets/$presetId/goto',
      token: token,
    );
  }

  Future<void> deleteCameraPreset(String token, int cameraId, int presetId) {
    return deleteVoid(
      '/admin/cameras/$cameraId/presets/$presetId',
      token: token,
    );
  }

  Future<void> reviewEvent(
    String token,
    int eventId,
    String status, {
    int? personId,
    String? note,
  }) {
    final body = <String, dynamic>{'status': status};
    if (personId != null) body['person_id'] = personId;
    final trimmedNote = note?.trim();
    if (trimmedNote != null && trimmedNote.isNotEmpty) {
      body['note'] = trimmedNote;
    }
    return postVoid(
      '/detections/events/$eventId/review',
      token: token,
      body: body,
    );
  }

  Future<void> rejectAllPendingReviews(String token) {
    return postVoid('/detections/review/reject-all', token: token);
  }

  Uri cameraStreamUri(int cameraId, {bool annotate = true, int maxFps = 60}) {
    return uri('/cameras/$cameraId/stream', {
      'annotate': annotate ? 'true' : 'false',
      'max_fps': '$maxFps',
    });
  }

  Future<List<CameraStreamSource>> cameraStreamSources(
    String token,
    int cameraId, {
    bool annotate = true,
    int maxFps = 60,
  }) async {
    final payload = await getJson(
      '/cameras/$cameraId/stream-source',
      token: token,
      query: {
        'annotate': annotate ? 'true' : 'false',
        'max_fps': '$maxFps',
      },
      timeout: const Duration(seconds: 5),
    );
    final map = _asMap(payload);
    final rawSources = map['sources'];
    final sources = <CameraStreamSource>[];
    if (rawSources is List) {
      for (final item in rawSources) {
        final source = _asMap(item);
        final rawUrl = '${source['url'] ?? ''}'.trim();
        if (rawUrl.isEmpty) continue;
        final parsed = Uri.tryParse(rawUrl);
        final sourceUri =
            parsed != null && parsed.hasScheme ? parsed : uri(rawUrl);
        if (sourceUri.scheme != 'http' && sourceUri.scheme != 'https') {
          continue;
        }
        final kind = '${source['kind'] ?? 'backend_proxy'}';
        if (kind != 'processor_direct' && !isBackendOrigin(sourceUri)) {
          continue;
        }
        final headers = <String, String>{};
        final rawHeaders = source['headers'];
        if (kind == 'processor_direct' && rawHeaders is Map) {
          for (final entry in rawHeaders.entries) {
            final name = '${entry.key}';
            if (name.toLowerCase() == 'x-processor-media-token') {
              headers[name] = '${entry.value}';
            }
          }
        }
        sources.add(
          CameraStreamSource(
            uri: sourceUri,
            headers: headers,
            kind: kind,
          ),
        );
      }
    }
    if (sources.isNotEmpty) return sources;
    return [
      CameraStreamSource(
        uri: cameraStreamUri(cameraId, annotate: annotate, maxFps: maxFps),
        headers: const {},
        kind: 'backend_proxy',
      ),
    ];
  }

  Uri cameraSnapshotUri(int cameraId, {bool annotate = false}) {
    return uri('/cameras/$cameraId/snapshot', {
      'annotate': annotate ? 'true' : 'false',
    });
  }

  Uri recordingFileUri(int recordingId, [String? mediaToken]) {
    return uri('/recordings/file/$recordingId');
  }

  Uri recordingMjpegUri(int recordingId, [String? mediaToken]) {
    return uri('/recordings/file/$recordingId/mjpeg', {
      'fps': '8',
      'max_width': '960',
      'quality': '72',
    });
  }

  Uri eventSnapshotUri(int eventId, [String? mediaToken]) {
    return uri('/detections/events/$eventId/snapshot');
  }

  Future<Uint8List> captureCameraJpegFrame(
    String token,
    int cameraId, {
    bool annotate = false,
  }) async {
    final request = http.Request(
      'GET',
      cameraSnapshotUri(cameraId, annotate: annotate),
    );
    request.headers['Accept'] = 'image/jpeg,*/*';
    request.headers['Authorization'] = 'Bearer $token';

    late http.StreamedResponse response;
    try {
      response = await _client.send(request).timeout(_requestTimeout);
    } catch (_) {
      throw ApiException(
        'Не удалось получить кадр live-потока (${baseUrlProvider()})',
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final body = await response.stream.bytesToString();
      throw ApiException(
        body.isEmpty
            ? 'Эфирный поток вернул HTTP ${response.statusCode}'
            : body,
        statusCode: response.statusCode,
      );
    }

    final buffer = BytesBuilder(copy: false);
    await for (final chunk in response.stream.timeout(_requestTimeout)) {
      buffer.add(chunk);
      final bytes = buffer.toBytes();
      final frame = _firstJpeg(bytes);
      if (frame != null) return frame;
      if (bytes.length > 8 * 1024 * 1024) {
        throw ApiException('Эфирный поток не отдал JPEG-кадр');
      }
    }
    throw ApiException('Эфирный поток завершился без JPEG-кадра');
  }

  Future<Map<String, dynamic>> uploadPersonPhoto(
    String token,
    int personId,
    String filePath, {
    int? cameraId,
  }) async {
    final request = http.MultipartRequest(
      'POST',
      uri('/persons/$personId/embeddings/photo'),
    );
    request.headers['Accept'] = 'application/json';
    request.headers['Authorization'] = 'Bearer $token';
    if (cameraId != null) request.fields['camera_id'] = '$cameraId';
    request.files.add(await http.MultipartFile.fromPath('file', filePath));

    late http.StreamedResponse streamed;
    try {
      streamed = await _client.send(request).timeout(_requestTimeout);
    } catch (_) {
      throw ApiException(
        'Не удалось отправить фото на backend (${baseUrlProvider()})',
      );
    }
    final response = await http.Response.fromStream(streamed);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(_readError(response), statusCode: response.statusCode);
    }
    if (response.bodyBytes.isEmpty) return <String, dynamic>{};
    return _asMap(jsonDecode(utf8.decode(response.bodyBytes)));
  }

  Future<Map<String, dynamic>> uploadPersonPhotoStream(
    String token,
    int personId, {
    required Stream<List<int>> stream,
    required int length,
    required String filename,
    int? cameraId,
  }) async {
    final request = http.MultipartRequest(
      'POST',
      uri('/persons/$personId/embeddings/photo'),
    );
    request.headers['Accept'] = 'application/json';
    request.headers['Authorization'] = 'Bearer $token';
    if (cameraId != null) request.fields['camera_id'] = '$cameraId';
    request.files.add(
      http.MultipartFile('file', stream, length, filename: filename),
    );

    late http.StreamedResponse streamed;
    try {
      streamed = await _client.send(request).timeout(_requestTimeout);
    } catch (_) {
      throw ApiException(
        'Не удалось отправить фото на backend (${baseUrlProvider()})',
      );
    }
    final response = await http.Response.fromStream(streamed);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(_readError(response), statusCode: response.statusCode);
    }
    if (response.bodyBytes.isEmpty) return <String, dynamic>{};
    return _asMap(jsonDecode(utf8.decode(response.bodyBytes)));
  }

  Future<Map<String, dynamic>> addPersonLiveEmbedding(
    String token,
    int personId,
    int cameraId,
  ) {
    return postJson(
      '/persons/$personId/embeddings/live',
      token: token,
      body: {'camera_id': cameraId},
    );
  }

  Future<Map<String, dynamic>> enrollPersonPhotoStream(
    String token, {
    required Stream<List<int>> stream,
    required int length,
    required String filename,
    String? firstName,
    String? lastName,
    String? middleName,
  }) async {
    return _multipartJson(
      '/persons/face/enroll-person-photo',
      token: token,
      fields: {
        if (_nullableText(firstName) != null) 'first_name': firstName!.trim(),
        if (_nullableText(lastName) != null) 'last_name': lastName!.trim(),
        if (_nullableText(middleName) != null)
          'middle_name': middleName!.trim(),
      },
      files: [http.MultipartFile('file', stream, length, filename: filename)],
    );
  }

  Future<Map<String, dynamic>> enrollPersonFromSnapshot(
    String token, {
    required int eventId,
    String? firstName,
    String? lastName,
    String? middleName,
  }) {
    return _multipartJson(
      '/persons/face/enroll-from-snapshot',
      token: token,
      fields: {
        'event_id': '$eventId',
        if (_nullableText(firstName) != null) 'first_name': firstName!.trim(),
        if (_nullableText(lastName) != null) 'last_name': lastName!.trim(),
        if (_nullableText(middleName) != null)
          'middle_name': middleName!.trim(),
      },
    );
  }

  Future<Map<String, dynamic>> enrollPersonFromRecording(
    String token, {
    required int recordingId,
    double? ts,
    String? firstName,
    String? lastName,
    String? middleName,
  }) {
    return _multipartJson(
      '/persons/face/enroll-from-recording',
      token: token,
      fields: {
        'recording_id': '$recordingId',
        if (ts != null) 'ts': '$ts',
        if (_nullableText(firstName) != null) 'first_name': firstName!.trim(),
        if (_nullableText(lastName) != null) 'last_name': lastName!.trim(),
        if (_nullableText(middleName) != null)
          'middle_name': middleName!.trim(),
      },
    );
  }

  Future<File> downloadReportSection(
    String token, {
    required String section,
    required String format,
    String? dateFrom,
    String? dateTo,
    int? groupId,
    Iterable<int> groupIds = const [],
    int? cameraId,
    Iterable<int> cameraIds = const [],
    int? processorId,
    Iterable<int> processorIds = const [],
    int? userId,
    Iterable<int> userIds = const [],
    int? personId,
    Iterable<int> personIds = const [],
  }) {
    return downloadFileWithQuery(
      '/reports/export',
      token: token,
      query: [
        MapEntry('section', section),
        MapEntry('format', format),
        MapEntry('date_from', dateFrom),
        MapEntry('date_to', dateTo),
        if (groupId != null) MapEntry('group_id', '$groupId'),
        for (final id in groupIds) MapEntry('group_ids', '$id'),
        if (cameraId != null) MapEntry('camera_id', '$cameraId'),
        for (final id in cameraIds) MapEntry('camera_ids', '$id'),
        if (processorId != null) MapEntry('processor_id', '$processorId'),
        for (final id in processorIds) MapEntry('processor_ids', '$id'),
        if (userId != null) MapEntry('user_id', '$userId'),
        for (final id in userIds) MapEntry('user_ids', '$id'),
        if (personId != null) MapEntry('person_id', '$personId'),
        for (final id in personIds) MapEntry('person_ids', '$id'),
      ],
      filename: 'cctv-$section.$format',
    );
  }

  Future<File> downloadAppearanceReport(
    String token, {
    required String format,
    int? personId,
    Iterable<int> personIds = const [],
    String? dateFrom,
    String? dateTo,
  }) {
    return downloadFileWithQuery(
      '/reports/appearances/export',
      token: token,
      query: [
        MapEntry('format', format),
        if (personId != null) MapEntry('person_id', '$personId'),
        for (final id in personIds) MapEntry('person_ids', '$id'),
        MapEntry('date_from', dateFrom),
        MapEntry('date_to', dateTo),
      ],
      filename: 'cctv-appearances.$format',
    );
  }

  static String? _nullableText(String? value) {
    final text = value?.trim() ?? '';
    return text.isEmpty ? null : text;
  }

  Future<Map<String, dynamic>> _multipartJson(
    String path, {
    required String token,
    Map<String, String> fields = const {},
    List<http.MultipartFile> files = const [],
  }) async {
    final request = http.MultipartRequest('POST', uri(path));
    request.headers['Accept'] = 'application/json';
    request.headers['Authorization'] = 'Bearer $token';
    request.fields.addAll(fields);
    request.files.addAll(files);

    late http.StreamedResponse streamed;
    try {
      streamed = await _client.send(request).timeout(_requestTimeout);
    } catch (_) {
      throw ApiException(
        'Не удалось отправить данные на backend (${baseUrlProvider()})',
      );
    }
    final response = await http.Response.fromStream(streamed);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(_readError(response), statusCode: response.statusCode);
    }
    if (response.bodyBytes.isEmpty) return <String, dynamic>{};
    return _asMap(jsonDecode(utf8.decode(response.bodyBytes)));
  }

  static Uint8List? _firstJpeg(Uint8List bytes) {
    var start = -1;
    for (var index = 0; index < bytes.length - 1; index++) {
      if (bytes[index] == 0xFF && bytes[index + 1] == 0xD8) {
        start = index;
        break;
      }
    }
    if (start < 0) return null;
    for (var index = start + 2; index < bytes.length - 1; index++) {
      if (bytes[index] == 0xFF && bytes[index + 1] == 0xD9) {
        return Uint8List.fromList(bytes.sublist(start, index + 2));
      }
    }
    return null;
  }

  static Future<Directory> _downloadDirectory() async {
    if (Platform.isWindows) {
      final home = Platform.environment['USERPROFILE'];
      if (home != null && home.isNotEmpty) {
        final downloads = Directory('$home${Platform.pathSeparator}Downloads');
        if (await downloads.exists()) return downloads;
      }
    }
    if (Platform.isLinux || Platform.isMacOS) {
      final home = Platform.environment['HOME'];
      if (home != null && home.isNotEmpty) {
        final downloads = Directory('$home${Platform.pathSeparator}Downloads');
        if (await downloads.exists()) return downloads;
      }
    }
    return getApplicationDocumentsDirectory();
  }

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
      if (detail is List && detail.isNotEmpty) {
        return _safeErrorText(
          _validationErrorText(detail),
          response.statusCode,
        );
      }
    } catch (_) {
      return _safeErrorText(text, response.statusCode);
    }
    return _safeErrorText(text, response.statusCode);
  }

  static String _validationErrorText(List<dynamic> errors) {
    final messages = <String>[];
    for (final item in errors) {
      if (item is! Map) continue;
      final loc = item['loc'];
      final field = loc is List && loc.isNotEmpty ? '${loc.last}' : '';
      final label = _fieldLabel(field);
      final type = '${item['type'] ?? ''}'.toLowerCase();
      final ctx = item['ctx'];
      final maxLength = ctx is Map ? ctx['max_length'] : null;
      final ge = ctx is Map ? ctx['ge'] : null;
      final le = ctx is Map ? ctx['le'] : null;
      String message;
      if (type.contains('string_too_long')) {
        message = '$label: не более ${maxLength ?? 'допустимого числа'} символов';
      } else if (type.contains('string_too_short')) {
        message = '$label: заполните поле';
      } else if (type.contains('int_parsing')) {
        message = '$label: введите число';
      } else if (type.contains('greater_than_equal')) {
        message = '$label: значение должно быть не меньше $ge';
      } else if (type.contains('less_than_equal')) {
        message = '$label: значение должно быть не больше $le';
      } else {
        message = '$label: проверьте значение';
      }
      messages.add(message);
    }
    if (messages.isEmpty) return 'Проверьте введённые данные';
    return 'Проверьте поля. ${messages.join('; ')}';
  }

  static String _fieldLabel(String field) {
    switch (field) {
      case 'host':
        return 'IP адрес камеры';
      case 'port':
        return 'Порт';
      case 'name':
        return 'Название';
      case 'location':
        return 'Локация';
      case 'username':
        return 'Логин';
      case 'password':
        return 'Пароль';
      default:
        return field.isEmpty ? 'Поле' : field;
    }
  }

  static String _safeErrorText(String text, int statusCode) {
    final normalized = text.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (normalized.isEmpty) return 'Backend вернул ошибку HTTP $statusCode';
    final translated = _translatedErrorText(normalized);
    if (translated != null) return translated;
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

  static String? _translatedErrorText(String text) {
    final lower = text.toLowerCase();
    if (lower == 'invalid credentials') {
      return 'Неверный логин или пароль';
    }
    if (lower == 'totp code required') {
      return 'Введите код двухфакторной аутентификации';
    }
    if (lower == 'invalid totp code') {
      return 'Неверный код двухфакторной аутентификации';
    }
    if (lower == 'too many login attempts') {
      return 'Слишком много попыток входа. Подождите и попробуйте снова.';
    }
    if (lower == 'too many totp attempts') {
      return 'Слишком много попыток ввода 2FA-кода. Подождите и попробуйте снова.';
    }
    if (lower == 'invalid current password') {
      return 'Текущий пароль указан неверно';
    }
    if (lower == 'totp not initialized') {
      return 'Сначала настройте двухфакторную аутентификацию';
    }
    if (lower == 'code expired') {
      return 'Код подключения истек. Создайте новый код.';
    }
    if (lower == 'invalid or already used code') {
      return 'Код подключения неверный или уже использован';
    }
    if (lower.contains('not authenticated') ||
        lower.contains('could not validate credentials') ||
        lower.contains('invalid authentication credentials')) {
      return 'Сессия истекла. Войдите снова.';
    }
    if (lower.contains('not enough permissions') ||
        lower.contains('forbidden')) {
      return 'Недостаточно прав для этого действия';
    }
    return null;
  }
}
