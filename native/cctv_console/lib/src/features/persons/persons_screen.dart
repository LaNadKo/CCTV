import 'dart:async';

import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/models/models.dart';
import '../../core/network/api_client.dart';
import '../../core/refresh/refresh_bus.dart';
import '../../core/theme/app_theme.dart';
import '../../shared/input/human_name.dart';
import '../../shared/widgets/glass_panel.dart';
import '../../shared/widgets/mjpeg_stream_view.dart';
import '../../shared/widgets/page_header.dart';
import '../auth/auth_controller.dart';

const int _minLiveCaptureIntervalMs = 100;
const int _maxLiveCaptureIntervalMs = 2000;
const int _maxLiveCaptureEmbeddings = 100;
const double _fallbackLiveCameraFps = 10;

class PersonsManagementScreen extends StatefulWidget {
  const PersonsManagementScreen({super.key});

  @override
  State<PersonsManagementScreen> createState() =>
      _PersonsManagementScreenState();
}

class _LiveCaptureResult {
  const _LiveCaptureResult({required this.status, required this.maxSimilarity});

  final String status;
  final double? maxSimilarity;
}

class _PersonsManagementScreenState extends State<PersonsManagementScreen>
    with RouteRefreshState<PersonsManagementScreen> {
  final _searchController = TextEditingController();
  final _createFirstName = TextEditingController();
  final _createLastName = TextEditingController();
  final _createMiddleName = TextEditingController();
  final _editFirstName = TextEditingController();
  final _editLastName = TextEditingController();
  final _editMiddleName = TextEditingController();
  Timer? _searchDebounce;

  bool _busy = false;
  String? _error;
  int? _selectedPersonId;
  int? _embeddingCameraId;
  bool _liveCaptureRunning = false;
  bool _liveCaptureBusy = false;
  int _liveCaptureIntervalMs = _minLiveCaptureIntervalMs;
  int _liveCaptureTarget = 20;
  int _liveCaptureAdded = 0;
  int _liveCaptureAttempts = 0;
  int _liveCaptureDuplicates = 0;
  String? _liveCaptureStatus;
  List<Map<String, dynamic>> _persons = const [];
  List<CameraSummary> _cameras = const [];
  List<Map<String, dynamic>> _appearances = const [];

  @override
  void initState() {
    super.initState();
    _searchController.addListener(_scheduleSearch);
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  String get refreshRoute => '/persons';

  @override
  Future<void> onRefreshRequested() {
    if (_busy || _liveCaptureRunning) return Future<void>.value();
    return _load();
  }

  @override
  void dispose() {
    _liveCaptureRunning = false;
    _searchDebounce?.cancel();
    _searchController.dispose();
    _createFirstName.dispose();
    _createLastName.dispose();
    _createMiddleName.dispose();
    _editFirstName.dispose();
    _editLastName.dispose();
    _editMiddleName.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    await _run(() async {
      final (api, token) = _deps();
      final result = await Future.wait([
        api.getJsonList(
          '/persons',
          token: token,
          query: {
            if (_searchController.text.trim().isNotEmpty)
              'q': _searchController.text.trim(),
            'limit': '300',
          },
        ),
        api.listCameras(token),
      ]);
      final persons = result[0] as List<Map<String, dynamic>>;
      final cameras = result[1] as List<CameraSummary>;
      final selectedId = _resolveSelectedPersonId(persons);
      final appearances = await _fetchAppearances(selectedId);
      setState(() {
        _persons = persons;
        _cameras = cameras;
        _selectedPersonId = selectedId;
        _appearances = appearances;
        if (_embeddingCameraId != null &&
            !_cameras.any((camera) => camera.cameraId == _embeddingCameraId)) {
          _embeddingCameraId = null;
        }
        _liveCaptureIntervalMs = _normalizeLiveInterval(_liveCaptureIntervalMs);
      });
      _syncEditControllers();
    });
  }

  void _scheduleSearch() {
    _searchDebounce?.cancel();
    _searchDebounce = Timer(const Duration(milliseconds: 300), () {
      if (mounted && !_busy && !_liveCaptureRunning) {
        unawaited(_load());
      }
    });
  }

  Future<void> _createPerson() async {
    final error = _validateNameControllers(
      lastName: _createLastName,
      firstName: _createFirstName,
      middleName: _createMiddleName,
    );
    if (error != null) {
      _toast(error);
      return;
    }
    await _run(() async {
      final (api, token) = _deps();
      final created = await api.postJson(
        '/persons',
        token: token,
        body: {
          'first_name': _optional(normalizeHumanName(_createFirstName.text)),
          'last_name': _optional(normalizeHumanName(_createLastName.text)),
          'middle_name': _optional(normalizeHumanName(_createMiddleName.text)),
        },
      );
      _createFirstName.clear();
      _createLastName.clear();
      _createMiddleName.clear();
      _selectedPersonId = created['person_id'] as int?;
      await _reloadQuietly();
      _markPersonsChanged();
      _toast('Персона создана');
    });
  }

  Future<void> _saveSelectedPerson() async {
    final personId = _selectedPersonId;
    if (personId == null) return;
    final error = _validateNameControllers(
      lastName: _editLastName,
      firstName: _editFirstName,
      middleName: _editMiddleName,
    );
    if (error != null) {
      _toast(error);
      return;
    }
    await _run(() async {
      final (api, token) = _deps();
      await api.patchJson(
        '/persons/$personId',
        token: token,
        body: {
          'first_name': normalizeHumanName(_editFirstName.text),
          'last_name': normalizeHumanName(_editLastName.text),
          'middle_name': normalizeHumanName(_editMiddleName.text),
        },
      );
      await _reloadQuietly();
      _markPersonsChanged();
      _toast('Карточка персоны сохранена');
    });
  }

  Future<void> _deleteSelectedPerson() async {
    final personId = _selectedPersonId;
    if (personId == null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Удалить персону?'),
        content: Text(
          'Персона ${_selectedLabel()} будет скрыта из списка и отвязана от камер.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Удалить'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await _run(() async {
      final (api, token) = _deps();
      await api.deleteVoid('/persons/$personId', token: token);
      _selectedPersonId = null;
      await _reloadQuietly();
      _markPersonsChanged();
      _toast('Персона удалена');
    });
  }

  Future<void> _addPhotoEmbedding() async {
    final personId = _selectedPersonId;
    if (personId == null) return;
    final picked = await openFile(
      acceptedTypeGroups: const [
        XTypeGroup(
          label: 'Изображения',
          extensions: ['jpg', 'jpeg', 'png', 'webp'],
          mimeTypes: ['image/jpeg', 'image/png', 'image/webp'],
        ),
      ],
    );
    if (picked == null) return;
    await _run(() async {
      final (api, token) = _deps();
      final result = await api.uploadPersonPhotoStream(
        token,
        personId,
        stream: picked.openRead(),
        length: await picked.length(),
        filename: picked.name,
        cameraId: _embeddingCameraId,
      );
      await _reloadQuietly();
      _markPersonsChanged();
      final status = '${result['status'] ?? 'added'}';
      final similarity = result['max_similarity'];
      _toast(
        status == 'added'
            ? 'Фото добавлено в эмбеддинги'
            : 'Backend вернул статус $status'
                  '${similarity == null ? '' : ', similarity $similarity'}',
      );
    });
  }

  Future<void> _captureLiveEmbedding() async {
    if (_liveCaptureBusy) return;
    if (_selectedPersonId == null) return;
    if (_embeddingCameraId == null) {
      _toast('Выберите камеру для live-кадра');
      return;
    }
    setState(() {
      _liveCaptureBusy = true;
      _liveCaptureStatus = 'Получаю live-кадр...';
    });
    try {
      final result = await _captureLiveEmbeddingSample(reload: true);
      final status = result.status;
      final similarity = result.maxSimilarity;
      final message = switch (status) {
        'added' => 'Эмбеддинг добавлен из live-потока',
        'duplicate' =>
          'Похожий ракурс уже есть${similarity == null ? '' : ': sim=${similarity.toStringAsFixed(3)}'}',
        'mismatch' =>
          'Лицо не похоже на выбранную персону${similarity == null ? '' : ': sim=${similarity.toStringAsFixed(3)}'}',
        _ => 'Кадр из эфира отправлен: $status',
      };
      if (!mounted) return;
      setState(() => _liveCaptureStatus = message);
      _toast(message);
    } catch (error) {
      if (!mounted) return;
      setState(() => _liveCaptureStatus = '$error');
      _toast('$error');
    } finally {
      if (mounted) setState(() => _liveCaptureBusy = false);
    }
  }

  Future<_LiveCaptureResult> _captureLiveEmbeddingSample({
    required bool reload,
  }) async {
    final personId = _selectedPersonId;
    final cameraId = _embeddingCameraId;
    if (personId == null) throw ApiException('Выберите персону');
    if (cameraId == null) throw ApiException('Выберите камеру для live-сбора');
    final (api, token) = _deps();
    final bytes = await api.captureCameraJpegFrame(token, cameraId);
    final result = await api.uploadPersonPhotoStream(
      token,
      personId,
      stream: Stream<List<int>>.value(bytes),
      length: bytes.length,
      filename:
          'live-camera-$cameraId-${DateTime.now().millisecondsSinceEpoch}.jpg',
      cameraId: cameraId,
    );
    if (reload) {
      await _reloadQuietly();
      _markPersonsChanged();
    }
    final similarity = result['max_similarity'];
    return _LiveCaptureResult(
      status: '${result['status'] ?? 'added'}',
      maxSimilarity: similarity is num ? similarity.toDouble() : null,
    );
  }

  Future<void> _startLiveAutoCapture() async {
    if (_liveCaptureRunning || _liveCaptureBusy) return;
    if (_selectedPersonId == null) {
      _toast('Выберите персону');
      return;
    }
    if (_embeddingCameraId == null) {
      _toast('Выберите камеру для live-сбора');
      return;
    }
    final personId = _selectedPersonId;
    final cameraId = _embeddingCameraId;
    final target = _normalizeLiveTarget(_liveCaptureTarget);
    final intervalMs = _normalizeLiveInterval(_liveCaptureIntervalMs);
    setState(() {
      _liveCaptureRunning = true;
      _liveCaptureBusy = false;
      _liveCaptureIntervalMs = intervalMs;
      _liveCaptureTarget = target;
      _liveCaptureAdded = 0;
      _liveCaptureAttempts = 0;
      _liveCaptureDuplicates = 0;
      _liveCaptureStatus =
          'Автосбор запущен: интервал $intervalMs мс, цель $target.';
    });

    var added = 0;
    var attempts = 0;
    var duplicates = 0;
    while (mounted &&
        _liveCaptureRunning &&
        personId == _selectedPersonId &&
        cameraId == _embeddingCameraId &&
        added < target &&
        attempts < _maxLiveCaptureEmbeddings) {
      final startedAt = DateTime.now();
      setState(() {
        _liveCaptureBusy = true;
        _liveCaptureStatus =
            'Кадр ${attempts + 1}/$_maxLiveCaptureEmbeddings...';
      });
      try {
        final result = await _captureLiveEmbeddingSample(reload: false);
        attempts += 1;
        if (result.status == 'added') {
          added += 1;
        } else if (result.status == 'duplicate') {
          duplicates += 1;
        } else if (result.status == 'mismatch') {
          if (mounted) {
            setState(() {
              _liveCaptureRunning = false;
              _liveCaptureStatus =
                  'Автосбор остановлен: лицо не похоже на выбранную персону.';
            });
          }
          break;
        }
        if (mounted) {
          setState(() {
            _liveCaptureAdded = added;
            _liveCaptureAttempts = attempts;
            _liveCaptureDuplicates = duplicates;
            _liveCaptureStatus =
                'Добавлено $added/$target, дублей $duplicates, попыток $attempts.';
          });
        }
      } catch (error) {
        if (mounted) {
          setState(() {
            _liveCaptureRunning = false;
            _liveCaptureStatus = '$error';
          });
        }
        break;
      } finally {
        if (mounted) setState(() => _liveCaptureBusy = false);
      }

      final elapsedMs = DateTime.now().difference(startedAt).inMilliseconds;
      final waitMs = intervalMs - elapsedMs;
      if (waitMs > 0 &&
          mounted &&
          _liveCaptureRunning &&
          added < target &&
          attempts < _maxLiveCaptureEmbeddings) {
        await Future<void>.delayed(Duration(milliseconds: waitMs));
      }
    }

    if (!mounted) return;
    final completed = added >= target;
    setState(() {
      _liveCaptureRunning = false;
      _liveCaptureBusy = false;
      _liveCaptureAdded = added;
      _liveCaptureAttempts = attempts;
      _liveCaptureDuplicates = duplicates;
      _liveCaptureStatus = completed
          ? 'Автосбор завершён: добавлено $added эмбеддингов.'
          : 'Автосбор остановлен: добавлено $added, попыток $attempts.';
    });
    unawaited(_reloadQuietly());
    _markPersonsChanged();
  }

  void _stopLiveAutoCapture() {
    if (!_liveCaptureRunning) return;
    setState(() {
      _liveCaptureRunning = false;
      _liveCaptureStatus = 'Автосбор останавливается...';
    });
  }

  Future<void> _createPersonFromPhoto() async {
    final error = _validateNameControllers(
      lastName: _createLastName,
      firstName: _createFirstName,
      middleName: _createMiddleName,
    );
    if (error != null) {
      _toast(error);
      return;
    }
    final picked = await openFile(
      acceptedTypeGroups: const [
        XTypeGroup(
          label: 'Изображения',
          extensions: ['jpg', 'jpeg', 'png', 'webp'],
          mimeTypes: ['image/jpeg', 'image/png', 'image/webp'],
        ),
      ],
    );
    if (picked == null) return;
    await _run(() async {
      final (api, token) = _deps();
      final result = await api.enrollPersonPhotoStream(
        token,
        stream: picked.openRead(),
        length: await picked.length(),
        filename: picked.name,
        firstName: normalizeHumanName(_createFirstName.text),
        lastName: normalizeHumanName(_createLastName.text),
        middleName: normalizeHumanName(_createMiddleName.text),
      );
      _createFirstName.clear();
      _createLastName.clear();
      _createMiddleName.clear();
      _selectedPersonId = result['person_id'] as int?;
      await _reloadQuietly();
      _markPersonsChanged();
      _toast('Персона создана из фото');
    });
  }

  Future<void> _reloadQuietly() async {
    final (api, token) = _deps();
    final result = await Future.wait([
      api.getJsonList('/persons', token: token),
      api.listCameras(token),
    ]);
    if (!mounted) return;
    final persons = result[0] as List<Map<String, dynamic>>;
    final cameras = result[1] as List<CameraSummary>;
    final selectedId = _resolveSelectedPersonId(persons);
    final appearances = await _fetchAppearances(selectedId);
    setState(() {
      _persons = persons;
      _cameras = cameras;
      _selectedPersonId = selectedId;
      _appearances = appearances;
    });
    _syncEditControllers();
  }

  Future<List<Map<String, dynamic>>> _fetchAppearances(int? personId) async {
    if (personId == null) return const [];
    final (api, token) = _deps();
    final result = await api.getJson(
      '/reports/appearances',
      token: token,
      query: {'person_id': '$personId'},
    );
    final map = result is Map
        ? result.map((key, value) => MapEntry('$key', value))
        : <String, dynamic>{};
    final items = map['items'];
    if (items is! List) return const [];
    return items
        .whereType<Map>()
        .map((item) => item.map((key, value) => MapEntry('$key', value)))
        .toList();
  }

  Future<void> _loadSelectedAppearances() async {
    try {
      final appearances = await _fetchAppearances(_selectedPersonId);
      if (mounted) setState(() => _appearances = appearances);
    } catch (_) {
      if (mounted) setState(() => _appearances = const []);
    }
  }

  (ApiClient, String) _deps() {
    final auth = context.read<AuthController>();
    final token = auth.accessToken;
    if (token == null) throw ApiException('Нет активной сессии');
    return (auth.apiClient, token);
  }

  Future<void> _run(Future<void> Function() action) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _markPersonsChanged() {
    if (!mounted) return;
    context.read<RefreshBus>().markStale(const [
      '/reviews',
      '/reports',
      '/live',
    ]);
  }

  int? _resolveSelectedPersonId(List<Map<String, dynamic>> persons) {
    if (persons.isEmpty) return null;
    if (_selectedPersonId != null &&
        persons.any((person) => person['person_id'] == _selectedPersonId)) {
      return _selectedPersonId;
    }
    return persons.first['person_id'] as int?;
  }

  void _selectPerson(int personId) {
    setState(() => _selectedPersonId = personId);
    _syncEditControllers();
    unawaited(_loadSelectedAppearances());
  }

  void _setEmbeddingCameraId(int? value) {
    setState(() {
      _embeddingCameraId = value;
      _liveCaptureIntervalMs = _normalizeLiveInterval(_liveCaptureIntervalMs);
    });
  }

  void _syncEditControllers() {
    final person = _selectedPerson();
    _editFirstName.text = '${person?['first_name'] ?? ''}';
    _editLastName.text = '${person?['last_name'] ?? ''}';
    _editMiddleName.text = '${person?['middle_name'] ?? ''}';
  }

  Map<String, dynamic>? _selectedPerson() {
    final personId = _selectedPersonId;
    if (personId == null) return null;
    for (final person in _persons) {
      if (person['person_id'] == personId) return person;
    }
    return null;
  }

  List<Map<String, dynamic>> get _filteredPersons {
    return _persons;
  }

  int get _embeddingsCount => _persons.fold<int>(
    0,
    (sum, person) => sum + ((person['embeddings_count'] as num?)?.toInt() ?? 0),
  );

  String _selectedLabel() {
    final person = _selectedPerson();
    return person == null ? 'не выбрана' : _personLabel(person);
  }

  String? _validateNameControllers({
    required TextEditingController lastName,
    required TextEditingController firstName,
    required TextEditingController middleName,
  }) {
    final fields = {
      'Фамилия': lastName.text,
      'Имя': firstName.text,
      'Отчество': middleName.text,
    };
    for (final entry in fields.entries) {
      final error = validateOptionalHumanName(entry.key, entry.value);
      if (error != null) return error;
    }
    return null;
  }

  int get _minLiveIntervalForSelectedCamera {
    CameraSummary? selectedCamera;
    for (final camera in _cameras) {
      if (camera.cameraId == _embeddingCameraId) {
        selectedCamera = camera;
        break;
      }
    }
    final fps = selectedCamera?.fps;
    final safeFps = fps != null && fps.isFinite && fps > 0
        ? (fps > 60 ? 60 : fps)
        : _fallbackLiveCameraFps;
    final byFps = (1000 / safeFps).ceil();
    final bounded = byFps < _minLiveCaptureIntervalMs
        ? _minLiveCaptureIntervalMs
        : byFps;
    return bounded > _maxLiveCaptureIntervalMs
        ? _maxLiveCaptureIntervalMs
        : bounded;
  }

  int _normalizeLiveInterval(int value) {
    final min = _minLiveIntervalForSelectedCamera;
    if (value < min) return min;
    if (value > _maxLiveCaptureIntervalMs) return _maxLiveCaptureIntervalMs;
    return value;
  }

  int _normalizeLiveTarget(int value) {
    if (value < 1) return 1;
    if (value > _maxLiveCaptureEmbeddings) return _maxLiveCaptureEmbeddings;
    return value;
  }

  void _setLiveCaptureInterval(double value) {
    setState(
      () => _liveCaptureIntervalMs = _normalizeLiveInterval(value.round()),
    );
  }

  void _setLiveCaptureTarget(double value) {
    setState(() => _liveCaptureTarget = _normalizeLiveTarget(value.round()));
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), behavior: SnackBarBehavior.floating),
    );
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    final token = auth.accessToken;
    final filtered = _filteredPersons;
    final selected = _selectedPerson();
    final livePreviewUri = _embeddingCameraId == null || token == null
        ? null
        : auth.apiClient.cameraStreamUri(_embeddingCameraId!, annotate: false);
    final livePreviewHeaders = token == null
        ? const <String, String>{}
        : {'Authorization': 'Bearer $token'};

    return RefreshIndicator(
      onRefresh: _load,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                PageHeader(
                  title: 'Персоны',
                  icon: Icons.badge_rounded,
                  trailing: PageActions(
                    children: [
                      IconButton.filledTonal(
                        onPressed: _busy ? null : _load,
                        icon: _busy
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Icon(Icons.refresh_rounded),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                if (_error != null) ...[
                  _InlineError(message: _error!),
                  const SizedBox(height: 12),
                ],
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    _Metric(
                      label: 'Персон',
                      value: '${_persons.length}',
                      icon: Icons.badge_rounded,
                    ),
                    _Metric(
                      label: 'В выборке',
                      value: '${filtered.length}',
                      icon: Icons.search_rounded,
                    ),
                    _Metric(
                      label: 'Эмбеддингов',
                      value: '$_embeddingsCount',
                      icon: Icons.data_object_rounded,
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                _CreatePersonPanel(
                  busy: _busy,
                  firstName: _createFirstName,
                  lastName: _createLastName,
                  middleName: _createMiddleName,
                  onCreate: _createPerson,
                  onCreateFromPhoto: _createPersonFromPhoto,
                ),
                const SizedBox(height: 14),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final narrow = constraints.maxWidth < 960;
                    final list = _PersonsListPanel(
                      persons: filtered,
                      selectedPersonId: _selectedPersonId,
                      searchController: _searchController,
                      onSelect: _selectPerson,
                    );
                    final detail = _PersonDetailPanel(
                      person: selected,
                      busy: _busy,
                      firstName: _editFirstName,
                      lastName: _editLastName,
                      middleName: _editMiddleName,
                      cameras: _cameras,
                      embeddingCameraId: _embeddingCameraId,
                      minLiveCaptureIntervalMs:
                          _minLiveIntervalForSelectedCamera,
                      liveCaptureIntervalMs: _normalizeLiveInterval(
                        _liveCaptureIntervalMs,
                      ),
                      liveCaptureTarget: _normalizeLiveTarget(
                        _liveCaptureTarget,
                      ),
                      liveCaptureAdded: _liveCaptureAdded,
                      liveCaptureAttempts: _liveCaptureAttempts,
                      liveCaptureDuplicates: _liveCaptureDuplicates,
                      liveCaptureRunning: _liveCaptureRunning,
                      liveCaptureBusy: _liveCaptureBusy,
                      liveCaptureStatus: _liveCaptureStatus,
                      livePreviewUri: livePreviewUri,
                      livePreviewHeaders: livePreviewHeaders,
                      onEmbeddingCameraChanged: _setEmbeddingCameraId,
                      onLiveCaptureIntervalChanged: _setLiveCaptureInterval,
                      onLiveCaptureTargetChanged: _setLiveCaptureTarget,
                      onStartLiveCapture: _startLiveAutoCapture,
                      onStopLiveCapture: _stopLiveAutoCapture,
                      onSave: _saveSelectedPerson,
                      onDelete: _deleteSelectedPerson,
                      onAddPhoto: _addPhotoEmbedding,
                      onCaptureLive: _captureLiveEmbedding,
                      appearances: _appearances,
                    );
                    if (narrow) {
                      return Column(
                        children: [list, const SizedBox(height: 14), detail],
                      );
                    }
                    return Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(width: 390, child: list),
                        const SizedBox(width: 14),
                        Expanded(child: detail),
                      ],
                    );
                  },
                ),
                const SizedBox(height: 24),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _PersonsListPanel extends StatelessWidget {
  const _PersonsListPanel({
    required this.persons,
    required this.selectedPersonId,
    required this.searchController,
    required this.onSelect,
  });

  final List<Map<String, dynamic>> persons;
  final int? selectedPersonId;
  final TextEditingController searchController;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Список персон',
            style: TextStyle(
              color: colors.textStrong,
              fontSize: 16,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: searchController,
            decoration: const InputDecoration(
              prefixIcon: Icon(Icons.search_rounded),
              labelText: 'Поиск по ФИО или ID',
            ),
          ),
          const SizedBox(height: 12),
          SizedBox(
            height: 520,
            child: persons.isEmpty
                ? const _EmptyState(text: 'Персоны не найдены')
                : ListView.builder(
                    itemCount: persons.length,
                    itemExtent: 82,
                    itemBuilder: (context, index) {
                      final person = persons[index];
                      final id = person['person_id'] as int;
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: _PersonListTile(
                          person: person,
                          selected: id == selectedPersonId,
                          onTap: () => onSelect(id),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}

class _PersonListTile extends StatelessWidget {
  const _PersonListTile({
    required this.person,
    required this.selected,
    required this.onTap,
  });

  final Map<String, dynamic> person;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final embeddings = (person['embeddings_count'] as num?)?.toInt() ?? 0;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 160),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        gradient: selected
            ? LinearGradient(
                colors: [
                  colors.primaryAccent.withValues(alpha: 0.22),
                  colors.secondaryAccent.withValues(alpha: 0.18),
                ],
              )
            : null,
        color: selected ? null : colors.surfaceMuted,
        border: Border.all(
          color: selected ? colors.primaryAccent : colors.border,
        ),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          child: Row(
            children: [
              CircleAvatar(
                radius: 20,
                backgroundColor: colors.primaryAccent.withValues(alpha: 0.16),
                child: Text(
                  '${person['person_id']}',
                  style: TextStyle(
                    color: colors.textStrong,
                    fontSize: 12,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(
                      _personLabel(person),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: colors.textStrong,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Эмбеддингов: $embeddings',
                      style: TextStyle(color: colors.muted, fontSize: 12),
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right_rounded, color: colors.muted),
            ],
          ),
        ),
      ),
    );
  }
}

class _CreatePersonPanel extends StatelessWidget {
  const _CreatePersonPanel({
    required this.busy,
    required this.firstName,
    required this.lastName,
    required this.middleName,
    required this.onCreate,
    required this.onCreateFromPhoto,
  });

  final bool busy;
  final TextEditingController firstName;
  final TextEditingController lastName;
  final TextEditingController middleName;
  final VoidCallback onCreate;
  final VoidCallback onCreateFromPhoto;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Новая персона',
            style: TextStyle(
              color: colors.textStrong,
              fontSize: 16,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 12),
          _NameFields(
            firstName: firstName,
            lastName: lastName,
            middleName: middleName,
          ),
          const SizedBox(height: 14),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              ElevatedButton.icon(
                onPressed: busy ? null : onCreate,
                icon: const Icon(Icons.person_add_alt_1_rounded, size: 18),
                label: const Text('Создать персону'),
              ),
              OutlinedButton.icon(
                onPressed: busy ? null : onCreateFromPhoto,
                icon: const Icon(Icons.add_a_photo_rounded, size: 18),
                label: const Text('Создать из фото'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _PersonDetailPanel extends StatelessWidget {
  const _PersonDetailPanel({
    required this.person,
    required this.busy,
    required this.firstName,
    required this.lastName,
    required this.middleName,
    required this.cameras,
    required this.embeddingCameraId,
    required this.minLiveCaptureIntervalMs,
    required this.liveCaptureIntervalMs,
    required this.liveCaptureTarget,
    required this.liveCaptureAdded,
    required this.liveCaptureAttempts,
    required this.liveCaptureDuplicates,
    required this.liveCaptureRunning,
    required this.liveCaptureBusy,
    required this.liveCaptureStatus,
    required this.livePreviewUri,
    required this.livePreviewHeaders,
    required this.onEmbeddingCameraChanged,
    required this.onLiveCaptureIntervalChanged,
    required this.onLiveCaptureTargetChanged,
    required this.onStartLiveCapture,
    required this.onStopLiveCapture,
    required this.onSave,
    required this.onDelete,
    required this.onAddPhoto,
    required this.onCaptureLive,
    required this.appearances,
  });

  final Map<String, dynamic>? person;
  final bool busy;
  final TextEditingController firstName;
  final TextEditingController lastName;
  final TextEditingController middleName;
  final List<CameraSummary> cameras;
  final int? embeddingCameraId;
  final int minLiveCaptureIntervalMs;
  final int liveCaptureIntervalMs;
  final int liveCaptureTarget;
  final int liveCaptureAdded;
  final int liveCaptureAttempts;
  final int liveCaptureDuplicates;
  final bool liveCaptureRunning;
  final bool liveCaptureBusy;
  final String? liveCaptureStatus;
  final Uri? livePreviewUri;
  final Map<String, String> livePreviewHeaders;
  final ValueChanged<int?> onEmbeddingCameraChanged;
  final ValueChanged<double> onLiveCaptureIntervalChanged;
  final ValueChanged<double> onLiveCaptureTargetChanged;
  final VoidCallback onStartLiveCapture;
  final VoidCallback onStopLiveCapture;
  final VoidCallback onSave;
  final VoidCallback onDelete;
  final VoidCallback onAddPhoto;
  final VoidCallback onCaptureLive;
  final List<Map<String, dynamic>> appearances;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Column(
      children: [
        GlassPanel(
          padding: const EdgeInsets.all(16),
          child: person == null
              ? const _EmptyState(text: 'Выберите персону из списка')
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                _personLabel(person!),
                                style: TextStyle(
                                  color: colors.textStrong,
                                  fontSize: 18,
                                  fontWeight: FontWeight.w900,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                'ID ${person!['person_id']} · эмбеддингов: ${person!['embeddings_count'] ?? 0}',
                                style: TextStyle(
                                  color: colors.muted,
                                  fontSize: 12,
                                ),
                              ),
                            ],
                          ),
                        ),
                        IconButton(
                          tooltip: 'Удалить персону',
                          onPressed: busy ? null : onDelete,
                          icon: Icon(
                            Icons.delete_rounded,
                            color: colors.danger,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    _NameFields(
                      firstName: firstName,
                      lastName: lastName,
                      middleName: middleName,
                    ),
                    const SizedBox(height: 14),
                    Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        ElevatedButton.icon(
                          onPressed: busy ? null : onSave,
                          icon: const Icon(Icons.save_rounded, size: 18),
                          label: const Text('Сохранить'),
                        ),
                        OutlinedButton.icon(
                          onPressed: busy ? null : onAddPhoto,
                          icon: const Icon(Icons.add_photo_alternate_rounded),
                          label: const Text('Добавить фото'),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    _CameraSelector(
                      cameras: cameras,
                      value: embeddingCameraId,
                      onChanged: onEmbeddingCameraChanged,
                    ),
                    const SizedBox(height: 14),
                    _LiveCapturePanel(
                      cameraSelected: embeddingCameraId != null,
                      busy: busy,
                      running: liveCaptureRunning,
                      captureBusy: liveCaptureBusy,
                      intervalMs: liveCaptureIntervalMs,
                      minIntervalMs: minLiveCaptureIntervalMs,
                      target: liveCaptureTarget,
                      added: liveCaptureAdded,
                      attempts: liveCaptureAttempts,
                      duplicates: liveCaptureDuplicates,
                      status: liveCaptureStatus,
                      livePreviewUri: livePreviewUri,
                      livePreviewHeaders: livePreviewHeaders,
                      onIntervalChanged: onLiveCaptureIntervalChanged,
                      onTargetChanged: onLiveCaptureTargetChanged,
                      onStart: onStartLiveCapture,
                      onStop: onStopLiveCapture,
                      onCaptureOnce: onCaptureLive,
                    ),
                    const SizedBox(height: 14),
                    _AppearancesPanel(items: appearances),
                  ],
                ),
        ),
      ],
    );
  }
}

class _AppearancesPanel extends StatelessWidget {
  const _AppearancesPanel({required this.items});

  final List<Map<String, dynamic>> items;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'История появлений',
            style: TextStyle(
              color: colors.textStrong,
              fontSize: 15,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 10),
          if (items.isEmpty)
            Text('Появлений пока нет.', style: TextStyle(color: colors.muted))
          else
            for (final item in items.take(10))
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(
                  children: [
                    Icon(
                      Icons.visibility_rounded,
                      color: colors.primaryAccent,
                      size: 18,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        '${item['camera_name'] ?? 'Камера #${item['camera_id']}'} · ${item['event_ts'] ?? '-'} · confidence ${item['confidence'] ?? '-'}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(color: colors.text, fontSize: 12),
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

class _LiveCapturePanel extends StatelessWidget {
  const _LiveCapturePanel({
    required this.cameraSelected,
    required this.busy,
    required this.running,
    required this.captureBusy,
    required this.intervalMs,
    required this.minIntervalMs,
    required this.target,
    required this.added,
    required this.attempts,
    required this.duplicates,
    required this.status,
    required this.livePreviewUri,
    required this.livePreviewHeaders,
    required this.onIntervalChanged,
    required this.onTargetChanged,
    required this.onStart,
    required this.onStop,
    required this.onCaptureOnce,
  });

  final bool cameraSelected;
  final bool busy;
  final bool running;
  final bool captureBusy;
  final int intervalMs;
  final int minIntervalMs;
  final int target;
  final int added;
  final int attempts;
  final int duplicates;
  final String? status;
  final Uri? livePreviewUri;
  final Map<String, String> livePreviewHeaders;
  final ValueChanged<double> onIntervalChanged;
  final ValueChanged<double> onTargetChanged;
  final VoidCallback onStart;
  final VoidCallback onStop;
  final VoidCallback onCaptureOnce;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final normalizedInterval = intervalMs
        .clamp(minIntervalMs, _maxLiveCaptureIntervalMs)
        .toDouble();
    final normalizedTarget = target
        .clamp(1, _maxLiveCaptureEmbeddings)
        .toDouble();
    final progress = target <= 0 ? 0.0 : (added / target).clamp(0.0, 1.0);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Сбор эмбеддингов из эфира',
                      style: TextStyle(
                        color: colors.textStrong,
                        fontSize: 15,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Минимальный интервал: $minIntervalMs мс. Сессия ограничена $_maxLiveCaptureEmbeddings эмбеддингами.',
                      style: TextStyle(color: colors.muted, fontSize: 12),
                    ),
                  ],
                ),
              ),
              if (captureBusy)
                const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
            ],
          ),
          const SizedBox(height: 12),
          ClipRRect(
            borderRadius: BorderRadius.circular(16),
            child: AspectRatio(
              aspectRatio: 16 / 9,
              child: DecoratedBox(
                decoration: BoxDecoration(color: colors.surfaceElevated),
                child: livePreviewUri == null
                    ? Center(
                        child: Text(
                          'Выберите камеру для live-сбора',
                          style: TextStyle(color: colors.muted, fontSize: 12),
                        ),
                      )
                    : MjpegStreamView(
                        uri: livePreviewUri!,
                        headers: livePreviewHeaders,
                        fit: BoxFit.contain,
                        placeholder: const Center(
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                        errorBuilder: (context, error) => Center(
                          child: Padding(
                            padding: const EdgeInsets.all(12),
                            child: Text(
                              '$error',
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                color: colors.danger,
                                fontSize: 12,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                        ),
                      ),
              ),
            ),
          ),
          const SizedBox(height: 12),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: progress,
              minHeight: 8,
              backgroundColor: colors.surfaceElevated.withValues(alpha: 0.45),
            ),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _CaptureStat(label: 'Добавлено', value: '$added/$target'),
              _CaptureStat(label: 'Попыток', value: '$attempts'),
              _CaptureStat(label: 'Дублей', value: '$duplicates'),
              _CaptureStat(label: 'Интервал', value: '$intervalMs мс'),
            ],
          ),
          const SizedBox(height: 12),
          _SliderRow(
            label: 'Интервал',
            valueLabel: '$intervalMs мс',
            value: normalizedInterval,
            min: minIntervalMs.toDouble(),
            max: _maxLiveCaptureIntervalMs.toDouble(),
            divisions: ((_maxLiveCaptureIntervalMs - minIntervalMs) / 50)
                .round(),
            enabled: !running && !captureBusy,
            onChanged: onIntervalChanged,
          ),
          _SliderRow(
            label: 'Цель',
            valueLabel: '$target',
            value: normalizedTarget,
            min: 1,
            max: _maxLiveCaptureEmbeddings.toDouble(),
            divisions: _maxLiveCaptureEmbeddings - 1,
            enabled: !running && !captureBusy,
            onChanged: onTargetChanged,
          ),
          if (status != null && status!.trim().isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              status!,
              style: TextStyle(
                color: running ? colors.primaryAccent : colors.muted,
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
          const SizedBox(height: 12),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              OutlinedButton.icon(
                onPressed: busy || running || captureBusy || !cameraSelected
                    ? null
                    : onCaptureOnce,
                icon: const Icon(Icons.camera_rounded, size: 18),
                label: const Text('Снимок из эфира'),
              ),
              ElevatedButton.icon(
                onPressed: busy || !cameraSelected
                    ? null
                    : (running ? onStop : (captureBusy ? null : onStart)),
                icon: Icon(
                  running
                      ? Icons.stop_circle_rounded
                      : Icons.play_circle_rounded,
                  size: 18,
                ),
                label: Text(running ? 'Остановить сбор' : 'Запустить сбор'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _CaptureStat extends StatelessWidget {
  const _CaptureStat({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: colors.surfaceElevated.withValues(alpha: 0.5),
        border: Border.all(color: colors.border),
      ),
      child: Text(
        '$label: $value',
        style: TextStyle(
          color: colors.text,
          fontSize: 12,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class _SliderRow extends StatelessWidget {
  const _SliderRow({
    required this.label,
    required this.valueLabel,
    required this.value,
    required this.min,
    required this.max,
    required this.divisions,
    required this.enabled,
    required this.onChanged,
  });

  final String label;
  final String valueLabel;
  final double value;
  final double min;
  final double max;
  final int divisions;
  final bool enabled;
  final ValueChanged<double> onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Row(
      children: [
        SizedBox(
          width: 82,
          child: Text(
            label,
            style: TextStyle(
              color: colors.text,
              fontSize: 12,
              fontWeight: FontWeight.w800,
            ),
          ),
        ),
        Expanded(
          child: Slider(
            value: value,
            min: min,
            max: max,
            divisions: divisions <= 0 ? null : divisions,
            label: valueLabel,
            onChanged: enabled ? onChanged : null,
          ),
        ),
        SizedBox(
          width: 64,
          child: Text(
            valueLabel,
            textAlign: TextAlign.right,
            style: TextStyle(
              color: colors.textStrong,
              fontSize: 12,
              fontWeight: FontWeight.w900,
            ),
          ),
        ),
      ],
    );
  }
}

class _NameFields extends StatelessWidget {
  const _NameFields({
    required this.firstName,
    required this.lastName,
    required this.middleName,
  });

  final TextEditingController firstName;
  final TextEditingController lastName;
  final TextEditingController middleName;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final narrow = constraints.maxWidth < 720;
        final fields = [
          TextField(
            controller: lastName,
            inputFormatters: humanNameInputFormatters(),
            textCapitalization: TextCapitalization.words,
            textInputAction: TextInputAction.next,
            decoration: const InputDecoration(labelText: 'Фамилия'),
          ),
          TextField(
            controller: firstName,
            inputFormatters: humanNameInputFormatters(),
            textCapitalization: TextCapitalization.words,
            textInputAction: TextInputAction.next,
            decoration: const InputDecoration(labelText: 'Имя'),
          ),
          TextField(
            controller: middleName,
            inputFormatters: humanNameInputFormatters(),
            textCapitalization: TextCapitalization.words,
            textInputAction: TextInputAction.done,
            decoration: const InputDecoration(labelText: 'Отчество'),
          ),
        ];
        if (narrow) {
          return Column(
            children: [
              for (final field in fields) ...[
                field,
                if (field != fields.last) const SizedBox(height: 10),
              ],
            ],
          );
        }
        return Row(
          children: [
            for (var index = 0; index < fields.length; index++) ...[
              Expanded(child: fields[index]),
              if (index != fields.length - 1) const SizedBox(width: 10),
            ],
          ],
        );
      },
    );
  }
}

class _CameraSelector extends StatelessWidget {
  const _CameraSelector({
    required this.cameras,
    required this.value,
    required this.onChanged,
  });

  final List<CameraSummary> cameras;
  final int? value;
  final ValueChanged<int?> onChanged;

  @override
  Widget build(BuildContext context) {
    return DropdownButtonFormField<int?>(
      initialValue: value,
      decoration: const InputDecoration(
        labelText: 'Камера для сбора из эфира и резерва через Процессор',
      ),
      items: [
        const DropdownMenuItem<int?>(
          value: null,
          child: Text('Не использовать fallback'),
        ),
        for (final camera in cameras)
          DropdownMenuItem<int?>(
            value: camera.cameraId,
            child: Text(camera.name),
          ),
      ],
      onChanged: onChanged,
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value, required this.icon});

  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      width: 178,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Row(
        children: [
          Icon(icon, color: colors.primaryAccent, size: 20),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: TextStyle(color: colors.muted, fontSize: 12),
                ),
                Text(
                  value,
                  style: TextStyle(
                    color: colors.textStrong,
                    fontSize: 22,
                    fontWeight: FontWeight.w900,
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

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Center(
      child: Text(
        text,
        style: TextStyle(color: colors.muted, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class _InlineError extends StatelessWidget {
  const _InlineError({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        color: colors.danger.withValues(alpha: 0.1),
        border: Border.all(color: colors.danger.withValues(alpha: 0.25)),
      ),
      child: Text(
        message,
        style: TextStyle(color: colors.danger, fontWeight: FontWeight.w700),
      ),
    );
  }
}

String _personLabel(Map<String, dynamic> person) {
  final parts =
      [person['last_name'], person['first_name'], person['middle_name']]
          .where((value) => value != null && '$value'.trim().isNotEmpty)
          .map((value) => '$value');
  final label = parts.join(' ').trim();
  return label.isEmpty ? 'Персона #${person['person_id']}' : label;
}

String? _optional(String value) {
  final text = value.trim();
  return text.isEmpty ? null : text;
}
