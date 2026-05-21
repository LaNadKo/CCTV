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
    late http.Response response;
    try {
      response = await _client
          .get(
            uri(path, query),
            headers: {
              'Accept': 'application/octet-stream',
              'Authorization': 'Bearer $token',
            },
          )
          .timeout(const Duration(seconds: 120));
    } catch (_) {
      throw ApiException(
        'Не удалось скачать файл с backend (${baseUrlProvider()})',
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(_readError(response), statusCode: response.statusCode);
    }
    final directory = await _downloadDirectory();
    await directory.create(recursive: true);
    final safeName = filename.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_');
    final file = File('${directory.path}${Platform.pathSeparator}$safeName');
    await file.writeAsBytes(response.bodyBytes, flush: true);
    return file;
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

  Future<void> changePassword(
    String token, {
    required String currentPassword,
    required String newPassword,
  }) {
    return postVoid(
      '/auth/change-password',
      token: token,
      body: {'current_password': currentPassword, 'new_password': newPassword},
    );
  }

  Future<bool> getTotpEnabled(String token) async {
    final status = await getJson('/auth/totp/status', token: token);
    final map = _asMap(status);
    return map['enabled'] == true;
  }

  Future<Map<String, dynamic>> setupTotp(String token) {
    return postJson('/auth/totp/setup', token: token);
  }

  Future<bool> activateTotp(String token, String code) async {
    final status = await postJson(
      '/auth/totp/activate',
      token: token,
      body: {'code': code},
    );
    return status['enabled'] == true;
  }

  Future<bool> disableTotp(String token) async {
    final status = await postJson('/auth/totp/disable', token: token);
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
    double timeoutSeconds = 0.6,
  }) {
    return postVoid(
      '/admin/cameras/$cameraId/onvif/ptz/continuous',
      token: token,
      body: {
        'pan': pan,
        'tilt': tilt,
        'zoom': zoom,
        'timeout_seconds': timeoutSeconds,
      },
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
    return postVoid(
      '/admin/cameras/$cameraId/onvif/ptz/absolute',
      token: token,
      body: {
        if (pan != null) 'pan': pan,
        if (tilt != null) 'tilt': tilt,
        if (zoom != null) 'zoom': zoom,
        if (speed != null) 'speed': speed,
      },
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
    return postVoid(
      '/detections/events/$eventId/review',
      token: token,
      body: {
        'status': status,
        if (personId != null) 'person_id': personId,
        if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
      },
    );
  }

  Future<void> rejectAllPendingReviews(String token) {
    return postVoid('/detections/review/reject-all', token: token);
  }

  Uri cameraStreamUri(int cameraId, {bool annotate = true}) {
    return uri('/cameras/$cameraId/stream', {
      'annotate': annotate ? 'true' : 'false',
    });
  }

  Uri recordingFileUri(int recordingId, String mediaToken) {
    return uri('/recordings/file/$recordingId', {'token': mediaToken});
  }

  Uri recordingMjpegUri(int recordingId, String mediaToken) {
    return uri('/recordings/file/$recordingId/mjpeg', {'token': mediaToken});
  }

  Uri eventSnapshotUri(int eventId, String mediaToken) {
    return uri('/detections/events/$eventId/snapshot', {'token': mediaToken});
  }

  Future<Uint8List> captureCameraJpegFrame(
    String token,
    int cameraId, {
    bool annotate = false,
  }) async {
    final request = http.Request(
      'GET',
      cameraStreamUri(cameraId, annotate: annotate),
    );
    request.headers['Accept'] = 'multipart/x-mixed-replace,image/jpeg,*/*';
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
        body.isEmpty ? 'Live-поток вернул HTTP ${response.statusCode}' : body,
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
        throw ApiException('Live-поток не отдал JPEG-кадр');
      }
    }
    throw ApiException('Live-поток завершился без JPEG-кадра');
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
    int? cameraId,
    int? processorId,
    int? userId,
  }) {
    return downloadFile(
      '/reports/export',
      token: token,
      query: {
        'section': section,
        'format': format,
        'date_from': dateFrom,
        'date_to': dateTo,
        if (groupId != null) 'group_id': '$groupId',
        if (cameraId != null) 'camera_id': '$cameraId',
        if (processorId != null) 'processor_id': '$processorId',
        if (userId != null) 'user_id': '$userId',
      },
      filename: 'cctv-$section.$format',
    );
  }

  Future<File> downloadAppearanceReport(
    String token, {
    required String format,
    int? personId,
    String? dateFrom,
    String? dateTo,
  }) {
    return downloadFile(
      '/reports/appearances/export',
      token: token,
      query: {
        'format': format,
        if (personId != null) 'person_id': '$personId',
        'date_from': dateFrom,
        'date_to': dateTo,
      },
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
