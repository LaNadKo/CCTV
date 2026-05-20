import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../core/network/api_client.dart';
import '../../core/theme/app_theme.dart';
import '../../shared/widgets/glass_panel.dart';
import '../auth/auth_controller.dart';

typedef RowMap = Map<String, dynamic>;

class RecordingsScreen extends StatelessWidget {
  const RecordingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DataModuleScreen(
      title: 'Записи',
      subtitle: 'Архив видео и снимков, которые backend получил от Processor.',
      icon: Icons.video_library_rounded,
      loadItems: (api, token) =>
          api.getJsonList('/recordings', token: token, query: {'limit': '100'}),
      columns: const [
        ModuleColumn('ID', ['recording_file_id'], width: 70),
        ModuleColumn('Камера', ['camera_id'], width: 80),
        ModuleColumn('Тип', ['file_kind'], width: 90),
        ModuleColumn('Начало', ['started_at'], width: 150),
        ModuleColumn('Длительность', ['duration_seconds'], width: 115),
        ModuleColumn('Размер', ['file_size_bytes'], width: 110),
        ModuleColumn('Путь', ['file_path'], width: 280),
      ],
    );
  }
}

class ReviewsScreen extends StatelessWidget {
  const ReviewsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DataModuleScreen(
      title: 'Ревью',
      subtitle: 'Проверка неизвестных и спорных событий распознавания.',
      icon: Icons.fact_check_rounded,
      loadItems: (api, token) =>
          api.getJsonList('/detections/pending', token: token),
      columns: const [
        ModuleColumn('ID', ['event_id'], width: 70),
        ModuleColumn('Камера', ['camera_name', 'camera_id'], width: 150),
        ModuleColumn('Тип', ['event_type', 'event_type_id'], width: 110),
        ModuleColumn('Персона', ['person_label', 'person_id'], width: 170),
        ModuleColumn('Уверенность', ['confidence'], width: 115),
        ModuleColumn('Время', ['event_ts'], width: 160),
      ],
      commands: [
        ModuleCommand(
          label: 'Отклонить всё',
          icon: Icons.clear_all_rounded,
          onRun: (context, api, token, reload) async {
            final ok = await confirmAction(
              context,
              title: 'Отклонить все события?',
              message: 'Все ожидающие ревью события получат статус rejected.',
            );
            if (!ok) return;
            await api.rejectAllPendingReviews(token);
            await reload();
          },
        ),
      ],
      rowCommands: [
        RowCommand(
          tooltip: 'Подтвердить',
          icon: Icons.check_rounded,
          color: (context) => context.colors.success,
          onRun: (context, api, token, row, reload) async {
            final id = rowInt(row, 'event_id');
            if (id == null) throw ApiException('Не найден event_id');
            await api.reviewEvent(token, id, 'approved');
            await reload();
          },
        ),
        RowCommand(
          tooltip: 'Отклонить',
          icon: Icons.close_rounded,
          color: (context) => context.colors.danger,
          onRun: (context, api, token, row, reload) async {
            final id = rowInt(row, 'event_id');
            if (id == null) throw ApiException('Не найден event_id');
            await api.reviewEvent(token, id, 'rejected');
            await reload();
          },
        ),
      ],
    );
  }
}

class GroupsScreen extends StatelessWidget {
  const GroupsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DataModuleScreen(
      title: 'Группы',
      subtitle: 'Логическое разделение камер по аудиториям, зонам и стендам.',
      icon: Icons.account_tree_rounded,
      loadItems: (api, token) => api.getJsonList('/groups', token: token),
      columns: const [
        ModuleColumn('ID', ['group_id'], width: 70),
        ModuleColumn('Название', ['name'], width: 190),
        ModuleColumn('Камер', ['camera_count'], width: 90),
        ModuleColumn('Описание', ['description'], width: 280),
        ModuleColumn('Создана', ['created_at'], width: 150),
      ],
      commands: [
        ModuleCommand(
          label: 'Добавить',
          icon: Icons.add_rounded,
          onRun: (context, api, token, reload) async {
            final values = await textFormDialog(
              context,
              title: 'Новая группа',
              fields: const [
                DialogField('name', 'Название', isRequired: true),
                DialogField('description', 'Описание', maxLines: 2),
              ],
            );
            if (values == null) return;
            await api.postJson(
              '/groups',
              token: token,
              body: cleanBody(values),
            );
            await reload();
          },
        ),
      ],
      rowCommands: [
        RowCommand.delete(
          idKey: 'group_id',
          title: 'Удалить группу?',
          pathBuilder: (id) => '/groups/$id',
        ),
      ],
    );
  }
}

