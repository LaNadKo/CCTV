import 'dart:async';

import 'package:flutter/material.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';
import 'package:provider/provider.dart';

import '../../core/models/models.dart';
import '../../core/network/api_client.dart';
import '../../core/refresh/refresh_bus.dart';
import '../../core/theme/app_theme.dart';
import '../../shared/input/human_name.dart';
import '../../shared/widgets/glass_panel.dart';
import '../auth/auth_controller.dart';
import '../modules/module_screens.dart'
    show
        EmptyPanel,
        ErrorPanel,
        ModuleHeader,
        RefreshButton,
        cleanBody,
        confirmAction,
        formatCell,
        roleName,
        showErrorSnack,
        showResultDialog,
        textFormDialog,
        DialogField;

typedef RowMap = Map<String, dynamic>;

class ReviewsManagementScreen extends StatefulWidget {
  const ReviewsManagementScreen({super.key});

  @override
  State<ReviewsManagementScreen> createState() =>
      _ReviewsManagementScreenState();
}

class _ReviewsManagementScreenState extends State<ReviewsManagementScreen>
    with RouteRefreshState<ReviewsManagementScreen> {
  final _search = TextEditingController();
  bool _loading = false;
  String? _error;
  List<RowMap> _events = const [];
  List<RowMap> _persons = const [];
  final Map<int, int?> _personByEvent = {};

  @override
  void initState() {
    super.initState();
    _search.addListener(() => setState(() {}));
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  String get refreshRoute => '/reviews';

  @override
  Future<void> onRefreshRequested() {
    if (_loading) return Future<void>.value();
    return _load();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final auth = context.read<AuthController>();
    final token = auth.accessToken;
    final api = context.read<ApiClient>();
    if (token == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      if ((auth.mediaToken ?? '').isEmpty) {
        await auth.refreshMediaToken();
      }
      final results = await Future.wait([
        api.getJsonList('/detections/pending', token: token),
        api.getJsonList('/persons', token: token),
      ]);
      if (!mounted) return;
      final events = results[0];
      final persons = results[1];
      _personByEvent.removeWhere(
        (eventId, _) => !events.any((event) => event['event_id'] == eventId),
      );
      for (final event in events) {
        final eventId = _asInt(event['event_id']);
        if (eventId != null && !_personByEvent.containsKey(eventId)) {
          _personByEvent[eventId] = _asInt(event['person_id']);
        }
      }
      setState(() {
        _events = events;
        _persons = persons;
      });
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  List<RowMap> get _filtered {
    final query = _search.text.trim().toLowerCase();
    if (query.isEmpty) return _events;
    return _events
        .where((event) {
          return event.values.any(
            (value) => '$value'.toLowerCase().contains(query),
          );
        })
        .toList(growable: false);
  }

  Future<void> _review(RowMap event, String status) async {
    final token = context.read<AuthController>().accessToken;
    if (token == null) return;
    final eventId = _asInt(event['event_id']);
    if (eventId == null) return;
    try {
      await context.read<ApiClient>().reviewEvent(
        token,
        eventId,
        status,
        personId: _personByEvent[eventId],
      );
      await _load();
      _markReviewsChanged();
    } catch (error) {
      if (mounted) showErrorSnack(context, '$error');
    }
  }

  Future<void> _pickPerson(RowMap event) async {
    final eventId = _asInt(event['event_id']);
    if (eventId == null) return;
    final selected = await _showEntityPicker(
      context,
      title: 'Выбор персоны',
      items: [
        const _PickerItem(id: 0, title: 'Не привязывать персону'),
        for (final person in _persons)
          _PickerItem(
            id: _asInt(person['person_id']) ?? 0,
            title: _personLabel(person),
            subtitle:
                'ID ${person['person_id']} · emb ${person['embeddings_count'] ?? 0}',
          ),
      ],
    );
    if (selected == null) return;
    setState(() => _personByEvent[eventId] = selected == 0 ? null : selected);
  }

  Future<void> _enrollFromSnapshot(RowMap event) async {
    final token = context.read<AuthController>().accessToken;
    final eventId = _asInt(event['event_id']);
    if (token == null || eventId == null) return;
    final name = await _personNameDialog(
      context,
      title: 'Создать персону из snapshot',
    );
    if (name == null) return;
    try {
      final result = await context.read<ApiClient>().enrollPersonFromSnapshot(
        token,
        eventId: eventId,
        firstName: name['first_name'],
        lastName: name['last_name'],
        middleName: name['middle_name'],
      );
      final personId = _asInt(result['person_id']);
      if (personId != null) _personByEvent[eventId] = personId;
      await _load();
      _markReviewsChanged();
    } catch (error) {
      if (mounted) showErrorSnack(context, '$error');
    }
  }

  Future<void> _enrollFromRecording(RowMap event) async {
    final token = context.read<AuthController>().accessToken;
    final eventId = _asInt(event['event_id']);
    final recordingId = _asInt(event['recording_file_id']);
    if (token == null || eventId == null || recordingId == null) return;
    final name = await _personNameDialog(
      context,
      title: 'Создать персону из записи',
    );
    if (name == null) return;
    try {
      final result = await context.read<ApiClient>().enrollPersonFromRecording(
        token,
        recordingId: recordingId,
        firstName: name['first_name'],
        lastName: name['last_name'],
        middleName: name['middle_name'],
      );
      final personId = _asInt(result['person_id']);
      if (personId != null) _personByEvent[eventId] = personId;
      await _load();
      _markReviewsChanged();
    } catch (error) {
      if (mounted) showErrorSnack(context, '$error');
    }
  }

  Future<void> _rejectAll() async {
    final token = context.read<AuthController>().accessToken;
    if (token == null) return;
    final ok = await confirmAction(
      context,
      title: 'Отклонить все события?',
      message: 'Все ожидающие события будут помечены как rejected.',
    );
    if (!ok) return;
    try {
      await context.read<ApiClient>().rejectAllPendingReviews(token);
      await _load();
      _markReviewsChanged();
    } catch (error) {
      if (mounted) showErrorSnack(context, '$error');
    }
  }

  void _markReviewsChanged() {
    if (!mounted) return;
    context.read<RefreshBus>().markStale(const ['/reports', '/persons']);
  }

  @override
  Widget build(BuildContext context) {
    final filtered = _filtered;
    return RefreshIndicator(
      onRefresh: _load,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: Column(
              children: [
                ModuleHeader(
                  title: 'Ревью',
                  subtitle:
                      'Подтверждение неизвестных событий, привязка к персоне и обучение из snapshot/recording.',
                  icon: Icons.fact_check_rounded,
                  trailing: Wrap(
                    spacing: 10,
                    children: [
                      ElevatedButton.icon(
                        onPressed: _events.isEmpty ? null : _rejectAll,
                        icon: const Icon(Icons.clear_all_rounded, size: 18),
                        label: const Text('Отклонить всё'),
                      ),
                      RefreshButton(loading: _loading, onPressed: _load),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _search,
                  decoration: InputDecoration(
                    prefixIcon: const Icon(Icons.search_rounded),
                    labelText: 'Поиск по событиям',
                    suffixIcon: _search.text.isEmpty
                        ? null
                        : IconButton(
                            onPressed: _search.clear,
                            icon: const Icon(Icons.close_rounded),
                          ),
                  ),
                ),
                const SizedBox(height: 14),
                if (_error != null)
                  ErrorPanel(message: _error!, onRetry: _load),
                if (_error != null) const SizedBox(height: 14),
              ],
            ),
          ),
          if (_loading && _events.isEmpty)
            const SliverToBoxAdapter(child: _LoadingPanel())
          else if (filtered.isEmpty)
            const SliverToBoxAdapter(
              child: EmptyPanel(message: 'Очередь ревью пуста.'),
            )
          else
            SliverList.builder(
              itemCount: filtered.length,
              itemBuilder: (context, index) {
                final event = filtered[index];
                final eventId = _asInt(event['event_id']);
                final personId = eventId == null
                    ? null
                    : _personByEvent[eventId];
                final person = _persons
                    .where((p) => p['person_id'] == personId)
                    .firstOrNull;
                return Padding(
                  padding: const EdgeInsets.only(bottom: 14),
                  child: _ReviewCard(
                    event: event,
                    selectedPerson: person,
                    mediaToken: context.watch<AuthController>().mediaToken,
                    onPickPerson: () => _pickPerson(event),
                    onApprove: () => _review(event, 'approved'),
                    onReject: () => _review(event, 'rejected'),
                    onEnrollSnapshot: () => _enrollFromSnapshot(event),
                    onEnrollRecording: () => _enrollFromRecording(event),
                  ),
                );
              },
            ),
          const SliverToBoxAdapter(child: SizedBox(height: 24)),
        ],
      ),
    );
  }
}

class GroupsManagementScreen extends StatefulWidget {
  const GroupsManagementScreen({super.key});

  @override
  State<GroupsManagementScreen> createState() => _GroupsManagementScreenState();
}

class _GroupsManagementScreenState extends State<GroupsManagementScreen>
    with RouteRefreshState<GroupsManagementScreen> {
  bool _loading = false;
  String? _error;
  List<RowMap> _groups = const [];
  List<CameraSummary> _cameras = const [];
  RowMap? _detail;
  int? _selectedId;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  String get refreshRoute => '/groups';

  @override
  Future<void> onRefreshRequested() {
    if (_loading) return Future<void>.value();
    return _load();
  }

  Future<void> _load() async {
    final token = context.read<AuthController>().accessToken;
    if (token == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final api = context.read<ApiClient>();
      final result = await Future.wait([
        api.getJsonList('/groups', token: token),
        api.listCameras(token),
      ]);
      final groups = result[0] as List<RowMap>;
      final cameras = result[1] as List<CameraSummary>;
      final selectedId = _selectedId ?? _asInt(groups.firstOrNull?['group_id']);
      RowMap? detail;
      if (selectedId != null) {
        detail = await api
            .getJson('/groups/$selectedId', token: token)
            .then(_asMap);
      }
      if (!mounted) return;
      setState(() {
        _groups = groups;
        _cameras = cameras;
        _selectedId = selectedId;
        _detail = detail;
      });
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _select(int groupId) async {
    _selectedId = groupId;
    await _load();
  }

  Future<void> _createGroup() async {
    final values = await textFormDialog(
      context,
      title: 'Новая группа',
      fields: const [
        DialogField('name', 'Название', isRequired: true),
        DialogField('description', 'Описание', maxLines: 3),
      ],
    );
    if (values == null) return;
    await _runMutation(() async {
      await context.read<ApiClient>().postJson(
        '/groups',
        token: context.read<AuthController>().accessToken,
        body: cleanBody(values),
      );
    });
  }

  Future<void> _editGroup() async {
    final detail = _detail;
    if (detail == null) return;
    final values = await textFormDialog(
      context,
      title: 'Редактировать группу',
      fields: [
        DialogField(
          'name',
          'Название',
          isRequired: true,
          initialValue: '${detail['name'] ?? ''}',
        ),
        DialogField(
          'description',
          'Описание',
          maxLines: 3,
          initialValue: '${detail['description'] ?? ''}',
        ),
      ],
    );
    if (values == null) return;
    await _runMutation(() async {
      await context.read<ApiClient>().patchJson(
        '/groups/${detail['group_id']}',
        token: context.read<AuthController>().accessToken,
        body: cleanBody(values),
      );
    });
  }

  Future<void> _deleteGroup() async {
    final id = _selectedId;
    if (id == null) return;
    final ok = await confirmAction(
      context,
      title: 'Удалить группу?',
      message: 'Камеры будут отвязаны от группы.',
    );
    if (!ok) return;
    await _runMutation(() async {
      await context.read<ApiClient>().deleteVoid(
        '/groups/$id',
        token: context.read<AuthController>().accessToken,
      );
      _selectedId = null;
    });
  }

  Future<void> _assign(CameraSummary camera) async {
    final id = _selectedId;
    if (id == null) return;
    await _runMutation(() async {
      await context.read<ApiClient>().postVoid(
        '/groups/$id/cameras/${camera.cameraId}',
        token: context.read<AuthController>().accessToken,
      );
    });
  }

  Future<void> _unassign(CameraSummary camera) async {
    final id = _selectedId;
    if (id == null) return;
    await _runMutation(() async {
      await context.read<ApiClient>().deleteVoid(
        '/groups/$id/cameras/${camera.cameraId}',
        token: context.read<AuthController>().accessToken,
      );
    });
  }

  Future<void> _runMutation(Future<void> Function() action) async {
    try {
      await action();
      await _load();
      _markGroupsChanged();
    } catch (error) {
      if (mounted) showErrorSnack(context, '$error');
    }
  }

  void _markGroupsChanged() {
    if (!mounted) return;
    context.read<RefreshBus>().markStale(const [
      '/live',
      '/cameras',
      '/reports',
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final isAdmin = context.watch<AuthController>().user?.isAdmin ?? false;
    final detail = _detail;
    final assignedIds = _asList(
      detail?['cameras'],
    ).map((item) => _asInt(item['camera_id'])).whereType<int>().toSet();
    final assigned = _cameras
        .where((camera) => assignedIds.contains(camera.cameraId))
        .toList();
    final available = _cameras
        .where((camera) => !assignedIds.contains(camera.cameraId))
        .toList();

    return RefreshIndicator(
      onRefresh: _load,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: Column(
              children: [
                ModuleHeader(
                  title: 'Группы',
                  subtitle: isAdmin
                      ? 'Группы видны всем пользователям, редактирование доступно администратору.'
                      : 'Просмотр групп и состава камер.',
                  icon: Icons.account_tree_rounded,
                  trailing: Wrap(
                    spacing: 10,
                    children: [
                      if (isAdmin)
                        ElevatedButton.icon(
                          onPressed: _createGroup,
                          icon: const Icon(Icons.add_rounded, size: 18),
                          label: const Text('Добавить'),
                        ),
                      RefreshButton(loading: _loading, onPressed: _load),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                if (_error != null)
                  ErrorPanel(message: _error!, onRetry: _load),
                if (_error != null) const SizedBox(height: 14),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final narrow = constraints.maxWidth < 920;
                    final left = _GroupList(
                      groups: _groups,
                      selectedId: _selectedId,
                      onSelect: _select,
                    );
                    final right = _GroupDetail(
                      detail: detail,
                      assigned: assigned,
                      available: available,
                      isAdmin: isAdmin,
                      onEdit: _editGroup,
                      onDelete: _deleteGroup,
                      onAssign: _assign,
                      onUnassign: _unassign,
                    );
                    if (narrow) {
                      return Column(
                        children: [left, const SizedBox(height: 14), right],
                      );
                    }
                    return Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(width: 360, child: left),
                        const SizedBox(width: 14),
                        Expanded(child: right),
                      ],
                    );
                  },
                ),
              ],
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: 24)),
        ],
      ),
    );
  }
}

class ProcessorsManagementScreen extends StatefulWidget {
  const ProcessorsManagementScreen({super.key});

  @override
  State<ProcessorsManagementScreen> createState() =>
      _ProcessorsManagementScreenState();
}

class _ProcessorsManagementScreenState extends State<ProcessorsManagementScreen>
    with RouteRefreshState<ProcessorsManagementScreen> {
  bool _loading = false;
  String? _error;
  List<ProcessorOut> _processors = const [];
  List<CameraSummary> _cameras = const [];
  List<RowMap> _commands = const [];
  int? _selectedId;

  static const _commandTypes = [
    'reload_assignments',
    'restart_workers',
    'stop_all_cameras',
    'resume_cameras',
    'refresh_gallery',
    'shutdown',
  ];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  String get refreshRoute => '/processors';

  @override
  Future<void> onRefreshRequested() {
    if (_loading) return Future<void>.value();
    return _load();
  }

  Future<void> _load() async {
    final token = context.read<AuthController>().accessToken;
    if (token == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final api = context.read<ApiClient>();
      final result = await Future.wait([
        api.listProcessors(token),
        api.listCameras(token),
      ]);
      final processors = result[0] as List<ProcessorOut>;
      final cameras = result[1] as List<CameraSummary>;
      final selectedId = _selectedId ?? processors.firstOrNull?.processorId;
      final commands = selectedId == null
          ? <RowMap>[]
          : await api.getJsonList(
              '/processors/$selectedId/commands',
              token: token,
              query: {'limit': '40'},
            );
      if (!mounted) return;
      setState(() {
        _processors = processors;
        _cameras = cameras;
        _selectedId = selectedId;
        _commands = commands;
      });
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _generateCode() async {
    final token = context.read<AuthController>().accessToken;
    if (token == null) return;
    try {
      final result = await context.read<ApiClient>().postJson(
        '/processors/generate-code',
        token: token,
      );
      if (!mounted) return;
      await showResultDialog(
        context,
        title: 'Код подключения Processor',
        value: '${result['code'] ?? ''}',
        note: 'Действует до: ${formatCell(result['expires_at'])}',
      );
    } catch (error) {
      if (mounted) showErrorSnack(context, '$error');
    }
  }

  Future<void> _assignCamera(CameraSummary camera) async {
    final token = context.read<AuthController>().accessToken;
    final processorId = _selectedId;
    if (token == null || processorId == null) return;
    try {
      await context.read<ApiClient>().postVoid(
        '/processors/$processorId/assign',
        token: token,
        body: {
          'camera_ids': [camera.cameraId],
        },
      );
      await _load();
      _markProcessorsChanged();
    } catch (error) {
      if (mounted) showErrorSnack(context, '$error');
    }
  }

  Future<void> _unassignCamera(CameraSummary camera) async {
    final token = context.read<AuthController>().accessToken;
    final processorId = _selectedId;
    if (token == null || processorId == null) return;
    try {
      await context.read<ApiClient>().deleteVoid(
        '/processors/$processorId/assign/${camera.cameraId}',
        token: token,
      );
      await _load();
      _markProcessorsChanged();
    } catch (error) {
      if (mounted) showErrorSnack(context, '$error');
    }
  }

  Future<void> _sendCommand(String commandType) async {
    final token = context.read<AuthController>().accessToken;
    final processorId = _selectedId;
    if (token == null || processorId == null) return;
    final ok = commandType == 'shutdown'
        ? await confirmAction(
            context,
            title: 'Отправить shutdown?',
            message: 'Processor может остановиться до ручного запуска.',
          )
        : true;
    if (!ok) return;
    try {
      await context.read<ApiClient>().postJson(
        '/processors/$processorId/commands',
        token: token,
        body: {'command_type': commandType, 'payload': <String, dynamic>{}},
      );
      await _load();
      _markProcessorsChanged();
    } catch (error) {
      if (mounted) showErrorSnack(context, '$error');
    }
  }

  Future<void> _cancelCommand(RowMap command) async {
    final token = context.read<AuthController>().accessToken;
    final processorId = _selectedId;
    final commandId = _asInt(command['command_id']);
    if (token == null || processorId == null || commandId == null) return;
    try {
      await context.read<ApiClient>().postJson(
        '/processors/$processorId/commands/$commandId/cancel',
        token: token,
      );
      await _load();
      _markProcessorsChanged();
    } catch (error) {
      if (mounted) showErrorSnack(context, '$error');
    }
  }

  Future<void> _deleteProcessor(ProcessorOut processor) async {
    final token = context.read<AuthController>().accessToken;
    if (token == null) return;
    final ok = await confirmAction(
      context,
      title: 'Удалить Processor?',
      message: 'Назначения камер для этого узла будут потеряны.',
    );
    if (!ok) return;
    try {
      await context.read<ApiClient>().deleteVoid(
        '/processors/${processor.processorId}',
        token: token,
      );
      _selectedId = null;
      await _load();
      _markProcessorsChanged();
    } catch (error) {
      if (mounted) showErrorSnack(context, '$error');
    }
  }

  void _markProcessorsChanged() {
    if (!mounted) return;
    context.read<RefreshBus>().markStale(const ['/live', '/reports']);
  }

  @override
  Widget build(BuildContext context) {
    final selected = _processors
        .where((processor) => processor.processorId == _selectedId)
        .firstOrNull;
    final assignedIds =
        selected?.assignedCameras.map((camera) => camera.cameraId).toSet() ??
        <int>{};
    final assigned = _cameras
        .where((camera) => assignedIds.contains(camera.cameraId))
        .toList();
    final available = _cameras
        .where((camera) => !assignedIds.contains(camera.cameraId))
        .toList();
    final online = _processors.where((processor) => processor.online).length;

    return RefreshIndicator(
      onRefresh: _load,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: Column(
              children: [
                ModuleHeader(
                  title: 'Processor',
                  subtitle:
                      'Централизованное управление узлами обработки, назначениями камер и командами.',
                  icon: Icons.memory_rounded,
                  trailing: Wrap(
                    spacing: 10,
                    children: [
                      ElevatedButton.icon(
                        onPressed: _generateCode,
                        icon: const Icon(Icons.key_rounded, size: 18),
                        label: const Text('Код подключения'),
                      ),
                      RefreshButton(loading: _loading, onPressed: _load),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                if (_error != null)
                  ErrorPanel(message: _error!, onRetry: _load),
                if (_error != null) const SizedBox(height: 14),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    _StatTile(label: 'Узлов', value: '${_processors.length}'),
                    _StatTile(label: 'Online', value: '$online'),
                    _StatTile(label: 'Камер', value: '${_cameras.length}'),
                  ],
                ),
                const SizedBox(height: 14),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final narrow = constraints.maxWidth < 980;
                    final left = _ProcessorList(
                      processors: _processors,
                      selectedId: _selectedId,
                      onSelect: (id) {
                        setState(() => _selectedId = id);
                        _load();
                      },
                    );
                    final right = _ProcessorDetail(
                      processor: selected,
                      assigned: assigned,
                      available: available,
                      commands: _commands,
                      commandTypes: _commandTypes,
                      onAssign: _assignCamera,
                      onUnassign: _unassignCamera,
                      onCommand: _sendCommand,
                      onCancelCommand: _cancelCommand,
                      onDelete: selected == null
                          ? null
                          : () => _deleteProcessor(selected),
                    );
                    if (narrow) {
                      return Column(
                        children: [left, const SizedBox(height: 14), right],
                      );
                    }
                    return Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(width: 390, child: left),
                        const SizedBox(width: 14),
                        Expanded(child: right),
                      ],
                    );
                  },
                ),
              ],
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: 24)),
        ],
      ),
    );
  }
}

