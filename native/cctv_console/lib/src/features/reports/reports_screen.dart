import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:open_filex/open_filex.dart';
import 'package:provider/provider.dart';

import '../../core/models/models.dart';
import '../../core/network/api_client.dart';
import '../../core/refresh/refresh_bus.dart';
import '../../core/theme/app_theme.dart';
import '../../shared/widgets/glass_panel.dart';
import '../../shared/widgets/page_header.dart';
import '../auth/auth_controller.dart';
import '../modules/module_screens.dart'
    show ModuleColumn, ReportSearchScope, ReportTable;

enum _ReportsView { summary, tables, export }

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
  final Set<int> _groupIds = <int>{};
  final Set<int> _cameraIds = <int>{};
  final Set<int> _processorIds = <int>{};
  final Set<int> _userIds = <int>{};
  final Set<int> _personIds = <int>{};

  Map<String, dynamic>? _dashboard;
  Map<String, dynamic>? _appearances;
  Timer? _appearanceSearchDebounce;
  String _appearanceSearch = '';
  int _appearanceTotal = 0;
  bool _appearanceHasMore = false;
  bool _loadingMoreAppearances = false;
  List<Map<String, dynamic>> _groups = const [];
  List<Map<String, dynamic>> _users = const [];
  List<Map<String, dynamic>> _persons = const [];
  List<CameraSummary> _cameras = const [];
  List<ProcessorOut> _processors = const [];
  _ReportsView _view = _ReportsView.summary;

  static const _sections = [
    _ReportSection(
      'user-actions',
      'Действия пользователей',
      Icons.people_alt_rounded,
    ),
    _ReportSection('groups', 'Группы камер', Icons.account_tree_rounded),
    _ReportSection('cameras', 'Камеры', Icons.videocam_rounded),
    _ReportSection('processors', 'Процессор', Icons.memory_rounded),
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
  void dispose() {
    _appearanceSearchDebounce?.cancel();
    super.dispose();
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
        .getJsonWithQuery(
          '/reports/dashboard',
          token: token,
          query: _dashboardQuery(),
        )
        .then(_map);
    final appearances = await _fetchAppearancesPage(api, token, offset: 0);
    if (!mounted) return;
    setState(() {
      _dashboard = dashboard;
      _appearances = appearances;
      _syncAppearancePageState(appearances);
    });
  }

  Future<Map<String, dynamic>> _fetchAppearancesPage(
    ApiClient api,
    String token, {
    required int offset,
  }) {
    return api
        .getJsonWithQuery(
          '/reports/appearances',
          token: token,
          query: _appearanceQuery(offset: offset),
        )
        .then(_map);
  }

  void _syncAppearancePageState(Map<String, dynamic> page) {
    _appearanceTotal = (page['total'] as num?)?.toInt() ?? 0;
    _appearanceHasMore = page['has_more'] == true;
  }

  Future<void> _loadMoreAppearances() async {
    if (_loadingMoreAppearances || !_appearanceHasMore) return;
    setState(() => _loadingMoreAppearances = true);
    try {
      final (api, token) = _deps();
      final current = _mapList(_appearances?['items']);
      final page = await _fetchAppearancesPage(
        api,
        token,
        offset: current.length,
      );
      final nextItems = _mapList(page['items']);
      if (!mounted) return;
      setState(() {
        _appearances = {
          ...page,
          'items': [...current, ...nextItems],
        };
        _syncAppearancePageState(page);
      });
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loadingMoreAppearances = false);
    }
  }

  void _onReportSearchChanged(String value) {
    _appearanceSearch = value.trim();
    _appearanceSearchDebounce?.cancel();
    _appearanceSearchDebounce = Timer(
      const Duration(milliseconds: 320),
      _reloadAppearancesForSearch,
    );
  }

  Future<void> _reloadAppearancesForSearch() async {
    if (!mounted) return;
    try {
      final (api, token) = _deps();
      final page = await _fetchAppearancesPage(api, token, offset: 0);
      if (!mounted) return;
      setState(() {
        _appearances = page;
        _syncAppearancePageState(page);
      });
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    }
  }

  Future<void> _export(_ReportSection section, String format) async {
    await _run(() async {
      final (api, token) = _deps();
      final file = section.id == 'appearances'
          ? await api.downloadAppearanceReport(
              token,
              format: format,
              personIds: _personIds,
              dateFrom: _iso(_dateFrom),
              dateTo: _iso(_dateTo),
            )
          : await api.downloadReportSection(
              token,
              section: section.id,
              format: format,
              dateFrom: _iso(_dateFrom),
              dateTo: _iso(_dateTo),
              groupIds: _groupIds,
              cameraIds: _cameraIds,
              processorIds: _processorIds,
              userIds: _userIds,
              personIds: _personIds,
            );
      await OpenFilex.open(file.path);
      _toast('Отчёт сохранён: ${file.path}');
    });
  }

  Future<void> _pickDateRange() async {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final firstDate = DateTime(2020);
    var initialStart = _dateFrom == null
        ? today.subtract(const Duration(days: 7))
        : DateTime(_dateFrom!.year, _dateFrom!.month, _dateFrom!.day);
    if (initialStart.isBefore(firstDate)) initialStart = firstDate;
    if (initialStart.isAfter(today)) initialStart = today;
    var initialEnd = _dateTo == null
        ? today
        : DateTime(_dateTo!.year, _dateTo!.month, _dateTo!.day);
    if (initialEnd.isBefore(initialStart)) initialEnd = initialStart;
    if (initialEnd.isAfter(today)) initialEnd = today;

    final range = await showDateRangePicker(
      context: context,
      firstDate: firstDate,
      lastDate: today,
      initialDateRange: DateTimeRange(start: initialStart, end: initialEnd),
      currentDate: today,
      helpText: 'Выберите период',
      cancelText: 'Отмена',
      confirmText: 'Готово',
      saveText: 'Применить',
      fieldStartHintText: 'Начало',
      fieldEndHintText: 'Конец',
      fieldStartLabelText: 'Начало периода',
      fieldEndLabelText: 'Конец периода',
    );
    if (range == null || !mounted) return;

    final start = DateTime(
      range.start.year,
      range.start.month,
      range.start.day,
    );
    final endOfDay = DateTime(
      range.end.year,
      range.end.month,
      range.end.day,
      23,
      59,
      59,
      999,
    );
    setState(() {
      _dateFrom = start;
      _dateTo = endOfDay.isAfter(now) ? now : endOfDay;
    });
  }

  void _clearFilters() {
    setState(() {
      _dateFrom = null;
      _dateTo = null;
      _groupIds.clear();
      _cameraIds.clear();
      _processorIds.clear();
      _userIds.clear();
      _personIds.clear();
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

  List<MapEntry<String, String?>> _dashboardQuery() => [
    MapEntry('date_from', _iso(_dateFrom)),
    MapEntry('date_to', _iso(_dateTo)),
    for (final id in _groupIds) MapEntry('group_ids', '$id'),
    for (final id in _cameraIds) MapEntry('camera_ids', '$id'),
    for (final id in _processorIds) MapEntry('processor_ids', '$id'),
    for (final id in _userIds) MapEntry('user_ids', '$id'),
    for (final id in _personIds) MapEntry('person_ids', '$id'),
  ];

  List<MapEntry<String, String?>> _appearanceQuery({required int offset}) => [
    MapEntry('date_from', _iso(_dateFrom)),
    MapEntry('date_to', _iso(_dateTo)),
    for (final id in _personIds) MapEntry('person_ids', '$id'),
    if (_appearanceSearch.isNotEmpty) MapEntry('q', _appearanceSearch),
    const MapEntry('limit', '200'),
    MapEntry('offset', '$offset'),
  ];

  void _normalizeSelectedIds() {
    final groupIds = _groups.map((item) => item['group_id']).whereType<int>();
    final cameraIds = _cameras.map((item) => item.cameraId);
    final processorIds = _processors.map((item) => item.processorId);
    final userIds = _users.map((item) => item['user_id']).whereType<int>();
    final personIds = _persons.map((item) => item['person_id']).whereType<int>();
    _groupIds.removeWhere((id) => !groupIds.contains(id));
    _cameraIds.removeWhere((id) => !cameraIds.contains(id));
    _processorIds.removeWhere((id) => !processorIds.contains(id));
    _userIds.removeWhere((id) => !userIds.contains(id));
    _personIds.removeWhere((id) => !personIds.contains(id));
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
                  groupIds: _groupIds,
                  cameraIds: _cameraIds,
                  processorIds: _processorIds,
                  userIds: _userIds,
                  personIds: _personIds,
                  onPickPeriod: _pickDateRange,
                  onClearPeriod: () => setState(() {
                    _dateFrom = null;
                    _dateTo = null;
                  }),
                  onGroupsChanged: (value) => setState(() {
                    _groupIds
                      ..clear()
                      ..addAll(value);
                  }),
                  onCamerasChanged: (value) => setState(() {
                    _cameraIds
                      ..clear()
                      ..addAll(value);
                  }),
                  onProcessorsChanged: (value) => setState(() {
                    _processorIds
                      ..clear()
                      ..addAll(value);
                  }),
                  onUsersChanged: (value) => setState(() {
                    _userIds
                      ..clear()
                      ..addAll(value);
                  }),
                  onPersonsChanged: (value) => setState(() {
                    _personIds
                      ..clear()
                      ..addAll(value);
                  }),
                  onApply: _applyFilters,
                  onClear: _clearFilters,
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  _InlineError(message: _error!),
                ],
                const SizedBox(height: 14),
                _ReportsModeTabs(
                  value: _view,
                  onChanged: (value) => setState(() => _view = value),
                ),
                const SizedBox(height: 14),
                if (_view == _ReportsView.summary) ...[
                  Wrap(
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      _Metric(
                        label: 'События',
                        value: '${events['total_events'] ?? 0}',
                      ),
                      _Metric(
                        label: 'Ревью',
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
                          title: 'Процессор',
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
                ] else if (_view == _ReportsView.tables)
                  _DetailedReportSections(
                    dashboard: dashboard,
                    appearances: appearanceItems,
                    appearanceTotal: _appearanceTotal,
                    appearanceHasMore: _appearanceHasMore,
                    loadingMoreAppearances: _loadingMoreAppearances,
                    onAppearanceSearchChanged: _onReportSearchChanged,
                    onLoadMoreAppearances: _loadMoreAppearances,
                  )
                else
                  _ExportPanel(
                    sections: _sections,
                    busy: _busy,
                    onExport: _export,
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
        subtitle: item.online ? 'онлайн' : item.status,
      ),
  ];

  List<_SelectItem> _userItems() => [
    for (final item in _users)
      _SelectItem(
        id: item['user_id'] as int,
        label: _userLabel(item),
        subtitle: 'Логин: ${item['login'] ?? '-'}',
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

class _ReportsModeTabs extends StatelessWidget {
  const _ReportsModeTabs({required this.value, required this.onChanged});

  final _ReportsView value;
  final ValueChanged<_ReportsView> onChanged;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 480;
        return SizedBox(
          width: double.infinity,
          child: SegmentedButton<_ReportsView>(
            showSelectedIcon: false,
            segments: [
              ButtonSegment(
                value: _ReportsView.summary,
                icon: compact
                    ? null
                    : const Icon(Icons.dashboard_customize_rounded, size: 18),
                label: const Text('Сводка'),
              ),
              ButtonSegment(
                value: _ReportsView.tables,
                icon: compact
                    ? null
                    : const Icon(Icons.table_rows_rounded, size: 18),
                label: Text(compact ? 'Данные' : 'Таблицы'),
              ),
              ButtonSegment(
                value: _ReportsView.export,
                icon: compact
                    ? null
                    : const Icon(Icons.file_download_rounded, size: 18),
                label: const Text('Экспорт'),
              ),
            ],
            selected: {value},
            onSelectionChanged: (selected) => onChanged(selected.first),
          ),
        );
      },
    );
  }
}

class _DetailedReportSections extends StatefulWidget {
  const _DetailedReportSections({
    required this.dashboard,
    required this.appearances,
    required this.appearanceTotal,
    required this.appearanceHasMore,
    required this.loadingMoreAppearances,
    required this.onAppearanceSearchChanged,
    required this.onLoadMoreAppearances,
  });

  final Map<String, dynamic> dashboard;
  final List<Map<String, dynamic>> appearances;
  final int appearanceTotal;
  final bool appearanceHasMore;
  final bool loadingMoreAppearances;
  final ValueChanged<String> onAppearanceSearchChanged;
  final VoidCallback onLoadMoreAppearances;

  @override
  State<_DetailedReportSections> createState() =>
      _DetailedReportSectionsState();
}

class _DetailedReportSectionsState extends State<_DetailedReportSections> {
  final _searchController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _searchController.addListener(_onSearchChanged);
  }

  void _onSearchChanged() {
    setState(() {});
    widget.onAppearanceSearchChanged(_searchController.text);
  }

  @override
  void dispose() {
    _searchController
      ..removeListener(_onSearchChanged)
      ..dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final events = _map(widget.dashboard['events']);
    final archive = _map(widget.dashboard['archive']);
    final security = _map(widget.dashboard['security']);
    final userActions = _map(widget.dashboard['user_actions']);
    return ReportSearchScope(
      query: _searchController.text,
      child: Column(
        children: [
          TextField(
            controller: _searchController,
            decoration: InputDecoration(
              labelText: 'Поиск по всем таблицам',
              hintText: 'Название, идентификатор, статус или значение',
              prefixIcon: const Icon(Icons.search_rounded),
              suffixIcon: _searchController.text.isEmpty
                  ? null
                  : IconButton(
                      tooltip: 'Очистить',
                      onPressed: _searchController.clear,
                      icon: const Icon(Icons.close_rounded),
                    ),
            ),
          ),
          const SizedBox(height: 14),
        ReportTable(
          title: 'Камеры',
          rows: _mapList(widget.dashboard['cameras']),
          columns: const [
            ModuleColumn('Камера', ['name'], width: 180),
            ModuleColumn('Группа', ['group_name'], width: 150),
            ModuleColumn('Локация', ['location'], width: 150),
            ModuleColumn('Тип', ['connection_kind'], width: 90),
            ModuleColumn('Процессор', ['assigned_processor'], width: 150),
            ModuleColumn('Онлайн', ['is_online'], width: 80),
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
              rows: _mapList(widget.dashboard['groups']),
              columns: const [
                ModuleColumn('Группа', ['name'], width: 180),
                ModuleColumn('Камер', ['camera_count'], width: 80),
                ModuleColumn('Онлайн', ['online_cameras'], width: 80),
                ModuleColumn('Офлайн', ['offline_cameras'], width: 80),
                ModuleColumn('События', ['event_count'], width: 90),
                ModuleColumn('Распознано', ['recognized_count'], width: 105),
                ModuleColumn('Ревью', ['pending_reviews'], width: 80),
                ModuleColumn('Записи', ['recordings_count'], width: 85),
                ModuleColumn('Размер', ['recordings_size_bytes'], width: 110),
              ],
            ),
            ReportTable(
              title: 'Процессор',
              rows: _mapList(widget.dashboard['processors']),
              columns: const [
                ModuleColumn('Узел', ['name'], width: 180),
                ModuleColumn('Статус', ['status'], width: 100),
                ModuleColumn('Онлайн', ['is_online'], width: 80),
                ModuleColumn('IP', ['ip_address'], width: 130),
                ModuleColumn('Версия', ['version'], width: 120),
                ModuleColumn('Heartbeat', ['last_heartbeat'], width: 145),
                ModuleColumn('Камер', ['assigned_cameras'], width: 90),
                ModuleColumn('События', ['event_count'], width: 90),
                ModuleColumn('Записи', ['recordings_count'], width: 85),
                ModuleColumn('CPU', ['cpu_percent'], width: 80),
                ModuleColumn('RAM', ['ram_percent'], width: 80),
                ModuleColumn('GPU', ['gpu_util_percent'], width: 80),
                ModuleColumn('Время', ['uptime_seconds'], width: 85),
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
          rows: widget.appearances,
          columns: const [
            ModuleColumn('Персона', ['person_label', 'person_id'], width: 180),
            ModuleColumn('Камера', ['camera_name', 'camera_id'], width: 180),
            ModuleColumn('Время', ['event_ts'], width: 150),
            ModuleColumn('Уверенность', ['confidence'], width: 110),
            ModuleColumn('Событие', ['event_id'], width: 90),
          ],
        ),
        if (widget.appearanceHasMore) ...[
          const SizedBox(height: 10),
          Align(
            alignment: Alignment.center,
            child: FilledButton.tonalIcon(
              onPressed: widget.loadingMoreAppearances
                  ? null
                  : widget.onLoadMoreAppearances,
              icon: widget.loadingMoreAppearances
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.expand_more_rounded),
              label: Text(
                'Показать ещё '
                '(${widget.appearances.length} из ${widget.appearanceTotal})',
              ),
            ),
          ),
        ],
        ],
      ),
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
        final columns = constraints.maxWidth >= 1680 ? 2 : 1;
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
    return PageHeader(
      title: 'Отчёты',
      icon: Icons.analytics_rounded,
      trailing: PageActions(
        children: [
          IconButton.filledTonal(
            onPressed: busy ? null : onRefresh,
            icon: busy
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
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
    required this.groupIds,
    required this.cameraIds,
    required this.processorIds,
    required this.userIds,
    required this.personIds,
    required this.onPickPeriod,
    required this.onClearPeriod,
    required this.onGroupsChanged,
    required this.onCamerasChanged,
    required this.onProcessorsChanged,
    required this.onUsersChanged,
    required this.onPersonsChanged,
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
  final Set<int> groupIds;
  final Set<int> cameraIds;
  final Set<int> processorIds;
  final Set<int> userIds;
  final Set<int> personIds;
  final VoidCallback onPickPeriod;
  final VoidCallback onClearPeriod;
  final ValueChanged<Set<int>> onGroupsChanged;
  final ValueChanged<Set<int>> onCamerasChanged;
  final ValueChanged<Set<int>> onProcessorsChanged;
  final ValueChanged<Set<int>> onUsersChanged;
  final ValueChanged<Set<int>> onPersonsChanged;
  final VoidCallback onApply;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        const spacing = 10.0;
        final maxWidth = constraints.maxWidth;
        final contentWidth = (maxWidth - 32).clamp(0.0, maxWidth).toDouble();
        final columns = contentWidth < 460 ? 1 : (contentWidth < 860 ? 2 : 3);
        final rawFieldWidth =
            (contentWidth - spacing * (columns - 1)) / columns;
        final fieldWidth = columns == 1
            ? contentWidth
            : rawFieldWidth.clamp(148.0, 248.0).toDouble();
        final periodWidth = columns == 1
            ? contentWidth
            : (fieldWidth * 2 + spacing).clamp(fieldWidth, contentWidth);
        final actionWidth = contentWidth < 420 ? fieldWidth : null;
        final compactLabels = contentWidth < 460;
        final fields = SizedBox(
          width: double.infinity,
          child: Wrap(
            spacing: spacing,
            runSpacing: spacing,
            children: [
              _DateRangeButton(
                width: periodWidth.toDouble(),
                compact: compactLabels,
                dateFrom: dateFrom,
                dateTo: dateTo,
                onPick: onPickPeriod,
                onClear: onClearPeriod,
              ),
              _SearchableMultiSelect(
                width: fieldWidth,
                label: 'Группа',
                values: groupIds,
                items: groups,
                icon: Icons.account_tree_rounded,
                onChanged: onGroupsChanged,
              ),
              _SearchableMultiSelect(
                width: fieldWidth,
                label: 'Камера',
                values: cameraIds,
                items: cameras,
                icon: Icons.videocam_rounded,
                onChanged: onCamerasChanged,
              ),
              _SearchableMultiSelect(
                width: fieldWidth,
                label: compactLabels ? 'Узел' : 'Процессор',
                values: processorIds,
                items: processors,
                icon: Icons.memory_rounded,
                onChanged: onProcessorsChanged,
              ),
              _SearchableMultiSelect(
                width: fieldWidth,
                label: compactLabels ? 'Польз.' : 'Пользователь',
                values: userIds,
                items: users,
                icon: Icons.manage_accounts_rounded,
                onChanged: onUsersChanged,
              ),
              _SearchableMultiSelect(
                width: fieldWidth,
                label: 'Персона',
                values: personIds,
                items: persons,
                icon: Icons.badge_rounded,
                onChanged: onPersonsChanged,
              ),
            ],
          ),
        );
        final actions = SizedBox(
          width: double.infinity,
          child: Wrap(
            spacing: spacing,
            runSpacing: spacing,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              SizedBox(
                width: actionWidth,
                child: ElevatedButton.icon(
                  onPressed: busy ? null : onApply,
                  icon: const Icon(Icons.filter_alt_rounded, size: 18),
                  label: const Text('Применить'),
                ),
              ),
              SizedBox(
                width: actionWidth,
                child: OutlinedButton.icon(
                  onPressed: busy ? null : onClear,
                  icon: const Icon(
                    Icons.filter_alt_off_rounded,
                    size: 18,
                  ),
                  label: const Text('Сбросить'),
                ),
              ),
            ],
          ),
        );
        final content = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            fields,
            const SizedBox(height: 14),
            actions,
          ],
        );

        if (compactLabels) {
          return SizedBox(
            width: double.infinity,
            child: GlassPanel(
              padding: EdgeInsets.zero,
              child: ExpansionTile(
                tilePadding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 4,
                ),
                childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                iconColor: context.colors.primaryAccent,
                collapsedIconColor: context.colors.muted,
                title: const Text(
                  'Фильтры',
                  style: TextStyle(fontWeight: FontWeight.w900),
                ),
                subtitle: Text(
                  _filtersSummary(
                    dateFrom: dateFrom,
                    dateTo: dateTo,
                    groupIds: groupIds,
                    cameraIds: cameraIds,
                    processorIds: processorIds,
                    userIds: userIds,
                    personIds: personIds,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                children: [content],
              ),
            ),
          );
        }

        return SizedBox(
          width: double.infinity,
          child: GlassPanel(
            padding: const EdgeInsets.all(16),
            child: content,
          ),
        );
      },
    );
  }
}

String _filtersSummary({
  required DateTime? dateFrom,
  required DateTime? dateTo,
  required Set<int> groupIds,
  required Set<int> cameraIds,
  required Set<int> processorIds,
  required Set<int> userIds,
  required Set<int> personIds,
}) {
  final active = <bool>[
    dateFrom != null || dateTo != null,
    groupIds.isNotEmpty,
    cameraIds.isNotEmpty,
    processorIds.isNotEmpty,
    userIds.isNotEmpty,
    personIds.isNotEmpty,
  ].where((value) => value).length;
  if (active == 0) {
    return 'Без ограничений';
  }
  return '$active активн. · ${_displayPeriod(dateFrom, dateTo)}';
}

class _DateRangeButton extends StatelessWidget {
  const _DateRangeButton({
    required this.width,
    required this.compact,
    required this.dateFrom,
    required this.dateTo,
    required this.onPick,
    required this.onClear,
  });

  final double width;
  final bool compact;
  final DateTime? dateFrom;
  final DateTime? dateTo;
  final VoidCallback onPick;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final hasValue = dateFrom != null || dateTo != null;
    return SizedBox(
      width: width,
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
                      compact ? 'Период' : 'Период отчёта',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: colors.muted, fontSize: 12),
                    ),
                    Text(
                      _displayPeriod(dateFrom, dateTo),
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
              if (hasValue)
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

class _SearchableMultiSelect extends StatelessWidget {
  const _SearchableMultiSelect({
    required this.width,
    required this.label,
    required this.values,
    required this.items,
    required this.icon,
    required this.onChanged,
  });

  final double width;
  final String label;
  final Set<int> values;
  final List<_SelectItem> items;
  final IconData icon;
  final ValueChanged<Set<int>> onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final selected = _selectedSummary(items, values);
    return SizedBox(
      width: width,
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
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: colors.muted, fontSize: 12),
                    ),
                    Text(
                      selected,
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
    final selected = await showModalBottomSheet<Set<int>>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) =>
          _MultiSelectSheet(label: label, items: items, initialValues: values),
    );
    if (selected == null) return;
    onChanged(selected);
  }
}

class _MultiSelectSheet extends StatefulWidget {
  const _MultiSelectSheet({
    required this.label,
    required this.items,
    required this.initialValues,
  });

  final String label;
  final List<_SelectItem> items;
  final Set<int> initialValues;

  @override
  State<_MultiSelectSheet> createState() => _MultiSelectSheetState();
}

class _MultiSelectSheetState extends State<_MultiSelectSheet> {
  final _query = TextEditingController();
  late final Set<int> _selected = {...widget.initialValues};

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
                    onPressed: () => Navigator.pop(context),
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
                onTap: () => Navigator.pop(context, <int>{}),
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
                            leading: Checkbox(
                              value: _selected.contains(item.id),
                              onChanged: (checked) => setState(() {
                                if (checked == true) {
                                  _selected.add(item.id);
                                } else {
                                  _selected.remove(item.id);
                                }
                              }),
                            ),
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
                            onTap: () => setState(() {
                              if (_selected.contains(item.id)) {
                                _selected.remove(item.id);
                              } else {
                                _selected.add(item.id);
                              }
                            }),
                          );
                        },
                      ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () => setState(_selected.clear),
                      child: const Text('Очистить'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: ElevatedButton(
                      onPressed: () => Navigator.pop(context, {..._selected}),
                      child: const Text('Готово'),
                    ),
                  ),
                ],
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

String _selectedSummary(List<_SelectItem> items, Set<int> ids) {
  if (ids.isEmpty) return 'Все';
  final labels = <String>[];
  for (final item in items) {
    if (ids.contains(item.id)) labels.add(item.label);
    if (labels.length == 2) break;
  }
  if (ids.length == 1 && labels.isNotEmpty) return labels.first;
  final prefix = labels.isEmpty ? '' : '${labels.join(', ')} · ';
  return '$prefix${ids.length} выбрано';
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

String _displayPeriod(DateTime? from, DateTime? to) {
  final dateFormat = DateFormat('dd.MM.yyyy');
  if (from == null && to == null) return 'Не выбран';
  if (from == null) return 'До ${dateFormat.format(to!.toLocal())}';
  if (to == null) return 'От ${dateFormat.format(from.toLocal())}';
  return '${dateFormat.format(from.toLocal())} - '
      '${dateFormat.format(to.toLocal())}';
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