class PersonsScreen extends StatelessWidget {
  const PersonsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DataModuleScreen(
      title: 'Персоны',
      subtitle: 'Карточки людей и количество обучающих эмбеддингов.',
      icon: Icons.badge_rounded,
      loadItems: (api, token) => api.getJsonList('/persons', token: token),
      columns: const [
        ModuleColumn('ID', ['person_id'], width: 70),
        ModuleColumn('Фамилия', ['last_name'], width: 150),
        ModuleColumn('Имя', ['first_name'], width: 150),
        ModuleColumn('Отчество', ['middle_name'], width: 150),
        ModuleColumn('Эмбеддинги', ['embeddings_count'], width: 120),
        ModuleColumn('Создана', ['created_at'], width: 150),
      ],
      commands: [
        ModuleCommand(
          label: 'Добавить',
          icon: Icons.person_add_alt_1_rounded,
          onRun: (context, api, token, reload) async {
            final values = await textFormDialog(
              context,
              title: 'Новая персона',
              fields: const [
                DialogField('last_name', 'Фамилия', isRequired: true),
                DialogField('first_name', 'Имя'),
                DialogField('middle_name', 'Отчество'),
              ],
            );
            if (values == null) return;
            await api.postJson(
              '/persons',
              token: token,
              body: cleanBody(values),
            );
            await reload();
          },
        ),
      ],
      rowCommands: [
        RowCommand.delete(
          idKey: 'person_id',
          title: 'Удалить персону?',
          pathBuilder: (id) => '/persons/$id',
        ),
      ],
    );
  }
}

class CamerasScreen extends StatelessWidget {
  const CamerasScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DataModuleScreen(
      title: 'Камеры',
      subtitle: 'ONVIF/RTSP/HTTP подключения, детекция и режим записи.',
      icon: Icons.videocam_rounded,
      loadItems: (api, token) => api.getJsonList('/cameras', token: token),
      columns: const [
        ModuleColumn('ID', ['camera_id'], width: 70),
        ModuleColumn('Название', ['name'], width: 170),
        ModuleColumn('Локация', ['location'], width: 170),
        ModuleColumn('IP', ['ip_address'], width: 130),
        ModuleColumn('Тип', ['connection_kind'], width: 100),
        ModuleColumn('ONVIF', ['onvif_enabled'], width: 90),
        ModuleColumn('PTZ', ['supports_ptz'], width: 80),
        ModuleColumn('Детекция', ['detection_enabled'], width: 95),
        ModuleColumn('Запись', ['recording_mode'], width: 110),
      ],
      commands: [
        ModuleCommand(
          label: 'Добавить',
          icon: Icons.add_rounded,
          onRun: (context, api, token, reload) async {
            final values = await textFormDialog(
              context,
              title: 'Новая камера',
              fields: const [
                DialogField('name', 'Название', isRequired: true),
                DialogField('ip_address', 'IP адрес'),
                DialogField('stream_url', 'RTSP/HTTP поток'),
                DialogField('location', 'Локация'),
                DialogField('connection_kind', 'Тип', initialValue: 'manual'),
              ],
            );
            if (values == null) return;
            await api.postJson(
              '/admin/cameras',
              token: token,
              body: {
                ...cleanBody(values),
                'detection_enabled': true,
                'recording_mode': 'event',
              },
            );
            await reload();
          },
        ),
      ],
      rowCommands: [
        RowCommand(
          tooltip: 'Обновить ONVIF',
          icon: Icons.sync_rounded,
          color: (context) => context.colors.primaryAccent,
          visible: (row) => rowBool(row, 'onvif_enabled'),
          onRun: (context, api, token, row, reload) async {
            final id = rowInt(row, 'camera_id');
            if (id == null) throw ApiException('Не найден camera_id');
            await api.postJson(
              '/admin/cameras/$id/onvif/refresh',
              token: token,
            );
            await reload();
          },
        ),
        RowCommand.delete(
          idKey: 'camera_id',
          title: 'Удалить камеру?',
          pathBuilder: (id) => '/admin/cameras/$id',
        ),
      ],
    );
  }
}