class UsersManagementScreen extends StatefulWidget {
  const UsersManagementScreen({super.key});

  @override
  State<UsersManagementScreen> createState() => _UsersManagementScreenState();
}

class _UsersManagementScreenState extends State<UsersManagementScreen>
    with RouteRefreshState<UsersManagementScreen> {
  bool _loading = false;
  String? _error;
  List<RowMap> _users = const [];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  String get refreshRoute => '/users';

  @override
  Future<void> onRefreshRequested() {
    if (_loading) return Future<void>.value();
    return _load();
  }

  Future<void> _load() async {
    final token = context.read<AuthController>().accessToken;
    if (token == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final users = await context.read<ApiClient>().getJsonList(
        '/admin/users',
        token: token,
      );
      if (mounted) setState(() => _users = users);
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _createUser() async {
    final values = await _userDialog(context, title: 'Новый пользователь');
    if (values == null) return;
    await _mutate(() async {
      await context.read<ApiClient>().postJson(
        '/admin/users',
        token: context.read<AuthController>().accessToken,
        body: values,
      );
    });
  }

  Future<void> _changeRole(RowMap user, int roleId) async {
    final userId = _asInt(user['user_id']);
    if (userId == null) return;
    await _mutate(() async {
      await context.read<ApiClient>().postJson(
        '/admin/users/$userId/role?role_id=$roleId',
        token: context.read<AuthController>().accessToken,
      );
    });
  }

  Future<void> _deleteUser(RowMap user) async {
    final userId = _asInt(user['user_id']);
    if (userId == null) return;
    final ok = await confirmAction(
      context,
      title: 'Удалить пользователя?',
      message: 'Учётная запись будет удалена.',
    );
    if (!ok) return;
    await _mutate(() async {
      await context.read<ApiClient>().deleteVoid(
        '/admin/users/$userId',
        token: context.read<AuthController>().accessToken,
      );
    });
  }

  Future<void> _mutate(Future<void> Function() action) async {
    try {
      await action();
      await _load();
      _markUsersChanged();
    } catch (error) {
      if (mounted) showErrorSnack(context, '$error');
    }
  }

  void _markUsersChanged() {
    if (!mounted) return;
    context.read<RefreshBus>().markStale(const ['/profile', '/reports']);
  }

  @override
  Widget build(BuildContext context) {
    final currentUserId = context.watch<AuthController>().user?.userId;
    return RefreshIndicator(
      onRefresh: _load,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: Column(
              children: [
                ModuleHeader(
                  title: 'Пользователи',
                  subtitle:
                      'Учётные записи, роли и защита от удаления текущего пользователя.',
                  icon: Icons.manage_accounts_rounded,
                  trailing: Wrap(
                    spacing: 10,
                    children: [
                      ElevatedButton.icon(
                        onPressed: _createUser,
                        icon: const Icon(
                          Icons.person_add_alt_rounded,
                          size: 18,
                        ),
                        label: const Text('Добавить'),
                      ),
                      RefreshButton(loading: _loading, onPressed: _load),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                if (_error != null)
                  ErrorPanel(message: _error!, onRetry: _load),
                if (_error != null) const SizedBox(height: 14),
              ],
            ),
          ),
          if (_users.isEmpty && !_loading)
            const SliverToBoxAdapter(
              child: EmptyPanel(message: 'Пользователей нет.'),
            )
          else
            SliverList.builder(
              itemCount: _users.length,
              itemBuilder: (context, index) {
                final user = _users[index];
                final userId = _asInt(user['user_id']);
                return Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: _UserCard(
                    user: user,
                    isCurrent: userId == currentUserId,
                    onRoleChanged: (roleId) => _changeRole(user, roleId),
                    onDelete: userId == currentUserId
                        ? null
                        : () => _deleteUser(user),
                  ),
                );
              },
            ),
          const SliverToBoxAdapter(child: SizedBox(height: 24)),
        ],
      ),
    );
  }
}

class ApiKeysManagementScreen extends StatefulWidget {
  const ApiKeysManagementScreen({super.key});

  @override
  State<ApiKeysManagementScreen> createState() =>
      _ApiKeysManagementScreenState();
}

class _ApiKeysManagementScreenState extends State<ApiKeysManagementScreen>
    with RouteRefreshState<ApiKeysManagementScreen> {
  bool _loading = false;
  String? _error;
  List<RowMap> _keys = const [];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  String get refreshRoute => '/api-keys';

  @override
  Future<void> onRefreshRequested() {
    if (_loading) return Future<void>.value();
    return _load();
  }

  Future<void> _load() async {
    final token = context.read<AuthController>().accessToken;
    if (token == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final keys = await context.read<ApiClient>().getJsonList(
        '/api-keys',
        token: token,
      );
      if (mounted) setState(() => _keys = keys);
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _createKey() async {
    final values = await _apiKeyDialog(context, title: 'Новый API ключ');
    if (values == null) return;
    try {
      final result = await context.read<ApiClient>().postJson(
        '/api-keys',
        token: context.read<AuthController>().accessToken,
        body: values,
      );
      if (!mounted) return;
      await showResultDialog(
        context,
        title: 'Новый API ключ',
        value: '${result['api_key'] ?? ''}',
        note: 'Ключ показывается один раз.',
      );
      await _load();
      _markApiKeysChanged();
    } catch (error) {
      if (mounted) showErrorSnack(context, '$error');
    }
  }

  Future<void> _editKey(RowMap key) async {
    final id = _asInt(key['api_key_id']);
    if (id == null) return;
    final values = await _apiKeyDialog(
      context,
      title: 'Редактировать API ключ',
      initial: key,
    );
    if (values == null) return;
    try {
      await context.read<ApiClient>().patchJson(
        '/api-keys/$id',
        token: context.read<AuthController>().accessToken,
        body: values,
      );
      await _load();
      _markApiKeysChanged();
    } catch (error) {
      if (mounted) showErrorSnack(context, '$error');
    }
  }

  Future<void> _deleteKey(RowMap key) async {
    final id = _asInt(key['api_key_id']);
    if (id == null) return;
    final ok = await confirmAction(
      context,
      title: 'Удалить API ключ?',
      message: 'Ключ перестанет работать для Processor и интеграций.',
    );
    if (!ok) return;
    try {
      await context.read<ApiClient>().deleteVoid(
        '/api-keys/$id',
        token: context.read<AuthController>().accessToken,
      );
      await _load();
      _markApiKeysChanged();
    } catch (error) {
      if (mounted) showErrorSnack(context, '$error');
    }
  }

  void _markApiKeysChanged() {
    if (!mounted) return;
    context.read<RefreshBus>().markStale(const ['/processors', '/reports']);
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _load,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: Column(
              children: [
                ModuleHeader(
                  title: 'API ключи',
                  subtitle:
                      'Создание, отключение, срок действия и scopes сервисных ключей.',
                  icon: Icons.vpn_key_rounded,
                  trailing: Wrap(
                    spacing: 10,
                    children: [
                      ElevatedButton.icon(
                        onPressed: _createKey,
                        icon: const Icon(Icons.add_rounded, size: 18),
                        label: const Text('Создать'),
                      ),
                      RefreshButton(loading: _loading, onPressed: _load),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                if (_error != null)
                  ErrorPanel(message: _error!, onRetry: _load),
                if (_error != null) const SizedBox(height: 14),
              ],
            ),
          ),
          if (_keys.isEmpty && !_loading)
            const SliverToBoxAdapter(
              child: EmptyPanel(message: 'API ключей нет.'),
            )
          else
            SliverList.builder(
              itemCount: _keys.length,
              itemBuilder: (context, index) {
                final key = _keys[index];
                return Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: _ApiKeyCard(
                    apiKey: key,
                    onEdit: () => _editKey(key),
                    onDelete: () => _deleteKey(key),
                  ),
                );
              },
            ),
          const SliverToBoxAdapter(child: SizedBox(height: 24)),
        ],
      ),
    );
  }
}

class _ReviewCard extends StatelessWidget {
  const _ReviewCard({
    required this.event,
    required this.selectedPerson,
    required this.mediaToken,
    required this.onPickPerson,
    required this.onApprove,
    required this.onReject,
    required this.onEnrollSnapshot,
    required this.onEnrollRecording,
  });

  final RowMap event;
  final RowMap? selectedPerson;
  final String? mediaToken;
  final VoidCallback onPickPerson;
  final VoidCallback onApprove;
  final VoidCallback onReject;
  final VoidCallback onEnrollSnapshot;
  final VoidCallback onEnrollRecording;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final api = context.read<ApiClient>();
    final snapshotUrl = _snapshotUrl(api, event, mediaToken);
    final recordingId = _asInt(event['recording_file_id']);
    final recordingUrl = recordingId == null || mediaToken == null
        ? null
        : api.recordingFileUri(recordingId, mediaToken!).toString();
    return GlassPanel(
      padding: const EdgeInsets.all(14),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final narrow = constraints.maxWidth < 780;
          final preview = _SnapshotBox(url: snapshotUrl);
          final body = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Событие #${event['event_id'] ?? '-'}',
                style: TextStyle(
                  color: colors.textStrong,
                  fontSize: 16,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  _InfoPill(
                    'Камера',
                    '${event['camera_name'] ?? event['camera_id'] ?? '-'}',
                  ),
                  _InfoPill(
                    'Время',
                    formatCell(event['event_ts'], keyHint: 'event_ts'),
                  ),
                  _InfoPill('Confidence', formatCell(event['confidence'])),
                  _InfoPill(
                    'Персона',
                    selectedPerson == null
                        ? 'не выбрана'
                        : _personLabel(selectedPerson!),
                  ),
                  if (recordingId != null) _InfoPill('Запись', '#$recordingId'),
                ],
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  ElevatedButton.icon(
                    onPressed: onApprove,
                    icon: const Icon(Icons.check_rounded, size: 18),
                    label: const Text('Подтвердить'),
                  ),
                  OutlinedButton.icon(
                    onPressed: onPickPerson,
                    icon: const Icon(Icons.person_search_rounded, size: 18),
                    label: const Text('Выбрать персону'),
                  ),
                  OutlinedButton.icon(
                    onPressed: snapshotUrl == null ? null : onEnrollSnapshot,
                    icon: const Icon(Icons.add_a_photo_rounded, size: 18),
                    label: const Text('Создать из snapshot'),
                  ),
                  OutlinedButton.icon(
                    onPressed: recordingId == null ? null : onEnrollRecording,
                    icon: const Icon(Icons.movie_creation_rounded, size: 18),
                    label: const Text('Создать из записи'),
                  ),
                  if (recordingUrl != null)
                    OutlinedButton.icon(
                      onPressed: () => showDialog<void>(
                        context: context,
                        builder: (_) => _ReviewVideoDialog(url: recordingUrl),
                      ),
                      icon: const Icon(Icons.play_circle_rounded, size: 18),
                      label: const Text('Видео'),
                    ),
                  OutlinedButton.icon(
                    onPressed: onReject,
                    icon: Icon(
                      Icons.close_rounded,
                      color: colors.danger,
                      size: 18,
                    ),
                    label: const Text('Отклонить'),
                  ),
                ],
              ),
            ],
          );
          if (narrow) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [preview, const SizedBox(height: 12), body],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(width: 280, child: preview),
              const SizedBox(width: 16),
              Expanded(child: body),
            ],
          );
        },
      ),
    );
  }
}

