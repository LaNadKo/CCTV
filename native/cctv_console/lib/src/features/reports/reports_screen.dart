import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:open_filex/open_filex.dart';
import 'package:provider/provider.dart';

import '../../core/models/models.dart';
import '../../core/network/api_client.dart';
import '../../core/refresh/refresh_bus.dart';
import '../../core/theme/app_theme.dart';
import '../../shared/widgets/glass_panel.dart';
import '../auth/auth_controller.dart';
import '../modules/module_screens.dart' show ModuleColumn, ReportTable;

class ReportsDashboardScreen extends StatefulWidget {
  const ReportsDashboardScreen({super.key});

  @override
  State<ReportsDashboardScreen> createState() => _ReportsDashboardScreenState();
}

class _ReportsDashboardScreenState extends State<ReportsDashboardScreen>
    with RouteRefreshState<ReportsDashboardScreen> {
  bool _busy = false;
  String? _error;

  DateTime? _dateFrom;
  DateTime? _dateTo;
  int? _groupId;
  int? _cameraId;
  int? _processorId;
  int? _userId;
  int? _personId;

  Map<String, dynamic>? _dashboard;
  Map<String, dynamic>? _appearances;
  List<Map<String, dynamic>> _groups = const [];
  List<Map<String, dynamic>> _users = const [];
  List<Map<String, dynamic>> _persons = const [];
  List<CameraSummary> _cameras = const [];
  List<ProcessorOut> _processors = const [];

  static const _sections = [
    _ReportSection(
      'user-actions',
      'Действия пользователей',
      Icons.people_alt_rounded,
    ),
    _ReportSection('groups', 'Группы камер', Icons.account_tree_rounded),
    _ReportSection('cameras', 'Камеры', Icons.videocam_rounded),
    _ReportSection('processors', 'Processor', Icons.memory_rounded),
    _ReportSection('events', 'События и ревью', Icons.fact_check_rounded),
    _ReportSection('archive', 'Архив записей', Icons.video_library_rounded),
    _ReportSection('security', 'Безопасность', Icons.shield_rounded),
    _ReportSection('appearances', 'Появления персон', Icons.badge_rounded),
  ];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  String get refreshRoute => '/reports';

  @override
  Future<void> onRefreshRequested() {
    if (_busy) return Future<void>.value();
    return _load();
  }

  Future<void> _load() async {
    await _run(() async {
      await _loadReferences();
      await _loadReports();
    });
  }

  Future<void> _applyFilters() async {
    await _run(_loadReports);
  }

  Future<void> _loadReferences() async {
    final (api, token) = _deps();
    final user = context.read<AuthController>().user;
    final isAdmin = user?.isAdmin ?? false;

    final results = await Future.wait<Object>([
      api.getJsonList('/groups', token: token),
      api.listCameras(token),
      isAdmin
          ? api.listProcessors(token)
          : Future<List<ProcessorOut>>.value(const []),
      isAdmin
          ? api.getJsonList('/admin/users', token: token)
          : Future<List<Map<String, dynamic>>>.value(
              user == null
                  ? const []
                  : [
                      {
                        'user_id': user.userId,
                        'login': user.login,
                        'first_name': user.firstName,
                        'last_name': user.lastName,
                        'middle_name': user.middleName,
                      },
                    ],
            ),
      api.getJsonList('/persons', token: token),
    ]);

    if (!mounted) return;
    setState(() {
      _groups = results[0] as List<Map<String, dynamic>>;
      _cameras = results[1] as List<CameraSummary>;
      _processors = results[2] as List<ProcessorOut>;
      _users = results[3] as List<Map<String, dynamic>>;
      _persons = results[4] as List<Map<String, dynamic>>;
      _normalizeSelectedIds();
    });
  }

  Future<void> _loadReports() async {
    final (api, token) = _deps();
    final dashboard = await api
        .getJson('/reports/dashboard', token: token, query: _dashboardQuery())
        .then(_map);
    final appearances = await api
        .getJson(
          '/reports/appearances',
          token: token,
          query: _appearanceQuery(),
        )
        .then(_map);
    if (!mounted) return;
    setState(() {
      _dashboard = dashboard;
      _appearances = appearances;
    });
  }

  Future<void> _export(_ReportSection section, String format) async {
    await _run(() async {
      final (api, token) = _deps();
      final file = section.id == 'appearances'
          ? await api.downloadAppearanceReport(
              token,
              format: format,
              personId: _personId,
              dateFrom: _iso(_dateFrom),
              dateTo: _iso(_dateTo),
            )
          : await api.downloadReportSection(
              token,
              section: section.id,
              format: format,
              dateFrom: _iso(_dateFrom),
              dateTo: _iso(_dateTo),
              groupId: _groupId,
              cameraId: _cameraId,
              processorId: _processorId,
              userId: _userId,
            );
      await OpenFilex.open(file.path);
      _toast('Отчёт сохранён: ${file.path}');
    });
  }

  Future<void> _pickDateTime({required bool from}) async {
    final now = DateTime.now();
    final current = (from ? _dateFrom : _dateTo) ?? now;
    final initial = current.isAfter(now) ? now : current;
    final date = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: DateTime(2020),
      lastDate: now,
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(initial),
    );
    if (time == null) return;

    var selected = DateTime(
      date.year,
      date.month,
      date.day,
      time.hour,
      time.minute,
    );
    if (selected.isAfter(now)) selected = now;
    setState(() {
      if (from) {
        _dateFrom = selected;
        if (_dateTo != null && _dateTo!.isBefore(selected)) {
          _dateTo = selected;
        }
      } else {
        _dateTo = selected;
        if (_dateFrom != null && _dateFrom!.isAfter(selected)) {
          _dateFrom = selected;
        }
      }
    });
  }

  void _clearFilters() {
    setState(() {
      _dateFrom = null;
      _dateTo = null;
      _groupId = null;
      _cameraId = null;
      _processorId = null;
      _userId = null;
      _personId = null;
    });
    _applyFilters();
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

  Map<String, String?> _dashboardQuery() => {
    'date_from': _iso(_dateFrom),
    'date_to': _iso(_dateTo),
    if (_groupId != null) 'group_id': '$_groupId',
    if (_cameraId != null) 'camera_id': '$_cameraId',
    if (_processorId != null) 'processor_id': '$_processorId',
    if (_userId != null) 'user_id': '$_userId',
  };

  Map<String, String?> _appearanceQuery() => {
    'date_from': _iso(_dateFrom),
    'date_to': _iso(_dateTo),
    if (_personId != null) 'person_id': '$_personId',
  };

  void _normalizeSelectedIds() {
    if (_groupId != null &&
        !_groups.any((item) => item['group_id'] == _groupId)) {
      _groupId = null;
    }
    if (_cameraId != null &&
        !_cameras.any((item) => item.cameraId == _cameraId)) {
      _cameraId = null;
    }
    if (_processorId != null &&
        !_processors.any((item) => item.processorId == _processorId)) {
      _processorId = null;
    }
    if (_userId != null && !_users.any((item) => item['user_id'] == _userId)) {
      _userId = null;
    }
    if (_personId != null &&
        !_persons.any((item) => item['person_id'] == _personId)) {
      _personId = null;
    }
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), behavior: SnackBarBehavior.floating),
    );
  }

  @override
  Widget build(BuildContext context) {
    final dashboard = _dashboard ?? const <String, dynamic>{};
    final appearances = _appearances ?? const <String, dynamic>{};
    final events = _map(dashboard['events']);
    final archive = _map(dashboard['archive']);
    final security = _map(dashboard['security']);
    final userActions = _map(dashboard['user_actions']);
    final cameras = _mapList(dashboard['cameras']);
    final processors = _mapList(dashboard['processors']);
    final groups = _mapList(dashboard['groups']);
    final appearanceItems = _mapList(appearances['items']);

    return RefreshIndicator(
      onRefresh: _load,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _Header(busy: _busy, onRefresh: _load),
                const SizedBox(height: 14),
                _Filters(
                  busy: _busy,
                  dateFrom: _dateFrom,
                  dateTo: _dateTo,
                  groups: _groupItems(),
                  cameras: _cameraItems(),
                  processors: _processorItems(),
                  users: _userItems(),
                  persons: _personItems(),
                  groupId: _groupId,
                  cameraId: _cameraId,
                  processorId: _processorId,
                  userId: _userId,
                  personId: _personId,
                  onPickFrom: () => _pickDateTime(from: true),
                  onPickTo: () => _pickDateTime(from: false),
                  onClearFrom: () => setState(() => _dateFrom = null),
                  onClearTo: () => setState(() => _dateTo = null),
                  onGroupChanged: (value) => setState(() => _groupId = value),
                  onCameraChanged: (value) => setState(() => _cameraId = value),
                  onProcessorChanged: (value) =>
                      setState(() => _processorId = value),
                  onUserChanged: (value) => setState(() => _userId = value),
                  onPersonChanged: (value) => setState(() => _personId = value),
                  onApply: _applyFilters,
                  onClear: _clearFilters,
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  _InlineError(message: _error!),
                ],
                const SizedBox(height: 14),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    _Metric(
                      label: 'События',
                      value: '${events['total_events'] ?? 0}',
                    ),
                    _Metric(
                      label: 'Pending review',
                      value: '${events['pending_reviews'] ?? 0}',
                    ),
                    _Metric(
                      label: 'Файлы архива',
                      value: '${archive['total_files'] ?? 0}',
                    ),
                    _Metric(
                      label: 'Покрытие 2FA',
                      value: '${security['totp_coverage_percent'] ?? 0}%',
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                _ExportPanel(
                  sections: _sections,
                  busy: _busy,
                  onExport: _export,
                ),
                const SizedBox(height: 14),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final narrow = constraints.maxWidth < 920;
                    final cards = [
                      _SimpleListCard(
                        title: 'Камеры',
                        items: cameras,
                        columns: const [
                          'name',
                          'group_name',
                          'connection_kind',
                          'event_count',
                        ],
                      ),
                      _SimpleListCard(
                        title: 'Processor',
                        items: processors,
                        columns: const [
                          'name',
                          'status',
                          'assigned_cameras',
                          'event_count',
                        ],
                      ),
                      _SimpleListCard(
                        title: 'Группы',
                        items: groups,
                        columns: const [
                          'name',
                          'camera_count',
                          'event_count',
                          'pending_reviews',
                        ],
                      ),
                    ];
                    if (narrow) {
                      return Column(
                        children: [
                          for (final card in cards) ...[
                            card,
                            const SizedBox(height: 14),
                          ],
                        ],
                      );
                    }
                    return Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(child: cards[0]),
                        const SizedBox(width: 14),
                        Expanded(child: cards[1]),
                        const SizedBox(width: 14),
                        Expanded(child: cards[2]),
                      ],
                    );
                  },
                ),
                const SizedBox(height: 14),
                _RecentActivityCard(
                  actions: _mapList(userActions['recent_actions']),
                  appearances: appearanceItems,
                ),
                const SizedBox(height: 14),
                _DetailedReportSections(
                  dashboard: dashboard,
                  appearances: appearanceItems,
                ),
                const SizedBox(height: 24),
              ],
            ),
          ),
        ],
      ),
    );
  }

  List<_SelectItem> _groupItems() => [
    for (final item in _groups)
      _SelectItem(
        id: item['group_id'] as int,
        label: '${item['name'] ?? 'Группа #${item['group_id']}'}',
        subtitle: 'Камер: ${item['camera_count'] ?? 0}',
      ),
  ];

  List<_SelectItem> _cameraItems() => [
    for (final item in _cameras)
      _SelectItem(
        id: item.cameraId,
        label: item.name,
        subtitle: item.location ?? item.ipAddress ?? 'Локация не указана',
      ),
  ];

  List<_SelectItem> _processorItems() => [
    for (final item in _processors)
      _SelectItem(
        id: item.processorId,
        label: item.name,
        subtitle: item.online ? 'online' : item.status,
      ),
  ];

  List<_SelectItem> _userItems() => [
    for (final item in _users)
      _SelectItem(
        id: item['user_id'] as int,
        label: _userLabel(item),
        subtitle: 'login: ${item['login'] ?? '-'}',
      ),
  ];

  List<_SelectItem> _personItems() => [
    for (final item in _persons)
      _SelectItem(
        id: item['person_id'] as int,
        label: _personLabel(item),
        subtitle: 'Эмбеддингов: ${item['embeddings_count'] ?? 0}',
      ),
  ];
}

