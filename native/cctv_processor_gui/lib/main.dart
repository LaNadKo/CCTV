// ignore_for_file: prefer_initializing_formals

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProcessorGuiApp());
}

enum ProcessorThemeMode { dark, light }

class ProcessorGuiApp extends StatefulWidget {
  const ProcessorGuiApp({super.key});

  @override
  State<ProcessorGuiApp> createState() => _ProcessorGuiAppState();
}

class _ProcessorGuiAppState extends State<ProcessorGuiApp> {
  ProcessorThemeMode _themeMode = ProcessorThemeMode.dark;

  @override
  void initState() {
    super.initState();
    unawaited(_loadThemeMode());
  }

  Future<void> _loadThemeMode() async {
    try {
      final bridge = await RuntimeBridge.detect();
      final config = await bridge.readConfig();
      if (!mounted) return;
      setState(() => _themeMode = processorThemeModeFrom(config));
    } catch (_) {
      // The main screen will show a runtime error if the Processor bundle is absent.
    }
  }

  Future<void> _setThemeMode(ProcessorThemeMode value) async {
    if (value == _themeMode) return;
    setState(() => _themeMode = value);
    try {
      final bridge = await RuntimeBridge.detect();
      final config = Map<String, dynamic>.from(await bridge.readConfig());
      config['theme_mode'] = value.name;
      await bridge.writeConfig(config);
    } catch (_) {
      // Keep the visual switch responsive even if config persistence is unavailable.
    }
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'CCTV Процессор',
      themeAnimationDuration: ProcessorMotion.theme,
      themeAnimationCurve: ProcessorMotion.emphasized,
      themeMode: _themeMode == ProcessorThemeMode.dark
          ? ThemeMode.dark
          : ThemeMode.light,
      theme: ProcessorTheme.light(),
      darkTheme: ProcessorTheme.dark(),
      home: ProcessorHome(
        themeMode: _themeMode,
        onThemeModeChanged: _setThemeMode,
      ),
    );
  }
}

class ProcessorHome extends StatefulWidget {
  const ProcessorHome({
    super.key,
    required this.themeMode,
    required this.onThemeModeChanged,
  });

  final ProcessorThemeMode themeMode;
  final Future<void> Function(ProcessorThemeMode mode) onThemeModeChanged;

  @override
  State<ProcessorHome> createState() => _ProcessorHomeState();
}

class ProcessorMotion {
  const ProcessorMotion._();

  static const fast = Duration(milliseconds: 140);
  static const standard = Duration(milliseconds: 220);
  static const theme = Duration(milliseconds: 360);
  static const curve = Curves.easeOutCubic;
  static const emphasized = Cubic(0.2, 0, 0, 1);

  static Duration resolved(BuildContext context, Duration duration) {
    final media = MediaQuery.maybeOf(context);
    if (media == null) return duration;
    if (media.disableAnimations || media.accessibleNavigation) {
      return Duration.zero;
    }
    return duration;
  }
}

ProcessorThemeMode processorThemeModeFrom(Map<String, dynamic> config) {
  final value = '${config['theme_mode'] ?? ''}'.trim().toLowerCase();
  return ProcessorThemeMode.values.firstWhere(
    (mode) => mode.name == value,
    orElse: () => ProcessorThemeMode.dark,
  );
}

class PressScale extends StatefulWidget {
  const PressScale({
    super.key,
    required this.child,
    this.enabled = true,
    this.scale = 0.975,
  });

  final Widget child;
  final bool enabled;
  final double scale;

  @override
  State<PressScale> createState() => _PressScaleState();
}

class _PressScaleState extends State<PressScale> {
  bool _pressed = false;
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final targetScale = !widget.enabled
        ? 1.0
        : _pressed
        ? widget.scale
        : _hovered
        ? 1.01
        : 1.0;
    return MouseRegion(
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() {
        _hovered = false;
        _pressed = false;
      }),
      child: Listener(
        onPointerDown: widget.enabled
            ? (_) => setState(() => _pressed = true)
            : null,
        onPointerCancel: (_) => setState(() => _pressed = false),
        onPointerUp: (_) => setState(() => _pressed = false),
        child: AnimatedScale(
          scale: targetScale,
          duration: ProcessorMotion.fast,
          curve: ProcessorMotion.curve,
          child: widget.child,
        ),
      ),
    );
  }
}

class _ProcessorHomeState extends State<ProcessorHome> {
  final _backendController = TextEditingController();
  final _codeController = TextEditingController();
  final _nameController = TextEditingController();
  final _maxWorkersController = TextEditingController();
  final _motionController = TextEditingController();
  final _segmentController = TextEditingController();
  final _recordingsController = TextEditingController();
  final _snapshotsController = TextEditingController();
  final _mediaPortController = TextEditingController();
  final _mediaTokenController = TextEditingController();
  final _primaryColorController = TextEditingController();
  final _secondaryColorController = TextEditingController();

  RuntimeBridge? _bridge;
  Map<String, dynamic> _config = defaultProcessorConfig();
  LocalMetrics _metrics = const LocalMetrics();
  Map<String, dynamic> _status = const {};
  Map<String, dynamic> _systemInfo = const {};
  Map<String, dynamic> _acceleration = const {};
  List<dynamic> _assignments = const [];
  List<dynamic> _gallery = const [];
  String _storageText = 'Пока нет данных';
  String _selectedTab = 'dashboard';
  String _statusMessage = 'Инициализация...';
  String _diskLog = '';
  String _sessionLog = '';
  String _accelPreference = 'auto';
  bool _busy = false;
  bool _refreshing = false;
  bool _running = false;
  bool _stopping = false;
  DateTime? _lastFullRefresh;
  DateTime? _lastMetricsRefresh;
  DateTime? _startedAt;
  Process? _process;
  Timer? _pollTimer;
  Timer? _logTimer;