class _ReviewVideoDialog extends StatefulWidget {
  const _ReviewVideoDialog({required this.url});

  final String url;

  @override
  State<_ReviewVideoDialog> createState() => _ReviewVideoDialogState();
}

class _ReviewVideoDialogState extends State<_ReviewVideoDialog> {
  late final Player _player;
  late final VideoController _controller;

  @override
  void initState() {
    super.initState();
    _player = Player();
    _controller = VideoController(_player);
    unawaited(_player.open(Media(widget.url), play: false));
  }

  @override
  void dispose() {
    unawaited(_player.dispose());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Фрагмент записи'),
      content: SizedBox(
        width: 760,
        child: AspectRatio(
          aspectRatio: 16 / 9,
          child: Video(controller: _controller),
        ),
      ),
      actions: [
        ElevatedButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Закрыть'),
        ),
      ],
    );
  }
}

class _GroupList extends StatelessWidget {
  const _GroupList({
    required this.groups,
    required this.selectedId,
    required this.onSelect,
  });

  final List<RowMap> groups;
  final int? selectedId;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    return GlassPanel(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Список групп', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 10),
          if (groups.isEmpty)
            const EmptyPanel(message: 'Групп пока нет.')
          else
            SizedBox(
              height: 520,
              child: ListView.builder(
                itemExtent: 74,
                itemCount: groups.length,
                itemBuilder: (context, index) {
                  final group = groups[index];
                  final id = _asInt(group['group_id']) ?? 0;
                  return _SelectableTile(
                    selected: id == selectedId,
                    title: '${group['name'] ?? 'Группа'}',
                    subtitle: 'Камер: ${group['camera_count'] ?? 0}',
                    onTap: () => onSelect(id),
                  );
                },
              ),
            ),
        ],
      ),
    );
  }
}