class _DetailedReportSections extends StatelessWidget {
  const _DetailedReportSections({
    required this.dashboard,
    required this.appearances,
  });

  final Map<String, dynamic> dashboard;
  final List<Map<String, dynamic>> appearances;

  @override
  Widget build(BuildContext context) {
    final events = _map(dashboard['events']);
    final archive = _map(dashboard['archive']);
    final security = _map(dashboard['security']);
    final userActions = _map(dashboard['user_actions']);
    return Column(
      children: [
        ReportTable(
          title: 'Камеры',
          rows: _mapList(dashboard['cameras']),
          columns: const [
            ModuleColumn('Камера', ['name'], width: 180),
            ModuleColumn('Группа', ['group_name'], width: 150),
            ModuleColumn('Локация', ['location'], width: 150),
            ModuleColumn('Тип', ['connection_kind'], width: 90),
            ModuleColumn('Processor', ['assigned_processor'], width: 150),
            ModuleColumn('Online', ['is_online'], width: 80),
            ModuleColumn('PTZ', ['supports_ptz'], width: 70),
            ModuleColumn('Детекция', ['detection_enabled'], width: 95),
            ModuleColumn('События', ['event_count'], width: 90),
            ModuleColumn('Распознано', ['recognized_count'], width: 105),
            ModuleColumn('Неизв.', ['unknown_count'], width: 80),
            ModuleColumn('Ревью', ['pending_reviews'], width: 80),
            ModuleColumn('Записи', ['recordings_count'], width: 85),
            ModuleColumn('Размер', ['recordings_size_bytes'], width: 110),
            ModuleColumn('Последнее', ['last_event_ts'], width: 145),
          ],
        ),
        const SizedBox(height: 14),
        _ReportTableGrid(
          children: [
            ReportTable(
              title: 'Группы камер',
              rows: _mapList(dashboard['groups']),
              columns: const [
                ModuleColumn('Группа', ['name'], width: 180),
                ModuleColumn('Камер', ['camera_count'], width: 80),
                ModuleColumn('Online', ['online_cameras'], width: 80),
                ModuleColumn('Offline', ['offline_cameras'], width: 80),
                ModuleColumn('События', ['event_count'], width: 90),
                ModuleColumn('Распознано', ['recognized_count'], width: 105),
                ModuleColumn('Ревью', ['pending_reviews'], width: 80),
                ModuleColumn('Записи', ['recordings_count'], width: 85),
                ModuleColumn('Размер', ['recordings_size_bytes'], width: 110),
              ],
            ),
            ReportTable(
              title: 'Processor',
              rows: _mapList(dashboard['processors']),
              columns: const [
                ModuleColumn('Узел', ['name'], width: 180),
                ModuleColumn('Статус', ['status'], width: 100),
                ModuleColumn('Online', ['is_online'], width: 80),
                ModuleColumn('IP', ['ip_address'], width: 130),
                ModuleColumn('Версия', ['version'], width: 120),
                ModuleColumn('Heartbeat', ['last_heartbeat'], width: 145),
                ModuleColumn('Камер', ['assigned_cameras'], width: 90),
                ModuleColumn('События', ['event_count'], width: 90),
                ModuleColumn('Записи', ['recordings_count'], width: 85),
                ModuleColumn('CPU', ['cpu_percent'], width: 80),
                ModuleColumn('RAM', ['ram_percent'], width: 80),
                ModuleColumn('GPU', ['gpu_util_percent'], width: 80),
                ModuleColumn('Uptime', ['uptime_seconds'], width: 85),
              ],
            ),
            ReportTable(
              title: 'Архив по камерам',
              rows: _mapList(archive['by_camera']),
              columns: const [
                ModuleColumn('Камера', [
                  'camera_name',
                  'camera_id',
                ], width: 180),
                ModuleColumn('Файлов', ['file_count'], width: 90),
                ModuleColumn('Видео', ['video_files'], width: 85),
                ModuleColumn('Снимки', ['snapshot_files'], width: 85),
                ModuleColumn('Размер', ['total_bytes'], width: 120),
                ModuleColumn('Последний файл', ['last_file_ts'], width: 150),
              ],
            ),
            ReportTable(
              title: 'Хранилища',
              rows: _mapList(archive['by_storage']),
              columns: const [
                ModuleColumn('Хранилище', [
                  'storage_name',
                  'root_path',
                ], width: 220),
                ModuleColumn('Файлов', ['file_count'], width: 90),
                ModuleColumn('Размер', ['total_bytes'], width: 120),
                ModuleColumn('Видео', ['video_files'], width: 85),
                ModuleColumn('Снимки', ['snapshot_files'], width: 85),
              ],
            ),
            ReportTable(
              title: 'Действия пользователей',
              rows: _mapList(userActions['top_users']),
              columns: const [
                ModuleColumn('Пользователь', [
                  'login',
                  'user_name',
                ], width: 170),
                ModuleColumn('Действий', ['action_count'], width: 90),
                ModuleColumn('Последнее', ['last_action_at'], width: 145),
              ],
            ),
            ReportTable(
              title: 'Последние действия',
              rows: _mapList(userActions['recent_actions']),
              columns: const [
                ModuleColumn('Время', ['created_at', 'event_ts'], width: 145),
                ModuleColumn('Пользователь', [
                  'login',
                  'user_name',
                ], width: 160),
                ModuleColumn('Действие', ['action'], width: 170),
                ModuleColumn('Объект', ['entity', 'target'], width: 150),
              ],
            ),
            ReportTable(
              title: 'Типы событий',
              rows: _mapList(events['events_by_type']),
              columns: const [
                ModuleColumn('Тип', ['event_type', 'type'], width: 160),
                ModuleColumn('Количество', ['count'], width: 110),
              ],
            ),
            ReportTable(
              title: 'Ревьюеры',
              rows: _mapList(events['top_reviewers']),
              columns: const [
                ModuleColumn('Пользователь', [
                  'login',
                  'user_name',
                ], width: 170),
                ModuleColumn('Ревью', ['review_count'], width: 90),
                ModuleColumn('Среднее, сек', ['average_seconds'], width: 120),
              ],
            ),
            ReportTable(
              title: 'Ошибки входа',
              rows: _mapList(security['recent_failures']),
              columns: const [
                ModuleColumn('Время', ['created_at', 'event_ts'], width: 145),
                ModuleColumn('Логин', ['login'], width: 150),
                ModuleColumn('IP', ['ip_address'], width: 130),
                ModuleColumn('Причина', ['reason'], width: 180),
              ],
            ),
          ],
        ),
        const SizedBox(height: 14),
        ReportTable(
          title: 'Появления персон',
          rows: appearances,
          columns: const [
            ModuleColumn('Персона', ['person_label', 'person_id'], width: 180),
            ModuleColumn('Камера', ['camera_name', 'camera_id'], width: 180),
            ModuleColumn('Время', ['event_ts'], width: 150),
            ModuleColumn('Уверенность', ['confidence'], width: 110),
            ModuleColumn('Событие', ['event_id'], width: 90),
          ],
        ),
      ],
    );
  }
}

