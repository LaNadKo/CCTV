import 'package:flutter/foundation.dart';

import '../network/api_client.dart';

class ServerFeaturesController extends ChangeNotifier {
  bool _setupAvailable = false;
  bool _loaded = false;
  bool _loading = false;
  DateTime? _lastAttempt;
  String? _loadedForToken;
  String? _loadedForBaseUrl;

  bool get setupAvailable => _setupAvailable;
  bool get loaded => _loaded;

  Future<void> refresh(ApiClient api, String? token) async {
    final cleanToken = token?.trim();
    if (cleanToken == null || cleanToken.isEmpty) {
      _set(setupAvailable: false, loaded: false, token: null, baseUrl: null);
      return;
    }

    final baseUrl = api.baseUrlProvider().replaceAll(RegExp(r'/+$'), '');
    final now = DateTime.now();
    final recentlyTried =
        _lastAttempt != null && now.difference(_lastAttempt!).inSeconds < 45;
    if (_loading ||
        (_loaded &&
            recentlyTried &&
            _loadedForToken == cleanToken &&
            _loadedForBaseUrl == baseUrl)) {
      return;
    }

    _loading = true;
    _lastAttempt = now;
    try {
      final payload = await api.getJson(
        '/system/features',
        token: cleanToken,
        timeout: const Duration(seconds: 5),
      );
      final root = payload is Map ? payload : const {};
      final setupAvailable =
          root['setup_available'] == true || root['nginx_available'] == true;
      _set(
        setupAvailable: setupAvailable,
        loaded: true,
        token: cleanToken,
        baseUrl: baseUrl,
      );
    } catch (_) {
      _set(
        setupAvailable: false,
        loaded: true,
        token: cleanToken,
        baseUrl: baseUrl,
      );
    } finally {
      _loading = false;
    }
  }

  void _set({
    required bool setupAvailable,
    required bool loaded,
    required String? token,
    required String? baseUrl,
  }) {
    final changed =
        _setupAvailable != setupAvailable ||
        _loaded != loaded ||
        _loadedForToken != token ||
        _loadedForBaseUrl != baseUrl;
    _setupAvailable = setupAvailable;
    _loaded = loaded;
    _loadedForToken = token;
    _loadedForBaseUrl = baseUrl;
    if (changed) notifyListeners();
  }
}