class _GroupDetail extends StatelessWidget {
  const _GroupDetail({
    required this.detail,
    required this.assigned,
    required this.available,
    required this.isAdmin,
    required this.onEdit,
    required this.onDelete,
    required this.onAssign,
    required this.onUnassign,
  });

  final RowMap? detail;
  final List<CameraSummary> assigned;
  final List<CameraSummary> available;
  final bool isAdmin;
  final VoidCallback onEdit;
  final VoidCallback onDelete;
  final ValueChanged<CameraSummary> onAssign;
  final ValueChanged<CameraSummary> onUnassign;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    if (detail == null) {
      return const EmptyPanel(message: 'Выберите группу.');
    }
    return GlassPanel(
      padding: const EdgeInsets.all(16),
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
                      '${detail!['name'] ?? 'Группа'}',
                      style: Theme.of(context).textTheme.headlineSmall,
                    ),
                    Text(
                      '${detail!['description'] ?? 'Описание не задано'}',
                      style: TextStyle(color: colors.muted),
                    ),
                  ],
                ),
              ),
              if (isAdmin) ...[
                IconButton(
                  onPressed: onEdit,
                  icon: const Icon(Icons.edit_rounded),
                ),
                IconButton(
                  onPressed: onDelete,
                  icon: Icon(Icons.delete_rounded, color: colors.danger),
                ),
              ],
            ],
          ),
          const SizedBox(height: 14),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              _StatTile(label: 'Камер в группе', value: '${assigned.length}'),
              _StatTile(label: 'Доступно', value: '${available.length}'),
            ],
          ),
          const SizedBox(height: 16),
          _CameraAssignmentList(
            title: 'Камеры группы',
            cameras: assigned,
            actionLabel: 'Убрать',
            actionIcon: Icons.remove_circle_outline_rounded,
            onAction: isAdmin ? onUnassign : null,
          ),
          const SizedBox(height: 14),
          _CameraAssignmentList(
            title: 'Добавить камеру',
            cameras: available,
            actionLabel: 'Добавить',
            actionIcon: Icons.add_circle_outline_rounded,
            onAction: isAdmin ? onAssign : null,
          ),
        ],
      ),
    );
  }
}