class _ReportTableGrid extends StatelessWidget {
  const _ReportTableGrid({required this.children});

  static const double _gap = 14;

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 1180 ? 2 : 1;
        final rows = <Widget>[];

        for (var i = 0; i < children.length; i += columns) {
          if (columns == 1) {
            rows.add(children[i]);
          } else {
            rows.add(
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: children[i]),
                  const SizedBox(width: _gap),
                  Expanded(
                    child: i + 1 < children.length
                        ? children[i + 1]
                        : const SizedBox.shrink(),
                  ),
                ],
              ),
            );
          }

          if (i + columns < children.length) {
            rows.add(const SizedBox(height: _gap));
          }
        }

        return Column(children: rows);
      },
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.busy, required this.onRefresh});

  final bool busy;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 600;
        final title = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Отчёты',
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                color: colors.textStrong,
                fontWeight: FontWeight.w900,
                fontSize: compact ? 24 : null,
                height: 1.05,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              'Сводка по пользователям, камерам, Processor, событиям, архиву и безопасности.',
              maxLines: compact ? 3 : 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: colors.muted,
                fontSize: compact ? 13 : 13,
                height: 1.25,
              ),
            ),
          ],
        );
        final refresh = IconButton.filledTonal(
          onPressed: busy ? null : onRefresh,
          icon: busy
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.refresh_rounded),
        );

        if (compact) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [title, const SizedBox(height: 10), refresh],
          );
        }

        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: title),
            refresh,
          ],
        );
      },
    );
  }
}