class ProcessorsScreen extends StatelessWidget {
  const ProcessorsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DataModuleScreen(
      title: 'Processor',
      subtitle: 'Узлы обработки видеопотоков, назначенные камеры и телеметрия.',
      icon: Icons.memory_rounded,
      loadItems: (api, token) => api.getJsonList('/processors', token: token),
      columns: const [
        ModuleColumn('ID', ['processor_id'], width: 70),
        ModuleColumn('Название', ['name'], width: 170),
        ModuleColumn('Статус', ['status'], width: 105),
        ModuleColumn('IP', ['ip_address', 'host'], width: 130),
        ModuleColumn('Версия', ['version'], width: 120),
        ModuleColumn('Камер', ['camera_count'], width: 90),
        ModuleColumn('Heartbeat', [
          'last_heartbeat',
          'last_heartbeat_at',
        ], width: 160),
      ],
      commands: [
        ModuleCommand(
          label: 'Код подключения',
          icon: Icons.key_rounded,
          onRun: (context, api, token, reload) async {
            final result = await api.postJson(
              '/processors/generate-code',
              token: token,
            );
            if (!context.mounted) return;
            await showResultDialog(
              context,
              title: 'Код Processor',
              value: '${result['code'] ?? ''}',
              note: 'Действует до: ${formatCell(result['expires_at'])}',
            );
          },
        ),
      ],
      rowCommands: [
        RowCommand.delete(
          idKey: 'processor_id',
          title: 'Удалить Processor?',
          pathBuilder: (id) => '/processors/$id',
        ),
      ],
    );
  }
}

class UsersScreen extends StatelessWidget {
  const UsersScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DataModuleScreen(
      title: 'Пользователи',
      subtitle: 'Учётные записи, роли и состояние обязательной смены пароля.',
      icon: Icons.manage_accounts_rounded,
      loadItems: (api, token) => api.getJsonList('/admin/users', token: token),
      columns: const [
        ModuleColumn('ID', ['user_id'], width: 70),
        ModuleColumn('Логин', ['login'], width: 140),
        ModuleColumn('Роль', ['role_id'], width: 90, formatter: roleName),
        ModuleColumn('Фамилия', ['last_name'], width: 140),
        ModuleColumn('Имя', ['first_name'], width: 140),
        ModuleColumn('Face login', ['face_login_enabled'], width: 110),
        ModuleColumn('Смена пароля', ['must_change_password'], width: 125),
      ],
      commands: [
        ModuleCommand(
          label: 'Добавить',
          icon: Icons.person_add_alt_rounded,
          onRun: (context, api, token, reload) async {
            final values = await textFormDialog(
              context,
              title: 'Новый пользователь',
              fields: const [
                DialogField('login', 'Логин', isRequired: true),
                DialogField(
                  'password',
                  'Пароль',
                  isRequired: true,
                  obscure: true,
                ),
                DialogField(
                  'role_id',
                  'Роль: 1 админ, 2 оператор, 3 наблюдатель',
                  initialValue: '3',
                ),
                DialogField('last_name', 'Фамилия'),
                DialogField('first_name', 'Имя'),
                DialogField('middle_name', 'Отчество'),
              ],
            );
            if (values == null) return;
            await api.postJson(
              '/admin/users',
              token: token,
              body: {
                ...cleanBody(values),
                'role_id': int.tryParse(values['role_id'] ?? '3') ?? 3,
              },
            );
            await reload();
          },
        ),
      ],
      rowCommands: [
        RowCommand.delete(
          idKey: 'user_id',
          title: 'Удалить пользователя?',
          pathBuilder: (id) => '/admin/users/$id',
        ),
      ],
    );
  }
}