class _ProcessorList extends StatelessWidget {
  const _ProcessorList({
    required this.processors,
    required this.selectedId,
    required this.onSelect,
  });

  final List<ProcessorOut> processors;
  final int? selectedId;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    return GlassPanel(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Узлы обработки', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 10),
          if (processors.isEmpty)
            const EmptyPanel(message: 'Processor пока не зарегистрированы.')
          else
            SizedBox(
              height: 560,
              child: ListView.builder(
                itemExtent: 86,
                itemCount: processors.length,
                itemBuilder: (context, index) {
                  final processor = processors[index];
                  return _SelectableTile(
                    selected: processor.processorId == selectedId,
                    title: processor.name,
                    subtitle:
                        '${processor.status} · ${processor.host ?? 'IP не указан'} · камер ${processor.assignedCameras.length}',
                    onTap: () => onSelect(processor.processorId),
                  );
                },
              ),
            ),
        ],
      ),
    );
  }
}

class _ProcessorDetail extends StatelessWidget {
  const _ProcessorDetail({
    required this.processor,
    required this.assigned,
    required this.available,
    required this.commands,
    required this.commandTypes,
    required this.onAssign,
    required this.onUnassign,
    required this.onCommand,
    required this.onCancelCommand,
    required this.onDelete,
  });

