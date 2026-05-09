import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../core/models/models.dart';
import '../../core/network/api_client.dart';

class AuthController extends ChangeNotifier {
  AuthController({required this.apiClient});

  static const _accessTokenKey = 'cctv.access_token';
  static const _mediaTokenKey = 'cctv.media_token';

  final ApiClient apiClient;
  final _secureStorage = const FlutterSecureStorage();

  CurrentUser? _user;
  String? _accessToken;
  String? _mediaToken;
  bool _isLoading = false;
  String? _error;

  CurrentUser? get user => _user;
  String? get accessToken => _accessToken;
  String? get mediaToken => _mediaToken;
  bool get isLoading => _isLoading;
  String? get error => _error;
  bool get isAuthenticated => _accessToken != null && _user != null;

  Future<void> restoreSession() async {
    _setLoading(true);
    try {
      final token = await _secureStorage.read(key: _accessTokenKey);
      final mediaToken = await _secureStorage.read(key: _mediaTokenKey);
      if (token == null || token.isEmpty) {
        _setLoading(false);
        return;
      }

      _accessToken = token;
      _mediaToken = mediaToken;
      _user = await apiClient.me(token);
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
      _user = await apiClient.me(response.accessToken);
      await _secureStorage.write(key: _accessTokenKey, value: _accessToken);
      if (_mediaToken != null) {
        await _secureStorage.write(key: _mediaTokenKey, value: _mediaToken);
      }
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
    await _secureStorage.write(key: _mediaTokenKey, value: _mediaToken);
    notifyListeners();
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
    _user = null;
    _error = null;
    await _secureStorage.delete(key: _accessTokenKey);
    await _secureStorage.delete(key: _mediaTokenKey);
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
}