class ApiKeysScreen extends StatelessWidget {
  const ApiKeysScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DataModuleScreen(
      title: 'API ключи',
      subtitle: 'Токены интеграции Processor и внешних клиентов.',
      icon: Icons.vpn_key_rounded,
      loadItems: (api, token) => api.getJsonList('/api-keys', token: token),
      columns: const [
        ModuleColumn('ID', ['api_key_id'], width: 70),
        ModuleColumn('Описание', ['description'], width: 240),
        ModuleColumn('Scopes', ['scopes'], width: 220),
        ModuleColumn('Активен', ['is_active'], width: 90),
        ModuleColumn('Создан', ['created_at'], width: 150),
        ModuleColumn('Истекает', ['expires_at'], width: 150),
      ],
      commands: [
        ModuleCommand(
          label: 'Создать',
          icon: Icons.add_rounded,
          onRun: (context, api, token, reload) async {
            final values = await textFormDialog(
              context,
              title: 'Новый API ключ',
              fields: const [
                DialogField('description', 'Описание', isRequired: true),
                DialogField(
                  'scopes',
                  'Scopes через запятую',
                  initialValue: 'detections:create',
                ),
              ],
            );
            if (values == null) return;
            final scopes = (values['scopes'] ?? '')
                .split(',')
                .map((value) => value.trim())
                .where((value) => value.isNotEmpty)
                .toList();
            final result = await api.postJson(
              '/api-keys',
              token: token,
              body: {'description': values['description'], 'scopes': scopes},
            );
            if (!context.mounted) return;
            await showResultDialog(
              context,
              title: 'Новый API ключ',
              value: '${result['api_key'] ?? ''}',
              note: 'Ключ показывается один раз.',
            );
            await reload();
          },
        ),
      ],
      rowCommands: [
        RowCommand.delete(
          idKey: 'api_key_id',
          title: 'Удалить API ключ?',
          pathBuilder: (id) => '/api-keys/$id',
        ),
      ],
    );
  }
}

class ReportsScreen extends StatefulWidget {
  const ReportsScreen({super.key});

  @override
  State<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends State<ReportsScreen> {
  bool _loading = false;
  String? _error;
  RowMap? _dashboard;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final token = context.read<AuthController>().accessToken;
    final api = context.read<ApiClient>();
    if (token == null) return;

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final json = await api.getJson('/reports/dashboard', token: token);
      if (!mounted) return;
      setState(() => _dashboard = mapFrom(json));
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final data = _dashboard;
    final events = mapFrom(data?['events']);
    final archive = mapFrom(data?['archive']);
    final security = mapFrom(data?['security']);
    final userActions = mapFrom(data?['user_actions']);

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          ModuleHeader(
            title: 'Отчёты',
            subtitle: data == null
                ? 'Сводка по системе видеонаблюдения.'
                : 'Сформировано: ${formatCell(data['generated_at'])}',
            icon: Icons.analytics_rounded,
            trailing: RefreshButton(loading: _loading, onPressed: _load),
          ),
          if (_error != null) ErrorPanel(message: _error!, onRetry: _load),
          const SizedBox(height: 14),
          if (data == null && !_loading)
            const EmptyPanel(message: 'Backend пока не вернул отчёт.')
          else if (data != null) ...[
            _MetricRail(
              items: [
                MetricItem('Событий', formatCell(events['total_events'])),
                MetricItem(
                  'Ожидают ревью',
                  formatCell(events['pending_reviews']),
                ),
                MetricItem('Записей', formatCell(archive['total_files'])),
                MetricItem(
                  'Пользователей',
                  formatCell(security['total_users']),
                ),
              ],
            ),
            const SizedBox(height: 14),
            ReportTable(
              title: 'Камеры',
              rows: listFrom(data['cameras']),
              columns: const [
                ModuleColumn('Камера', ['name'], width: 180),
                ModuleColumn('Группа', ['group_name'], width: 150),
                ModuleColumn('Online', ['is_online'], width: 80),
                ModuleColumn('События', ['event_count'], width: 95),
                ModuleColumn('Ревью', ['pending_reviews'], width: 90),
                ModuleColumn('Записи', ['recordings_count'], width: 90),
              ],
            ),
            const SizedBox(height: 14),
            ReportTable(
              title: 'Processor',
              rows: listFrom(data['processors']),
              columns: const [
                ModuleColumn('Узел', ['name'], width: 180),
                ModuleColumn('Статус', ['status'], width: 100),
                ModuleColumn('Камер', ['assigned_cameras'], width: 90),
                ModuleColumn('CPU', ['cpu_percent'], width: 80),
                ModuleColumn('RAM', ['ram_percent'], width: 80),
                ModuleColumn('GPU', ['gpu_util_percent'], width: 80),
              ],
            ),
            const SizedBox(height: 14),
            _ReportSummary(
              title: 'Безопасность и действия',
              rows: {
                'Активные пользователи': userActions['active_users'],
                'Успешные входы': security['successful_logins'],
                'Ошибки входа': security['failed_logins'],
                'TOTP пользователей': security['totp_enabled_users'],
                'Активные API ключи': security['api_keys_active'],
              },
            ),
            const SizedBox(height: 24),
          ],
        ],
      ),
    );
  }
}