class _Filters extends StatelessWidget {
  const _Filters({
    required this.busy,
    required this.dateFrom,
    required this.dateTo,
    required this.groups,
    required this.cameras,
    required this.processors,
    required this.users,
    required this.persons,
    required this.groupId,
    required this.cameraId,
    required this.processorId,
    required this.userId,
    required this.personId,
    required this.onPickFrom,
    required this.onPickTo,
    required this.onClearFrom,
    required this.onClearTo,
    required this.onGroupChanged,
    required this.onCameraChanged,
    required this.onProcessorChanged,
    required this.onUserChanged,
    required this.onPersonChanged,
    required this.onApply,
    required this.onClear,
  });

  final bool busy;
  final DateTime? dateFrom;
  final DateTime? dateTo;
  final List<_SelectItem> groups;
  final List<_SelectItem> cameras;
  final List<_SelectItem> processors;
  final List<_SelectItem> users;
  final List<_SelectItem> persons;
  final int? groupId;
  final int? cameraId;
  final int? processorId;
  final int? userId;
  final int? personId;
  final VoidCallback onPickFrom;
  final VoidCallback onPickTo;
  final VoidCallback onClearFrom;
  final VoidCallback onClearTo;
  final ValueChanged<int?> onGroupChanged;
  final ValueChanged<int?> onCameraChanged;
  final ValueChanged<int?> onProcessorChanged;
  final ValueChanged<int?> onUserChanged;
  final ValueChanged<int?> onPersonChanged;
  final VoidCallback onApply;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              _DateTimeButton(
                label: 'Дата/время от',
                value: dateFrom,
                onPick: onPickFrom,
                onClear: onClearFrom,
              ),
              _DateTimeButton(
                label: 'Дата/время до',
                value: dateTo,
                onPick: onPickTo,
                onClear: onClearTo,
              ),
              _SearchableSelect(
                label: 'Группа',
                value: groupId,
                items: groups,
                icon: Icons.account_tree_rounded,
                onChanged: onGroupChanged,
              ),
              _SearchableSelect(
                label: 'Камера',
                value: cameraId,
                items: cameras,
                icon: Icons.videocam_rounded,
                onChanged: onCameraChanged,
              ),
              _SearchableSelect(
                label: 'Processor',
                value: processorId,
                items: processors,
                icon: Icons.memory_rounded,
                onChanged: onProcessorChanged,
              ),
              _SearchableSelect(
                label: 'Пользователь',
                value: userId,
                items: users,
                icon: Icons.manage_accounts_rounded,
                onChanged: onUserChanged,
              ),
              _SearchableSelect(
                label: 'Персона для появлений',
                value: personId,
                items: persons,
                icon: Icons.badge_rounded,
                onChanged: onPersonChanged,
              ),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              ElevatedButton.icon(
                onPressed: busy ? null : onApply,
                icon: const Icon(Icons.filter_alt_rounded, size: 18),
                label: const Text('Применить'),
              ),
              OutlinedButton.icon(
                onPressed: busy ? null : onClear,
                icon: const Icon(Icons.filter_alt_off_rounded, size: 18),
                label: const Text('Сбросить'),
              ),
              Text(
                'Экспорт использует текущие фильтры экрана.',
                style: TextStyle(color: context.colors.muted, fontSize: 12),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _DateTimeButton extends StatelessWidget {
  const _DateTimeButton({
    required this.label,
    required this.value,
    required this.onPick,
    required this.onClear,
  });

  final String label;
  final DateTime? value;
  final VoidCallback onPick;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return SizedBox(
      width: 230,
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onPick,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            color: colors.surfaceMuted,
            border: Border.all(color: colors.border),
          ),
          child: Row(
            children: [
              Icon(Icons.calendar_month_rounded, color: colors.primaryAccent),
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
                      value == null ? 'Не выбрано' : _displayDate(value!),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: colors.textStrong,
                        fontWeight: FontWeight.w800,
                        fontSize: 13,
                      ),
                    ),
                  ],
                ),
              ),
              if (value != null)
                IconButton(
                  tooltip: 'Очистить',
                  onPressed: onClear,
                  icon: const Icon(Icons.close_rounded, size: 18),
                )
              else
                Icon(Icons.expand_more_rounded, color: colors.muted),
            ],
          ),
        ),
      ),
    );
  }
}