  final ProcessorOut? processor;
  final List<CameraSummary> assigned;
  final List<CameraSummary> available;
  final List<RowMap> commands;
  final List<String> commandTypes;
  final ValueChanged<CameraSummary> onAssign;
  final ValueChanged<CameraSummary> onUnassign;
  final ValueChanged<String> onCommand;
  final ValueChanged<RowMap> onCancelCommand;
  final VoidCallback? onDelete;

  @override
  Widget build(BuildContext context) {
    final processor = this.processor;
    final colors = context.colors;
    if (processor == null) {
      return const EmptyPanel(message: 'Выберите Processor.');
    }
    final metrics = processor.metrics ?? const <String, dynamic>{};
    final capabilities = processor.capabilities ?? const <String, dynamic>{};
    final accel = capabilities['acceleration'] is Map
        ? (capabilities['acceleration'] as Map).map(
            (key, value) => MapEntry('$key', value),
          )
        : const <String, dynamic>{};
    return GlassPanel(
      padding: const EdgeInsets.all(16),
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
                      processor.name,
                      style: Theme.of(context).textTheme.headlineSmall,
                    ),
                    Text(
                      '${processor.status} · ${processor.host ?? 'IP не указан'} · heartbeat ${formatCell(processor.lastHeartbeatAt, keyHint: 'last_heartbeat')}',
                      style: TextStyle(color: colors.muted),
                    ),
                  ],
                ),
              ),
              IconButton(
                onPressed: onDelete,
                icon: Icon(Icons.delete_rounded, color: colors.danger),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              _StatTile(label: 'CPU', value: _percent(metrics['cpu_percent'])),
              _StatTile(label: 'RAM', value: _percent(metrics['ram_percent'])),
              _StatTile(
                label: 'GPU',
                value: _percent(metrics['gpu_util_percent']),
              ),
              _StatTile(
                label: 'Команды',
                value:
                    '${processor.pendingCommands}/${processor.runningCommands}',
              ),
            ],
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _InfoChip(
                icon: Icons.fingerprint_rounded,
                label: 'UID',
                value: processor.nodeUid ?? '-',
              ),
              _InfoChip(
                icon: Icons.dns_rounded,
                label: 'OS',
                value: processor.osInfo ?? '-',
              ),
              _InfoChip(
                icon: Icons.memory_rounded,
                label: 'Ускорение',
                value:
                    '${accel['selected_device'] ?? accel['preference'] ?? '-'}',
              ),
              _InfoChip(
                icon: Icons.new_releases_rounded,
                label: 'Версия',
                value: processor.version ?? '-',
              ),
            ],
          ),
          const SizedBox(height: 16),
          Text(
            'Удалённые команды',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final type in commandTypes)
                OutlinedButton(
                  onPressed: () => onCommand(type),
                  child: Text(_commandLabel(type)),
                ),
            ],
          ),
          const SizedBox(height: 16),
          _CameraAssignmentList(
            title: 'Назначенные камеры',
            cameras: assigned,
            actionLabel: 'Отвязать',
            actionIcon: Icons.link_off_rounded,
            onAction: onUnassign,
          ),
          const SizedBox(height: 14),
          _CameraAssignmentList(
            title: 'Назначить камеру',
            cameras: available,
            actionLabel: 'Назначить',
            actionIcon: Icons.add_link_rounded,
            onAction: onAssign,
          ),
          const SizedBox(height: 16),
          Text('История команд', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 8),
          if (commands.isEmpty)
            Text('Команд пока нет.', style: TextStyle(color: colors.muted))
          else
            for (final command in commands.take(12))
              _CommandRow(
                command: command,
                onCancel: () => onCancelCommand(command),
              ),
        ],
      ),
    );
  }
}

class _InfoChip extends StatelessWidget {
  const _InfoChip({
    required this.icon,
    required this.label,
    required this.value,
  });

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      constraints: const BoxConstraints(maxWidth: 260),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: colors.surfaceMuted,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: colors.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: colors.primaryAccent),
          const SizedBox(width: 8),
          Flexible(
            child: Text(
              '$label: $value',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(color: colors.muted, fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }
}

class _UserCard extends StatelessWidget {
  const _UserCard({
    required this.user,
    required this.isCurrent,
    required this.onRoleChanged,
    required this.onDelete,
  });

  final RowMap user;
  final bool isCurrent;
  final ValueChanged<int> onRoleChanged;
  final VoidCallback? onDelete;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final roleId = _asInt(user['role_id']) ?? 3;
    return GlassPanel(
      padding: const EdgeInsets.all(14),
      child: Row(
        children: [
          CircleAvatar(
            backgroundColor: colors.primaryAccent.withValues(alpha: 0.16),
            child: Text('${user['user_id'] ?? '-'}'),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${user['login'] ?? '-'}${isCurrent ? ' · текущий пользователь' : ''}',
                  style: TextStyle(
                    color: colors.textStrong,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  [
                    _userName(user),
                    'роль: ${roleName(roleId)}',
                    'смена пароля: ${formatCell(user['must_change_password'])}',
                  ].join(' · '),
                  style: TextStyle(color: colors.muted, fontSize: 12),
                ),
              ],
            ),
          ),
          Tooltip(
            message: isCurrent
                ? 'Роль текущего пользователя нельзя менять из активной сессии'
                : 'Изменить роль',
            child: DropdownButton<int>(
              value: roleId,
              underline: const SizedBox.shrink(),
              items: const [
                DropdownMenuItem(value: 1, child: Text('Админ')),
                DropdownMenuItem(value: 2, child: Text('Оператор')),
                DropdownMenuItem(value: 3, child: Text('Смотрящий')),
              ],
              onChanged: isCurrent
                  ? null
                  : (value) {
                      if (value != null && value != roleId) {
                        onRoleChanged(value);
                      }
                    },
            ),
          ),
          IconButton(
            tooltip: isCurrent
                ? 'Нельзя удалить текущего пользователя'
                : 'Удалить',
            onPressed: onDelete,
            icon: Icon(
              Icons.delete_outline_rounded,
              color: onDelete == null ? colors.muted : colors.danger,
            ),
          ),
        ],
      ),
    );
  }
}

