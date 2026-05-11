import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../core/models/models.dart';
import '../../core/network/api_client.dart';

class AuthController extends ChangeNotifier {
  AuthController({required this.apiClient});

  static const _accessTokenKey = 'cctv.access_token';
  static const _mediaTokenKey = 'cctv.media_token';
  static const _mediaTokenExpiresAtKey = 'cctv.media_token_expires_at';

  final ApiClient apiClient;
  final _secureStorage = const FlutterSecureStorage();

  CurrentUser? _user;
  String? _accessToken;
  String? _mediaToken;
  DateTime? _mediaTokenExpiresAt;
  Timer? _mediaRefreshTimer;
  bool _isLoading = false;
  String? _error;

  CurrentUser? get user => _user;
  String? get accessToken => _accessToken;
  String? get mediaToken => _mediaToken;
  DateTime? get mediaTokenExpiresAt => _mediaTokenExpiresAt;
  bool get isLoading => _isLoading;
  String? get error => _error;
  bool get isAuthenticated => _accessToken != null && _user != null;

  Future<void> restoreSession() async {
    _setLoading(true);
    try {
      final token = await _secureStorage.read(key: _accessTokenKey);
      final mediaToken = await _secureStorage.read(key: _mediaTokenKey);
      final mediaExpiresAt = DateTime.tryParse(
        await _secureStorage.read(key: _mediaTokenExpiresAtKey) ?? '',
      );
      if (token == null || token.isEmpty) {
        _setLoading(false);
        return;
      }

      _accessToken = token;
      _mediaToken = mediaToken;
      _mediaTokenExpiresAt = mediaExpiresAt;
      _user = await apiClient.me(token);
      if (_mediaToken == null ||
          _mediaTokenExpiresAt == null ||
          _mediaTokenExpiresAt!.isBefore(
            DateTime.now().add(const Duration(minutes: 2)),
          )) {
        await refreshMediaToken();
      } else {
        _scheduleMediaRefresh();
      }
      _error = null;
    } catch (_) {
      await logout(notify: false);
    } finally {
      _setLoading(false);
    }
  }

  Future<void> login({
    required String login,
    required String password,
    String? totpCode,
  }) async {
    _setLoading(true);
    try {
      final response = await apiClient.login(
        login: login,
        password: password,
        totpCode: totpCode,
      );
      _accessToken = response.accessToken;
      _mediaToken = response.mediaAccessToken;
      _mediaTokenExpiresAt = _expiresAt(response.mediaTokenExpiresSeconds);
      _user = await apiClient.me(response.accessToken);
      await _secureStorage.write(key: _accessTokenKey, value: _accessToken);
      if (_mediaToken != null) {
        await _secureStorage.write(key: _mediaTokenKey, value: _mediaToken);
      }
      await _persistMediaExpiry();
      _scheduleMediaRefresh();
      _error = null;
    } catch (error) {
      _error = '$error';
      rethrow;
    } finally {
      _setLoading(false);
    }
  }

  Future<void> refreshMediaToken() async {
    final token = _accessToken;
    if (token == null) return;
    final response = await apiClient.createMediaToken(token);
    _mediaToken = response.mediaAccessToken;
    _mediaTokenExpiresAt = _expiresAt(response.expiresSeconds);
    await _secureStorage.write(key: _mediaTokenKey, value: _mediaToken);
    await _persistMediaExpiry();
    _scheduleMediaRefresh();
    notifyListeners();
  }

  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    final token = _accessToken;
    if (token == null) return;
    await apiClient.changePassword(
      token,
      currentPassword: currentPassword,
      newPassword: newPassword,
    );
    await reloadUser();
  }

  Future<void> reloadUser() async {
    final token = _accessToken;
    if (token == null) return;
    _user = await apiClient.me(token);
    notifyListeners();
  }

  Future<void> updateProfile({
    String? firstName,
    String? lastName,
    String? middleName,
  }) async {
    final token = _accessToken;
    if (token == null) return;
    _user = await apiClient.updateProfile(
      token,
      firstName: firstName,
      lastName: lastName,
      middleName: middleName,
    );
    notifyListeners();
  }

  Future<void> logout({bool notify = true}) async {
    _accessToken = null;
    _mediaToken = null;
    _mediaTokenExpiresAt = null;
    _mediaRefreshTimer?.cancel();
    _mediaRefreshTimer = null;
    _user = null;
    _error = null;
    await _secureStorage.delete(key: _accessTokenKey);
    await _secureStorage.delete(key: _mediaTokenKey);
    await _secureStorage.delete(key: _mediaTokenExpiresAtKey);
    if (notify) notifyListeners();
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }

  void _setLoading(bool value) {
    _isLoading = value;
    notifyListeners();
  }

  DateTime _expiresAt(int? seconds) {
    final safeSeconds = seconds == null || seconds <= 0 ? 900 : seconds;
    return DateTime.now().add(Duration(seconds: safeSeconds));
  }

  Future<void> _persistMediaExpiry() async {
    final expiresAt = _mediaTokenExpiresAt;
    if (expiresAt == null) {
      await _secureStorage.delete(key: _mediaTokenExpiresAtKey);
      return;
    }
    await _secureStorage.write(
      key: _mediaTokenExpiresAtKey,
      value: expiresAt.toIso8601String(),
    );
  }

  void _scheduleMediaRefresh() {
    _mediaRefreshTimer?.cancel();
    final expiresAt = _mediaTokenExpiresAt;
    if (_accessToken == null || expiresAt == null) return;
    final refreshAt = expiresAt.subtract(const Duration(minutes: 2));
    final delay = refreshAt.difference(DateTime.now());
    _mediaRefreshTimer = Timer(
      delay.isNegative ? const Duration(seconds: 5) : delay,
      () {
        unawaited(refreshMediaToken().catchError((_) {}));
      },
    );
  }

  @override
  void dispose() {
    _mediaRefreshTimer?.cancel();
    super.dispose();
  }
}