class _SearchableSelect extends StatelessWidget {
  const _SearchableSelect({
    required this.label,
    required this.value,
    required this.items,
    required this.icon,
    required this.onChanged,
  });

  final String label;
  final int? value;
  final List<_SelectItem> items;
  final IconData icon;
  final ValueChanged<int?> onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final selected = _itemById(items, value);
    return SizedBox(
      width: 248,
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () => _openPicker(context),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            color: colors.surfaceMuted,
            border: Border.all(color: colors.border),
          ),
          child: Row(
            children: [
              Icon(icon, color: colors.primaryAccent),
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
                      selected?.label ?? 'Все',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: colors.textStrong,
                        fontWeight: FontWeight.w800,
                        fontSize: 13,
                      ),
                    ),
                  ],
                ),
              ),
              Icon(Icons.search_rounded, color: colors.muted),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _openPicker(BuildContext context) async {
    final selected = await showModalBottomSheet<int>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => _SelectSheet(label: label, items: items),
    );
    if (selected == null || selected == _SelectSheet.cancelled) return;
    if (selected == _SelectSheet.all) {
      onChanged(null);
      return;
    }
    onChanged(selected);
  }
}

class _SelectSheet extends StatefulWidget {
  const _SelectSheet({required this.label, required this.items});

  static const int cancelled = -2147483648;
  static const int all = -2147483647;