class HelpScreen extends StatelessWidget {
  const HelpScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return ListView(
      children: [
        const ModuleHeader(
          title: 'Справка',
          subtitle: 'Краткая карта модулей нативной консоли.',
          icon: Icons.help_outline_rounded,
        ),
        const SizedBox(height: 14),
        GlassPanel(
          padding: const EdgeInsets.all(18),
          child: DefaultTextStyle(
            style: TextStyle(color: colors.text, fontSize: 14, height: 1.55),
            child: const Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                HelpLine(
                  'Live',
                  'просмотр потоков и быстрые ONVIF/PTZ команды.',
                ),
                HelpLine('Записи', 'архив файлов, созданных Processor.'),
                HelpLine(
                  'Ревью',
                  'подтверждение или отклонение событий распознавания.',
                ),
                HelpLine(
                  'Камеры',
                  'подключения, ONVIF обновление и удаление камер.',
                ),
                HelpLine(
                  'Processor',
                  'узлы обработки, код подключения и состояние.',
                ),
                HelpLine(
                  'Настройки',
                  'адрес backend, тема, акценты и плотность Live.',
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class DataModuleScreen extends StatefulWidget {
  const DataModuleScreen({
    super.key,
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.loadItems,
    required this.columns,
    this.commands = const [],
    this.rowCommands = const [],
  });

  final String title;
  final String subtitle;
  final IconData icon;
  final Future<List<RowMap>> Function(ApiClient api, String token) loadItems;
  final List<ModuleColumn> columns;
  final List<ModuleCommand> commands;
  final List<RowCommand> rowCommands;

  @override
  State<DataModuleScreen> createState() => _DataModuleScreenState();
}

class _DataModuleScreenState extends State<DataModuleScreen> {
  final _searchController = TextEditingController();
  bool _loading = false;
  String? _error;
  List<RowMap> _items = const [];

  @override
  void initState() {
    super.initState();
    _searchController.addListener(() => setState(() {}));
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final token = context.read<AuthController>().accessToken;
    final api = context.read<ApiClient>();
    if (token == null) return;

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final items = await widget.loadItems(api, token);
      if (!mounted) return;
      setState(() => _items = items);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  List<RowMap> get _filtered {
    final query = _searchController.text.trim().toLowerCase();
    if (query.isEmpty) return _items;
    return _items.where((row) {
      return row.values.any((value) => '$value'.toLowerCase().contains(query));
    }).toList();
  }

  Future<void> _runModuleCommand(ModuleCommand command) async {
    final token = context.read<AuthController>().accessToken;
    final api = context.read<ApiClient>();
    if (token == null) return;
    try {
      await command.onRun(context, api, token, _load);
    } catch (error) {
      if (!mounted) return;
      showErrorSnack(context, '$error');
    }
  }

  Future<void> _runRowCommand(RowCommand command, RowMap row) async {
    final token = context.read<AuthController>().accessToken;
    final api = context.read<ApiClient>();
    if (token == null) return;
    try {
      await command.onRun(context, api, token, row, _load);
    } catch (error) {
      if (!mounted) return;
      showErrorSnack(context, '$error');
    }
  }

  @override
  Widget build(BuildContext context) {
    final filtered = _filtered;
    final colors = context.colors;

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          ModuleHeader(
            title: widget.title,
            subtitle: widget.subtitle,
            icon: widget.icon,
            trailing: Wrap(
              spacing: 10,
              runSpacing: 8,
              children: [
                for (final command in widget.commands)
                  ElevatedButton.icon(
                    onPressed: () => _runModuleCommand(command),
                    icon: Icon(command.icon, size: 18),
                    label: Text(command.label),
                  ),
                RefreshButton(loading: _loading, onPressed: _load),
              ],
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _searchController,
            decoration: InputDecoration(
              prefixIcon: const Icon(Icons.search_rounded),
              labelText: 'Поиск',
              suffixIcon: _searchController.text.isEmpty
                  ? null
                  : IconButton(
                      onPressed: _searchController.clear,
                      icon: const Icon(Icons.close_rounded),
                    ),
            ),
          ),
          const SizedBox(height: 14),
          if (_error != null) ErrorPanel(message: _error!, onRetry: _load),
          if (_error != null) const SizedBox(height: 14),
          if (filtered.isEmpty && !_loading)
            EmptyPanel(
              message: _items.isEmpty
                  ? 'Данных пока нет.'
                  : 'Ничего не найдено.',
            )
          else
            GlassPanel(
              padding: const EdgeInsets.all(10),
              child: Scrollbar(
                thumbVisibility: true,
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    headingRowHeight: 38,
                    dataRowMinHeight: 42,
                    dataRowMaxHeight: 54,
                    horizontalMargin: 10,
                    columnSpacing: 14,
                    headingTextStyle: TextStyle(
                      color: colors.muted,
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                    ),
                    dataTextStyle: TextStyle(
                      color: colors.text,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                    columns: [
                      for (final column in widget.columns)
                        DataColumn(
                          label: SizedBox(
                            width: column.width,
                            child: Text(column.label),
                          ),
                        ),
                      if (widget.rowCommands.isNotEmpty)
                        const DataColumn(
                          label: SizedBox(width: 104, child: Text('Действия')),
                        ),
                    ],
                    rows: [
                      for (final row in filtered)
                        DataRow(
                          cells: [
                            for (final column in widget.columns)
                              DataCell(
                                SizedBox(
                                  width: column.width,
                                  child: Text(
                                    column.read(row),
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                              ),
                            if (widget.rowCommands.isNotEmpty)
                              DataCell(
                                SizedBox(
                                  width: 104,
                                  child: Row(
                                    children: [
                                      for (final command in widget.rowCommands)
                                        if (command.visible(row))
                                          IconButton(
                                            tooltip: command.tooltip,
                                            onPressed: () =>
                                                _runRowCommand(command, row),
                                            icon: Icon(
                                              command.icon,
                                              size: 19,
                                              color: command.color(context),
                                            ),
                                          ),
                                    ],
                                  ),
                                ),
                              ),
                          ],
                        ),
                    ],
                  ),
                ),
              ),
            ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}

class ModuleHeader extends StatelessWidget {
  const ModuleHeader({
    super.key,
    required this.title,
    required this.subtitle,
    required this.icon,
    this.trailing,
  });

  final String title;
  final String subtitle;
  final IconData icon;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 46,
          height: 46,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            color: colors.surfaceMuted,
            border: Border.all(color: colors.border),
          ),
          child: Icon(icon, color: colors.primaryAccent, size: 22),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  color: colors.textStrong,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                subtitle,
                style: TextStyle(color: colors.muted, fontSize: 14),
              ),
            ],
          ),
        ),
        if (trailing != null) ...[const SizedBox(width: 12), trailing!],
      ],
    );
  }
}

class ModuleColumn {
  const ModuleColumn(this.label, this.keys, {this.width = 140, this.formatter});

  final String label;
  final List<String> keys;
  final double width;
  final String Function(Object? value)? formatter;

  String read(RowMap row) {
    Object? value;
    for (final key in keys) {
      if (row.containsKey(key) && row[key] != null) {
        value = row[key];
        break;
      }
    }
    if (formatter != null) return formatter!(value);
    return formatCell(value, keyHint: keys.isEmpty ? null : keys.first);
  }
}

class ModuleCommand {
  const ModuleCommand({
    required this.label,
    required this.icon,
    required this.onRun,
  });

  final String label;
  final IconData icon;
  final Future<void> Function(
    BuildContext context,
    ApiClient api,
    String token,
    Future<void> Function() reload,
  )
  onRun;
}

class RowCommand {
  const RowCommand({
    required this.tooltip,
    required this.icon,
    required this.onRun,
    this.color = defaultRowCommandColor,
    this.visible = alwaysVisible,
  });

  factory RowCommand.delete({
    required String idKey,
    required String title,
    required String Function(int id) pathBuilder,
  }) {
    return RowCommand(
      tooltip: 'Удалить',
      icon: Icons.delete_outline_rounded,
      color: (context) => context.colors.danger,
      onRun: (context, api, token, row, reload) async {
        final id = rowInt(row, idKey);
        if (id == null) throw ApiException('Не найден $idKey');
        final ok = await confirmAction(
          context,
          title: title,
          message: 'Действие нельзя отменить.',
        );
        if (!ok) return;
        await api.deleteVoid(pathBuilder(id), token: token);
        await reload();
      },
    );
  }

  final String tooltip;
  final IconData icon;
  final Future<void> Function(
    BuildContext context,
    ApiClient api,
    String token,
    RowMap row,
    Future<void> Function() reload,
  )
  onRun;
  final Color Function(BuildContext context) color;
  final bool Function(RowMap row) visible;
}

class DialogField {
  const DialogField(
    this.key,
    this.label, {
    this.isRequired = false,
    this.obscure = false,
    this.initialValue = '',
    this.maxLines = 1,
  });

  final String key;
  final String label;
  final bool isRequired;
  final bool obscure;
  final String initialValue;
  final int maxLines;
}

class RefreshButton extends StatelessWidget {
  const RefreshButton({
    super.key,
    required this.loading,
    required this.onPressed,
  });

  final bool loading;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: loading ? null : onPressed,
      icon: loading
          ? const SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : const Icon(Icons.refresh_rounded, size: 18),
      label: const Text('Обновить'),
    );
  }
}

class ErrorPanel extends StatelessWidget {
  const ErrorPanel({super.key, required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(14),
      child: Row(
        children: [
          Icon(Icons.warning_rounded, color: colors.warning, size: 20),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: TextStyle(color: colors.text, fontSize: 13),
            ),
          ),
          OutlinedButton(onPressed: onRetry, child: const Text('Повторить')),
        ],
      ),
    );
  }
}

