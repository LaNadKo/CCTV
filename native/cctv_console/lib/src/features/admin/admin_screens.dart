// ignore_for_file: use_build_context_synchronously

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
typedef ProcessorCommandSender = Future<void> Function(
  String commandType, {
  Map<String, dynamic>? payload,
});

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
  final Map<int, List<RowMap>> _candidatesByEvent = {};
  final Map<int, String> _candidateNotesByEvent = {};
  final Set<int> _loadingCandidates = {};

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
      _candidatesByEvent.removeWhere(
        (eventId, _) => !events.any((event) => event['event_id'] == eventId),
      );
      _candidateNotesByEvent.removeWhere(
        (eventId, _) => !events.any((event) => event['event_id'] == eventId),
      );
      _loadingCandidates.removeWhere(
        (eventId) => !events.any((event) => event['event_id'] == eventId),
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

  Future<void> _loadCandidates(RowMap event) async {
    final token = context.read<AuthController>().accessToken;
    final eventId = _asInt(event['event_id']);
    if (token == null || eventId == null) return;
    if (_candidatesByEvent.containsKey(eventId) ||
        _loadingCandidates.contains(eventId)) {
      return;
    }
    final snapshotUrl = '${event['snapshot_url'] ?? ''}'.trim();
    if (snapshotUrl.isEmpty) {
      setState(() {
        _candidatesByEvent[eventId] = const [];
        _candidateNotesByEvent[eventId] =
            'У события нет снимка для сравнения.';
      });
      return;
    }
    setState(() => _loadingCandidates.add(eventId));
    try {
      final candidates = await context
          .read<ApiClient>()
          .listReviewCandidates(token, eventId, limit: 3);
      if (!mounted) return;
      setState(() {
        _candidatesByEvent[eventId] = candidates;
        if (candidates.isEmpty) {
          _candidateNotesByEvent[eventId] =
              'Совпадений не найдено: нет лица на снимке или нет обученных embeddings.';
        } else {
          _candidateNotesByEvent.remove(eventId);
        }
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _candidatesByEvent[eventId] = const [];
        _candidateNotesByEvent[eventId] =
            'Не удалось загрузить предположения: $error';
      });
    } finally {
      if (mounted) setState(() => _loadingCandidates.remove(eventId));
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
      title: 'Создать персону из снимка',
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
                    candidatePersons: eventId == null
                        ? const []
                        : _candidatesByEvent[eventId] ?? const [],
                    candidateNote: eventId == null
                        ? null
                        : _candidateNotesByEvent[eventId],
                    loadingCandidates:
                        eventId != null && _loadingCandidates.contains(eventId),
                    mediaToken: context.watch<AuthController>().mediaToken,
                    onPickPerson: () => _pickPerson(event),
                    onLoadCandidates: () => _loadCandidates(event),
                    onSelectCandidate: (personId) {
                      if (eventId == null) return;
                      setState(() => _personByEvent[eventId] = personId);
                    },
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
  final _groupSearchController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _groupSearchController.addListener(() => setState(() {}));
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _groupSearchController.dispose();
    super.dispose();
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
    final visibleGroups = _filterGroups(_groups, _groupSearchController.text);
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
                      groups: visibleGroups,
                      totalCount: _groups.length,
                      searchController: _groupSearchController,
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
  final _processorSearchController = TextEditingController();
  int? _selectedId;

  static const _commandTypes = [
    'reload_assignments',
    'restart_workers',
    'stop_all_cameras',
    'resume_cameras',
    'refresh_gallery',
    'start_runtime',
    'stop_runtime',
    'restart_runtime',
    'apply_detection_settings',
  ];

  @override
  void initState() {
    super.initState();
    _processorSearchController.addListener(() => setState(() {}));
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _processorSearchController.dispose();
    super.dispose();
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
        title: 'Код подключения Процессора',
        value: '${result['code'] ?? ''}',
        note: 'Действует до: ${formatCell(result['expires_at'])}',
        segmentedCode: true,
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

  Future<void> _sendCommand(
    String commandType, {
    Map<String, dynamic>? payload,
  }) async {
    final token = context.read<AuthController>().accessToken;
    final api = context.read<ApiClient>();
    final processorId = _selectedId;
    if (token == null || processorId == null) return;
    final ok = commandType == 'stop_runtime'
        ? await confirmAction(
            context,
            title: 'Остановить Runtime?',
            message: 'Runtime остановит обработку камер до повторного запуска.',
          )
        : true;
    if (!mounted) return;
    if (!ok) return;
    try {
      await api.postJson(
        '/processors/$processorId/commands',
        token: token,
        body: {'command_type': commandType, 'payload': payload ?? <String, dynamic>{}},
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
      title: 'Удалить Процессор?',
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

  List<ProcessorOut> get _filteredProcessors {
    final query = _processorSearchController.text.trim().toLowerCase();
    if (query.isEmpty) return _processors;
    return _processors.where((processor) {
      final haystack = [
        processor.name,
        processor.status,
        processor.host,
        processor.nodeUid,
        processor.osInfo,
        processor.version,
        'id ${processor.processorId}',
        ...processor.assignedCameras.map(
          (camera) => '${camera.name} ${camera.location ?? ''}',
        ),
      ].whereType<String>().join(' ').toLowerCase();
      return haystack.contains(query);
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    final visibleProcessors = _filteredProcessors;
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
                  title: 'Процессор',
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
                    _StatTile(label: 'Онлайн', value: '$online'),
                    _StatTile(label: 'Камер', value: '${_cameras.length}'),
                  ],
                ),
                const SizedBox(height: 14),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final narrow = constraints.maxWidth < 980;
                    final left = _ProcessorList(
                      processors: visibleProcessors,
                      totalCount: _processors.length,
                      searchController: _processorSearchController,
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
  final _searchController = TextEditingController();
  Timer? _searchDebounce;
  bool _loading = false;
  String? _error;
  List<RowMap> _users = const [];

  @override
  void initState() {
    super.initState();
    _searchController.addListener(_scheduleSearch);
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _searchDebounce?.cancel();
    _searchController
      ..removeListener(_scheduleSearch)
      ..dispose();
    super.dispose();
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
        query: {
          if (_searchController.text.trim().isNotEmpty)
            'q': _searchController.text.trim(),
          'limit': '300',
        },
      );
      if (mounted) setState(() => _users = users);
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _scheduleSearch() {
    _searchDebounce?.cancel();
    _searchDebounce = Timer(const Duration(milliseconds: 300), () {
      if (mounted) unawaited(_load());
    });
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
                TextField(
                  controller: _searchController,
                  decoration: InputDecoration(
                    labelText: 'Поиск пользователей',
                    hintText: 'Логин, ФИО, роль, статус или ID',
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
      message: 'Ключ перестанет работать для Процессора и интеграций.',
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
    required this.candidatePersons,
    required this.candidateNote,
    required this.loadingCandidates,
    required this.mediaToken,
    required this.onPickPerson,
    required this.onLoadCandidates,
    required this.onSelectCandidate,
    required this.onApprove,
    required this.onReject,
    required this.onEnrollSnapshot,
    required this.onEnrollRecording,
  });

  final RowMap event;
  final RowMap? selectedPerson;
  final List<RowMap> candidatePersons;
  final String? candidateNote;
  final bool loadingCandidates;
  final String? mediaToken;
  final VoidCallback onPickPerson;
  final VoidCallback onLoadCandidates;
  final ValueChanged<int> onSelectCandidate;
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
                  _InfoPill('Уверенность', formatCell(event['confidence'])),
                  _InfoPill(
                    'Персона',
                    selectedPerson == null
                        ? 'не выбрана'
                        : _personLabel(selectedPerson!),
                  ),
                  if (recordingId != null) _InfoPill('Запись', '#$recordingId'),
                ],
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  OutlinedButton.icon(
                    onPressed: loadingCandidates ? null : onLoadCandidates,
                    icon: loadingCandidates
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.person_pin_rounded, size: 18),
                    label: const Text('Показать предположения'),
                  ),
                  if (candidatePersons.isNotEmpty)
                    _InfoPill('Предположения', '${candidatePersons.length}'),
                  for (final candidate in candidatePersons)
                    OutlinedButton.icon(
                      onPressed: () {
                        final personId = _asInt(candidate['person_id']);
                        if (personId != null) onSelectCandidate(personId);
                      },
                      icon: const Icon(Icons.person_pin_rounded, size: 18),
                      label: Text(_candidateLabel(candidate)),
                    ),
                  if ((candidateNote ?? '').isNotEmpty)
                    _InfoPill('Предположения', candidateNote!),
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
                    label: const Text('Создать из снимка'),
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

List<RowMap> _filterGroups(List<RowMap> groups, String rawQuery) {
  final query = rawQuery.trim().toLowerCase();
  if (query.isEmpty) return groups;
  return groups.where((group) {
    final text =
        '${group['name'] ?? ''} ${group['description'] ?? ''} ${group['camera_count'] ?? ''}'
            .toLowerCase();
    return _looseAdminContains(text, query);
  }).toList(growable: false);
}

bool _looseAdminContains(String text, String query) {
  if (text.contains(query)) return true;
  final parts = query
      .split(RegExp(r'\s+'))
      .where((part) => part.isNotEmpty)
      .toList(growable: false);
  if (parts.isEmpty) return true;
  final words = text.split(RegExp(r'\s+')).where((word) => word.isNotEmpty);
  return parts.every((part) {
    if (text.contains(part)) return true;
    return words.any((word) => _adminEditDistance(word, part) <= 1);
  });
}

int _adminEditDistance(String a, String b) {
  if ((a.length - b.length).abs() > 1) return 2;
  if (a == b) return 0;
  var i = 0;
  var j = 0;
  var edits = 0;
  while (i < a.length && j < b.length) {
    if (a.codeUnitAt(i) == b.codeUnitAt(j)) {
      i++;
      j++;
      continue;
    }
    edits++;
    if (edits > 1) return edits;
    if (a.length > b.length) {
      i++;
    } else if (b.length > a.length) {
      j++;
    } else {
      i++;
      j++;
    }
  }
  if (i < a.length || j < b.length) edits++;
  return edits;
}

class _GroupList extends StatelessWidget {
  const _GroupList({
    required this.groups,
    required this.totalCount,
    required this.searchController,
    required this.selectedId,
    required this.onSelect,
  });

  final List<RowMap> groups;
  final int totalCount;
  final TextEditingController searchController;
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
          TextField(
            controller: searchController,
            decoration: InputDecoration(
              prefixIcon: const Icon(Icons.search_rounded),
              labelText: 'Поиск групп',
              suffixIcon: searchController.text.isEmpty
                  ? null
                  : IconButton(
                      onPressed: searchController.clear,
                      icon: const Icon(Icons.close_rounded),
                    ),
            ),
          ),
          const SizedBox(height: 10),
          if (groups.isEmpty)
            EmptyPanel(
              message: totalCount == 0
                  ? 'Групп пока нет.'
                  : 'Под фильтр групп нет.',
            )
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
    required this.totalCount,
    required this.searchController,
    required this.selectedId,
    required this.onSelect,
  });

  final List<ProcessorOut> processors;
  final int totalCount;
  final TextEditingController searchController;
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
          TextField(
            controller: searchController,
            decoration: InputDecoration(
              hintText: 'Имя, IP, статус, UID или камера',
              prefixIcon: const Icon(Icons.search_rounded),
              suffixIcon: searchController.text.isEmpty
                  ? null
                  : IconButton(
                      tooltip: 'Очистить',
                      onPressed: searchController.clear,
                      icon: const Icon(Icons.close_rounded),
                    ),
            ),
          ),
          const SizedBox(height: 10),
          if (processors.isEmpty)
            EmptyPanel(
              message: totalCount == 0
                  ? 'Процессоры пока не зарегистрированы.'
                  : 'По запросу ничего не найдено.',
            )
          else
            SizedBox(
              height: 500,
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
  final ProcessorCommandSender onCommand;
  final ValueChanged<RowMap> onCancelCommand;
  final VoidCallback? onDelete;

  @override
  Widget build(BuildContext context) {
    final processor = this.processor;
    final colors = context.colors;
    if (processor == null) {
      return const EmptyPanel(message: 'Выберите Процессор.');
    }
    final metrics = processor.metrics ?? const <String, dynamic>{};
    final capabilities = processor.capabilities ?? const <String, dynamic>{};
    final accel = capabilities['acceleration'] is Map
        ? (capabilities['acceleration'] as Map).map(
            (key, value) => MapEntry('$key', value),
          )
        : const <String, dynamic>{};
    final detectionSettings = _asMap(capabilities['detection_settings']);
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
                if (type != 'apply_detection_settings')
                OutlinedButton(
                  onPressed: () => onCommand(type),
                  child: Text(_commandLabel(type)),
                ),
            ],
          ),
          const SizedBox(height: 16),
          _DetectionSettingsPanel(
            settings: detectionSettings,
            onApply: (payload) => onCommand(
              'apply_detection_settings',
              payload: payload,
            ),
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

class _DetectionSettingsPanel extends StatefulWidget {
  const _DetectionSettingsPanel({
    required this.settings,
    required this.onApply,
  });

  final RowMap settings;
  final ValueChanged<Map<String, dynamic>> onApply;

  @override
  State<_DetectionSettingsPanel> createState() =>
      _DetectionSettingsPanelState();
}

class _DetectionSettingsPanelState extends State<_DetectionSettingsPanel> {
  final _maxWorkers = TextEditingController();
  final _motionThreshold = TextEditingController();
  final _recordingSegment = TextEditingController();
  final _pendingTimeout = TextEditingController();
  String _accel = 'auto';
  int _faceScanDivisor = 4;
  int _overlayFrameDivisor = 1;

  @override
  void initState() {
    super.initState();
    _load(widget.settings);
  }

  @override
  void didUpdateWidget(covariant _DetectionSettingsPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.settings != widget.settings) {
      _load(widget.settings);
    }
  }

  @override
  void dispose() {
    _maxWorkers.dispose();
    _motionThreshold.dispose();
    _recordingSegment.dispose();
    _pendingTimeout.dispose();
    super.dispose();
  }

  void _load(RowMap settings) {
    _maxWorkers.text = '${_settingInt(settings['max_workers'], 4)}';
    _motionThreshold.text = _settingDouble(
      settings['motion_threshold'],
      25,
    ).toStringAsFixed(1);
    _recordingSegment.text =
        '${_settingInt(settings['recording_segment_seconds'], 60)}';
    _pendingTimeout.text = _settingDouble(
      settings['antispoof_pending_timeout_seconds'],
      2.8,
    ).toStringAsFixed(1);
    _accel = _settingString(settings['processor_accel'], 'auto', {
      'auto',
      'cuda',
      'cpu',
    });
    _faceScanDivisor = _settingChoice(settings['face_scan_divisor'], 4);
    _overlayFrameDivisor = _settingChoice(settings['overlay_frame_divisor'], 1);
  }

  void _applyPreset(
    int maxWorkers,
    double motionThreshold,
    int faceScanDivisor,
    int overlayFrameDivisor,
  ) {
    setState(() {
      _maxWorkers.text = '$maxWorkers';
      _motionThreshold.text = motionThreshold.toStringAsFixed(1);
      _faceScanDivisor = faceScanDivisor;
      _overlayFrameDivisor = overlayFrameDivisor;
    });
  }

  Map<String, dynamic> _payload() {
    return {
      'max_workers': _readInt(_maxWorkers, 4).clamp(1, 16),
      'motion_threshold': _readDouble(_motionThreshold, 25).clamp(1, 120),
      'recording_segment_seconds': _readInt(_recordingSegment, 60).clamp(
        10,
        60,
      ),
      'processor_accel': _accel,
      'face_scan_divisor': _faceScanDivisor,
      'overlay_frame_divisor': _overlayFrameDivisor,
      'antispoof_pending_timeout_seconds': _readDouble(
        _pendingTimeout,
        2.8,
      ).clamp(0.8, 8.0),
    };
  }

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
            'Производительность',
            style: TextStyle(
              color: colors.textStrong,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              _SettingsTextField(
                controller: _maxWorkers,
                label: 'Макс. камер',
              ),
              _SettingsTextField(
                controller: _motionThreshold,
                label: 'Порог движения',
              ),
              _SettingsTextField(
                controller: _recordingSegment,
                label: 'Сегмент записи, сек',
              ),
              _SettingsTextField(
                controller: _pendingTimeout,
                label: 'Таймаут антиспуфа, сек',
              ),
              _SettingsSelect<String>(
                label: 'Ускорение',
                value: _accel,
                values: const ['auto', 'cuda', 'cpu'],
                display: (value) => value,
                onChanged: (value) => setState(() => _accel = value),
              ),
              _SettingsSelect<int>(
                label: 'Сканирование лиц',
                value: _faceScanDivisor,
                values: const [2, 4, 8, 16],
                display: (value) => '/$value',
                onChanged: (value) =>
                    setState(() => _faceScanDivisor = value),
              ),
              _SettingsSelect<int>(
                label: 'Оверлей эфира',
                value: _overlayFrameDivisor,
                values: const [1, 2, 4, 8],
                display: (value) => '/$value',
                onChanged: (value) =>
                    setState(() => _overlayFrameDivisor = value),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              OutlinedButton(
                onPressed: () => _applyPreset(2, 32, 8, 2),
                child: const Text('Экономия'),
              ),
              OutlinedButton(
                onPressed: () => _applyPreset(4, 25, 4, 1),
                child: const Text('Баланс'),
              ),
              OutlinedButton(
                onPressed: () => _applyPreset(6, 18, 2, 1),
                child: const Text('Максимум'),
              ),
              ElevatedButton.icon(
                onPressed: () => widget.onApply(_payload()),
                icon: const Icon(Icons.tune_rounded, size: 18),
                label: const Text('Применить настройки детекции'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _SettingsTextField extends StatelessWidget {
  const _SettingsTextField({
    required this.controller,
    required this.label,
  });

  final TextEditingController controller;
  final String label;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 220,
      child: TextField(
        controller: controller,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: InputDecoration(labelText: label),
      ),
    );
  }
}

class _SettingsSelect<T> extends StatelessWidget {
  const _SettingsSelect({
    required this.label,
    required this.value,
    required this.values,
    required this.display,
    required this.onChanged,
  });

  final String label;
  final T value;
  final List<T> values;
  final String Function(T value) display;
  final ValueChanged<T> onChanged;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 220,
      child: DropdownButtonFormField<T>(
        initialValue: values.contains(value) ? value : values.first,
        decoration: InputDecoration(labelText: label),
        items: [
          for (final item in values)
            DropdownMenuItem<T>(value: item, child: Text(display(item))),
        ],
        onChanged: (value) {
          if (value != null) onChanged(value);
        },
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
                  '${apiKey['description'] ?? 'API-ключ #${apiKey['api_key_id']}'}',
                  style: TextStyle(
                    color: colors.textStrong,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  'Права: ${formatCell(apiKey['scopes'])} · активен: ${formatCell(apiKey['is_active'])} · истекает: ${formatCell(apiKey['expires_at'])}',
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

class _CameraAssignmentList extends StatefulWidget {
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
  State<_CameraAssignmentList> createState() => _CameraAssignmentListState();
}

class _CameraAssignmentListState extends State<_CameraAssignmentList> {
  final _search = TextEditingController();

  @override
  void initState() {
    super.initState();
    _search.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final cameras = _filterAssignmentCameras(widget.cameras, _search.text);
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
            widget.title,
            style: TextStyle(
              color: colors.textStrong,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _search,
            decoration: InputDecoration(
              prefixIcon: const Icon(Icons.search_rounded),
              labelText: 'Поиск камер',
              suffixIcon: _search.text.isEmpty
                  ? null
                  : IconButton(
                      onPressed: _search.clear,
                      icon: const Icon(Icons.close_rounded),
                    ),
            ),
          ),
          const SizedBox(height: 10),
          if (widget.cameras.isEmpty)
            Text('Нет камер.', style: TextStyle(color: colors.muted))
          else if (cameras.isEmpty)
            Text('Под фильтр камер нет.', style: TextStyle(color: colors.muted))
          else
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final camera in cameras)
                  ActionChip(
                    avatar: Icon(widget.actionIcon, size: 18),
                    label: ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 220),
                      child: Text(
                        _assignmentCameraLabel(camera),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    onPressed: widget.onAction == null
                        ? null
                        : () => widget.onAction!(camera),
                    tooltip:
                        '${widget.actionLabel}: ${camera.name} · ${camera.ipAddress ?? 'IP не указан'} · ${camera.location ?? 'Локация не указана'}',
                  ),
              ],
            ),
        ],
      ),
    );
  }
}

List<CameraSummary> _filterAssignmentCameras(
  List<CameraSummary> cameras,
  String rawQuery,
) {
  final query = rawQuery.trim().toLowerCase();
  if (query.isEmpty) return cameras;
  final ipLike = RegExp(r'^[0-9.]+$').hasMatch(query);
  return cameras.where((camera) {
    final ip = (camera.ipAddress ?? '').toLowerCase();
    final stream = (camera.streamUrl ?? '').toLowerCase();
    if (ipLike) return ip.contains(query) || stream.contains(query);
    final text =
        '${camera.name} ${camera.location ?? ''} ${camera.connectionKind}'
            .toLowerCase();
    return _looseAdminContains(text, query);
  }).toList(growable: false);
}

String _assignmentCameraLabel(CameraSummary camera) {
  final detail = (camera.ipAddress ?? camera.location ?? '').trim();
  return detail.isEmpty ? camera.name : '${camera.name} · $detail';
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
                      'Не удалось открыть снимок',
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
                      labelText: 'Права через запятую',
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

String _candidateLabel(RowMap candidate) {
  final rawLabel = '${candidate['person_label'] ?? ''}'.trim();
  final label = rawLabel.isEmpty
      ? 'ID ${candidate['person_id'] ?? '-'}'
      : rawLabel;
  final value = candidate['probability'];
  final number = value is num ? value : num.tryParse('$value');
  if (number == null) return label;
  return '$label - ${number.toStringAsFixed(number >= 10 ? 0 : 1)}%';
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

int _settingInt(Object? value, int fallback) {
  final number = value is num ? value : num.tryParse('$value');
  return number?.toInt() ?? fallback;
}

double _settingDouble(Object? value, double fallback) {
  final number = value is num ? value : num.tryParse('$value');
  return number?.toDouble() ?? fallback;
}

int _settingChoice(Object? value, int fallback) {
  final number = _settingInt(value, fallback);
  return {1, 2, 4, 8, 16}.contains(number) ? number : fallback;
}

String _settingString(
  Object? value,
  String fallback,
  Set<String> allowed,
) {
  final raw = '$value'.trim().toLowerCase();
  return allowed.contains(raw) ? raw : fallback;
}

int _readInt(TextEditingController controller, int fallback) {
  return int.tryParse(controller.text.trim()) ?? fallback;
}

double _readDouble(TextEditingController controller, double fallback) {
  return double.tryParse(controller.text.trim().replaceAll(',', '.')) ??
      fallback;
}

String _commandLabel(String type) {
  return switch (type) {
    'reload_assignments' => 'Перезагрузить назначения',
    'restart_workers' => 'Перезапустить воркеры',
    'stop_all_cameras' => 'Остановить камеры',
    'resume_cameras' => 'Включить камеры',
    'refresh_gallery' => 'Обновить галерею',
    'start_runtime' => 'Запустить Runtime',
    'stop_runtime' => 'Остановить Runtime',
    'restart_runtime' => 'Перезапустить Runtime',
    'apply_detection_settings' => 'Применить настройки детекции',
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
