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
  static const _liveGridColumnsKey = 'cctv.live_grid_columns';
  static const _liveCameraOrderKey = 'cctv.live_camera_order';
  static const _primaryNavKey = 'cctv.primary_nav';
  static const _lastRouteKey = 'cctv.last_route';

  String _apiBaseUrl = 'http://127.0.0.1:8001';
  CctvThemeMode _themeMode = CctvThemeMode.system;
  Color _primaryAccent = const Color(0xFF5EF0FF);
  Color _secondaryAccent = const Color(0xFF6F7BFF);
  LiveDensity _liveDensity = LiveDensity.comfortable;
  int _liveGridColumns = 0;
  List<int> _liveCameraOrder = const [];
  List<String> _primaryNav = List<String>.from(defaultPrimaryNav);
  String _lastRoute = '/live';

  String get apiBaseUrl => _apiBaseUrl;
  CctvThemeMode get themeMode => _themeMode;
  Color get primaryAccent => _primaryAccent;
  Color get secondaryAccent => _secondaryAccent;
  LiveDensity get liveDensity => _liveDensity;
  int get liveGridColumns => _liveGridColumns;
  List<int> get liveCameraOrder => List.unmodifiable(_liveCameraOrder);
  List<String> get primaryNav => List.unmodifiable(_primaryNav);
  String get lastRoute => _lastRoute;

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
    _liveGridColumns = _parseLiveGridColumns(prefs.getInt(_liveGridColumnsKey));
    _liveCameraOrder = _parseCameraOrder(
      prefs.getStringList(_liveCameraOrderKey),
    );
    _primaryNav = _normalizePrimaryNav(
      prefs.getStringList(_primaryNavKey) ?? _primaryNav,
    );
    _lastRoute = _normalizeRoute(prefs.getString(_lastRouteKey) ?? _lastRoute);
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

  Future<void> setLiveGridColumns(int value) async {
    final normalized = _parseLiveGridColumns(value);
    if (normalized == _liveGridColumns) return;
    _liveGridColumns = normalized;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_liveGridColumnsKey, normalized);
  }

  Future<void> setLiveCameraOrder(List<int> cameraIds) async {
    final unique = <int>[];
    for (final id in cameraIds) {
      if (id > 0 && !unique.contains(id)) unique.add(id);
    }
    if (_listEqualsInt(unique, _liveCameraOrder)) return;
    _liveCameraOrder = unique;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(
      _liveCameraOrderKey,
      unique.map((id) => '$id').toList(),
    );
  }

  Future<void> setPrimaryNav(List<String> routes) async {
    final normalized = _normalizePrimaryNav(routes);
    if (_listEquals(normalized, _primaryNav)) return;
    _primaryNav = normalized;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(_primaryNavKey, normalized);
  }

  Future<void> setLastRoute(String route) async {
    final normalized = _normalizeRoute(route);
    if (normalized == _lastRoute) return;
    _lastRoute = normalized;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_lastRouteKey, normalized);
  }

  Future<void> setAccentPreset(Color primary, Color secondary) async {
    _primaryAccent = primary;
    _secondaryAccent = secondary;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_primaryAccentKey, colorToHex(primary));
    await prefs.setString(_secondaryAccentKey, colorToHex(secondary));
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
    _liveGridColumns = 0;
    _liveCameraOrder = const [];
    _primaryNav = List<String>.from(defaultPrimaryNav);
    notifyListeners();

    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_themeModeKey);
    await prefs.remove(_primaryAccentKey);
    await prefs.remove(_secondaryAccentKey);
    await prefs.remove(_liveDensityKey);
    await prefs.remove(_liveGridColumnsKey);
    await prefs.remove(_liveCameraOrderKey);
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

  static int _parseLiveGridColumns(int? value) {
    if (value == null) return 0;
    return const [0, 1, 2, 3].contains(value) ? value : 0;
  }

  static List<int> _parseCameraOrder(List<String>? values) {
    if (values == null) return const [];
    final result = <int>[];
    for (final value in values) {
      final id = int.tryParse(value);
      if (id != null && id > 0 && !result.contains(id)) result.add(id);
    }
    return result;
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

  static String _normalizeRoute(String route) {
    final value = route.trim();
    if (value.startsWith('/')) return value;
    return '/live';
  }

  static bool _listEquals(List<String> left, List<String> right) {
    if (left.length != right.length) return false;
    for (var index = 0; index < left.length; index++) {
      if (left[index] != right[index]) return false;
    }
    return true;
  }

  static bool _listEqualsInt(List<int> left, List<int> right) {
    if (left.length != right.length) return false;
    for (var index = 0; index < left.length; index++) {
      if (left[index] != right[index]) return false;
    }
    return true;
  }
}