  final String label;
  final List<_SelectItem> items;

  @override
  State<_SelectSheet> createState() => _SelectSheetState();
}

class _SelectSheetState extends State<_SelectSheet> {
  final _query = TextEditingController();

  @override
  void initState() {
    super.initState();
    _query.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final query = _query.text.trim().toLowerCase();
    final filtered = query.isEmpty
        ? widget.items
        : widget.items
              .where(
                (item) =>
                    item.label.toLowerCase().contains(query) ||
                    item.subtitle.toLowerCase().contains(query) ||
                    '${item.id}'.contains(query),
              )
              .toList();
    return Padding(
      padding: EdgeInsets.only(
        left: 18,
        right: 18,
        bottom: MediaQuery.viewInsetsOf(context).bottom + 18,
      ),
      child: GlassPanel(
        padding: const EdgeInsets.all(16),
        child: SizedBox(
          height: 520,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      widget.label,
                      style: TextStyle(
                        color: colors.textStrong,
                        fontSize: 18,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ),
                  IconButton(
                    onPressed: () =>
                        Navigator.pop(context, _SelectSheet.cancelled),
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _query,
                autofocus: true,
                decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.search_rounded),
                  labelText: 'Поиск',
                ),
              ),
              const SizedBox(height: 12),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(Icons.all_inclusive_rounded, color: colors.muted),
                title: Text(
                  'Все',
                  style: TextStyle(
                    color: colors.textStrong,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                onTap: () => Navigator.pop(context, _SelectSheet.all),
              ),
              const Divider(height: 1),
              Expanded(
                child: filtered.isEmpty
                    ? Center(
                        child: Text(
                          'Ничего не найдено',
                          style: TextStyle(color: colors.muted),
                        ),
                      )
                    : ListView.builder(
                        itemCount: filtered.length,
                        itemExtent: 64,
                        itemBuilder: (context, index) {
                          final item = filtered[index];
                          return ListTile(
                            contentPadding: EdgeInsets.zero,
                            title: Text(
                              item.label,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                color: colors.textStrong,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                            subtitle: item.subtitle.isEmpty
                                ? null
                                : Text(
                                    item.subtitle,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: TextStyle(
                                      color: colors.muted,
                                      fontSize: 12,
                                    ),
                                  ),
                            onTap: () => Navigator.pop(context, item.id),
                          );
                        },
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ExportPanel extends StatelessWidget {
  const _ExportPanel({
    required this.sections,
    required this.busy,
    required this.onExport,
  });

  final List<_ReportSection> sections;
  final bool busy;
  final Future<void> Function(_ReportSection section, String format) onExport;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Экспорт отчётов',
            style: TextStyle(
              color: colors.textStrong,
              fontWeight: FontWeight.w900,
              fontSize: 16,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'PDF, Excel и Word формируются backend-ом по активным фильтрам.',
            style: TextStyle(color: colors.muted, fontSize: 12),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              for (final section in sections)
                _ExportChip(section: section, busy: busy, onExport: onExport),
            ],
          ),
        ],
      ),
    );
  }
}

class _ExportChip extends StatelessWidget {
  const _ExportChip({
    required this.section,
    required this.busy,
    required this.onExport,
  });

  final _ReportSection section;
  final bool busy;
  final Future<void> Function(_ReportSection section, String format) onExport;

  @override
  Widget build(BuildContext context) {
    return PopupMenuButton<String>(
      enabled: !busy,
      tooltip: 'Экспорт',
      onSelected: (format) => onExport(section, format),
      itemBuilder: (context) => const [
        PopupMenuItem(value: 'pdf', child: Text('PDF')),
        PopupMenuItem(value: 'xlsx', child: Text('Excel')),
        PopupMenuItem(value: 'docx', child: Text('Word')),
      ],
      child: ActionChip(
        avatar: Icon(section.icon, size: 18),
        label: Text(section.title),
        onPressed: null,
      ),
    );
  }
}

class _SimpleListCard extends StatelessWidget {
  const _SimpleListCard({
    required this.title,
    required this.items,
    required this.columns,
  });

  final String title;
  final List<Map<String, dynamic>> items;
  final List<String> columns;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: TextStyle(
              color: colors.textStrong,
              fontWeight: FontWeight.w900,
              fontSize: 16,
            ),
          ),
          const SizedBox(height: 10),
          if (items.isEmpty)
            Text('Нет данных', style: TextStyle(color: colors.muted))
          else
            for (final item in items.take(8))
              Container(
                margin: const EdgeInsets.only(bottom: 8),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(14),
                  color: colors.surfaceMuted,
                  border: Border.all(color: colors.border),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${item[columns.first] ?? '-'}',
                      style: TextStyle(
                        color: colors.textStrong,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Wrap(
                      spacing: 8,
                      runSpacing: 4,
                      children: [
                        for (final column in columns.skip(1))
                          Text(
                            '$column: ${item[column] ?? '-'}',
                            style: TextStyle(color: colors.muted, fontSize: 12),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
        ],
      ),
    );
  }
}

class _RecentActivityCard extends StatelessWidget {
  const _RecentActivityCard({required this.actions, required this.appearances});

  final List<Map<String, dynamic>> actions;
  final List<Map<String, dynamic>> appearances;

  @override
  Widget build(BuildContext context) {
    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final narrow = constraints.maxWidth < 900;
          final children = [
            _ActivityColumn(
              title: 'Последние действия',
              items: actions,
              primaryKey: 'action',
              secondaryKeys: const ['user_label', 'occurred_at', 'source_ip'],
            ),
            _ActivityColumn(
              title: 'Появления персон',
              items: appearances,
              primaryKey: 'person_label',
              secondaryKeys: const ['camera_name', 'event_ts', 'confidence'],
            ),
          ];
          if (narrow) {
            return Column(
              children: [children[0], const SizedBox(height: 14), children[1]],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: children[0]),
              const SizedBox(width: 14),
              Expanded(child: children[1]),
            ],
          );
        },
      ),
    );
  }
}