class EmptyPanel extends StatelessWidget {
  const EmptyPanel({super.key, required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(18),
      child: Text(message, style: TextStyle(color: colors.muted, fontSize: 14)),
    );
  }
}

class MetricItem {
  const MetricItem(this.label, this.value);

  final String label;
  final String value;
}

class _MetricRail extends StatelessWidget {
  const _MetricRail({required this.items});

  final List<MetricItem> items;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
      child: Wrap(
        spacing: 28,
        runSpacing: 14,
        children: [
          for (final item in items)
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.value,
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    color: colors.textStrong,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                Text(
                  item.label,
                  style: TextStyle(color: colors.muted, fontSize: 12),
                ),
              ],
            ),
        ],
      ),
    );
  }
}

class ReportTable extends StatelessWidget {
  const ReportTable({
    super.key,
    required this.title,
    required this.rows,
    required this.columns,
  });

  final String title;
  final List<RowMap> rows;
  final List<ModuleColumn> columns;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(14),
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
          if (rows.isEmpty)
            Text('Нет данных.', style: TextStyle(color: colors.muted))
          else
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: DataTable(
                headingRowHeight: 34,
                dataRowMinHeight: 38,
                dataRowMaxHeight: 48,
                horizontalMargin: 8,
                columnSpacing: 12,
                headingTextStyle: TextStyle(
                  color: colors.muted,
                  fontSize: 12,
                  fontWeight: FontWeight.w800,
                ),
                dataTextStyle: TextStyle(color: colors.text, fontSize: 13),
                columns: [
                  for (final column in columns)
                    DataColumn(
                      label: SizedBox(
                        width: column.width,
                        child: Text(column.label),
                      ),
                    ),
                ],
                rows: [
                  for (final row in rows.take(20))
                    DataRow(
                      cells: [
                        for (final column in columns)
                          DataCell(
                            SizedBox(
                              width: column.width,
                              child: Text(
                                column.read(row),
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
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

class _ReportSummary extends StatelessWidget {
  const _ReportSummary({required this.title, required this.rows});

  final String title;
  final Map<String, Object?> rows;

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
          const SizedBox(height: 12),
          for (final entry in rows.entries)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 5),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      entry.key,
                      style: TextStyle(color: colors.muted),
                    ),
                  ),
                  Text(
                    formatCell(entry.value),
                    style: TextStyle(
                      color: colors.textStrong,
                      fontWeight: FontWeight.w800,
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

class HelpLine extends StatelessWidget {
  const HelpLine(this.title, this.body, {super.key});

  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: RichText(
        text: TextSpan(
          style: TextStyle(color: colors.text, fontSize: 14, height: 1.45),
          children: [
            TextSpan(
              text: '$title: ',
              style: TextStyle(
                color: colors.textStrong,
                fontWeight: FontWeight.w900,
              ),
            ),
            TextSpan(text: body),
          ],
        ),
      ),
    );
  }
}

Future<Map<String, String>?> textFormDialog(
  BuildContext context, {
  required String title,
  required List<DialogField> fields,
}) async {
  final formKey = GlobalKey<FormState>();
  final controllers = {
    for (final field in fields)
      field.key: TextEditingController(text: field.initialValue),
  };

  try {
    return await showDialog<Map<String, String>>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          title: Text(title),
          content: SizedBox(
            width: 420,
            child: Form(
              key: formKey,
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    for (final field in fields)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: TextFormField(
                          controller: controllers[field.key],
                          obscureText: field.obscure,
                          maxLines: field.obscure ? 1 : field.maxLines,
                          decoration: InputDecoration(labelText: field.label),
                          validator: (value) {
                            if (field.isRequired &&
                                (value ?? '').trim().isEmpty) {
                              return 'Заполните поле';
                            }
                            return null;
                          },
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: const Text('Отмена'),
            ),
            ElevatedButton(
              onPressed: () {
                if (!formKey.currentState!.validate()) return;
                Navigator.of(dialogContext).pop({
                  for (final entry in controllers.entries)
                    entry.key: entry.value.text.trim(),
                });
              },
              child: const Text('Сохранить'),
            ),
          ],
        );
      },
    );
  } finally {
    for (final controller in controllers.values) {
      controller.dispose();
    }
  }
}

Future<bool> confirmAction(
  BuildContext context, {
  required String title,
  required String message,
}) async {
  final result = await showDialog<bool>(
    context: context,
    builder: (dialogContext) {
      return AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Отмена'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Подтвердить'),
          ),
        ],
      );
    },
  );
  return result ?? false;
}

