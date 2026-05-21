import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ConnectionProfile {
  const ConnectionProfile({
    required this.id,
    required this.name,
    required this.baseUrl,
    this.login,
    this.lastUsedAt,
  });

  final String id;
  final String name;
  final String baseUrl;
  final String? login;
  final DateTime? lastUsedAt;

  ConnectionProfile copyWith({
    String? id,
    String? name,
    String? baseUrl,
    String? login,
    DateTime? lastUsedAt,
  }) {
    return ConnectionProfile(
      id: id ?? this.id,
      name: name ?? this.name,
      baseUrl: baseUrl ?? this.baseUrl,
      login: login ?? this.login,
      lastUsedAt: lastUsedAt ?? this.lastUsedAt,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'baseUrl': baseUrl,
      if (login != null && login!.isNotEmpty) 'login': login,
      if (lastUsedAt != null) 'lastUsedAt': lastUsedAt!.toIso8601String(),
    };
  }

  static ConnectionProfile? fromJson(Object? raw) {
    if (raw is! Map) return null;
    final id = '${raw['id'] ?? ''}'.trim();
    final baseUrl = _normalizeUrl('${raw['baseUrl'] ?? ''}');
    if (id.isEmpty || baseUrl.isEmpty) return null;
    final name = '${raw['name'] ?? ''}'.trim();
    return ConnectionProfile(
      id: id,
      name: name.isEmpty ? _defaultName(baseUrl) : name,
      baseUrl: baseUrl,
      login: '${raw['login'] ?? ''}'.trim().isEmpty
          ? null
          : '${raw['login']}'.trim(),
      lastUsedAt: DateTime.tryParse('${raw['lastUsedAt'] ?? ''}'),
    );
  }

  static String _defaultName(String baseUrl) {
    final uri = Uri.tryParse(baseUrl);
    final host = uri?.host;
    return host == null || host.isEmpty ? 'CCTV Server' : host;
  }
}

class ConnectionProfilesController extends ChangeNotifier {
  static const _profilesKey = 'cctv.connection_profiles.v1';
  static const _activeProfileKey = 'cctv.connection_profiles.active';

  final List<ConnectionProfile> _profiles = [];
  String? _activeProfileId;

  List<ConnectionProfile> get profiles => List.unmodifiable(_profiles);
  String? get activeProfileId => _activeProfileId;

  ConnectionProfile? get activeProfile {
    final id = _activeProfileId;
    if (id == null) return _profiles.isEmpty ? null : _profiles.first;
    for (final profile in _profiles) {
      if (profile.id == id) return profile;
    }
    return _profiles.isEmpty ? null : _profiles.first;
  }

  Future<void> load({required String fallbackBaseUrl}) async {
    final prefs = await SharedPreferences.getInstance();
    _profiles.clear();
    final encoded = prefs.getString(_profilesKey);
    if (encoded != null && encoded.trim().isNotEmpty) {
      try {
        final raw = jsonDecode(encoded);
        if (raw is List) {
          for (final item in raw) {
            final profile = ConnectionProfile.fromJson(item);
            if (profile != null) _profiles.add(profile);
          }
        }
      } catch (_) {
        _profiles.clear();
      }
    }

    if (_profiles.isEmpty) {
      final normalized = _normalizeUrl(fallbackBaseUrl);
      _profiles.add(
        ConnectionProfile(
          id: _newId(),
          name: 'Локальный сервер',
          baseUrl: normalized.isEmpty ? 'http://127.0.0.1:8001' : normalized,
        ),
      );
    }

    final storedActive = prefs.getString(_activeProfileKey);
    _activeProfileId = _profiles.any((profile) => profile.id == storedActive)
        ? storedActive
        : _profiles.first.id;
    await _persist();
    notifyListeners();
  }

  Future<ConnectionProfile> saveProfile({
    String? id,
    required String name,
    required String baseUrl,
    String? login,
    bool makeActive = true,
  }) async {
    final normalizedUrl = _normalizeUrl(baseUrl);
    final safeId = (id == null || id.trim().isEmpty) ? _newId() : id.trim();
    final safeName = name.trim().isEmpty
        ? ConnectionProfile._defaultName(normalizedUrl)
        : name.trim();
    final profile = ConnectionProfile(
      id: safeId,
      name: safeName,
      baseUrl: normalizedUrl,
      login: login?.trim().isEmpty == true ? null : login?.trim(),
      lastUsedAt: DateTime.now(),
    );

    final index = _profiles.indexWhere((item) => item.id == safeId);
    if (index >= 0) {
      _profiles[index] = profile;
    } else {
      _profiles.add(profile);
    }
    if (makeActive) _activeProfileId = profile.id;
    await _persist();
    notifyListeners();
    return profile;
  }

  Future<void> selectProfile(String id) async {
    if (!_profiles.any((profile) => profile.id == id)) return;
    _activeProfileId = id;
    await _persist();
    notifyListeners();
  }

  Future<void> markLoginUsed(String login) async {
    final active = activeProfile;
    if (active == null) return;
    await saveProfile(
      id: active.id,
      name: active.name,
      baseUrl: active.baseUrl,
      login: login,
      makeActive: true,
    );
  }

  Future<void> deleteProfile(String id) async {
    if (_profiles.length <= 1) return;
    _profiles.removeWhere((profile) => profile.id == id);
    if (_activeProfileId == id) _activeProfileId = _profiles.first.id;
    await _persist();
    notifyListeners();
  }

  Future<void> _persist() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      _profilesKey,
      jsonEncode(_profiles.map((profile) => profile.toJson()).toList()),
    );
    final active = activeProfile;
    if (active != null) {
      await prefs.setString(_activeProfileKey, active.id);
    }
  }

  static String _newId() =>
      DateTime.now().microsecondsSinceEpoch.toRadixString(36);
}

String normalizeConnectionUrl(String value) => _normalizeUrl(value);

String _normalizeUrl(String value) {
  final trimmed = value.trim();
  if (trimmed.isEmpty) return '';
  return trimmed.replaceAll(RegExp(r'/+$'), '');
}
