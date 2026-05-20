import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

enum CctvThemeMode { system, dark, light }

enum LiveDensity { compact, comfortable, focus }

class ThemeController extends ChangeNotifier {
  static const maxPrimaryNavItems = 5;
  static const defaultPrimaryNav = [
    '/live',
    '/recordings',
    '/reviews',
    '/reports',
  ];

  static const _apiBaseUrlKey = 'cctv.api_base_url';
  static const _themeModeKey = 'cctv.theme_mode';
  static const _primaryAccentKey = 'cctv.primary_accent';
  static const _secondaryAccentKey = 'cctv.secondary_accent';
  static const _liveDensityKey = 'cctv.live_density';
  static const _primaryNavKey = 'cctv.primary_nav';

  String _apiBaseUrl = 'http://127.0.0.1:8001';
  CctvThemeMode _themeMode = CctvThemeMode.system;
  Color _primaryAccent = const Color(0xFF5EF0FF);
  Color _secondaryAccent = const Color(0xFF6F7BFF);
  LiveDensity _liveDensity = LiveDensity.comfortable;
  List<String> _primaryNav = List<String>.from(defaultPrimaryNav);

  String get apiBaseUrl => _apiBaseUrl;
  CctvThemeMode get themeMode => _themeMode;
  Color get primaryAccent => _primaryAccent;
  Color get secondaryAccent => _secondaryAccent;
  LiveDensity get liveDensity => _liveDensity;
  List<String> get primaryNav => List.unmodifiable(_primaryNav);

  ThemeMode get materialThemeMode {
    switch (_themeMode) {
      case CctvThemeMode.dark:
        return ThemeMode.dark;
      case CctvThemeMode.light:
        return ThemeMode.light;
      case CctvThemeMode.system:
        return ThemeMode.system;
    }
  }

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    _apiBaseUrl = _normalizeUrl(prefs.getString(_apiBaseUrlKey) ?? _apiBaseUrl);
    _themeMode = _parseThemeMode(prefs.getString(_themeModeKey));
    _primaryAccent = _parseColor(
      prefs.getString(_primaryAccentKey),
      _primaryAccent,
    );
    _secondaryAccent = _parseColor(
      prefs.getString(_secondaryAccentKey),
      _secondaryAccent,
    );
    _liveDensity = _parseLiveDensity(prefs.getString(_liveDensityKey));
    _primaryNav = _normalizePrimaryNav(
      prefs.getStringList(_primaryNavKey) ?? _primaryNav,
    );
    notifyListeners();
  }

  Future<void> setApiBaseUrl(String value) async {
    final normalized = _normalizeUrl(value);
    if (normalized == _apiBaseUrl) return;
    _apiBaseUrl = normalized;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_apiBaseUrlKey, normalized);
  }

  Future<void> setThemeMode(CctvThemeMode value) async {
    if (value == _themeMode) return;
    _themeMode = value;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_themeModeKey, value.name);
  }

  Future<void> setPrimaryAccent(Color value) async {
    _primaryAccent = value;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_primaryAccentKey, colorToHex(value));
  }

  Future<void> setSecondaryAccent(Color value) async {
    _secondaryAccent = value;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_secondaryAccentKey, colorToHex(value));
  }

  Future<void> setLiveDensity(LiveDensity value) async {
    if (value == _liveDensity) return;
    _liveDensity = value;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_liveDensityKey, value.name);
  }

  Future<void> setPrimaryNav(List<String> routes) async {
    final normalized = _normalizePrimaryNav(routes);
    if (_listEquals(normalized, _primaryNav)) return;
    _primaryNav = normalized;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(_primaryNavKey, normalized);
  }

  Future<void> resetPrimaryNav() async {
    _primaryNav = List<String>.from(defaultPrimaryNav);
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_primaryNavKey);
  }

  Future<void> resetAppearance() async {
    _themeMode = CctvThemeMode.system;
    _primaryAccent = const Color(0xFF5EF0FF);
    _secondaryAccent = const Color(0xFF6F7BFF);
    _liveDensity = LiveDensity.comfortable;
    _primaryNav = List<String>.from(defaultPrimaryNav);
    notifyListeners();

    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_themeModeKey);
    await prefs.remove(_primaryAccentKey);
    await prefs.remove(_secondaryAccentKey);
    await prefs.remove(_liveDensityKey);
    await prefs.remove(_primaryNavKey);
  }

  static String colorToHex(Color color) {
    final value = color.toARGB32() & 0x00FFFFFF;
    return '#${value.toRadixString(16).padLeft(6, '0')}';
  }

  static CctvThemeMode _parseThemeMode(String? value) {
    return CctvThemeMode.values.firstWhere(
      (mode) => mode.name == value,
      orElse: () => CctvThemeMode.system,
    );
  }

  static LiveDensity _parseLiveDensity(String? value) {
    return LiveDensity.values.firstWhere(
      (density) => density.name == value,
      orElse: () => LiveDensity.comfortable,
    );
  }

  static Color _parseColor(String? value, Color fallback) {
    if (value == null) return fallback;
    final normalized = value.trim().replaceFirst('#', '');
    if (!RegExp(r'^[0-9a-fA-F]{6}$').hasMatch(normalized)) return fallback;
    return Color(int.parse('FF$normalized', radix: 16));
  }

  static String _normalizeUrl(String value) {
    final trimmed = value.trim();
    if (trimmed.isEmpty) return 'http://127.0.0.1:8001';
    return trimmed.replaceAll(RegExp(r'/+$'), '');
  }

  static List<String> _normalizePrimaryNav(List<String> routes) {
    final unique = <String>[];
    for (final route in routes) {
      final normalized = route.trim();
      if (normalized.isEmpty || unique.contains(normalized)) continue;
      unique.add(normalized);
      if (unique.length >= maxPrimaryNavItems) break;
    }
    return unique.isEmpty ? List<String>.from(defaultPrimaryNav) : unique;
  }

  static bool _listEquals(List<String> left, List<String> right) {
    if (left.length != right.length) return false;
    for (var index = 0; index < left.length; index++) {
      if (left[index] != right[index]) return false;
    }
    return true;
  }
}