class _ApiKeyCard extends StatelessWidget {
  const _ApiKeyCard({
    required this.apiKey,
    required this.onEdit,
    required this.onDelete,
  });

  final RowMap apiKey;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(14),
      child: Row(
        children: [
          Icon(Icons.vpn_key_rounded, color: colors.primaryAccent),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${apiKey['description'] ?? 'API key #${apiKey['api_key_id']}'}',
                  style: TextStyle(
                    color: colors.textStrong,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  'Scopes: ${formatCell(apiKey['scopes'])} · активен: ${formatCell(apiKey['is_active'])} · истекает: ${formatCell(apiKey['expires_at'])}',
                  style: TextStyle(color: colors.muted, fontSize: 12),
                ),
              ],
            ),
          ),
          IconButton(onPressed: onEdit, icon: const Icon(Icons.edit_rounded)),
          IconButton(
            onPressed: onDelete,
            icon: Icon(Icons.delete_outline_rounded, color: colors.danger),
          ),
        ],
      ),
    );
  }
}

class _CameraAssignmentList extends StatelessWidget {
  const _CameraAssignmentList({
    required this.title,
    required this.cameras,
    required this.actionLabel,
    required this.actionIcon,
    required this.onAction,
  });

  final String title;
  final List<CameraSummary> cameras;
  final String actionLabel;
  final IconData actionIcon;
  final ValueChanged<CameraSummary>? onAction;

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
            title,
            style: TextStyle(
              color: colors.textStrong,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 10),
          if (cameras.isEmpty)
            Text('Нет камер.', style: TextStyle(color: colors.muted))
          else
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final camera in cameras)
                  ActionChip(
                    avatar: Icon(actionIcon, size: 18),
                    label: Text(camera.name),
                    onPressed: onAction == null
                        ? null
                        : () => onAction!(camera),
                    tooltip: actionLabel,
                  ),
              ],
            ),
        ],
      ),
    );
  }
}

class _CommandRow extends StatelessWidget {
  const _CommandRow({required this.command, required this.onCancel});

  final RowMap command;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final status = '${command['status'] ?? '-'}';
    final cancellable = status == 'pending' || status == 'running';
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              '#${command['command_id']} · ${_commandLabel('${command['command_type']}')} · $status · ${formatCell(command['created_at'], keyHint: 'created_at')}',
              style: TextStyle(
                color: colors.text,
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          IconButton(
            tooltip: 'Отменить',
            onPressed: cancellable ? onCancel : null,
            icon: const Icon(Icons.cancel_rounded, size: 18),
          ),
        ],
      ),
    );
  }
}