  @override
  void initState() {
    super.initState();
    unawaited(_bootstrap());
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _logTimer?.cancel();
    for (final controller in [
      _backendController,
      _codeController,
      _nameController,
      _maxWorkersController,
      _motionController,
      _segmentController,
      _recordingsController,
      _snapshotsController,
      _mediaPortController,
      _mediaTokenController,
      _primaryColorController,
      _secondaryColorController,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _bootstrap() async {
    final bridge = await RuntimeBridge.detect();
    final config = await bridge.readConfig();
    if (!mounted) return;
    setState(() {
      _bridge = bridge;
      _config = config;
      _accelPreference = '${config['processor_accel'] ?? 'auto'}';
      _statusMessage = 'Среда выполнения найдена: ${bridge.launcherDescription}';
    });
    _syncControllersFromConfig();
    await _refreshAll();
    _pollTimer = Timer.periodic(
      const Duration(seconds: 5),
      (_) => _refreshAll(),
    );
    _logTimer = Timer.periodic(
      const Duration(seconds: 2),
      (_) => _readLogTail(),
    );
  }

  void _syncControllersFromConfig() {
    _backendController.text = '${_config['backend_url'] ?? ''}';
    _nameController.text =
        '${_config['processor_name'] ?? Platform.localHostname}';
    _maxWorkersController.text = '${_config['max_workers'] ?? 4}';
    _motionController.text = '${_config['motion_threshold'] ?? 25.0}';
    _segmentController.text = '${_config['recording_segment_seconds'] ?? 60}';
    _recordingsController.text = '${_config['recordings_dir'] ?? ''}';
    _snapshotsController.text = '${_config['snapshots_dir'] ?? ''}';
    _mediaPortController.text = '${_config['media_port'] ?? 8777}';
    _mediaTokenController.text = '${_config['media_token'] ?? ''}';
    _primaryColorController.text =
        '${_config['theme_primary_color'] ?? '#49C8E8'}';
    _secondaryColorController.text =
        '${_config['theme_secondary_color'] ?? '#4C6FFF'}';
  }

  Future<void> _toggleThemeMode() async {
    final next = widget.themeMode == ProcessorThemeMode.dark
        ? ProcessorThemeMode.light
        : ProcessorThemeMode.dark;
    setState(() {
      _config = {..._config, 'theme_mode': next.name};
      _statusMessage = next == ProcessorThemeMode.dark
          ? 'Включена тёмная тема.'
          : 'Включена светлая тема.';
    });
    await widget.onThemeModeChanged(next);
  }

  Map<String, dynamic> _configFromControllers() {
    final next = Map<String, dynamic>.from(_config);
    next['backend_url'] = _backendController.text.trim().replaceAll(
      RegExp(r'/+$'),
      '',
    );
    next['processor_name'] = _nameController.text.trim().isEmpty
        ? Platform.localHostname
        : _nameController.text.trim();
    next['processor_accel'] = _accelPreference;
    next['max_workers'] = _intFrom(
      _maxWorkersController.text,
      4,
      min: 1,
      max: 64,
    );
    next['motion_threshold'] = _doubleFrom(
      _motionController.text,
      25.0,
      min: 0.0,
      max: 255.0,
    );
    next['recording_segment_seconds'] = _intFrom(
      _segmentController.text,
      60,
      min: 10,
      max: 60,
    );
    next['recordings_dir'] = _recordingsController.text.trim();
    next['snapshots_dir'] = _snapshotsController.text.trim();
    next['media_port'] = _intFrom(
      _mediaPortController.text,
      8777,
      min: 1,
      max: 65535,
    );
    next['media_token'] = _mediaTokenController.text.trim();
    next['theme_primary_color'] = _safeHex(
      _primaryColorController.text,
      '#49C8E8',
    );
    next['theme_secondary_color'] = _safeHex(
      _secondaryColorController.text,
      '#4C6FFF',
    );
    next['theme_mode'] = widget.themeMode.name;
    next.putIfAbsent('processor_node_uid', () => randomHex(32));
    return normalizeProcessorConfig(next, _bridge?.runtimeDir.path);
  }

  Future<void> _refreshAll({
    bool forceFull = false,
    bool allowWhileBusy = false,
  }) async {
    final bridge = _bridge;
    if (bridge == null || (_busy && !allowWhileBusy) || _refreshing) return;
    _refreshing = true;
    try {
      final now = DateTime.now();
      final includeMetricsRefresh =
          forceFull ||
          _lastMetricsRefresh == null ||
          now.difference(_lastMetricsRefresh!) >= const Duration(seconds: 30);
      final includeFullRefresh =
          forceFull &&
          (_lastFullRefresh == null ||
              now.difference(_lastFullRefresh!) >= const Duration(minutes: 5));
      final config = await bridge.readConfig();
      final runtimePid = await bridge.runningHeadlessPid();
      final metrics = includeMetricsRefresh
          ? await bridge.localMetrics()
          : _metrics;
      if (includeMetricsRefresh) {
        _lastMetricsRefresh = DateTime.now();
      }
      final status = await bridge.readBackendStatus(config);
      var systemInfo = _systemInfo;
      var acceleration = _acceleration;
      if (includeFullRefresh && !bridge.cliIsSlowBundle) {
        systemInfo = _asMap(
          await bridge.runCliJson([
            'system-info',
            '--json',
          ], timeout: const Duration(seconds: 45)),
        );
        acceleration = _asMap(
          await bridge.runCliJson([
            'acceleration',
            '--json',
            '--processor-accel',
            _accelPreference,
          ], timeout: const Duration(seconds: 45)),
        );
        _lastFullRefresh = DateTime.now();
      }
      final assignments = status['assignments'];
      if (!mounted) return;
      setState(() {
        _config = config;
        _metrics = metrics;
        _status = status;
        _systemInfo = systemInfo;
        _acceleration = acceleration;
        _assignments = assignments is List ? assignments : const [];
        _storageText = _stringifyStorage(
          status['storage'],
          status['storage_error'],
        );
        if (_process == null) {
          _running = runtimePid != null;
          if (_running && _startedAt == null) {
            _startedAt = DateTime.now();
          }
          if (!_running) {
            _startedAt = null;
          }
        }
        _statusMessage = _running
            ? 'Процессор запущен локально. PID: ${_process?.pid ?? runtimePid ?? '-'}'
            : _statusMessage;
      });
      if (includeFullRefresh || _gallery.isEmpty) {
        await _readGallery();
      }
      await _readLogTail();
    } catch (error) {
      if (!mounted) return;
      setState(() => _statusMessage = 'Ошибка обновления статуса: $error');
    } finally {
      _refreshing = false;
    }
  }

  Future<void> _readGallery() async {
    final bridge = _bridge;
    if (bridge == null || _status['connected'] != true) return;
    try {
      final payload = await bridge.readBackendGallery(
        await bridge.readConfig(),
      );
      if (!mounted) return;
      setState(() => _gallery = payload);
    } catch (_) {
      if (!mounted) return;
      setState(() => _gallery = const []);
    }
  }

  Future<void> _readLogTail() async {
    final bridge = _bridge;
    if (bridge == null) return;
    try {
      final guiText = await _readTail(bridge.processOutputLogPath);
      final processorText = await _readTail(bridge.logPath);
      final parts = [
        if (guiText.trim().isNotEmpty)
          '--- processor_gui_output.log ---\n$guiText',
        if (processorText.trim().isNotEmpty)
          '--- processor.log ---\n$processorText',
      ];
      if (parts.isEmpty) return;
      if (!mounted) return;
      setState(() => _diskLog = parts.join('\n'));
    } catch (_) {
      // Log file can be locked while processor writes to it.
    }
  }

  Future<String> _readTail(String path) async {
    final file = File(path);
    if (!await file.exists()) return '';
    final bytes = await file.readAsBytes();
    final text = const Utf8Decoder(allowMalformed: true).convert(bytes);
    final tail = text.length > 32000
        ? text.substring(text.length - 32000)
        : text;
    return sanitizeProcessOutput(tail);
  }

  Future<void> _saveSettings() async {
    final bridge = _bridge;
    if (bridge == null) return;
    setState(() {
      _busy = true;
      _statusMessage = 'Сохранение настроек...';
    });
    try {
      final next = _configFromControllers();
      await bridge.writeConfig(next);
      if (!mounted) return;
      setState(() {
        _config = next;
        _statusMessage = _running
            ? 'Настройки сохранены. Для параметров среды выполнения перезапустите Процессор.'
            : 'Настройки сохранены.';
      });
      _syncControllersFromConfig();
      await _refreshAll(allowWhileBusy: true);
    } catch (error) {
      if (!mounted) return;
      setState(() => _statusMessage = 'Ошибка сохранения: $error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _resetConfig() async {
    final bridge = _bridge;
    if (bridge == null || _running) return;
    setState(() => _busy = true);
    try {
      final config = defaultProcessorConfig(runtimeDir: bridge.runtimeDir.path);
      await bridge.writeConfig(config);
      if (!mounted) return;
      setState(() {
        _config = config;
        _accelPreference = 'auto';
        _statusMessage = 'Конфигурация сброшена.';
      });
      _syncControllersFromConfig();
      await _refreshAll(allowWhileBusy: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _testBackend() async {
    final url = _backendController.text.trim().replaceAll(RegExp(r'/+$'), '');
    if (url.isEmpty) {
      setState(() => _statusMessage = 'Введите адрес сервера.');
      return;
    }
    setState(() {
      _busy = true;
      _statusMessage = 'Проверка $url/health...';
    });
    final client = HttpClient();
    try {
      final request = await client
          .getUrl(Uri.parse('$url/health'))
          .timeout(const Duration(seconds: 8));
      final response = await request.close().timeout(
        const Duration(seconds: 8),
      );
      final body = await utf8.decodeStream(response);
      if (!mounted) return;
      setState(() {
        _statusMessage = response.statusCode == 200
            ? 'Backend доступен: $body'
            : 'Backend ответил статусом ${response.statusCode}: $body';
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _statusMessage = 'Backend недоступен: $error');
    } finally {
      client.close(force: true);
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _connectProcessor() async {
    final bridge = _bridge;
    if (bridge == null) return;
    final code = _codeController.text.trim();
    if (_backendController.text.trim().isEmpty || code.isEmpty) {
      setState(() => _statusMessage = 'Нужны адрес сервера и код подключения.');
      return;
    }
    final connectConfig = _configFromControllers();
    setState(() {
      _busy = true;
      _statusMessage = 'Подключение Процессора к серверу...';
    });
    try {
      final payload = await bridge.connectProcessor(connectConfig, code);
      final config = normalizeProcessorConfig({
        ...connectConfig,
        'backend_url': '${connectConfig['backend_url'] ?? ''}'.replaceAll(
          RegExp(r'/+$'),
          '',
        ),
        'api_key': '${payload['api_key'] ?? ''}',
        'processor_id': payload['processor_id'],
        'processor_name': payload['name'] ?? connectConfig['processor_name'],
      }, bridge.runtimeDir.path);
      await bridge.writeConfig(config);
      if (!mounted) return;
      setState(() {
        _config = config;
        _codeController.clear();
        _statusMessage =
            'Подключено. ID Процессора: ${_asMap(payload)['processor_id'] ?? config['processor_id']}.';
        _selectedTab = 'dashboard';
      });
      _syncControllersFromConfig();
      await _refreshAll(allowWhileBusy: true);
    } catch (error) {
      if (!mounted) return;
      setState(() => _statusMessage = 'Ошибка подключения: $error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _disconnectProcessor() async {
    final bridge = _bridge;
    if (bridge == null || _running) return;
    setState(() {
      _busy = true;
      _statusMessage = 'Удаление локального API-ключа...';
    });
    try {
      final config = Map<String, dynamic>.from(await bridge.readConfig());
      config['api_key'] = '';
      config['processor_id'] = null;
      await bridge.writeConfig(config);
      if (!mounted) return;
      setState(() {
        _config = config;
        _statusMessage = 'Локальная привязка удалена.';
      });
      _syncControllersFromConfig();
      await _refreshAll(allowWhileBusy: true);
    } catch (error) {
      if (!mounted) return;
      setState(() => _statusMessage = 'Ошибка отключения: $error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _startProcessor() async {
    final bridge = _bridge;
    if (bridge == null || _running) return;
    await _saveSettings();
    final config = _configFromControllers();
    if ('${config['backend_url'] ?? ''}'.isEmpty ||
        '${config['api_key'] ?? ''}'.isEmpty ||
        config['processor_id'] == null) {
      setState(() {
        _selectedTab = 'connect';
        _statusMessage =
            'Сначала подключите Процессор к серверу и получите API-ключ.';
      });
      return;
    }
    setState(() {
      _busy = true;
      _statusMessage = 'Запуск фонового Процессора...';
    });
    try {
      final existingPid = await bridge.runningHeadlessPid();
      if (existingPid != null) {
        if (!mounted) return;
        setState(() {
          _process = null;
          _running = true;
          _startedAt ??= DateTime.now();
          _stopping = false;
          _statusMessage = 'Процессор уже запущен. PID: $existingPid';
        });
        await _refreshAll(allowWhileBusy: true);
        return;
      }
      final process = await bridge.startHeadless(
        onOutput: (line) => _appendSessionLog(line),
      );
      if (!mounted) return;
      setState(() {
        _process = process;
        _running = true;
        _startedAt = DateTime.now();
        _stopping = false;
        _statusMessage = 'Процессор запущен. PID: ${process.pid}';
      });
      unawaited(
        process.exitCode.then((code) async {
          if (!mounted) return;
          final stoppedByUser = _stopping;
          final existingPid = await bridge.runningHeadlessPid();
          if (!stoppedByUser && existingPid != null) {
            if (!mounted) return;
            setState(() {
              _running = true;
              _process = null;
              _startedAt ??= DateTime.now();
              _stopping = false;
              _statusMessage = 'Процессор уже запущен. PID: $existingPid';
            });
            return;
          }
          await _markProcessorOffline();
          setState(() {
            _running = false;
            _process = null;
            _startedAt = null;
            _stopping = false;
            _statusMessage = stoppedByUser
                ? 'Процессор остановлен.'
                : 'Процессор завершился с кодом $code.';
          });
        }),
      );
    } catch (error) {
      if (!mounted) return;
      setState(() => _statusMessage = 'Ошибка запуска: $error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _stopProcessor() async {
    final bridge = _bridge;
    final process = _process;
    if (process == null) {
      final existingPid = await bridge?.runningHeadlessPid();
      if (existingPid != null) {
        setState(() {
          _stopping = true;
          _statusMessage = 'Остановка Процессора...';
        });
        await bridge!.stopRuntimeProcess(existingPid);
      }
      await _markProcessorOffline();
      setState(() {
        _running = false;
        _startedAt = null;
        _stopping = false;
      });
      return;
    }
    setState(() {
      _stopping = true;
      _statusMessage = 'Остановка Процессора...';
    });
    try {
      process.kill();
      await process.exitCode.timeout(const Duration(seconds: 6));
    } catch (_) {
      if (Platform.isWindows) {
        await Process.run('taskkill', ['/PID', '${process.pid}', '/T', '/F']);
      }
    }
    await _markProcessorOffline();
    if (!mounted) return;
    setState(() {
      _running = false;
      _process = null;
      _startedAt = null;
      _stopping = false;
      _statusMessage = 'Процессор остановлен.';
    });
  }

  Future<void> _markProcessorOffline() async {
    final config = _configFromControllers();
    final backendUrl = '${config['backend_url'] ?? ''}'.replaceAll(
      RegExp(r'/+$'),
      '',
    );
    final apiKey = '${config['api_key'] ?? ''}'.trim();
    final processorId = _nullableInt(config['processor_id']);
    if (backendUrl.isEmpty || apiKey.isEmpty || processorId == null) {
      return;
    }

    final client = HttpClient();
    try {
      final request = await client
          .postUrl(Uri.parse('$backendUrl/processors/$processorId/heartbeat'))
          .timeout(const Duration(seconds: 5));
      request.headers.contentType = ContentType.json;
      request.headers.set('X-Api-Key', apiKey);
      request.write(jsonEncode({'status': 'offline', 'stats': {}}));
      final response = await request.close().timeout(
        const Duration(seconds: 5),
      );
      await response.drain<void>();
      if (response.statusCode < 200 || response.statusCode >= 300) {
        _appendSessionLog(
          'Не удалось перевести Процессор в offline: HTTP ${response.statusCode}\n',
        );
      }
    } catch (error) {
      _appendSessionLog('Не удалось перевести Процессор в offline: $error\n');
    } finally {
      client.close(force: true);
    }
  }

  void _appendSessionLog(String line) {
    if (!mounted) return;
    setState(() {
      _sessionLog += line;
      if (_sessionLog.length > 32000) {
        _sessionLog = _sessionLog.substring(_sessionLog.length - 32000);
      }
    });
  }

  Future<void> _runPrewarm() async {
    final bridge = _bridge;
    if (bridge == null) return;
    setState(() {
      _busy = true;
      _statusMessage = 'Проверка и прогрев моделей...';
    });
    try {
      final payload = await bridge.runCliJson([
        'acceleration',
        '--json',
        '--processor-accel',
        _accelPreference,
        '--prewarm',
      ], timeout: const Duration(minutes: 3));
      if (!mounted) return;
      setState(() {
        _acceleration = _asMap(payload);
        _statusMessage =
            'Прогрев завершён. Face: ${_acceleration['face_prewarm_device'] ?? 'см. детали'}, Body: ${_acceleration['body_prewarm_device'] ?? 'см. детали'}.';
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _statusMessage = 'Ошибка прогрева: $error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _openRuntimePath(String path) async {
    final bridge = _bridge;
    if (bridge == null || path.trim().isEmpty) return;
    await bridge.openPath(path.trim());
  }

  Future<void> _pickDirectory(TextEditingController controller) async {
    final bridge = _bridge;
    if (bridge == null) return;
    final selected = await bridge.pickDirectory(controller.text.trim());
    if (selected == null || selected.isEmpty || !mounted) return;
    setState(() => controller.text = selected);
  }

  @override
  Widget build(BuildContext context) {
    final bridge = _bridge;
    final colors = context.processorColors;
    return Scaffold(
      body: DecoratedBox(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [colors.backdropStart, colors.bg, colors.backdropEnd],
          ),
        ),
        child: Stack(
          children: [
            const Positioned.fill(child: RepaintBoundary(child: _ProcessorAuroraBackdrop())),
            const Positioned.fill(child: RepaintBoundary(child: _GridBackdrop())),
            SafeArea(
              child: Row(
                children: [
                  _Sidebar(
                    selected: _selectedTab,
                    running: _running,
                    connected: _status['connected'] == true,
                    onSelect: (value) => setState(() => _selectedTab = value),
                  ),
                  Expanded(
                    child: AnimatedSwitcher(
                      duration: ProcessorMotion.resolved(
                        context,
                        ProcessorMotion.standard,
                      ),
                      switchInCurve: ProcessorMotion.emphasized,
                      switchOutCurve: Curves.easeInCubic,
                      transitionBuilder: (child, animation) {
                        final offset = Tween<Offset>(
                          begin: const Offset(0, 0.012),
                          end: Offset.zero,
                        ).animate(animation);
                        return FadeTransition(
                          opacity: animation,
                          child: SlideTransition(position: offset, child: child),
                        );
                      },
                      child: bridge == null
                          ? const Center(child: CircularProgressIndicator())
                          : _buildContent(bridge),
                    ),
                  ),
                ],
              ),
            ),
            if (_busy)
              Positioned(
                right: 24,
                bottom: 24,
                child: _StatusToast(message: _statusMessage),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildContent(RuntimeBridge bridge) {
    return Padding(
      key: ValueKey(_selectedTab),
      padding: const EdgeInsets.fromLTRB(12, 18, 22, 18),
      child: Column(
        children: [
          _TopStatusBar(
            message: _statusMessage,
            bridge: bridge,
            running: _running,
            busy: _busy,
            onRefresh: _refreshAll,
            themeMode: widget.themeMode,
            onToggleTheme: _toggleThemeMode,
          ),
          const SizedBox(height: 14),
          Expanded(
            child: switch (_selectedTab) {
              'connect' => _connectPage(bridge),
              'settings' => _settingsPage(bridge),
              'diagnostics' => _diagnosticsPage(bridge),
              'logs' => _logsPage(bridge),
              'help' => _helpPage(),
              _ => _dashboardPage(bridge),
            },
          ),
        ],
      ),
    );
  }

  Widget _dashboardPage(RuntimeBridge bridge) {
    final colors = context.processorColors;
    final uptime = _startedAt == null
        ? '-'
        : _formatDuration(DateTime.now().difference(_startedAt!));
    final processorId = _config['processor_id'];
    final bound = processorId != null && '$processorId'.trim().isNotEmpty;
    return SingleChildScrollView(
      padding: const EdgeInsets.only(bottom: 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _HeroPanel(
            eyebrow: 'УПРАВЛЕНИЕ ПРОЦЕССОРОМ',
            title:
                '${_config['processor_name'] ?? Platform.localHostname} · ${bound ? 'ID $processorId' : 'не подключён'}',
            trailing: Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                if (!bound)
                  OutlinedButton.icon(
                    onPressed: _busy
                        ? null
                        : () => setState(() => _selectedTab = 'connect'),
                    icon: const Icon(Icons.link_rounded),
                    label: const Text('Подключить'),
                  ),
                ElevatedButton.icon(
                  onPressed: _busy || _running || !bound
                      ? null
                      : _startProcessor,
                  icon: const Icon(Icons.play_arrow_rounded),
                  label: const Text('Запустить'),
                ),
                OutlinedButton.icon(
                  onPressed: !_running ? null : _stopProcessor,
                  icon: const Icon(Icons.stop_rounded),
                  label: const Text('Остановить'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          LayoutBuilder(
            builder: (context, constraints) {
              final compact = constraints.maxWidth < 720;
              final columns = constraints.maxWidth >= 1180
                  ? 4
                  : constraints.maxWidth >= 840
                      ? 3
                      : 2;
              final cards = [
                _MetricCard(
                  label: 'Сервис',
                  value: _running ? 'Работает' : 'Остановлен',
                  icon: Icons.power_settings_new_rounded,
                  accent: _running ? colors.success : colors.warning,
                ),
                _MetricCard(
                  label: 'CPU',
                  value: _metrics.cpuPercent == null
                      ? '-'
                      : '${_metrics.cpuPercent!.toStringAsFixed(0)}%',
                  icon: Icons.speed_rounded,
                ),
                _MetricCard(
                  label: 'RAM',
                  value: _metrics.ramText,
                  icon: Icons.memory_rounded,
                ),
                _MetricCard(
                  label: 'GPU',
                  value: _metrics.gpuText(_systemInfo),
                  icon: Icons.developer_board_rounded,
                ),
                _MetricCard(
                  label: 'Сеть',
                  value: _metrics.netText,
                  icon: Icons.lan_rounded,
                ),
                _MetricCard(
                  label: 'Диск',
                  value: _metrics.diskText,
                  icon: Icons.storage_rounded,
                ),
                _MetricCard(
                  label: 'Камеры',
                  value: '${_assignments.length}',
                  icon: Icons.videocam_rounded,
                ),
                _MetricCard(
                  label: 'Время работы',
                  value: uptime,
                  icon: Icons.timer_rounded,
                ),
              ];
              if (compact) {
                return Column(
                  children: cards
                      .map(
                        (card) => Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: card,
                        ),
                      )
                      .toList(),
                );
              }
              return GridView.count(
                crossAxisCount: columns,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                crossAxisSpacing: 12,
                mainAxisSpacing: 12,
                childAspectRatio: columns == 2 ? 3.4 : 2.9,
                children: cards,
              );
            },
          ),
          const SizedBox(height: 14),
          _TwoColumnLayout(
            primaryFlex: 3,
            secondaryFlex: 2,
            primary: _GlassPanel(
              child: _Section(
                title: 'Назначенные камеры',
                subtitle: _status['assignments_error'] == null
                    ? null
                    : '${_status['assignments_error']}',
                child: _assignments.isEmpty
                    ? const _EmptyState(
                        text: 'Камеры пока не назначены этому Процессору.',
                      )
                    : Column(
                        children: [
                          for (final item in _assignments.take(8))
                            _CameraAssignmentRow(item: _asMap(item)),
                        ],
                      ),
              ),
            ),
            secondary: _GlassPanel(
              child: _Section(
                title: 'Быстрые действия',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _ActionTile(
                      label: 'Открыть записи',
                      icon: Icons.video_library_rounded,
                      onTap: () => _openRuntimePath(
                        '${_config['recordings_dir'] ?? ''}',
                      ),
                    ),
                    _ActionTile(
                      label: 'Открыть снимки',
                      icon: Icons.image_rounded,
                      onTap: () => _openRuntimePath(
                        '${_config['snapshots_dir'] ?? ''}',
                      ),
                    ),
                    _ActionTile(
                      label: 'Открыть лог',
                      icon: Icons.subject_rounded,
                      onTap: () => _openRuntimePath(bridge.logPath),
                    ),
                    _ActionTile(
                      label: 'Открыть конфиг',
                      icon: Icons.tune_rounded,
                      onTap: () => _openRuntimePath(bridge.configPath),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _connectPage(RuntimeBridge bridge) {
    return SingleChildScrollView(
      padding: const EdgeInsets.only(bottom: 18),
      child: Column(
        children: [
          _HeroPanel(
            eyebrow: 'ПОДКЛЮЧЕНИЕ',
            title: 'Подключение к серверу',
            trailing: _ConnectionBadge(connected: _status['connected'] == true),
          ),
          const SizedBox(height: 14),
          _TwoColumnLayout(
            primaryFlex: 3,
            secondaryFlex: 2,
            primary: _GlassPanel(
              child: _Section(
                title: 'Данные подключения',
                child: Column(
                  children: [
                    _TextField(
                      controller: _backendController,
                      label: 'Адрес сервера',
                      hint: 'http://127.0.0.1:8001',
                    ),
                    _CodeInputField(
                      controller: _codeController,
                      label: 'Код подключения',
                    ),
                    _TextField(
                      controller: _nameController,
                      label: 'Имя Процессора',
                      hint: Platform.localHostname,
                    ),
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        OutlinedButton.icon(
                          onPressed: _busy ? null : _testBackend,
                          icon: const Icon(Icons.health_and_safety_rounded),
                          label: const Text('Проверить'),
                        ),
                        ElevatedButton.icon(
                          onPressed: _busy ? null : _connectProcessor,
                          icon: const Icon(Icons.link_rounded),
                          label: const Text('Подключить'),
                        ),
                        OutlinedButton.icon(
                          onPressed:
                              _busy || _running ? null : _disconnectProcessor,
                          icon: const Icon(Icons.link_off_rounded),
                          label: const Text('Сбросить ключ'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            secondary: _GlassPanel(
              child: _Section(
                title: 'Локальная сводка',
                child: Column(
                  children: [
                    _InfoRow('Среда выполнения', bridge.runtimeDir.path),
                    _InfoRow('Запуск', bridge.launcherDescription),
                    _InfoRow('Сервер', '${_config['backend_url'] ?? '-'}'),
                    _InfoRow(
                      'ID Процессора',
                      '${_config['processor_id'] ?? '-'}',
                    ),
                    _InfoRow(
                      'API-ключ',
                      '${_config['api_key'] ?? ''}'.isEmpty
                          ? 'нет'
                          : 'сохранён локально',
                    ),
                    _InfoRow(
                      'Публикуемый IP',
                      '${_config['advertised_ip'] ?? 'авто'}',
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _settingsPage(RuntimeBridge bridge) {
    return SingleChildScrollView(
      padding: const EdgeInsets.only(bottom: 18),
      child: Column(
        children: [
          _HeroPanel(
            eyebrow: 'НАСТРОЙКИ ПРОЦЕССОРА',
            title: 'Настройки среды выполнения',
            trailing: Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                OutlinedButton.icon(
                  onPressed: _busy || _running ? null : _resetConfig,
                  icon: const Icon(Icons.restart_alt_rounded),
                  label: const Text('Сбросить'),
                ),
                ElevatedButton.icon(
                  onPressed: _busy ? null : _saveSettings,
                  icon: const Icon(Icons.save_rounded),
                  label: const Text('Сохранить'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          LayoutBuilder(
            builder: (context, constraints) {
              final compact = constraints.maxWidth < 860;
              final cards = [
                _settingsPerformance(),
                _settingsStorage(bridge),
                _settingsRuntime(),
                _settingsTheme(),
              ];
              if (compact) {
                return Column(
                  children: cards
                      .map(
                        (card) => Padding(
                          padding: const EdgeInsets.only(bottom: 14),
                          child: card,
                        ),
                      )
                      .toList(),
                );
              }
              return GridView.count(
                crossAxisCount: 2,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                crossAxisSpacing: 14,
                mainAxisSpacing: 14,
                childAspectRatio: 1.55,
                children: cards,
              );
            },
          ),
        ],
      ),
    );
  }

  Widget _settingsPerformance() {
    return _GlassPanel(
      child: _Section(
        title: 'Производительность',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: _TextField(
                    controller: _maxWorkersController,
                    label: 'Макс. камер',
                    numeric: true,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _TextField(
                    controller: _motionController,
                    label: 'Порог движения',
                    numeric: true,
                  ),
                ),
              ],
            ),
            Row(
              children: [
                Expanded(
                  child: _TextField(
                    controller: _segmentController,
                    label: 'Сегмент записи, сек',
                    numeric: true,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _DropdownField(
                    label: 'Ускорение',
                    value: _accelPreference,
                    values: const [
                      'auto',
                      'cpu',
                      'nvidia',
                      'intel',
                      'amd',
                      'directml',
                    ],
                    onChanged: (value) =>
                        setState(() => _accelPreference = value ?? 'auto'),
                  ),
                ),
              ],
            ),
            Row(
              children: [
                Expanded(
                  child: _DropdownField<int>(
                    label: 'Сканирование лиц',
                    value: _sanitizeFaceScanDivisor(
                      _config['face_scan_divisor'],
                      8,
                    ),
                    values: const [2, 4, 8, 16, 32, 64, 120],
                    labelBuilder: _divisorLabel,
                    onChanged: (value) => setState(
                      () => _config['face_scan_divisor'] = value ?? 4,
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _DropdownField<int>(
                    label: 'Оверлей эфира',
                    value: _sanitizeDivisor(
                      _config['overlay_frame_divisor'],
                      1,
                    ),
                    values: const [1, 2, 4, 8, 16, 32, 64, 120],
                    labelBuilder: _divisorLabel,
                    onChanged: (value) => setState(
                      () => _config['overlay_frame_divisor'] = value ?? 1,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                _PresetChip(
                  label: 'Экономия',
                  onTap: () => _applyPreset(32, 8),
                ),
                _PresetChip(label: 'Баланс', onTap: () => _applyPreset(8, 1)),
                _PresetChip(label: 'Максимум', onTap: () => _applyPreset(2, 1)),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _settingsStorage(RuntimeBridge bridge) {
    return _GlassPanel(
      child: _Section(
        title: 'Локальное хранилище',
        child: Column(
          children: [
            _TextField(
              controller: _recordingsController,
              label: 'Папка записей',
            ),
            _TextField(
              controller: _snapshotsController,
              label: 'Папка снимков',
            ),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () => _pickDirectory(_recordingsController),
                    icon: const Icon(Icons.folder_rounded),
                    label: const Text('Выбрать записи'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () => _pickDirectory(_snapshotsController),
                    icon: const Icon(Icons.folder_rounded),
                    label: const Text('Выбрать снимки'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () =>
                        _openRuntimePath(_recordingsController.text),
                    icon: const Icon(Icons.folder_open_rounded),
                    label: const Text('Открыть записи'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () =>
                        _openRuntimePath(_snapshotsController.text),
                    icon: const Icon(Icons.folder_open_rounded),
                    label: const Text('Открыть снимки'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            _SmallNote(text: _storageText),
          ],
        ),
      ),
    );
  }

  Widget _settingsRuntime() {
    return _GlassPanel(
      child: _Section(
        title: 'Медиасервер',
        child: Column(
          children: [
            _TextField(
              controller: _mediaPortController,
              label: 'Порт медиасервера',
              numeric: true,
            ),
            _TextField(
              controller: _mediaTokenController,
              label: 'Токен медиасервера',
              obscure: true,
            ),
            _SmallNote(
              text:
                  'Токен используется сервером для доступа к эфиру и архиву. Если изменить его во время работы, перезапустите Процессор.',
            ),
          ],
        ),
      ),
    );
  }

  Widget _settingsTheme() {
    return _GlassPanel(
      child: _Section(
        title: 'Тема GUI',
        child: Column(
          children: [
            Row(
              children: [
                Expanded(
                  child: _TextField(
                    controller: _primaryColorController,
                    label: 'Основной цвет',
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _TextField(
                    controller: _secondaryColorController,
                    label: 'Доп. цвет',
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                _ColorPreview(
                  color: _safeHex(_primaryColorController.text, '#49C8E8'),
                ),
                const SizedBox(width: 10),
                _ColorPreview(
                  color: _safeHex(_secondaryColorController.text, '#4C6FFF'),
                ),
                const SizedBox(width: 10),
                OutlinedButton(
                  onPressed: () {
                    _primaryColorController.text = '#49C8E8';
                    _secondaryColorController.text = '#4C6FFF';
                    setState(() {});
                  },
                  child: const Text('Процессор'),
                ),
                const SizedBox(width: 8),
                OutlinedButton(
                  onPressed: () {
                    _primaryColorController.text = '#5EF0FF';
                    _secondaryColorController.text = '#6F7BFF';
                    setState(() {});
                  },
                  child: const Text('Консоль'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _diagnosticsPage(RuntimeBridge bridge) {
    return SingleChildScrollView(
      padding: const EdgeInsets.only(bottom: 18),
      child: Column(
        children: [
          _HeroPanel(
            eyebrow: 'ДИАГНОСТИКА',
            title: 'Диагностика Процессора',
            trailing: ElevatedButton.icon(
              onPressed: _busy ? null : _runPrewarm,
              icon: const Icon(Icons.model_training_rounded),
              label: const Text('Прогреть модели'),
            ),
          ),
          const SizedBox(height: 14),
          _TwoColumnLayout(
            primary: _JsonCard(title: 'Acceleration', payload: _acceleration),
            secondary: _JsonCard(title: 'System info', payload: _systemInfo),
          ),
          const SizedBox(height: 14),
          _TwoColumnLayout(
            primary: _GlassPanel(
              child: _Section(
                title: 'Галерея персон',
                child: _gallery.isEmpty
                    ? const _EmptyState(
                        text: 'Галерея пуста или Процессор не подключён.',
                      )
                    : Column(
                        children: [
                          for (final item in _gallery.take(12))
                            _InfoRow(
                              '${_asMap(item)['person_id'] ?? '-'}',
                              '${_asMap(item)['label'] ?? item}',
                            ),
                        ],
                      ),
              ),
            ),
            secondary: _JsonCard(title: 'CLI status', payload: _status),
          ),
        ],
      ),
    );
  }

  Widget _logsPage(RuntimeBridge bridge) {
    final text = [
      if (_sessionLog.trim().isNotEmpty)
        '--- session stdout/stderr ---\n$_sessionLog',
      if (_diskLog.trim().isNotEmpty) '--- processor.log ---\n$_diskLog',
      if (_sessionLog.trim().isEmpty && _diskLog.trim().isEmpty)
        'Лог пока пуст.',
    ].join('\n');
    return Column(
      children: [
        _HeroPanel(
          eyebrow: 'SERVICE LOG',
          title: 'Журнал работы',
          trailing: Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              OutlinedButton.icon(
                onPressed: () => _openRuntimePath(bridge.logPath),
                icon: const Icon(Icons.open_in_new_rounded),
                label: const Text('processor.log'),
              ),
              OutlinedButton.icon(
                onPressed: () => _openRuntimePath(bridge.processOutputLogPath),
                icon: const Icon(Icons.terminal_rounded),
                label: const Text('stdout/stderr'),
              ),
              OutlinedButton.icon(
                onPressed: () => setState(() {
                  _sessionLog = '';
                  _diskLog = '';
                }),
                icon: const Icon(Icons.cleaning_services_rounded),
                label: const Text('Очистить окно'),
              ),
            ],
          ),
        ),
        const SizedBox(height: 14),
        Expanded(
          child: _GlassPanel(
            child: SingleChildScrollView(
              child: SelectableText(
                text,
                style: GoogleFonts.jetBrainsMono(
                  fontSize: 12,
                  height: 1.35,
                  color: context.processorColors.text,
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _helpPage() {
    return SingleChildScrollView(
      padding: const EdgeInsets.only(bottom: 18),
      child: Column(
        children: const [
          _HeroPanel(
            eyebrow: 'СПРАВКА',
            title: 'Справка по нативному GUI',
          ),
          SizedBox(height: 14),
          _HelpGrid(),
        ],
      ),
    );
  }

  void _applyPreset(int faceDivisor, int overlayDivisor) {
    _config['face_scan_divisor'] = faceDivisor;
    _config['overlay_frame_divisor'] = overlayDivisor;
    setState(
      () => _statusMessage =
          'Выбран пресет: сканирование /$faceDivisor, оверлей /$overlayDivisor. Сохраните настройки.',
    );
  }
}

class RuntimeBridge {
  RuntimeBridge({
    required this.runtimeDir,
    required this.launcherDescription,
    required String executable,
    required List<String> baseArgs,
    required String cliExecutable,
    required List<String> cliBaseArgs,
    required Directory workingDirectory,
    this.cliIsSlowBundle = false,
  }) : _executable = executable,
       _baseArgs = baseArgs,
       _cliExecutable = cliExecutable,
       _cliBaseArgs = cliBaseArgs,
       _workingDirectory = workingDirectory;

  final Directory runtimeDir;
  final String launcherDescription;
  final bool cliIsSlowBundle;
  final String _executable;
  final List<String> _baseArgs;
  final String _cliExecutable;
  final List<String> _cliBaseArgs;
  final Directory _workingDirectory;

  String get configPath => joinPath(runtimeDir.path, 'processor_config.json');
  String get logPath => joinPath(runtimeDir.path, 'processor.log');
  String get processOutputLogPath =>
      joinPath(runtimeDir.path, 'processor_gui_output.log');

  Future<int?> runningHeadlessPid() async {
    if (!Platform.isWindows) return null;
    final executableFile = File(_executable);
    final executableName = executableFile.uri.pathSegments.isEmpty
        ? ''
        : executableFile.uri.pathSegments.last;
    if (!executableName.toLowerCase().endsWith('.exe')) return null;
    final safePath = executableFile.path.replaceAll("'", "''");
    final safeName = executableName.replaceAll("'", "''");
    final script =
        '''
\$targetPath = '$safePath'
Get-CimInstance Win32_Process -Filter "Name='$safeName'" |
  Where-Object { \$_.ExecutablePath -eq \$targetPath } |
  Select-Object -First 1 -ExpandProperty ProcessId
''';
    try {
      final result = await Process.run('powershell.exe', [
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-Command',
        script,
      ]).timeout(const Duration(seconds: 5));
      if (result.exitCode != 0) return null;
      return int.tryParse('${result.stdout}'.trim());
    } catch (_) {
      return null;
    }
  }

  Future<void> stopRuntimeProcess(int pid) async {
    if (pid <= 0) return;
    if (Platform.isWindows) {
      await Process.run('taskkill', ['/PID', '$pid', '/T', '/F']);
      return;
    }
    Process.killPid(pid);
  }

  static Future<RuntimeBridge> detect() async {
    final appDir = File(Platform.resolvedExecutable).parent;
    final processorRuntimeBinaries = Platform.isWindows
        ? const ['CCTV-Processor-Runtime.exe', 'CCTV-Processor.exe']
        : const ['CCTV-Processor-Runtime', 'CCTV-Processor'];
    final processorCliBinary = Platform.isWindows
        ? 'CCTV-Processor-CLI.exe'
        : 'CCTV-Processor-CLI';
    final pythonExecutable = Platform.isWindows ? 'python' : 'python3';
    final bundledDir = Directory(joinPath(appDir.path, 'processor'));
    final bundledExe = await _firstExistingFile(
      bundledDir,
      processorRuntimeBinaries,
    );
    if (bundledExe != null) {
      final bundledCli = File(joinPath(bundledDir.path, processorCliBinary));
      final hasCli = await bundledCli.exists();
      return RuntimeBridge(
        runtimeDir: bundledDir,
        launcherDescription: 'портативная Python-среда Процессора',
        executable: bundledExe.path,
        baseArgs: const [],
        cliExecutable: hasCli ? bundledCli.path : bundledExe.path,
        cliBaseArgs: hasCli ? const [] : const ['--cli'],
        workingDirectory: bundledDir,
        cliIsSlowBundle: hasCli,
      );
    }

    final localExe = await _firstExistingFile(appDir, processorRuntimeBinaries);
    if (localExe != null) {
      final localCli = File(joinPath(appDir.path, processorCliBinary));
      final hasCli = await localCli.exists();
      return RuntimeBridge(
        runtimeDir: appDir,
        launcherDescription: 'локальная Python-среда Процессора',
        executable: localExe.path,
        baseArgs: const [],
        cliExecutable: hasCli ? localCli.path : localExe.path,
        cliBaseArgs: hasCli ? const [] : const ['--cli'],
        workingDirectory: appDir,
        cliIsSlowBundle: hasCli,
      );
    }

    final repo = findRepoRoot([Directory.current, appDir]);
    if (repo != null) {
      final distRoot = Directory(joinPath(repo.path, 'processor', 'dist'));
      for (final dirName in const [
        'CCTV-Processor-Runtime',
        'CCTV-Processor',
      ]) {
        final distDir = Directory(joinPath(distRoot.path, dirName));
        final distExe = await _firstExistingFile(
          distDir,
          processorRuntimeBinaries,
        );
        if (distExe != null) {
          final distLocalCli = File(joinPath(distDir.path, processorCliBinary));
          final distRootCli = File(joinPath(distRoot.path, processorCliBinary));
          final cli = await distLocalCli.exists()
              ? distLocalCli
              : (await distRootCli.exists() ? distRootCli : distExe);
          final hasCli = cli.path != distExe.path;
          return RuntimeBridge(
            runtimeDir: distDir,
            launcherDescription: 'Python-среда Процессора из репозитория',
            executable: distExe.path,
            baseArgs: const [],
            cliExecutable: cli.path,
            cliBaseArgs: hasCli ? const [] : const ['--cli'],
            workingDirectory: distDir,
            cliIsSlowBundle: hasCli,
          );
        }
      }
      final runRuntime = File(
        joinPath(repo.path, 'processor', 'run_runtime.py'),
      );
      final cliPy = File(joinPath(repo.path, 'processor', 'cli.py'));
      return RuntimeBridge(
        runtimeDir: Directory(joinPath(repo.path, 'processor')),
        launcherDescription: 'исходная Python-среда',
        executable: pythonExecutable,
        baseArgs: [runRuntime.path],
        cliExecutable: pythonExecutable,
        cliBaseArgs: [cliPy.path],
        workingDirectory: repo,
      );
    }

    throw StateError(
      'Не найдена среда выполнения Процессора. Положите папку processor рядом с интерфейсом или запускайте из репозитория.',
    );
  }

  static Future<File?> _firstExistingFile(
    Directory directory,
    List<String> names,
  ) async {
    for (final name in names) {
      final file = File(joinPath(directory.path, name));
      if (await file.exists()) return file;
    }
    return null;
  }

  Future<Map<String, dynamic>> readConfig() async {
    final file = File(configPath);
    if (!await file.exists()) {
      return defaultProcessorConfig(runtimeDir: runtimeDir.path);
    }
    try {
      final raw = jsonDecode(await file.readAsString());
      return normalizeProcessorConfig(_asMap(raw), runtimeDir.path);
    } catch (_) {
      return defaultProcessorConfig(runtimeDir: runtimeDir.path);
    }
  }

  Future<void> writeConfig(Map<String, dynamic> config) async {
    await runtimeDir.create(recursive: true);
    final file = File(configPath);
    await file.writeAsString(
      const JsonEncoder.withIndent(
        '  ',
      ).convert(normalizeProcessorConfig(config, runtimeDir.path)),
      encoding: utf8,
      flush: true,
    );
    await _restrictConfigPermissions(file);
  }

  Future<void> _restrictConfigPermissions(File file) async {
    try {
      if (Platform.isWindows) {
        final user = Platform.environment['USERNAME'];
        final domain = Platform.environment['USERDOMAIN'];
        if (user == null || user.isEmpty) return;
        final account = domain == null || domain.isEmpty
            ? user
            : '$domain\\$user';
        await Process.run('icacls', [
          file.path,
          '/inheritance:r',
          '/grant:r',
          '$account:(R,W)',
          '*S-1-5-18:(F)',
          '*S-1-5-32-544:(F)',
        ]);
      } else {
        await Process.run('chmod', ['600', file.path]);
      }
    } catch (_) {
      // Permission hardening is best-effort; config writes must stay available.
    }
  }

  Future<Map<String, dynamic>> connectProcessor(
    Map<String, dynamic> config,
    String code, {
    Duration timeout = const Duration(seconds: 12),
  }) async {
    final baseUrl = _backendBaseUrl(config);
    if (baseUrl.isEmpty) {
      throw StateError('Адрес сервера не задан');
    }
    final payload = {
      'code': code,
      'name': '${config['processor_name'] ?? Platform.localHostname}',
      'node_uid': '${config['processor_node_uid'] ?? ''}',
      'hostname': Platform.localHostname,
      'os_info': Platform.operatingSystemVersion,
      'version': '1.0.0',
      'capabilities': {
        'max_workers': config['max_workers'],
        'processor_accel': config['processor_accel'],
        'media_port': config['media_port'],
        'media_token': config['media_token'],
        'runtime': 'flutter-gui',
      },
    };
    return _asMap(
      await _postJson(
        _backendUri(baseUrl, '/processors/connect'),
        payload,
        timeout: timeout,
      ),
    );
  }

  Future<Map<String, dynamic>> readBackendStatus(
    Map<String, dynamic> config, {
    Duration timeout = const Duration(seconds: 5),
  }) async {
    final baseUrl = _backendBaseUrl(config);
    final apiKey = '${config['api_key'] ?? ''}'.trim();
    final processorId = _nullableInt(config['processor_id']);
    final payload = <String, dynamic>{
      'base_dir': runtimeDir.path,
      'config_file': configPath,
      'log_file': logPath,
      'configured': baseUrl.isNotEmpty,
      'connected': apiKey.isNotEmpty && processorId != null,
      'processor_name': config['processor_name'],
      'processor_id': processorId,
      'backend_url': baseUrl,
    };
    if (baseUrl.isEmpty) return payload;

    try {
      payload['health'] = await _getJson(
        _backendUri(baseUrl, '/health'),
        timeout: timeout,
      );
    } catch (error) {
      payload['health_error'] = '$error';
    }

    if (apiKey.isEmpty || processorId == null) return payload;

    try {
      final assignments = await _getJson(
        _backendUri(baseUrl, '/processors/$processorId/assignments'),
        apiKey: apiKey,
        timeout: timeout,
      );
      final list = assignments is List ? assignments : const [];
      payload['assignments_count'] = list.length;
      payload['assignments'] = list;
    } catch (error) {
      payload['assignments_error'] = '$error';
    }

    try {
      payload['storage'] = await _getJson(
        _backendUri(baseUrl, '/processors/$processorId/storage-config'),
        apiKey: apiKey,
        timeout: timeout,
      );
    } catch (error) {
      payload['storage_error'] = '$error';
    }

    return payload;
  }

  Future<List<dynamic>> readBackendGallery(
    Map<String, dynamic> config, {
    Duration timeout = const Duration(seconds: 5),
  }) async {
    final baseUrl = _backendBaseUrl(config);
    final apiKey = '${config['api_key'] ?? ''}'.trim();
    final processorId = _nullableInt(config['processor_id']);
    if (baseUrl.isEmpty || apiKey.isEmpty || processorId == null) {
      return const [];
    }
    final payload = await _getJson(
      _backendUri(baseUrl, '/processors/$processorId/gallery'),
      apiKey: apiKey,
      timeout: timeout,
    );
    return payload is List ? payload : const [];
  }

  String _backendBaseUrl(Map<String, dynamic> config) {
    return '${config['backend_url'] ?? ''}'.trim().replaceAll(
      RegExp(r'/+$'),
      '',
    );
  }

  Uri _backendUri(
    String baseUrl,
    String path, {
    Map<String, String>? queryParameters,
  }) {
    return Uri.parse('$baseUrl$path').replace(queryParameters: queryParameters);
  }

  Future<Object?> _getJson(
    Uri uri, {
    String? apiKey,
    required Duration timeout,
  }) async {
    final client = HttpClient()..connectionTimeout = timeout;
    try {
      final request = await client.getUrl(uri).timeout(timeout);
      request.headers.set(HttpHeaders.acceptHeader, 'application/json');
      if (apiKey != null && apiKey.isNotEmpty) {
        request.headers.set('X-Api-Key', apiKey);
      }
      final response = await request.close().timeout(timeout);
      final body = await utf8.decodeStream(response).timeout(timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw StateError('HTTP ${response.statusCode}: $body');
      }
      return body.trim().isEmpty ? null : jsonDecode(body);
    } finally {
      client.close(force: true);
    }
  }

  Future<Object?> _postJson(
    Uri uri,
    Map<String, dynamic> payload, {
    String? apiKey,
    required Duration timeout,
  }) async {
    final client = HttpClient()..connectionTimeout = timeout;
    try {
      final request = await client.postUrl(uri).timeout(timeout);
      request.headers.contentType = ContentType.json;
      request.headers.set(HttpHeaders.acceptHeader, 'application/json');
      if (apiKey != null && apiKey.isNotEmpty) {
        request.headers.set('X-Api-Key', apiKey);
      }
      request.write(jsonEncode(payload));
      final response = await request.close().timeout(timeout);
      final body = await utf8.decodeStream(response).timeout(timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw StateError('HTTP ${response.statusCode}: $body');
      }
      return body.trim().isEmpty ? null : jsonDecode(body);
    } finally {
      client.close(force: true);
    }
  }

  Future<CommandResult> runCli(
    List<String> args, {
    Duration timeout = const Duration(seconds: 30),
  }) async {
    File? captureFile;
    var commandArgs = [..._cliBaseArgs, ...args];
    if (cliIsSlowBundle) {
      final stamp = DateTime.now().microsecondsSinceEpoch;
      captureFile = File(
        joinPath(
          Directory.systemTemp.path,
          'cctv_processor_cli_$stamp.json',
        ),
      );
      commandArgs = [
        ..._cliBaseArgs,
        '--cli-capture-file',
        captureFile.path,
        ...args,
      ];
    }

    final result = await Process.run(
      _cliExecutable,
      commandArgs,
      workingDirectory: _workingDirectory.path,
      environment: _processEnvironment(),
      stdoutEncoding: utf8,
      stderrEncoding: utf8,
    ).timeout(timeout);

    CommandResult commandResult;
    if (captureFile != null && await captureFile.exists()) {
      try {
        final payload = jsonDecode(await captureFile.readAsString());
        final data = payload is Map ? payload : const {};
        commandResult = CommandResult(
          exitCode: _nullableInt(data['exit_code']) ?? result.exitCode,
          stdout: sanitizeProcessOutput('${data['stdout'] ?? ''}'),
          stderr: sanitizeProcessOutput('${data['stderr'] ?? ''}'),
        );
      } finally {
        try {
          await captureFile.delete();
        } catch (_) {
          // Temporary diagnostics files are best-effort cleanup.
        }
      }
    } else {
      commandResult = CommandResult(
        exitCode: result.exitCode,
        stdout: sanitizeProcessOutput('${result.stdout}'),
        stderr: sanitizeProcessOutput('${result.stderr}'),
      );
    }
    if (commandResult.exitCode != 0) {
      throw StateError(
        commandResult.stderr.trim().isEmpty
            ? commandResult.stdout
            : commandResult.stderr,
      );
    }
    return commandResult;
  }

  Future<Object?> runCliJson(
    List<String> args, {
    Duration timeout = const Duration(seconds: 30),
  }) async {
    final result = await runCli(args, timeout: timeout);
    return decodeLooseJson(result.stdout);
  }

  Future<Process> startHeadless({
    required ValueChanged<String> onOutput,
  }) async {
    final args = [..._baseArgs, '--headless'];
    final process = await Process.start(
      _executable,
      args,
      workingDirectory: _workingDirectory.path,
      environment: _processEnvironment(),
    );
    final sink = File(
      processOutputLogPath,
    ).openWrite(mode: FileMode.append, encoding: utf8);
    void attach(Stream<List<int>> stream, String source) {
      var pending = '';
      void emit(String text) {
        final clean = sanitizeProcessOutput(text);
        if (clean.trim().isEmpty) return;
        final entry = '${DateTime.now().toIso8601String()} [$source] $clean';
        sink.write(entry);
        onOutput(entry);
      }

      stream
          .transform(const Utf8Decoder(allowMalformed: true))
          .listen(
            (chunk) {
              pending += chunk;
              final lines = pending.split('\n');
              pending = lines.removeLast();
              for (final line in lines) {
                emit('$line\n');
              }
              if (pending.length > 8192) {
                emit(pending);
                pending = '';
              }
            },
            onDone: () {
              if (pending.trim().isNotEmpty) emit(pending);
            },
          );
    }

    attach(process.stdout, 'stdout');
    attach(process.stderr, 'stderr');
    unawaited(process.exitCode.whenComplete(sink.close));
    return process;
  }

  Map<String, String> _processEnvironment() {
    return {
      'PROCESSOR_RUNTIME_DIR': runtimeDir.path,
      'PYTHONUTF8': '1',
      'PYTHONIOENCODING': 'utf-8',
      'ORT_LOGGING_LEVEL': '3',
      'ORT_LOG_SEVERITY_LEVEL': '3',
      'GLOG_minloglevel': '2',
    };
  }

  Future<LocalMetrics> localMetrics() async {
    if (!Platform.isWindows) return const LocalMetrics();
    const script = r'''
$ErrorActionPreference = "SilentlyContinue"
$os = Get-CimInstance Win32_OperatingSystem
$cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
$driveName = (Get-Location).Path.Substring(0,1)
$drive = Get-PSDrive -Name $driveName
$netAdapters = Get-CimInstance Win32_PerfFormattedData_Tcpip_NetworkInterface | Where-Object { $_.Name -notmatch "Loopback|isatap|Teredo" }
$sent = ($netAdapters | Measure-Object -Property BytesSentPersec -Sum).Sum
$recv = ($netAdapters | Measure-Object -Property BytesReceivedPersec -Sum).Sum
$gpuName = (Get-CimInstance Win32_VideoController | Select-Object -First 1 -ExpandProperty Name)
$gpuUtil = $null
$gpuTemp = $null
$nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvidia) {
  $gpuRaw = & nvidia-smi --query-gpu=utilization.gpu,temperature.gpu,name --format=csv,noheader,nounits 2>$null | Select-Object -First 1
  if ($gpuRaw) {
    $parts = $gpuRaw -split ","
    if ($parts.Length -ge 1) { $gpuUtil = [double]($parts[0].Trim()) }
    if ($parts.Length -ge 2) { $gpuTemp = [double]($parts[1].Trim()) }
    if ($parts.Length -ge 3) { $gpuName = $parts[2].Trim() }
  }
}
[PSCustomObject]@{
  cpu_percent = [double]$cpu
  ram_total_gb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
  ram_used_gb = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1MB, 2)
  disk_total_gb = [math]::Round(($drive.Used + $drive.Free) / 1GB, 2)
  disk_used_gb = [math]::Round($drive.Used / 1GB, 2)
  net_sent_mbps = [math]::Round(($sent * 8) / 1MB, 2)
  net_recv_mbps = [math]::Round(($recv * 8) / 1MB, 2)
  gpu_name = $gpuName
  gpu_util_percent = $gpuUtil
  gpu_temp_c = $gpuTemp
} | ConvertTo-Json -Compress
''';
    try {
      final result = await Process.run('powershell.exe', [
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-Command',
        script,
      ]).timeout(const Duration(seconds: 10));
      if (result.exitCode != 0) return const LocalMetrics();
      return LocalMetrics.fromJson(_asMap(decodeLooseJson('${result.stdout}')));
    } catch (_) {
      return const LocalMetrics();
    }
  }

  Future<void> openPath(String path) async {
    final target = path.trim();
    if (target.isEmpty) return;
    if (Platform.isWindows) {
      await Process.start('explorer.exe', [target]);
      return;
    }
    if (Platform.isMacOS) {
      await Process.start('open', [target]);
      return;
    }
    await Process.start('xdg-open', [target]);
  }

  Future<String?> pickDirectory(String initialPath) async {
    if (!Platform.isWindows) return null;
    final safeInitial = initialPath.replaceAll("'", "''");
    final script =
        '''
Add-Type -AssemblyName System.Windows.Forms
\$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
\$dialog.Description = "Выберите папку Процессора"
\$dialog.ShowNewFolderButton = \$true
if ('$safeInitial' -and (Test-Path '$safeInitial')) { \$dialog.SelectedPath = '$safeInitial' }
if (\$dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output \$dialog.SelectedPath }
''';
    final result = await Process.run('powershell.exe', [
      '-NoProfile',
      '-STA',
      '-ExecutionPolicy',
      'Bypass',
      '-Command',
      script,
    ]);
    if (result.exitCode != 0) return null;
    final selected = '${result.stdout}'.trim();
    return selected.isEmpty ? null : selected;
  }
}

String sanitizeProcessOutput(String chunk) {
  var text = chunk
      .replaceAll('\uFEFF', '')
      .replaceAll('\u0000', '')
      .replaceAll('\uFFFD', '')
      .replaceAll(RegExp(r'\x1B\[[0-?]*[ -/]*[@-~]'), '')
      .replaceAll('\r\n', '\n')
      .replaceAll('\r', '\n');
  final lines = text
      .split('\n')
      .where((line) => !_isNoisyProcessLine(line))
      .join('\n');
  if (lines.isEmpty) return '';
  return lines.endsWith('\n') ? lines : '$lines\n';
}

bool _isNoisyProcessLine(String line) {
  final trimmed = line.trim();
  if (trimmed.isEmpty) return true;
  if (trimmed == '----------------------------------------') return true;
  final lower = trimmed.toLowerCase();
  if (lower.contains('verifyoutputsizes')) return true;
  if (lower.contains('expected shape from model')) return true;
  if (lower.contains('actual shape of') && lower.contains('for output')) {
    return true;
  }
  if (lower.contains('onnxruntime') && lower.contains('execution_frame.cc')) {
    return true;
  }
  if (lower.contains('exception occurred during processing of request from')) {
    return true;
  }
  if (lower.contains('during handling of the above exception')) return true;
  if (lower.contains('connectionabortederror')) return true;
  if (lower.contains('connectionreseterror')) return true;
  if (lower.contains('brokenpipeerror')) return true;
  if (lower.contains('socketserver.py')) return true;
  if (lower.contains('http\\server.py') || lower.contains('http/server.py')) {
    return true;
  }
  if (lower.contains('processor\\media_server.py') ||
      lower.contains('processor/media_server.py')) {
    return true;
  }
  return false;
}

class CommandResult {
  const CommandResult({
    required this.exitCode,
    required this.stdout,
    required this.stderr,
  });

  final int exitCode;
  final String stdout;
  final String stderr;
}

class LocalMetrics {
  const LocalMetrics({
    this.cpuPercent,
    this.ramTotalGb,
    this.ramUsedGb,
    this.diskTotalGb,
    this.diskUsedGb,
    this.netSentMbps,
    this.netRecvMbps,
    this.gpuName,
    this.gpuUtilPercent,
    this.gpuTempC,
  });

  final double? cpuPercent;
  final double? ramTotalGb;
  final double? ramUsedGb;
  final double? diskTotalGb;
  final double? diskUsedGb;
  final double? netSentMbps;
  final double? netRecvMbps;
  final String? gpuName;
  final double? gpuUtilPercent;
  final double? gpuTempC;

  String get ramText {
    if (ramTotalGb == null || ramUsedGb == null) return '-';
    return '${ramUsedGb!.toStringAsFixed(1)} / ${ramTotalGb!.toStringAsFixed(1)} GB';
  }

  String get diskText {
    if (diskTotalGb == null || diskUsedGb == null) return '-';
    return '${diskUsedGb!.toStringAsFixed(0)} / ${diskTotalGb!.toStringAsFixed(0)} GB';
  }

  String get netText {
    if (netSentMbps == null || netRecvMbps == null) return '-';
    return '↑${netSentMbps!.toStringAsFixed(1)} ↓${netRecvMbps!.toStringAsFixed(1)}';
  }

  String gpuText(Map<String, dynamic> systemInfo) {
    final name = gpuName ?? '${systemInfo['gpu'] ?? ''}';
    if (name.trim().isEmpty) return 'GPU не обнаружена';
    final util = gpuUtilPercent == null
        ? ''
        : ' ${gpuUtilPercent!.toStringAsFixed(0)}%';
    final temp = gpuTempC == null ? '' : ' ${gpuTempC!.toStringAsFixed(0)}C';
    return '$name$util$temp';
  }

  factory LocalMetrics.fromJson(Map<String, dynamic> json) {
    return LocalMetrics(
      cpuPercent: _num(json['cpu_percent']),
      ramTotalGb: _num(json['ram_total_gb']),
      ramUsedGb: _num(json['ram_used_gb']),
      diskTotalGb: _num(json['disk_total_gb']),
      diskUsedGb: _num(json['disk_used_gb']),
      netSentMbps: _num(json['net_sent_mbps']),
      netRecvMbps: _num(json['net_recv_mbps']),
      gpuName: '${json['gpu_name'] ?? ''}'.trim().isEmpty
          ? null
          : '${json['gpu_name']}',
      gpuUtilPercent: _num(json['gpu_util_percent']),
      gpuTempC: _num(json['gpu_temp_c']),
    );
  }
}

class _Sidebar extends StatelessWidget {
  const _Sidebar({
    required this.selected,
    required this.running,
    required this.connected,
    required this.onSelect,
  });

  final String selected;
  final bool running;
  final bool connected;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    const items = [
      ('dashboard', Icons.dashboard_rounded, 'Монитор'),
      ('connect', Icons.link_rounded, 'Подключение'),
      ('settings', Icons.tune_rounded, 'Настройки'),
      ('diagnostics', Icons.science_rounded, 'Диагностика'),
      ('logs', Icons.subject_rounded, 'Журнал'),
      ('help', Icons.help_rounded, 'Справка'),
    ];
    return Container(
      width: 258,
      margin: const EdgeInsets.fromLTRB(18, 18, 8, 18),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: colors.panel.withValues(alpha: 0.78),
        borderRadius: BorderRadius.circular(28),
        border: Border.all(color: colors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(22),
              gradient: LinearGradient(
                colors: [
                  colors.accent.withValues(alpha: 0.22),
                  colors.surface.withValues(alpha: 0.90),
                ],
              ),
              border: Border.all(color: colors.border),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'CCTV',
                  style: TextStyle(
                    color: colors.accent,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  'Процессор',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 8),
                Text(
                  'Локальное управление сервисом',
                  style: TextStyle(color: colors.muted, fontSize: 12),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          for (final item in items)
            Padding(
              padding: const EdgeInsets.only(bottom: 7),
              child: _NavButton(
                active: selected == item.$1,
                icon: item.$2,
                label: item.$3,
                onTap: () => onSelect(item.$1),
              ),
            ),
          const Spacer(),
          _RuntimePill(
            label: connected ? 'Сервер связан' : 'Нет привязки',
            active: connected,
          ),
          const SizedBox(height: 8),
          _RuntimePill(
            label: running ? 'Сервис работает' : 'Сервис остановлен',
            active: running,
          ),
        ],
      ),
    );
  }
}

class _NavButton extends StatelessWidget {
  const _NavButton({
    required this.active,
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final bool active;
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    return PressScale(
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: AnimatedContainer(
          duration: ProcessorMotion.resolved(context, ProcessorMotion.fast),
          curve: ProcessorMotion.curve,
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
          decoration: BoxDecoration(
            color: active
                ? colors.accent.withValues(alpha: 0.16)
                : Colors.transparent,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: active ? colors.borderStrong : Colors.transparent,
            ),
          ),
          child: Row(
            children: [
              Icon(icon, color: active ? colors.accent : colors.text, size: 20),
              const SizedBox(width: 10),
              Text(
                label,
                style: TextStyle(
                  fontWeight: FontWeight.w800,
                  color: active ? colors.accent : colors.text,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _RuntimePill extends StatelessWidget {
  const _RuntimePill({required this.label, required this.active});

  final String label;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    final statusColor = active ? colors.success : colors.warning;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: statusColor.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: statusColor.withValues(alpha: 0.28)),
      ),
      child: Row(
        children: [
          Icon(Icons.circle, size: 9, color: statusColor),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              label,
              style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800),
            ),
          ),
        ],
      ),
    );
  }
}

class _TopStatusBar extends StatelessWidget {
  const _TopStatusBar({
    required this.message,
    required this.bridge,
    required this.running,
    required this.busy,
    required this.onRefresh,
    required this.themeMode,
    required this.onToggleTheme,
  });

  final String message;
  final RuntimeBridge bridge;
  final bool running;
  final bool busy;
  final VoidCallback onRefresh;
  final ProcessorThemeMode themeMode;
  final VoidCallback onToggleTheme;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    return _GlassPanel(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(14),
              gradient: LinearGradient(
                colors: [colors.accent, colors.secondary],
              ),
            ),
            child: Icon(Icons.memory_rounded, color: colors.activeForeground),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  message,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 2),
                Text(
                  bridge.runtimeDir.path,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(color: colors.muted, fontSize: 12),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          _ProcessorThemeToggle(
            themeMode: themeMode,
            onPressed: onToggleTheme,
          ),
          const SizedBox(width: 8),
          if (busy)
            const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          else
            IconButton.filledTonal(
              onPressed: onRefresh,
              icon: const Icon(Icons.refresh_rounded),
              tooltip: 'Обновить',
            ),
        ],
      ),
    );
  }
}

class _ProcessorThemeToggle extends StatelessWidget {
  const _ProcessorThemeToggle({
    required this.themeMode,
    required this.onPressed,
  });

  final ProcessorThemeMode themeMode;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    final dark = themeMode == ProcessorThemeMode.dark;
    const moonBackground = Color(0xFF102A4A);
    const moonBorder = Color(0xFF28496D);
    const moonColor = Color(0xFFD7E8FF);
    return Tooltip(
      message: dark ? 'Включить светлую тему' : 'Включить тёмную тему',
      child: PressScale(
        child: IconButton(
          onPressed: onPressed,
          style: IconButton.styleFrom(
            fixedSize: const Size(42, 42),
            backgroundColor: dark ? moonBackground : colors.surfaceMuted,
            foregroundColor: dark ? moonColor : colors.warning,
            side: BorderSide(color: dark ? moonBorder : colors.border),
          ),
          icon: AnimatedSwitcher(
            duration: ProcessorMotion.resolved(
              context,
              ProcessorMotion.standard,
            ),
            switchInCurve: ProcessorMotion.emphasized,
            switchOutCurve: Curves.easeInCubic,
            transitionBuilder: (child, animation) {
              final curved = CurvedAnimation(
                parent: animation,
                curve: ProcessorMotion.emphasized,
                reverseCurve: Curves.easeInCubic,
              );
              return FadeTransition(
                opacity: curved,
                child: RotationTransition(
                  turns: Tween<double>(
                    begin: dark ? -0.08 : 0.08,
                    end: 0,
                  ).animate(curved),
                  child: ScaleTransition(
                    scale: Tween<double>(begin: 0.84, end: 1).animate(curved),
                    child: child,
                  ),
                ),
              );
            },
            child: Icon(
              dark ? Icons.dark_mode_rounded : Icons.wb_sunny_rounded,
              key: ValueKey<bool>(dark),
            ),
          ),
        ),
      ),
    );
  }
}

class _TwoColumnLayout extends StatelessWidget {
  const _TwoColumnLayout({
    required this.primary,
    required this.secondary,
    this.primaryFlex = 1,
    this.secondaryFlex = 1,
  });

  final Widget primary;
  final Widget secondary;
  final int primaryFlex;
  final int secondaryFlex;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth < 900) {
          return Column(
            children: [
              primary,
              const SizedBox(height: 14),
              secondary,
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(flex: primaryFlex, child: primary),
            const SizedBox(width: 14),
            Expanded(flex: secondaryFlex, child: secondary),
          ],
        );
      },
    );
  }
}

class _HeroPanel extends StatelessWidget {
  const _HeroPanel({required this.eyebrow, required this.title, this.trailing});

  final String eyebrow;
  final String title;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    return _GlassPanel(
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 720;
          final titleBlock = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                eyebrow,
                style: TextStyle(
                  color: colors.accent,
                  fontWeight: FontWeight.w900,
                  fontSize: 12,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                title,
                maxLines: compact ? 3 : 2,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.displaySmall,
              ),
            ],
          );
          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                titleBlock,
                if (trailing != null) ...[
                  const SizedBox(height: 14),
                  Align(alignment: Alignment.centerLeft, child: trailing!),
                ],
              ],
            );
          }
          return Row(
            children: [
              Expanded(child: titleBlock),
              if (trailing != null) ...[const SizedBox(width: 18), trailing!],
            ],
          );
        },
      ),
    );
  }
}

class _GlassPanel extends StatelessWidget {
  const _GlassPanel({
    required this.child,
    this.padding = const EdgeInsets.all(20),
  });

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    final dark = Theme.of(context).brightness == Brightness.dark;
    const radius = 24.0;
    return ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 14, sigmaY: 14),
        child: Container(
          padding: padding,
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [
                colors.surface.withValues(alpha: dark ? 0.58 : 0.72),
                colors.panel.withValues(alpha: dark ? 0.42 : 0.82),
              ],
            ),
            borderRadius: BorderRadius.circular(radius),
            border: Border.all(color: colors.border),
            boxShadow: [
              BoxShadow(
                color: colors.shadow.withValues(alpha: dark ? 0.18 : 0.08),
                blurRadius: 34,
                offset: const Offset(0, 20),
              ),
              BoxShadow(
                color: colors.accent.withValues(alpha: dark ? 0.05 : 0.07),
                blurRadius: 44,
                offset: Offset.zero,
              ),
            ],
          ),
          foregroundDecoration: BoxDecoration(
            borderRadius: BorderRadius.circular(radius),
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [
                Colors.white.withValues(alpha: dark ? 0.1 : 0.32),
                Colors.white.withValues(alpha: 0),
                colors.accent.withValues(alpha: dark ? 0.035 : 0.05),
              ],
              stops: const [0, 0.45, 1],
            ),
          ),
          child: child,
        ),
      ),
    );
  }
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({
    required this.label,
    required this.value,
    required this.icon,
    this.accent,
  });

  final String label;
  final String value;
  final IconData icon;
  final Color? accent;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    final resolvedAccent = accent ?? colors.accent;
    return _GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: resolvedAccent.withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(15),
              border: Border.all(color: resolvedAccent.withValues(alpha: 0.28)),
            ),
            child: Icon(icon, color: resolvedAccent),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Tooltip(
                  message: value,
                  waitDuration: const Duration(milliseconds: 450),
                  child: Text(
                    value,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      fontSize: value.length > 36
                          ? 16
                          : value.length > 22
                              ? 18
                              : null,
                      height: 1.05,
                    ),
                  ),
                ),
                Text(
                  label,
                  style: TextStyle(color: colors.muted, fontSize: 12),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.child, this.subtitle});

  final String title;
  final Widget child;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    final sectionSubtitle = subtitle?.trim();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: Theme.of(context).textTheme.headlineSmall),
        if (sectionSubtitle != null && sectionSubtitle.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(
            sectionSubtitle,
            style: TextStyle(color: colors.muted, fontSize: 13),
          ),
        ],
        const SizedBox(height: 16),
        child,
      ],
    );
  }
}

class _CodeInputField extends StatefulWidget {
  const _CodeInputField({required this.controller, required this.label});

  final TextEditingController controller;
  final String label;

  @override
  State<_CodeInputField> createState() => _CodeInputFieldState();
}

class _CodeInputFieldState extends State<_CodeInputField> {
  final _focusNode = FocusNode();

  @override
  void initState() {
    super.initState();
    _focusNode.addListener(_refresh);
    widget.controller.addListener(_refresh);
  }

  @override
  void didUpdateWidget(covariant _CodeInputField oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.removeListener(_refresh);
      widget.controller.addListener(_refresh);
    }
  }

  @override
  void dispose() {
    _focusNode
      ..removeListener(_refresh)
      ..dispose();
    widget.controller.removeListener(_refresh);
    super.dispose();
  }

  void _refresh() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    const length = 8;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(left: 2, bottom: 8),
            child: Text(
              widget.label,
              style: TextStyle(
                color: colors.muted,
                fontSize: 13,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: () => _focusNode.requestFocus(),
            child: Stack(
              alignment: Alignment.center,
              children: [
                LayoutBuilder(
                  builder: (context, constraints) {
                    const gap = 8.0;
                    final cellWidth =
                        ((constraints.maxWidth - (length - 1) * gap) / length)
                            .clamp(38.0, 56.0);
                    final value = widget.controller.text;
                    return Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        for (var i = 0; i < length; i++) ...[
                          _CodeCell(
                            char: i < value.length ? value[i] : '',
                            active:
                                _focusNode.hasFocus &&
                                i == math.min(value.length, length),
                            filled: i < value.length,
                            width: cellWidth,
                          ),
                          if (i != length - 1) const SizedBox(width: gap),
                        ],
                      ],
                    );
                  },
                ),
                Positioned.fill(
                  child: Opacity(
                    opacity: 0.01,
                    child: TextField(
                      controller: widget.controller,
                      focusNode: _focusNode,
                      keyboardType: TextInputType.visiblePassword,
                      textCapitalization: TextCapitalization.characters,
                      autocorrect: false,
                      enableSuggestions: false,
                      showCursor: false,
                      maxLength: length,
                      inputFormatters: [
                        FilteringTextInputFormatter.allow(
                          RegExp(r'[A-Za-z0-9_-]'),
                        ),
                        _UpperCaseTextFormatter(),
                        LengthLimitingTextInputFormatter(length),
                      ],
                      decoration: const InputDecoration(
                        border: InputBorder.none,
                        contentPadding: EdgeInsets.zero,
                        counterText: '',
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CodeCell extends StatelessWidget {
  const _CodeCell({
    required this.char,
    required this.active,
    required this.filled,
    required this.width,
  });

  final String char;
  final bool active;
  final bool filled;
  final double width;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    return AnimatedContainer(
      duration: ProcessorMotion.resolved(context, ProcessorMotion.fast),
      curve: ProcessorMotion.curve,
      width: width,
      height: 58,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: colors.surface.withValues(alpha: filled ? 0.95 : 0.78),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: active
              ? colors.accent
              : (filled ? colors.borderStrong : colors.border),
          width: active ? 1.8 : 1.1,
        ),
        boxShadow: active
            ? [
                BoxShadow(
                  color: colors.accent.withValues(alpha: 0.18),
                  blurRadius: 18,
                  spreadRadius: 1,
                ),
              ]
            : null,
      ),
      child: Text(
        char,
        style: TextStyle(
          color: colors.textStrong,
          fontSize: 22,
          height: 1,
          fontWeight: FontWeight.w900,
        ),
      ),
    );
  }
}

class _UpperCaseTextFormatter extends TextInputFormatter {
  const _UpperCaseTextFormatter();

  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    return newValue.copyWith(text: newValue.text.toUpperCase());
  }
}

class _TextField extends StatelessWidget {
  const _TextField({
    required this.controller,
    required this.label,
    this.hint,
    this.obscure = false,
    this.numeric = false,
  });

  final TextEditingController controller;
  final String label;
  final String? hint;
  final bool obscure;
  final bool numeric;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextField(
        controller: controller,
        obscureText: obscure,
        keyboardType: numeric ? TextInputType.number : TextInputType.text,
        style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
        decoration: InputDecoration(labelText: label, hintText: hint),
      ),
    );
  }
}

class _DropdownField<T> extends StatelessWidget {
  const _DropdownField({
    required this.label,
    required this.value,
    required this.values,
    required this.onChanged,
    this.labelBuilder,
  });

  final String label;
  final T value;
  final List<T> values;
  final ValueChanged<T?> onChanged;
  final String Function(T value)? labelBuilder;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: DropdownButtonFormField<T>(
        initialValue: values.contains(value) ? value : values.first,
        decoration: InputDecoration(labelText: label),
        items: [
          for (final item in values)
            DropdownMenuItem(
              value: item,
              child: Text(labelBuilder?.call(item) ?? '$item'),
            ),
        ],
        onChanged: onChanged,
      ),
    );
  }
}

class _PresetChip extends StatelessWidget {
  const _PresetChip({required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    return ActionChip(
      label: Text(label),
      onPressed: onTap,
      backgroundColor: colors.accent.withValues(alpha: 0.12),
      side: BorderSide(color: colors.accent.withValues(alpha: 0.24)),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 145,
            child: Text(
              label,
              style: TextStyle(
                color: colors.muted,
                fontWeight: FontWeight.w800,
                fontSize: 12,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
          ),
        ],
      ),
    );
  }
}

class _ActionTile extends StatelessWidget {
  const _ActionTile({
    required this.label,
    required this.icon,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: OutlinedButton.icon(
        onPressed: onTap,
        icon: Icon(icon),
        label: Align(alignment: Alignment.centerLeft, child: Text(label)),
      ),
    );
  }
}

class _CameraAssignmentRow extends StatelessWidget {
  const _CameraAssignmentRow({required this.item});

  final Map<String, dynamic> item;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colors.panel.withValues(alpha: 0.52),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: colors.border),
      ),
      child: Row(
        children: [
          Icon(Icons.videocam_rounded, color: colors.accent),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${item['name'] ?? 'Камера'} #${item['camera_id'] ?? '-'}',
                  style: const TextStyle(fontWeight: FontWeight.w900),
                ),
                const SizedBox(height: 3),
                Text(
                  '${item['source'] ?? item['stream_url'] ?? item['ip_address'] ?? '-'}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(color: colors.muted, fontSize: 12),
                ),
              ],
            ),
          ),
          _MiniBadge('${item['recording_mode'] ?? 'record'}'),
        ],
      ),
    );
  }
}

class _MiniBadge extends StatelessWidget {
  const _MiniBadge(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: colors.secondary.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        text,
        style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w900),
      ),
    );
  }
}

class _JsonCard extends StatelessWidget {
  const _JsonCard({required this.title, required this.payload});

  final String title;
  final Map<String, dynamic> payload;

  @override
  Widget build(BuildContext context) {
    return _GlassPanel(
      child: _Section(
        title: title,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 420),
          child: SingleChildScrollView(
            child: SelectableText(
              const JsonEncoder.withIndent('  ').convert(payload),
              style: GoogleFonts.jetBrainsMono(fontSize: 12, height: 1.35),
            ),
          ),
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: colors.panel.withValues(alpha: 0.45),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: colors.border),
      ),
      child: Text(text, style: TextStyle(color: colors.muted)),
    );
  }
}

class _SmallNote extends StatelessWidget {
  const _SmallNote({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    return Align(
      alignment: Alignment.centerLeft,
      child: Text(
        text,
        style: TextStyle(color: colors.muted, fontSize: 12, height: 1.35),
      ),
    );
  }
}

class _ConnectionBadge extends StatelessWidget {
  const _ConnectionBadge({required this.connected});

  final bool connected;

  @override
  Widget build(BuildContext context) {
    return _MiniBadge(connected ? 'API-ключ сохранён' : 'Нужна привязка');
  }
}

class _ColorPreview extends StatelessWidget {
  const _ColorPreview({required this.color});

  final String color;

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    return Container(
      width: 44,
      height: 44,
      decoration: BoxDecoration(
        color: parseColor(color),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: colors.borderStrong),
      ),
    );
  }
}

class _StatusToast extends StatelessWidget {
  const _StatusToast({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return _GlassPanel(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const SizedBox(
            width: 18,
            height: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: 10),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Text(message, maxLines: 2, overflow: TextOverflow.ellipsis),
          ),
        ],
      ),
    );
  }
}

class _HelpGrid extends StatelessWidget {
  const _HelpGrid();

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    const items = [
      (
        'Подключение',
        'Укажите адрес сервера и код подключения. После успешной привязки API-ключ остаётся локально в processor_config.json.',
      ),
      (
        'Запуск',
        'Кнопка запуска поднимает тот же Python-процесс в фоновом режиме. Вся логика обнаружения остаётся в Python.',
      ),
      (
        'Настройки',
        'Частоты, папки, медиатокен, порт и ускорение пишутся в тот же конфиг. Для параметров среды выполнения нужен перезапуск.',
      ),
      (
        'Диагностика',
        'Раздел использует встроенный CLI-режим Runtime для команд status, system-info, acceleration и gallery.',
      ),
      (
        'Журнал',
        'Показывает stdout/stderr текущего процесса и хвост processor.log. Очистка окна не удаляет файл.',
      ),
      (
        'Портативная сборка',
        'Для портативной сборки рядом с GUI кладётся папка processor с CCTV-Processor-Runtime. Отдельный CLI не требуется.',
      ),
    ];
    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisSpacing: 14,
      mainAxisSpacing: 14,
      childAspectRatio: 2.8,
      children: [
        for (final item in items)
          _GlassPanel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(item.$1, style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 8),
                Text(
                  item.$2,
                  style: TextStyle(color: colors.muted, height: 1.35),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _GridBackdrop extends StatelessWidget {
  const _GridBackdrop();

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      painter: _GridPainter(color: context.processorColors.textStrong),
    );
  }
}

class _GridPainter extends CustomPainter {
  const _GridPainter({required this.color});

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color.withValues(alpha: 0.028)
      ..strokeWidth = 1;
    const step = 44.0;
    for (var x = 0.0; x < size.width; x += step) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
    }
    for (var y = 0.0; y < size.height; y += step) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _GridPainter oldDelegate) {
    return oldDelegate.color != color;
  }
}

class _ProcessorAuroraBackdrop extends StatelessWidget {
  const _ProcessorAuroraBackdrop();

  @override
  Widget build(BuildContext context) {
    final colors = context.processorColors;
    final dark = Theme.of(context).brightness == Brightness.dark;
    return CustomPaint(
      painter: _ProcessorAuroraPainter(
        primary: colors.accent,
        secondary: colors.secondary,
        dark: dark,
      ),
    );
  }
}

class _ProcessorAuroraPainter extends CustomPainter {
  const _ProcessorAuroraPainter({
    required this.primary,
    required this.secondary,
    required this.dark,
  });

  final Color primary;
  final Color secondary;
  final bool dark;

  @override
  void paint(Canvas canvas, Size size) {
    final alpha = dark ? 0.40 : 0.24;
    final upperPaint = Paint()
      ..shader = LinearGradient(
        colors: [
          primary.withValues(alpha: alpha),
          secondary.withValues(alpha: alpha * 0.76),
          secondary.withValues(alpha: 0),
        ],
      ).createShader(Offset.zero & size)
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 34);

    final upperPath = Path()
      ..moveTo(-size.width * 0.1, size.height * 0.16)
      ..cubicTo(
        size.width * 0.2,
        -size.height * 0.02,
        size.width * 0.54,
        size.height * 0.24,
        size.width * 1.1,
        size.height * 0.04,
      )
      ..lineTo(size.width * 1.1, size.height * 0.24)
      ..cubicTo(
        size.width * 0.68,
        size.height * 0.44,
        size.width * 0.24,
        size.height * 0.26,
        -size.width * 0.1,
        size.height * 0.48,
      )
      ..close();
    canvas.drawPath(upperPath, upperPaint);

    final lowerPaint = Paint()
      ..shader = LinearGradient(
        begin: Alignment.bottomLeft,
        end: Alignment.topRight,
        colors: [
          secondary.withValues(alpha: alpha * 0.80),
          primary.withValues(alpha: alpha * 0.60),
          primary.withValues(alpha: 0),
        ],
      ).createShader(Offset.zero & size)
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 42);

    final lowerPath = Path()
      ..moveTo(-size.width * 0.12, size.height * 0.88)
      ..cubicTo(
        size.width * 0.24,
        size.height * 0.72,
        size.width * 0.6,
        size.height * 1.02,
        size.width * 1.12,
        size.height * 0.76,
      )
      ..lineTo(size.width * 1.12, size.height * 1.08)
      ..lineTo(-size.width * 0.12, size.height * 1.08)
      ..close();
    canvas.drawPath(lowerPath, lowerPaint);
  }

  @override
  bool shouldRepaint(covariant _ProcessorAuroraPainter oldDelegate) {
    return oldDelegate.primary != primary ||
        oldDelegate.secondary != secondary ||
        oldDelegate.dark != dark;
  }
}

extension ProcessorColorsContext on BuildContext {
  ProcessorColors get processorColors {
    return Theme.of(this).extension<ProcessorColors>() ??
        ProcessorColors.dark();
  }
}

class ProcessorColors extends ThemeExtension<ProcessorColors> {
  const ProcessorColors({
    required this.bg,
    required this.backdropStart,
    required this.backdropEnd,
    required this.panel,
    required this.surface,
    required this.surfaceMuted,
    required this.text,
    required this.textStrong,
    required this.muted,
    required this.border,
    required this.borderStrong,
    required this.accent,
    required this.secondary,
    required this.success,
    required this.warning,
    required this.danger,
    required this.activeForeground,
    required this.shadow,
  });

  final Color bg;
  final Color backdropStart;
  final Color backdropEnd;
  final Color panel;
  final Color surface;
  final Color surfaceMuted;
  final Color text;
  final Color textStrong;
  final Color muted;
  final Color border;
  final Color borderStrong;
  final Color accent;
  final Color secondary;
  final Color success;
  final Color warning;
  final Color danger;
  final Color activeForeground;
  final Color shadow;

  static ProcessorColors dark() => const ProcessorColors(
    bg: Color(0xFF050812),
    backdropStart: Color(0xFF08111F),
    backdropEnd: Color(0xFF0C0716),
    panel: Color(0xFF0A1020),
    surface: Color(0xFF121B2B),
    surfaceMuted: Color(0xFF182437),
    text: Color(0xFFE7EEF9),
    textStrong: Colors.white,
    muted: Color(0xFFA7B6CA),
    border: Color(0x26FFFFFF),
    borderStrong: Color(0x525EF0FF),
    accent: Color(0xFF5EF0FF),
    secondary: Color(0xFF4C6FFF),
    success: Color(0xFF22C55E),
    warning: Color(0xFFF59E0B),
    danger: Color(0xFFEF4444),
    activeForeground: Color(0xFF06111D),
    shadow: Colors.black,
  );

  static ProcessorColors light() => const ProcessorColors(
    bg: Color(0xFFF6FAFF),
    backdropStart: Color(0xFFEAF5FF),
    backdropEnd: Color(0xFFF8FBFF),
    panel: Color(0xFFFFFFFF),
    surface: Color(0xFFEAF2FB),
    surfaceMuted: Color(0xFFE3EDF8),
    text: Color(0xFF334155),
    textStrong: Color(0xFF0F172A),
    muted: Color(0xFF64748B),
    border: Color(0xFFD6E2F0),
    borderStrong: Color(0x995EBFEA),
    accent: Color(0xFF147EA3),
    secondary: Color(0xFF4C6FFF),
    success: Color(0xFF15803D),
    warning: Color(0xFFD97706),
    danger: Color(0xFFDC2626),
    activeForeground: Colors.white,
    shadow: Color(0xFF1E293B),
  );

  @override
  ProcessorColors copyWith({
    Color? bg,
    Color? backdropStart,
    Color? backdropEnd,
    Color? panel,
    Color? surface,
    Color? surfaceMuted,
    Color? text,
    Color? textStrong,
    Color? muted,
    Color? border,
    Color? borderStrong,
    Color? accent,
    Color? secondary,
    Color? success,
    Color? warning,
    Color? danger,
    Color? activeForeground,
    Color? shadow,
  }) {
    return ProcessorColors(
      bg: bg ?? this.bg,
      backdropStart: backdropStart ?? this.backdropStart,
      backdropEnd: backdropEnd ?? this.backdropEnd,
      panel: panel ?? this.panel,
      surface: surface ?? this.surface,
      surfaceMuted: surfaceMuted ?? this.surfaceMuted,
      text: text ?? this.text,
      textStrong: textStrong ?? this.textStrong,
      muted: muted ?? this.muted,
      border: border ?? this.border,
      borderStrong: borderStrong ?? this.borderStrong,
      accent: accent ?? this.accent,
      secondary: secondary ?? this.secondary,
      success: success ?? this.success,
      warning: warning ?? this.warning,
      danger: danger ?? this.danger,
      activeForeground: activeForeground ?? this.activeForeground,
      shadow: shadow ?? this.shadow,
    );
  }

  @override
  ProcessorColors lerp(ThemeExtension<ProcessorColors>? other, double t) {
    if (other is! ProcessorColors) return this;
    return ProcessorColors(
      bg: Color.lerp(bg, other.bg, t)!,
      backdropStart: Color.lerp(backdropStart, other.backdropStart, t)!,
      backdropEnd: Color.lerp(backdropEnd, other.backdropEnd, t)!,
      panel: Color.lerp(panel, other.panel, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      surfaceMuted: Color.lerp(surfaceMuted, other.surfaceMuted, t)!,
      text: Color.lerp(text, other.text, t)!,
      textStrong: Color.lerp(textStrong, other.textStrong, t)!,
      muted: Color.lerp(muted, other.muted, t)!,
      border: Color.lerp(border, other.border, t)!,
      borderStrong: Color.lerp(borderStrong, other.borderStrong, t)!,
      accent: Color.lerp(accent, other.accent, t)!,
      secondary: Color.lerp(secondary, other.secondary, t)!,
      success: Color.lerp(success, other.success, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
      danger: Color.lerp(danger, other.danger, t)!,
      activeForeground: Color.lerp(
        activeForeground,
        other.activeForeground,
        t,
      )!,
      shadow: Color.lerp(shadow, other.shadow, t)!,
    );
  }
}

class ProcessorTheme {
  static ThemeData light() => _build(ProcessorColors.light(), Brightness.light);

  static ThemeData dark() => _build(ProcessorColors.dark(), Brightness.dark);

  static ThemeData _build(ProcessorColors colors, Brightness brightness) {
    final base = ThemeData(
      useMaterial3: true,
      brightness: brightness,
      scaffoldBackgroundColor: colors.bg,
      colorScheme: ColorScheme.fromSeed(
        seedColor: colors.accent,
        brightness: brightness,
        primary: colors.accent,
        secondary: colors.secondary,
        surface: colors.surface,
      ),
      extensions: [colors],
    );
    final textTheme = GoogleFonts.spaceGroteskTextTheme(
      base.textTheme,
    ).apply(bodyColor: colors.text, displayColor: colors.textStrong);
    return base.copyWith(
      textTheme: textTheme.copyWith(
        displaySmall: GoogleFonts.spaceGrotesk(
          fontSize: 30,
          fontWeight: FontWeight.w900,
          color: colors.textStrong,
          height: 1.05,
        ),
        headlineSmall: GoogleFonts.spaceGrotesk(
          fontSize: 19,
          fontWeight: FontWeight.w900,
          color: colors.textStrong,
        ),
        titleLarge: GoogleFonts.spaceGrotesk(
          fontSize: 18,
          fontWeight: FontWeight.w900,
          color: colors.textStrong,
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: colors.panel.withValues(
          alpha: brightness == Brightness.dark ? 0.62 : 0.86,
        ),
        labelStyle: TextStyle(color: colors.muted, fontSize: 13),
        hintStyle: TextStyle(color: colors.muted, fontSize: 13),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide(color: colors.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide(color: colors.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide(color: colors.accent),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          elevation: 0,
          backgroundColor: colors.accent,
          foregroundColor: colors.activeForeground,
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 15),
          textStyle: const TextStyle(fontWeight: FontWeight.w900),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: colors.textStrong,
          side: BorderSide(color: colors.border),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
        ),
      ),
    );
  }
}

Map<String, dynamic> defaultProcessorConfig({String? runtimeDir}) {
  final base = runtimeDir ?? Directory.current.path;
  return normalizeProcessorConfig({
    'backend_url': '',
    'api_key': '',
    'processor_id': null,
    'processor_name': Platform.localHostname,
    'processor_node_uid': randomHex(32),
    'advertised_ip': '',
    'poll_interval': 1,
    'heartbeat_interval': 10,
    'max_workers': 4,
    'processor_accel': 'auto',
    'motion_threshold': 25.0,
    'face_scan_divisor': 4,
    'overlay_frame_divisor': 1,
    'face_scan_interval': 0.35,
    'theme_mode': ProcessorThemeMode.dark.name,
    'theme_primary_color': '#49C8E8',
    'theme_secondary_color': '#4C6FFF',
    'recording_segment_seconds': 60,
    'recordings_dir': joinPath(base, 'media', 'recordings'),
    'snapshots_dir': joinPath(base, 'media', 'snapshots'),
    'media_port': 8777,
    'media_token': randomHex(48),
  }, base);
}

Map<String, dynamic> normalizeProcessorConfig(
  Map<String, dynamic> raw,
  String? runtimeDir,
) {
  final base = runtimeDir ?? Directory.current.path;
  final config = Map<String, dynamic>.from(raw);
  config['theme_mode'] = processorThemeModeFrom(config).name;
  config['processor_name'] = '${config['processor_name'] ?? ''}'.trim().isEmpty
      ? Platform.localHostname
      : '${config['processor_name']}';
  config['processor_node_uid'] =
      '${config['processor_node_uid'] ?? ''}'.trim().isEmpty
      ? randomHex(32)
      : '${config['processor_node_uid']}';
  config['processor_accel'] =
      const [
        'auto',
        'cpu',
        'nvidia',
        'intel',
        'amd',
        'directml',
      ].contains(config['processor_accel'])
      ? config['processor_accel']
      : 'auto';
  config['poll_interval'] = _intFrom(
    '${config['poll_interval'] ?? 1}',
    1,
    min: 1,
    max: 60,
  );
  config['heartbeat_interval'] = _intFrom(
    '${config['heartbeat_interval'] ?? 10}',
    10,
    min: 5,
    max: 300,
  );
  config['max_workers'] = _intFrom(
    '${config['max_workers'] ?? 4}',
    4,
    min: 1,
    max: 64,
  );
  config['motion_threshold'] = _doubleFrom(
    '${config['motion_threshold'] ?? 25.0}',
    25.0,
    min: 0.0,
    max: 255.0,
  );
  config['recording_segment_seconds'] = _intFrom(
    '${config['recording_segment_seconds'] ?? 60}',
    60,
    min: 10,
    max: 60,
  );
  config['media_port'] = _intFrom(
    '${config['media_port'] ?? 8777}',
    8777,
    min: 1,
    max: 65535,
  );
  config['face_scan_divisor'] = _sanitizeFaceScanDivisor(
    config['face_scan_divisor'],
    8,
  );
  config['overlay_frame_divisor'] = _sanitizeDivisor(
    config['overlay_frame_divisor'],
    1,
  );
  config['face_scan_interval'] = math.min(
    5.0,
    (config['face_scan_divisor'] as int) / 24.0,
  );
  config['recordings_dir'] = '${config['recordings_dir'] ?? ''}'.trim().isEmpty
      ? joinPath(base, 'media', 'recordings')
      : '${config['recordings_dir']}';
  config['snapshots_dir'] = '${config['snapshots_dir'] ?? ''}'.trim().isEmpty
      ? joinPath(base, 'media', 'snapshots')
      : '${config['snapshots_dir']}';
  config['media_token'] = '${config['media_token'] ?? ''}'.trim().isEmpty
      ? randomHex(48)
      : '${config['media_token']}';
  config['theme_primary_color'] = _safeHex(
    '${config['theme_primary_color'] ?? ''}',
    '#49C8E8',
  );
  config['theme_secondary_color'] = _safeHex(
    '${config['theme_secondary_color'] ?? ''}',
    '#4C6FFF',
  );
  return config;
}

int _sanitizeDivisor(Object? value, int fallback) {
  final raw = int.tryParse('$value') ?? fallback;
  const choices = [1, 2, 4, 8, 16, 32, 64, 120];
  for (final item in choices) {
    if (raw <= item) return item;
  }
  return choices.last;
}

int _sanitizeFaceScanDivisor(Object? value, int fallback) {
  return math.max(2, _sanitizeDivisor(value, fallback));
}

String _divisorLabel(int value) {
  if (value == 120) return '1 кадр / 5 сек';
  return '/$value';
}

int _intFrom(String text, int fallback, {int? min, int? max}) {
  var value = int.tryParse(text.trim()) ?? fallback;
  if (min != null && value < min) value = min;
  if (max != null && value > max) value = max;
  return value;
}

int? _nullableInt(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse('${value ?? ''}'.trim());
}

double _doubleFrom(String text, double fallback, {double? min, double? max}) {
  var value = double.tryParse(text.trim().replaceAll(',', '.')) ?? fallback;
  if (min != null && value < min) value = min;
  if (max != null && value > max) value = max;
  return value;
}

double? _num(Object? value) {
  if (value == null) return null;
  if (value is num) return value.toDouble();
  return double.tryParse('$value'.trim().replaceAll(',', '.'));
}

String _safeHex(String value, String fallback) {
  final compact = value.trim().replaceAll('#', '');
  if (RegExp(r'^[0-9a-fA-F]{6}$').hasMatch(compact)) {
    return '#${compact.toUpperCase()}';
  }
  return fallback;
}

Color parseColor(String value) {
  final hex = _safeHex(value, '#49C8E8').substring(1);
  return Color(int.parse('FF$hex', radix: 16));
}

String randomHex(int length) {
  final random = math.Random.secure();
  const chars = '0123456789abcdef';
  return List.generate(
    length,
    (_) => chars[random.nextInt(chars.length)],
  ).join();
}

String joinPath(String first, [String? second, String? third, String? fourth]) {
  final parts = [
    first,
    second,
    third,
    fourth,
  ].whereType<String>().where((part) => part.isNotEmpty).toList();
  final separator = Platform.pathSeparator;
  var result = parts.first;
  for (final part in parts.skip(1)) {
    final clean = part.replaceAll(RegExp(r'^[\\/]+'), '');
    result = result.endsWith(separator)
        ? '$result$clean'
        : '$result$separator$clean';
  }
  return result;
}

Directory? findRepoRoot(List<Directory> starts) {
  for (final start in starts) {
    var current = start.absolute;
    for (var depth = 0; depth < 10; depth++) {
      if (File(
            joinPath(current.path, 'processor', 'run_runtime.py'),
          ).existsSync() &&
          File(joinPath(current.path, 'processor', 'main.py')).existsSync()) {
        return current;
      }
      final parent = current.parent;
      if (parent.path == current.path) break;
      current = parent;
    }
  }
  return null;
}

Object? decodeLooseJson(String text) {
  final trimmed = sanitizeProcessOutput(text).trim();
  if (trimmed.isEmpty) return null;
  try {
    return jsonDecode(trimmed);
  } catch (_) {
    final firstObject = trimmed.indexOf('{');
    final firstArray = trimmed.indexOf('[');
    final starts = [
      firstObject,
      firstArray,
    ].where((index) => index >= 0).toList()..sort();
    if (starts.isEmpty) rethrow;
    final start = starts.first;
    final endObject = trimmed.lastIndexOf('}');
    final endArray = trimmed.lastIndexOf(']');
    final end = math.max(endObject, endArray);
    if (end <= start) rethrow;
    return jsonDecode(trimmed.substring(start, end + 1));
  }
}

Map<String, dynamic> _asMap(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return value.map((key, val) => MapEntry('$key', val));
  return <String, dynamic>{};
}

String _stringifyStorage(Object? storage, Object? error) {
  if (error != null) return '$error';
  final map = _asMap(storage);
  if (map.isEmpty) return 'Пока нет данных';
  return const JsonEncoder.withIndent('  ').convert(map);
}

String _formatDuration(Duration duration) {
  final hours = duration.inHours;
  final minutes = duration.inMinutes.remainder(60).toString().padLeft(2, '0');
  final seconds = duration.inSeconds.remainder(60).toString().padLeft(2, '0');
  return '$hours:$minutes:$seconds';
}