Future<void> showResultDialog(
  BuildContext context, {
  required String title,
  required String value,
  String? note,
}) {
  return showDialog<void>(
    context: context,
    builder: (dialogContext) {
      final colors = dialogContext.colors;
      return AlertDialog(
        title: Text(title),
        content: SelectableText(
          [value, if (note != null && note.isNotEmpty) '\n$note'].join('\n'),
          style: TextStyle(
            color: colors.textStrong,
            fontSize: 15,
            fontWeight: FontWeight.w800,
          ),
        ),
        actions: [
          ElevatedButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Закрыть'),
          ),
        ],
      );
    },
  );
}

Map<String, dynamic> cleanBody(Map<String, String> values) {
  return {
    for (final entry in values.entries)
      if (entry.value.trim().isNotEmpty) entry.key: entry.value.trim(),
  };
}

String formatCell(Object? value, {String? keyHint}) {
  if (value == null) return '—';
  if (value is bool) return value ? 'Да' : 'Нет';
  if (value is List) return value.isEmpty ? '—' : value.join(', ');
  if (value is Map) return value.isEmpty ? '—' : '${value.length} полей';
  if (value is num) {
    if ((keyHint ?? '').contains('bytes')) return formatBytes(value);
    if (value is double && value != value.roundToDouble()) {
      return value.toStringAsFixed(2);
    }
    return '$value';
  }
  final text = '$value';
  final date = DateTime.tryParse(text);
  if (date != null &&
      (keyHint?.contains('_at') == true || keyHint?.contains('_ts') == true)) {
    return DateFormat('dd.MM.yyyy HH:mm').format(date.toLocal());
  }
  return text.isEmpty ? '—' : text;
}

String formatBytes(num bytes) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  var value = bytes.toDouble();
  var index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index++;
  }
  return '${value.toStringAsFixed(index == 0 ? 0 : 1)} ${units[index]}';
}

String roleName(Object? value) {
  final id = int.tryParse('$value');
  if (id == 1) return 'Админ';
  if (id == 2) return 'Оператор';
  return 'Наблюдатель';
}

int? rowInt(RowMap row, String key) {
  final value = row[key];
  if (value is int) return value;
  return int.tryParse('$value');
}

bool rowBool(RowMap row, String key) {
  final value = row[key];
  if (value is bool) return value;
  return '$value'.toLowerCase() == 'true';
}

Map<String, dynamic> mapFrom(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return value.map((key, item) => MapEntry('$key', item));
  return <String, dynamic>{};
}

List<RowMap> listFrom(Object? value) {
  if (value is! List) return const [];
  return value.map(mapFrom).toList();
}

bool alwaysVisible(RowMap row) => true;

Color defaultRowCommandColor(BuildContext context) => context.colors.textStrong;

void showErrorSnack(BuildContext context, String message) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
}