class _SelectableTile extends StatelessWidget {
  const _SelectableTile({
    required this.selected,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final bool selected;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 150),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            color: selected
                ? colors.primaryAccent.withValues(alpha: 0.15)
                : colors.surfaceMuted,
            border: Border.all(
              color: selected ? colors.primaryAccent : colors.border,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(
                title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: colors.textStrong,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                subtitle,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(color: colors.muted, fontSize: 12),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SnapshotBox extends StatelessWidget {
  const _SnapshotBox({required this.url});

  final String? url;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AspectRatio(
      aspectRatio: 16 / 9,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(18),
        child: Container(
          color: Colors.black.withValues(alpha: 0.28),
          child: url == null
              ? Center(
                  child: Text(
                    'Snapshot недоступен',
                    style: TextStyle(color: colors.muted),
                  ),
                )
              : Image.network(
                  url!,
                  fit: BoxFit.cover,
                  errorBuilder: (_, _, _) => Center(
                    child: Text(
                      'Не удалось открыть snapshot',
                      style: TextStyle(color: colors.muted),
                    ),
                  ),
                ),
        ),
      ),
    );
  }
}

class _InfoPill extends StatelessWidget {
  const _InfoPill(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Text(
        '$label: $value',
        style: TextStyle(
          color: colors.text,
          fontSize: 12,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class _StatTile extends StatelessWidget {
  const _StatTile({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      width: 152,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: TextStyle(color: colors.muted, fontSize: 11)),
          const SizedBox(height: 3),
          Text(
            value,
            style: TextStyle(
              color: colors.textStrong,
              fontSize: 20,
              fontWeight: FontWeight.w900,
            ),
          ),
        ],
      ),
    );
  }
}

class _LoadingPanel extends StatelessWidget {
  const _LoadingPanel();

  @override
  Widget build(BuildContext context) {
    return GlassPanel(
      padding: const EdgeInsets.all(18),
      child: Row(
        children: [
          const SizedBox(
            width: 20,
            height: 20,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: 12),
          Text('Загрузка...', style: TextStyle(color: context.colors.muted)),
        ],
      ),
    );
  }
}

Future<Map<String, dynamic>?> _userDialog(
  BuildContext context, {
  required String title,
}) async {
  final login = TextEditingController();
  final password = TextEditingController();
  final lastName = TextEditingController();
  final firstName = TextEditingController();
  final middleName = TextEditingController();
  var roleId = 3;
  String? error;
  try {
    return showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) {
          return AlertDialog(
            title: Text(title),
            content: SizedBox(
              width: 430,
              child: SingleChildScrollView(
                child: Column(
                  children: [
                    TextField(
                      controller: login,
                      decoration: const InputDecoration(labelText: 'Логин'),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: password,
                      obscureText: true,
                      decoration: const InputDecoration(labelText: 'Пароль'),
                    ),
                    const SizedBox(height: 10),
                    DropdownButtonFormField<int>(
                      initialValue: roleId,
                      decoration: const InputDecoration(labelText: 'Роль'),
                      items: const [
                        DropdownMenuItem(
                          value: 1,
                          child: Text('Администратор'),
                        ),
                        DropdownMenuItem(value: 2, child: Text('Оператор')),
                        DropdownMenuItem(value: 3, child: Text('Смотрящий')),
                      ],
                      onChanged: (value) => setState(() => roleId = value ?? 3),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: lastName,
                      inputFormatters: humanNameInputFormatters(),
                      textCapitalization: TextCapitalization.words,
                      textInputAction: TextInputAction.next,
                      decoration: const InputDecoration(labelText: 'Фамилия'),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: firstName,
                      inputFormatters: humanNameInputFormatters(),
                      textCapitalization: TextCapitalization.words,
                      textInputAction: TextInputAction.next,
                      decoration: const InputDecoration(labelText: 'Имя'),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: middleName,
                      inputFormatters: humanNameInputFormatters(),
                      textCapitalization: TextCapitalization.words,
                      textInputAction: TextInputAction.done,
                      decoration: const InputDecoration(labelText: 'Отчество'),
                    ),
                    if (error != null) ...[
                      const SizedBox(height: 10),
                      Text(
                        error!,
                        style: TextStyle(
                          color: context.colors.danger,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('Отмена'),
              ),
              ElevatedButton(
                onPressed: () {
                  final nameFields = {
                    'Фамилия': lastName.text,
                    'Имя': firstName.text,
                    'Отчество': middleName.text,
                  };
                  for (final entry in nameFields.entries) {
                    final validation = validateOptionalHumanName(
                      entry.key,
                      entry.value,
                    );
                    if (validation != null) {
                      setState(() => error = validation);
                      return;
                    }
                  }
                  Navigator.pop(context, {
                    'login': login.text.trim(),
                    'password': password.text,
                    'role_id': roleId,
                    if (normalizeHumanName(lastName.text).isNotEmpty)
                      'last_name': normalizeHumanName(lastName.text),
                    if (normalizeHumanName(firstName.text).isNotEmpty)
                      'first_name': normalizeHumanName(firstName.text),
                    if (normalizeHumanName(middleName.text).isNotEmpty)
                      'middle_name': normalizeHumanName(middleName.text),
                  });
                },
                child: const Text('Сохранить'),
              ),
            ],
          );
        },
      ),
    );
  } finally {
    login.dispose();
    password.dispose();
    lastName.dispose();
    firstName.dispose();
    middleName.dispose();
  }
}

Future<Map<String, dynamic>?> _apiKeyDialog(
  BuildContext context, {
  required String title,
  RowMap? initial,
}) async {
  final description = TextEditingController(
    text: '${initial?['description'] ?? ''}',
  );
  final scopes = TextEditingController(
    text: initial == null
        ? 'detections:create'
        : _stringList(initial['scopes']).join(', '),
  );
  final expiresAt = TextEditingController(
    text: '${initial?['expires_at'] ?? ''}',
  );
  var isActive = initial?['is_active'] != false;
  try {
    return showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) {
          return AlertDialog(
            title: Text(title),
            content: SizedBox(
              width: 430,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextField(
                    controller: description,
                    decoration: const InputDecoration(labelText: 'Описание'),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: scopes,
                    decoration: const InputDecoration(
                      labelText: 'Scopes через запятую',
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: expiresAt,
                    decoration: const InputDecoration(
                      labelText: 'Истекает ISO, опционально',
                    ),
                  ),
                  const SizedBox(height: 10),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Активен'),
                    value: isActive,
                    onChanged: (value) => setState(() => isActive = value),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('Отмена'),
              ),
              ElevatedButton(
                onPressed: () => Navigator.pop(context, {
                  'description': description.text.trim().isEmpty
                      ? null
                      : description.text.trim(),
                  'scopes': scopes.text
                      .split(',')
                      .map((scope) => scope.trim())
                      .where((scope) => scope.isNotEmpty)
                      .toList(),
                  'is_active': isActive,
                  if (expiresAt.text.trim().isNotEmpty)
                    'expires_at': expiresAt.text.trim(),
                }),
                child: const Text('Сохранить'),
              ),
            ],
          );
        },
      ),
    );
  } finally {
    description.dispose();
    scopes.dispose();
    expiresAt.dispose();
  }
}

Future<Map<String, String>?> _personNameDialog(
  BuildContext context, {
  required String title,
}) {
  return textFormDialog(
    context,
    title: title,
    fields: const [
      DialogField('last_name', 'Фамилия'),
      DialogField('first_name', 'Имя'),
      DialogField('middle_name', 'Отчество'),
    ],
  );
}

Future<int?> _showEntityPicker(
  BuildContext context, {
  required String title,
  required List<_PickerItem> items,
}) {
  return showModalBottomSheet<int>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (context) => _PickerSheet(title: title, items: items),
  );
}

class _PickerSheet extends StatefulWidget {
  const _PickerSheet({required this.title, required this.items});

  final String title;
  final List<_PickerItem> items;

  @override
  State<_PickerSheet> createState() => _PickerSheetState();
}

class _PickerSheetState extends State<_PickerSheet> {
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
                    item.title.toLowerCase().contains(query) ||
                    item.subtitle.toLowerCase().contains(query),
              )
              .toList();
    return Padding(
      padding: EdgeInsets.fromLTRB(
        18,
        18,
        18,
        MediaQuery.viewInsetsOf(context).bottom + 18,
      ),
      child: GlassPanel(
        padding: const EdgeInsets.all(16),
        child: SizedBox(
          height: 520,
          child: Column(
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      widget.title,
                      style: Theme.of(context).textTheme.headlineSmall,
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
              const SizedBox(height: 10),
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
                            title: Text(
                              item.title,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                            subtitle: item.subtitle.isEmpty
                                ? null
                                : Text(
                                    item.subtitle,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
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

class _PickerItem {
  const _PickerItem({
    required this.id,
    required this.title,
    this.subtitle = '',
  });

  final int id;
  final String title;
  final String subtitle;
}

String? _snapshotUrl(ApiClient api, RowMap event, String? mediaToken) {
  final value = event['snapshot_url'];
  if (value == null || '$value'.isEmpty) return null;
  final text = '$value';
  if (text.startsWith('http://') || text.startsWith('https://')) return text;
  if (mediaToken != null && text.startsWith('/detections/events/')) {
    return api.uri(text, {'token': mediaToken}).toString();
  }
  return api.uri(text).toString();
}

String _personLabel(RowMap person) {
  final parts =
      [person['last_name'], person['first_name'], person['middle_name']]
          .where((value) => value != null && '$value'.trim().isNotEmpty)
          .map((value) => '$value');
  final label = parts.join(' ').trim();
  return label.isEmpty ? 'Персона #${person['person_id']}' : label;
}

String _userName(RowMap user) {
  final parts = [user['last_name'], user['first_name'], user['middle_name']]
      .where((value) => value != null && '$value'.trim().isNotEmpty)
      .map((value) => '$value');
  final label = parts.join(' ').trim();
  return label.isEmpty ? 'ФИО не указано' : label;
}

String _percent(Object? value) {
  final number = value is num ? value : num.tryParse('$value');
  if (number == null) return '-';
  return '${number.toStringAsFixed(0)}%';
}

String _commandLabel(String type) {
  return switch (type) {
    'reload_assignments' => 'Перезагрузить назначения',
    'restart_workers' => 'Перезапустить воркеры',
    'stop_all_cameras' => 'Остановить камеры',
    'resume_cameras' => 'Возобновить камеры',
    'refresh_gallery' => 'Обновить галерею',
    'shutdown' => 'Выключить',
    _ => type,
  };
}

int? _asInt(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse('$value');
}

Map<String, dynamic> _asMap(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return value.map((key, item) => MapEntry('$key', item));
  return <String, dynamic>{};
}

List<RowMap> _asList(Object? value) {
  if (value is! List) return const [];
  return value
      .whereType<Map>()
      .map((item) => item.map((key, value) => MapEntry('$key', value)))
      .toList();
}

List<String> _stringList(Object? value) {
  if (value is! List) return const [];
  return value.map((item) => '$item').toList();
}

extension _FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull {
    final iterator = this.iterator;
    return iterator.moveNext() ? iterator.current : null;
  }
}
