// ignore_for_file: prefer_initializing_formals

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProcessorGuiApp());
}

class ProcessorGuiApp extends StatelessWidget {
  const ProcessorGuiApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'CCTV Processor',
      theme: ProcessorTheme.dark(),
      home: const ProcessorHome(),
    );
  }
}

class ProcessorHome extends StatefulWidget {
  const ProcessorHome({super.key});

  @override
  State<ProcessorHome> createState() => _ProcessorHomeState();
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
  bool _running = false;
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
      _statusMessage = 'Runtime найден: ${bridge.launcherDescription}';
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
    next.putIfAbsent('processor_node_uid', () => randomHex(32));
    return normalizeProcessorConfig(next, _bridge?.runtimeDir.path);
  }

  Future<void> _refreshAll() async {
    final bridge = _bridge;
    if (bridge == null || _busy) return;
    try {
      final results = await Future.wait<Object?>([
        bridge.localMetrics(),
        bridge.runCliJson([
          'status',
          '--json',
        ], timeout: const Duration(seconds: 18)),
        bridge.runCliJson([
          'system-info',
          '--json',
        ], timeout: const Duration(seconds: 18)),
        bridge.runCliJson([
          'acceleration',
          '--json',
          '--processor-accel',
          _accelPreference,
        ], timeout: const Duration(seconds: 30)),
      ]);
      final status = _asMap(results[1]);
      final assignments = status['assignments'];
      if (!mounted) return;
      setState(() {
        _metrics = results[0] as LocalMetrics;
        _status = status;
        _systemInfo = _asMap(results[2]);
        _acceleration = _asMap(results[3]);
        _assignments = assignments is List ? assignments : const [];
        _storageText = _stringifyStorage(
          status['storage'],
          status['storage_error'],
        );
        _statusMessage = _running
            ? 'Processor запущен локально. PID: ${_process?.pid ?? '-'}'
            : _statusMessage;
      });
      await _readGallery();
      await _readLogTail();
    } catch (error) {
      if (!mounted) return;
      setState(() => _statusMessage = 'Ошибка обновления статуса: $error');
    }
  }

  Future<void> _readGallery() async {
    final bridge = _bridge;
    if (bridge == null || _status['connected'] != true) return;
    try {
      final payload = await bridge.runCliJson([
        'gallery',
        '--json',
        '--limit',
        '100',
      ], timeout: const Duration(seconds: 18));
      if (!mounted) return;
      setState(() => _gallery = payload is List ? payload : const []);
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
    final text = await file.readAsString(encoding: utf8);
    return text.length > 32000 ? text.substring(text.length - 32000) : text;
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
            ? 'Настройки сохранены. Для runtime-параметров перезапустите Processor.'
            : 'Настройки сохранены.';
      });
      _syncControllersFromConfig();
      await _refreshAll();
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
      await _refreshAll();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _testBackend() async {
    final url = _backendController.text.trim().replaceAll(RegExp(r'/+$'), '');
    if (url.isEmpty) {
      setState(() => _statusMessage = 'Введите URL backend.');
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
      setState(() => _statusMessage = 'Нужны URL backend и код подключения.');
      return;
    }
    final connectConfig = _configFromControllers();
    setState(() {
      _busy = true;
      _statusMessage = 'Подключение Processor к backend...';
    });
    try {
      final args = [
        'connect',
        '--backend-url',
        _backendController.text.trim().replaceAll(RegExp(r'/+$'), ''),
        '--code',
        code,
        '--name',
        _nameController.text.trim().isEmpty
            ? Platform.localHostname
            : _nameController.text.trim(),
        '--processor-accel',
        _accelPreference,
        '--max-workers',
        '${connectConfig['max_workers']}',
        '--motion-threshold',
        '${connectConfig['motion_threshold']}',
        '--face-scan-interval',
        '${connectConfig['face_scan_interval']}',
        '--recording-segment-seconds',
        '${connectConfig['recording_segment_seconds']}',
        '--recordings-dir',
        '${connectConfig['recordings_dir']}',
        '--snapshots-dir',
        '${connectConfig['snapshots_dir']}',
        '--media-port',
        '${connectConfig['media_port']}',
        '--media-token',
        '${connectConfig['media_token']}',
        '--json',
      ];
      final payload = await bridge.runCliJson(
        args,
        timeout: const Duration(seconds: 35),
      );
      final config = await bridge.readConfig();
      if (!mounted) return;
      setState(() {
        _config = config;
        _codeController.clear();
        _statusMessage =
            'Подключено. Processor ID: ${_asMap(payload)['processor_id'] ?? config['processor_id']}.';
        _selectedTab = 'dashboard';
      });
      _syncControllersFromConfig();
      await _refreshAll();
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
      await bridge.runCli(['disconnect'], timeout: const Duration(seconds: 15));
      final config = await bridge.readConfig();
      if (!mounted) return;
      setState(() {
        _config = config;
        _statusMessage = 'Локальная привязка удалена.';
      });
      _syncControllersFromConfig();
      await _refreshAll();
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
            'Сначала подключите Processor к backend и получите API-ключ.';
      });
      return;
    }
    setState(() {
      _busy = true;
      _statusMessage = 'Запуск headless Processor...';
    });
    try {
      final process = await bridge.startHeadless(
        onOutput: (line) => _appendSessionLog(line),
      );
      if (!mounted) return;
      setState(() {
        _process = process;
        _running = true;
        _startedAt = DateTime.now();
        _statusMessage = 'Processor запущен. PID: ${process.pid}';
      });
      unawaited(
        process.exitCode.then((code) {
          if (!mounted) return;
          setState(() {
            _running = false;
            _process = null;
            _statusMessage = 'Processor завершился с кодом $code.';
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
    final process = _process;
    if (process == null) {
      setState(() => _running = false);
      return;
    }
    setState(() => _statusMessage = 'Остановка Processor...');
    try {
      process.kill();
      await process.exitCode.timeout(const Duration(seconds: 6));
    } catch (_) {
      if (Platform.isWindows) {
        await Process.run('taskkill', ['/PID', '${process.pid}', '/T', '/F']);
      }
    }
    if (!mounted) return;
    setState(() {
      _running = false;
      _process = null;
      _statusMessage = 'Processor остановлен.';
    });
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
    return Scaffold(
      body: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: RadialGradient(
            center: Alignment(-0.8, -0.9),
            radius: 1.2,
            colors: [Color(0xFF12323B), Color(0xFF07111F), Color(0xFF04080E)],
          ),
        ),
        child: Stack(
          children: [
            const Positioned.fill(child: _GridBackdrop()),
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
                      duration: const Duration(milliseconds: 180),
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
    final uptime = _startedAt == null
        ? '-'
        : _formatDuration(DateTime.now().difference(_startedAt!));
    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _HeroPanel(
            eyebrow: 'PROCESSOR CONTROL',
            title:
                '${_config['processor_name'] ?? Platform.localHostname} · ID ${_config['processor_id'] ?? 'не назначен'}',
            subtitle:
                'Единая нативная панель для запуска Python Processor, мониторинга и локальной диагностики.',
            trailing: Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                ElevatedButton.icon(
                  onPressed: _busy || _running ? null : _startProcessor,
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
              final compact = constraints.maxWidth < 980;
              final cards = [
                _MetricCard(
                  label: 'Сервис',
                  value: _running ? 'Работает' : 'Остановлен',
                  icon: Icons.power_settings_new_rounded,
                  accent: _running ? AppPalette.success : AppPalette.warning,
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
                  label: 'Uptime',
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
                crossAxisCount: constraints.maxWidth > 1280 ? 4 : 3,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                crossAxisSpacing: 12,
                mainAxisSpacing: 12,
                childAspectRatio: 2.9,
                children: cards,
              );
            },
          ),
          const SizedBox(height: 14),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                flex: 3,
                child: _GlassPanel(
                  child: _Section(
                    title: 'Назначенные камеры',
                    subtitle: _status['assignments_error'] == null
                        ? 'Берётся из backend через существующий Processor CLI.'
                        : '${_status['assignments_error']}',
                    child: _assignments.isEmpty
                        ? const _EmptyState(
                            text: 'Камеры пока не назначены этому Processor.',
                          )
                        : Column(
                            children: [
                              for (final item in _assignments.take(8))
                                _CameraAssignmentRow(item: _asMap(item)),
                            ],
                          ),
                  ),
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                flex: 2,
                child: _GlassPanel(
                  child: _Section(
                    title: 'Быстрые действия',
                    subtitle: 'Открытие локальных файлов runtime.',
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
        ],
      ),
    );
  }

  Widget _connectPage(RuntimeBridge bridge) {
    return SingleChildScrollView(
      child: Column(
        children: [
          _HeroPanel(
            eyebrow: 'PROCESSOR LINK',
            title: 'Подключение к backend',
            subtitle:
                'Используется тот же код подключения и тот же API-ключ, что в старом GUI. Секреты сохраняются локально в processor_config.json.',
            trailing: _ConnectionBadge(connected: _status['connected'] == true),
          ),
          const SizedBox(height: 14),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                flex: 3,
                child: _GlassPanel(
                  child: _Section(
                    title: 'Данные подключения',
                    subtitle: 'Код создаётся в Console на сервере.',
                    child: Column(
                      children: [
                        _TextField(
                          controller: _backendController,
                          label: 'Backend URL',
                          hint: 'http://127.0.0.1:8001',
                        ),
                        _TextField(
                          controller: _codeController,
                          label: 'Код подключения',
                          hint: 'ABCD1234',
                          obscure: true,
                        ),
                        _TextField(
                          controller: _nameController,
                          label: 'Имя Processor',
                          hint: Platform.localHostname,
                        ),
                        const SizedBox(height: 10),
                        Row(
                          children: [
                            OutlinedButton.icon(
                              onPressed: _busy ? null : _testBackend,
                              icon: const Icon(Icons.health_and_safety_rounded),
                              label: const Text('Проверить'),
                            ),
                            const SizedBox(width: 10),
                            ElevatedButton.icon(
                              onPressed: _busy ? null : _connectProcessor,
                              icon: const Icon(Icons.link_rounded),
                              label: const Text('Подключить'),
                            ),
                            const SizedBox(width: 10),
                            OutlinedButton.icon(
                              onPressed: _busy || _running
                                  ? null
                                  : _disconnectProcessor,
                              icon: const Icon(Icons.link_off_rounded),
                              label: const Text('Сбросить ключ'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                flex: 2,
                child: _GlassPanel(
                  child: _Section(
                    title: 'Локальная сводка',
                    subtitle: 'Данные из config/status CLI.',
                    child: Column(
                      children: [
                        _InfoRow('Runtime', bridge.runtimeDir.path),
                        _InfoRow('Launcher', bridge.launcherDescription),
                        _InfoRow('Backend', '${_config['backend_url'] ?? '-'}'),
                        _InfoRow(
                          'Processor ID',
                          '${_config['processor_id'] ?? '-'}',
                        ),
                        _InfoRow(
                          'API key',
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
        ],
      ),
    );
  }

  Widget _settingsPage(RuntimeBridge bridge) {
    return SingleChildScrollView(
      child: Column(
        children: [
          _HeroPanel(
            eyebrow: 'PROCESSOR SETUP',
            title: 'Настройки runtime',
            subtitle:
                'Поля пишутся в тот же processor_config.json. Изменения частот, ускорения и папок применяются после перезапуска Processor.',
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                OutlinedButton.icon(
                  onPressed: _busy || _running ? null : _resetConfig,
                  icon: const Icon(Icons.restart_alt_rounded),
                  label: const Text('Сбросить'),
                ),
                const SizedBox(width: 10),
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
              final compact = constraints.maxWidth < 980;
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
        subtitle: 'Аналог старых пресетов и частот сканирования.',
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
                    value: _sanitizeDivisor(_config['face_scan_divisor'], 8),
                    values: const [1, 2, 4, 8, 16, 32, 64, 120],
                    labelBuilder: _divisorLabel,
                    onChanged: (value) => setState(
                      () => _config['face_scan_divisor'] = value ?? 8,
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _DropdownField<int>(
                    label: 'Оверлей live',
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
                _PresetChip(label: 'Максимум', onTap: () => _applyPreset(1, 1)),
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
        subtitle: 'Пути остаются локальными для текущего Processor.',
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
        title: 'Media runtime',
        subtitle: 'Параметры внутреннего media server Processor.',
        child: Column(
          children: [
            _TextField(
              controller: _mediaPortController,
              label: 'Media port',
              numeric: true,
            ),
            _TextField(
              controller: _mediaTokenController,
              label: 'Media token',
              obscure: true,
            ),
            _SmallNote(
              text:
                  'Token используется backend для live/архивного proxy. Если изменить его во время работы, перезапустите Processor.',
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
        subtitle: 'Сохраняется в конфиг для совместимости со старым GUI.',
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
                  child: const Text('Processor'),
                ),
                const SizedBox(width: 8),
                OutlinedButton(
                  onPressed: () {
                    _primaryColorController.text = '#5EF0FF';
                    _secondaryColorController.text = '#6F7BFF';
                    setState(() {});
                  },
                  child: const Text('Console'),
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
      child: Column(
        children: [
          _HeroPanel(
            eyebrow: 'RUNTIME DIAGNOSTICS',
            title: 'Диагностика Processor',
            subtitle:
                'Проверка CLI, ускорения, локальной системы, галереи персон и назначений камер.',
            trailing: ElevatedButton.icon(
              onPressed: _busy ? null : _runPrewarm,
              icon: const Icon(Icons.model_training_rounded),
              label: const Text('Прогреть модели'),
            ),
          ),
          const SizedBox(height: 14),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: _JsonCard(title: 'Acceleration', payload: _acceleration),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: _JsonCard(title: 'System info', payload: _systemInfo),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: _GlassPanel(
                  child: _Section(
                    title: 'Галерея персон',
                    subtitle: 'Данные берутся из backend через CLI gallery.',
                    child: _gallery.isEmpty
                        ? const _EmptyState(
                            text: 'Галерея пуста или Processor не подключён.',
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
              ),
              const SizedBox(width: 14),
              Expanded(
                child: _JsonCard(title: 'CLI status', payload: _status),
              ),
            ],
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
          subtitle:
              'Сюда попадает live-вывод запущенного headless-процесса и хвост processor.log.',
          trailing: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              OutlinedButton.icon(
                onPressed: () => _openRuntimePath(bridge.logPath),
                icon: const Icon(Icons.open_in_new_rounded),
                label: const Text('processor.log'),
              ),
              const SizedBox(width: 10),
              OutlinedButton.icon(
                onPressed: () => _openRuntimePath(bridge.processOutputLogPath),
                icon: const Icon(Icons.terminal_rounded),
                label: const Text('stdout/stderr'),
              ),
              const SizedBox(width: 10),
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
            child: SelectableText(
              text,
              style: GoogleFonts.jetBrainsMono(
                fontSize: 12,
                height: 1.35,
                color: AppPalette.text,
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _helpPage() {
    return SingleChildScrollView(
      child: Column(
        children: const [
          _HeroPanel(
            eyebrow: 'PROCESSOR GUIDE',
            title: 'Справка по нативному GUI',
            subtitle:
                'Новая нативка заменяет только оболочку. Python runtime, детект, запись, media server и обмен с backend остаются прежними.',
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
    required Directory workingDirectory,
  }) : _executable = executable,
       _baseArgs = baseArgs,
       _workingDirectory = workingDirectory;

  final Directory runtimeDir;
  final String launcherDescription;
  final String _executable;
  final List<String> _baseArgs;
  final Directory _workingDirectory;

  String get configPath => joinPath(runtimeDir.path, 'processor_config.json');
  String get logPath => joinPath(runtimeDir.path, 'processor.log');
  String get processOutputLogPath =>
      joinPath(runtimeDir.path, 'processor_gui_output.log');

  static Future<RuntimeBridge> detect() async {
    final appDir = File(Platform.resolvedExecutable).parent;
    final processorBinary = Platform.isWindows
        ? 'CCTV-Processor.exe'
        : 'CCTV-Processor';
    final pythonExecutable = Platform.isWindows ? 'python' : 'python3';
    final bundledDir = Directory(joinPath(appDir.path, 'processor'));
    final bundledExe = File(joinPath(bundledDir.path, processorBinary));
    if (await bundledExe.exists()) {
      return RuntimeBridge(
        runtimeDir: bundledDir,
        launcherDescription: 'bundled PyInstaller runtime',
        executable: bundledExe.path,
        baseArgs: const [],
        workingDirectory: bundledDir,
      );
    }

    final localExe = File(joinPath(appDir.path, processorBinary));
    if (await localExe.exists()) {
      return RuntimeBridge(
        runtimeDir: appDir,
        launcherDescription: 'local PyInstaller runtime',
        executable: localExe.path,
        baseArgs: const [],
        workingDirectory: appDir,
      );
    }

    final repo = findRepoRoot([Directory.current, appDir]);
    if (repo != null) {
      final distDir = Directory(
        joinPath(repo.path, 'processor', 'dist', 'CCTV-Processor'),
      );
      final distExe = File(joinPath(distDir.path, processorBinary));
      if (await distExe.exists()) {
        return RuntimeBridge(
          runtimeDir: distDir,
          launcherDescription: 'repository PyInstaller runtime',
          executable: distExe.path,
          baseArgs: const [],
          workingDirectory: distDir,
        );
      }
      final runGui = File(joinPath(repo.path, 'processor', 'run_gui.py'));
      return RuntimeBridge(
        runtimeDir: Directory(joinPath(repo.path, 'processor')),
        launcherDescription: 'source Python runtime',
        executable: pythonExecutable,
        baseArgs: [runGui.path],
        workingDirectory: repo,
      );
    }

    throw StateError(
      'Не найден Processor runtime. Положите папку processor рядом с GUI или запускайте из репозитория.',
    );
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
  }

  Future<CommandResult> runCli(
    List<String> args, {
    Duration timeout = const Duration(seconds: 30),
  }) async {
    final commandArgs = [..._baseArgs, '--cli', ...args];
    final result = await Process.run(
      _executable,
      commandArgs,
      workingDirectory: _workingDirectory.path,
      environment: _processEnvironment(),
      stdoutEncoding: utf8,
      stderrEncoding: utf8,
    ).timeout(timeout);
    final commandResult = CommandResult(
      exitCode: result.exitCode,
      stdout: '${result.stdout}',
      stderr: '${result.stderr}',
    );
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
      stream.transform(const Utf8Decoder(allowMalformed: true)).listen((chunk) {
        final entry = '${DateTime.now().toIso8601String()} [$source] $chunk';
        sink.write(entry);
        onOutput(entry);
      });
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
\$dialog.Description = "Выберите папку Processor"
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
    return '${name.length > 22 ? '${name.substring(0, 22)}...' : name}$util$temp';
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
        color: AppPalette.panel.withValues(alpha: 0.78),
        borderRadius: BorderRadius.circular(28),
        border: Border.all(color: AppPalette.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(22),
              gradient: const LinearGradient(
                colors: [Color(0xFF14313D), Color(0xFF0A1425)],
              ),
              border: Border.all(color: AppPalette.border),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'CCTV',
                  style: TextStyle(
                    color: AppPalette.accent,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  'Processor',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 8),
                Text(
                  'Нативная оболочка для Python runtime',
                  style: TextStyle(color: AppPalette.muted, fontSize: 12),
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
            label: connected ? 'Backend связан' : 'Нет привязки',
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
    return InkWell(
      borderRadius: BorderRadius.circular(16),
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
        decoration: BoxDecoration(
          color: active
              ? AppPalette.accent.withValues(alpha: 0.16)
              : Colors.transparent,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: active ? AppPalette.borderStrong : Colors.transparent,
          ),
        ),
        child: Row(
          children: [
            Icon(
              icon,
              color: active ? AppPalette.accent : AppPalette.text,
              size: 20,
            ),
            const SizedBox(width: 10),
            Text(
              label,
              style: TextStyle(
                fontWeight: FontWeight.w800,
                color: active ? AppPalette.accent : AppPalette.text,
              ),
            ),
          ],
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
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: (active ? AppPalette.success : AppPalette.warning).withValues(
          alpha: 0.12,
        ),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: (active ? AppPalette.success : AppPalette.warning).withValues(
            alpha: 0.28,
          ),
        ),
      ),
      child: Row(
        children: [
          Icon(
            Icons.circle,
            size: 9,
            color: active ? AppPalette.success : AppPalette.warning,
          ),
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
  });

  final String message;
  final RuntimeBridge bridge;
  final bool running;
  final bool busy;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    return _GlassPanel(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(14),
              gradient: const LinearGradient(
                colors: [AppPalette.accent, AppPalette.secondary],
              ),
            ),
            child: const Icon(Icons.memory_rounded, color: Color(0xFF06111D)),
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
                  style: TextStyle(color: AppPalette.muted, fontSize: 12),
                ),
              ],
            ),
          ),
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

class _HeroPanel extends StatelessWidget {
  const _HeroPanel({
    required this.eyebrow,
    required this.title,
    required this.subtitle,
    this.trailing,
  });

  final String eyebrow;
  final String title;
  final String subtitle;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return _GlassPanel(
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  eyebrow,
                  style: const TextStyle(
                    color: AppPalette.accent,
                    fontWeight: FontWeight.w900,
                    fontSize: 12,
                  ),
                ),
                const SizedBox(height: 6),
                Text(title, style: Theme.of(context).textTheme.displaySmall),
                const SizedBox(height: 8),
                Text(
                  subtitle,
                  style: TextStyle(color: AppPalette.muted, height: 1.35),
                ),
              ],
            ),
          ),
          if (trailing != null) ...[const SizedBox(width: 18), trailing!],
        ],
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
    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: AppPalette.surface.withValues(alpha: 0.82),
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: AppPalette.border),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.18),
            blurRadius: 36,
            offset: const Offset(0, 24),
          ),
        ],
      ),
      child: child,
    );
  }
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({
    required this.label,
    required this.value,
    required this.icon,
    this.accent = AppPalette.accent,
  });

  final String label;
  final String value;
  final IconData icon;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    return _GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: accent.withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(15),
              border: Border.all(color: accent.withValues(alpha: 0.28)),
            ),
            child: Icon(icon, color: accent),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  value,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                Text(
                  label,
                  style: TextStyle(color: AppPalette.muted, fontSize: 12),
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
  const _Section({
    required this.title,
    required this.subtitle,
    required this.child,
  });

  final String title;
  final String subtitle;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 4),
        Text(subtitle, style: TextStyle(color: AppPalette.muted, fontSize: 13)),
        const SizedBox(height: 16),
        child,
      ],
    );
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
    return ActionChip(
      label: Text(label),
      onPressed: onTap,
      backgroundColor: AppPalette.accent.withValues(alpha: 0.12),
      side: BorderSide(color: AppPalette.accent.withValues(alpha: 0.24)),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
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
                color: AppPalette.muted,
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
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppPalette.panel.withValues(alpha: 0.52),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppPalette.border),
      ),
      child: Row(
        children: [
          const Icon(Icons.videocam_rounded, color: AppPalette.accent),
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
                  style: TextStyle(color: AppPalette.muted, fontSize: 12),
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
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: AppPalette.secondary.withValues(alpha: 0.15),
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
        subtitle: 'Сырые данные для быстрой проверки.',
        child: SelectableText(
          const JsonEncoder.withIndent('  ').convert(payload),
          style: GoogleFonts.jetBrainsMono(fontSize: 12, height: 1.35),
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
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppPalette.panel.withValues(alpha: 0.45),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppPalette.border),
      ),
      child: Text(text, style: TextStyle(color: AppPalette.muted)),
    );
  }
}

class _SmallNote extends StatelessWidget {
  const _SmallNote({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Text(
        text,
        style: TextStyle(color: AppPalette.muted, fontSize: 12, height: 1.35),
      ),
    );
  }
}

class _ConnectionBadge extends StatelessWidget {
  const _ConnectionBadge({required this.connected});

  final bool connected;

  @override
  Widget build(BuildContext context) {
    return _MiniBadge(connected ? 'API key сохранён' : 'Нужна привязка');
  }
}

class _ColorPreview extends StatelessWidget {
  const _ColorPreview({required this.color});

  final String color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 44,
      height: 44,
      decoration: BoxDecoration(
        color: parseColor(color),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppPalette.borderStrong),
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
    const items = [
      (
        'Подключение',
        'Укажите backend URL и код подключения. После успешной привязки API-ключ остаётся локально в processor_config.json.',
      ),
      (
        'Запуск',
        'Кнопка запуска поднимает тот же Python Processor в headless-режиме. Вся логика обнаружения остаётся в Python.',
      ),
      (
        'Настройки',
        'Частоты, папки, media token, порт и ускорение пишутся в тот же конфиг. Для runtime-параметров нужен перезапуск.',
      ),
      (
        'Диагностика',
        'Раздел использует существующие CLI-команды status, system-info, acceleration и gallery.',
      ),
      (
        'Журнал',
        'Показывает stdout/stderr текущего процесса и хвост processor.log. Очистка окна не удаляет файл.',
      ),
      (
        'Portable',
        'Для портативной сборки рядом с GUI кладётся папка processor с бинарником CCTV-Processor и Python runtime.',
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
                  style: TextStyle(color: AppPalette.muted, height: 1.35),
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
    return CustomPaint(painter: _GridPainter());
  }
}

class _GridPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = Colors.white.withValues(alpha: 0.028)
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
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class ProcessorTheme {
  static ThemeData dark() {
    final base = ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: AppPalette.bg,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppPalette.accent,
        brightness: Brightness.dark,
        primary: AppPalette.accent,
        secondary: AppPalette.secondary,
        surface: AppPalette.surface,
      ),
    );
    final textTheme = GoogleFonts.spaceGroteskTextTheme(
      base.textTheme,
    ).apply(bodyColor: AppPalette.text, displayColor: AppPalette.textStrong);
    return base.copyWith(
      textTheme: textTheme.copyWith(
        displaySmall: GoogleFonts.spaceGrotesk(
          fontSize: 30,
          fontWeight: FontWeight.w900,
          color: AppPalette.textStrong,
          height: 1.05,
        ),
        headlineSmall: GoogleFonts.spaceGrotesk(
          fontSize: 19,
          fontWeight: FontWeight.w900,
          color: AppPalette.textStrong,
        ),
        titleLarge: GoogleFonts.spaceGrotesk(
          fontSize: 18,
          fontWeight: FontWeight.w900,
          color: AppPalette.textStrong,
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppPalette.panel.withValues(alpha: 0.62),
        labelStyle: TextStyle(color: AppPalette.muted, fontSize: 13),
        hintStyle: TextStyle(color: AppPalette.muted, fontSize: 13),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: AppPalette.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: AppPalette.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: AppPalette.accent),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          elevation: 0,
          backgroundColor: AppPalette.accent,
          foregroundColor: const Color(0xFF06111D),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 15),
          textStyle: const TextStyle(fontWeight: FontWeight.w900),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AppPalette.textStrong,
          side: const BorderSide(color: AppPalette.border),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
        ),
      ),
    );
  }
}

class AppPalette {
  static const bg = Color(0xFF050B13);
  static const panel = Color(0xFF0A1422);
  static const surface = Color(0xFF0D1828);
  static const text = Color(0xFFE7EEF9);
  static const textStrong = Colors.white;
  static const muted = Color(0xFF91A3BD);
  static const border = Color(0x1FFFFFFF);
  static const borderStrong = Color(0x3D5EF0FF);
  static const accent = Color(0xFF5EF0FF);
  static const secondary = Color(0xFF7C8CFF);
  static const success = Color(0xFF22C55E);
  static const warning = Color(0xFFF59E0B);
  static const danger = Color(0xFFEF4444);
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
    'max_workers': 4,
    'processor_accel': 'auto',
    'motion_threshold': 25.0,
    'face_scan_divisor': 8,
    'overlay_frame_divisor': 1,
    'face_scan_interval': 0.35,
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
  config['face_scan_divisor'] = _sanitizeDivisor(
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

String _divisorLabel(int value) {
  if (value == 1) return 'Покадровая';
  if (value == 120) return '1 кадр / 5 сек';
  return '/$value';
}

int _intFrom(String text, int fallback, {int? min, int? max}) {
  var value = int.tryParse(text.trim()) ?? fallback;
  if (min != null && value < min) value = min;
  if (max != null && value > max) value = max;
  return value;
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
            joinPath(current.path, 'processor', 'run_gui.py'),
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
  final trimmed = text.trim();
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