class _ActivityColumn extends StatelessWidget {
  const _ActivityColumn({
    required this.title,
    required this.items,
    required this.primaryKey,
    required this.secondaryKeys,
  });

  final String title;
  final List<Map<String, dynamic>> items;
  final String primaryKey;
  final List<String> secondaryKeys;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: TextStyle(
            color: colors.textStrong,
            fontWeight: FontWeight.w900,
            fontSize: 16,
          ),
        ),
        const SizedBox(height: 10),
        if (items.isEmpty)
          Text('Нет данных', style: TextStyle(color: colors.muted))
        else
          ListView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: items.length > 10 ? 10 : items.length,
            itemBuilder: (context, index) {
              final item = items[index];
              return ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(
                  '${item[primaryKey] ?? '-'}',
                  style: TextStyle(color: colors.textStrong),
                ),
                subtitle: Text(
                  secondaryKeys
                      .map((key) => item[key])
                      .where((value) => value != null)
                      .join(' • '),
                  style: TextStyle(color: colors.muted, fontSize: 12),
                ),
              );
            },
          ),
      ],
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      width: 180,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: TextStyle(color: colors.muted, fontSize: 12)),
          const SizedBox(height: 4),
          Text(
            value,
            style: TextStyle(
              color: colors.textStrong,
              fontSize: 24,
              fontWeight: FontWeight.w900,
            ),
          ),
        ],
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

class _ReportSection {
  const _ReportSection(this.id, this.title, this.icon);

  final String id;
  final String title;
  final IconData icon;
}

class _SelectItem {
  const _SelectItem({
    required this.id,
    required this.label,
    this.subtitle = '',
  });

  final int id;
  final String label;
  final String subtitle;
}

_SelectItem? _itemById(List<_SelectItem> items, int? id) {
  if (id == null) return null;
  for (final item in items) {
    if (item.id == id) return item;
  }
  return null;
}

Map<String, dynamic> _map(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return value.map((key, value) => MapEntry('$key', value));
  return const {};
}

List<Map<String, dynamic>> _mapList(Object? value) {
  if (value is List) {
    return value
        .whereType<Map>()
        .map((item) => item.map((key, value) => MapEntry('$key', value)))
        .toList();
  }
  return const [];
}

String? _iso(DateTime? value) => value?.toIso8601String();

String _displayDate(DateTime value) {
  return DateFormat('dd.MM.yyyy HH:mm').format(value.toLocal());
}

String _personLabel(Map<String, dynamic> person) {
  final parts =
      [person['last_name'], person['first_name'], person['middle_name']]
          .where((value) => value != null && '$value'.trim().isNotEmpty)
          .map((value) => '$value');
  final label = parts.join(' ').trim();
  return label.isEmpty ? 'Персона #${person['person_id']}' : label;
}

String _userLabel(Map<String, dynamic> user) {
  final parts = [user['last_name'], user['first_name'], user['middle_name']]
      .where((value) => value != null && '$value'.trim().isNotEmpty)
      .map((value) => '$value');
  final label = parts.join(' ').trim();
  return label.isEmpty ? '${user['login'] ?? 'ID ${user['user_id']}'}' : label;
}
