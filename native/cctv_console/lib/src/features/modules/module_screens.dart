import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../core/network/api_client.dart';
import '../../core/theme/app_theme.dart';
import '../../shared/widgets/glass_panel.dart';
import '../../shared/widgets/segmented_code_field.dart';
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

class ReviewsScreen extends StatefulWidget {
  const ReviewsScreen({super.key});

  @override
  State<ReviewsScreen> createState() => _ReviewsScreenState();
}

class _ReviewsScreenState extends State<ReviewsScreen> {
  final _searchController = TextEditingController();
  bool _loading = false;
  String? _error;
  List<RowMap> _events = const [];

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
      final events = await api.getJsonList('/detections/pending', token: token);
      if (!mounted) return;
      setState(() => _events = events);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  List<RowMap> get _filtered {
    final query = _searchController.text.trim().toLowerCase();
    if (query.isEmpty) return _events;
    return _events.where((row) {
      return row.values.any((value) => '$value'.toLowerCase().contains(query));
    }).toList();
  }

  Future<void> _review(RowMap row, String status) async {
    final token = context.read<AuthController>().accessToken;
    final api = context.read<ApiClient>();
    final id = rowInt(row, 'event_id');
    if (token == null || id == null) return;
    try {
      await api.reviewEvent(token, id, status);
      await _load();
    } catch (error) {
      if (!mounted) return;
      showErrorSnack(context, '$error');
    }
  }

  Future<void> _rejectAll() async {
    final token = context.read<AuthController>().accessToken;
    final api = context.read<ApiClient>();
    if (token == null) return;
    final ok = await confirmAction(
      context,
      title: 'Отклонить все события?',
      message: 'Все ожидающие ревью события получат статус rejected.',
    );
    if (!ok) return;
    try {
      await api.rejectAllPendingReviews(token);
      await _load();
    } catch (error) {
      if (!mounted) return;
      showErrorSnack(context, '$error');
    }
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
                      'Проверка неизвестных и спорных событий распознавания.',
                  icon: Icons.fact_check_rounded,
                  trailing: Wrap(
                    spacing: 10,
                    runSpacing: 8,
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
                  controller: _searchController,
                  decoration: InputDecoration(
                    prefixIcon: const Icon(Icons.search_rounded),
                    labelText: 'Поиск по событиям',
                    suffixIcon: _searchController.text.isEmpty
                        ? null
                        : IconButton(
                            onPressed: _searchController.clear,
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
            const _LoadingRowsSliver(count: 5)
          else if (filtered.isEmpty && !_loading)
            SliverToBoxAdapter(
              child: EmptyPanel(
                message: _events.isEmpty
                    ? 'Очередь ревью пуста.'
                    : 'Ничего не найдено.',
              ),
            )
          else
            SliverList.builder(
              itemCount: filtered.length,
              itemBuilder: (context, index) {
                final row = filtered[index];
                return Padding(
                  padding: const EdgeInsets.only(bottom: 14),
                  child: _ReviewEventCard(
                    row: row,
                    onApprove: () => _review(row, 'approved'),
                    onReject: () => _review(row, 'rejected'),
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

class _ReviewEventCard extends StatelessWidget {
  const _ReviewEventCard({
    required this.row,
    required this.onApprove,
    required this.onReject,
  });

  final RowMap row;
  final VoidCallback onApprove;
  final VoidCallback onReject;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final api = context.read<ApiClient>();
    final token = context.read<AuthController>().accessToken;
    final snapshotUrl = _snapshotUrl(api, row);
    final details = [
      _Detail('ID', formatCell(row['event_id'])),
      _Detail('Камера', formatCell(row['camera_name'] ?? row['camera_id'])),
      _Detail('Локация', formatCell(row['camera_location'])),
      _Detail('Время', formatCell(row['event_ts'], keyHint: 'event_ts')),
      _Detail('Уверенность', formatCell(row['confidence'])),
    ];

    return GlassPanel(
      padding: const EdgeInsets.all(14),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 760;
          final image = _SnapshotPreview(url: snapshotUrl, token: token);
          final info = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Событие #${formatCell(row['event_id'])}',
                style: TextStyle(
                  color: colors.textStrong,
                  fontSize: 16,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 10,
                runSpacing: 8,
                children: [
                  for (final detail in details)
                    _DetailPill(label: detail.label, value: detail.value),
                ],
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 10,
                runSpacing: 8,
                children: [
                  ElevatedButton.icon(
                    onPressed: onApprove,
                    icon: const Icon(Icons.check_rounded, size: 18),
                    label: const Text('Подтвердить'),
                  ),
                  OutlinedButton.icon(
                    onPressed: onReject,
                    icon: Icon(
                      Icons.close_rounded,
                      size: 18,
                      color: colors.danger,
                    ),
                    label: const Text('Отклонить'),
                  ),
                ],
              ),
            ],
          );

          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [image, const SizedBox(height: 12), info],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(width: 260, child: image),
              const SizedBox(width: 16),
              Expanded(child: info),
            ],
          );
        },
      ),
    );
  }

  String? _snapshotUrl(ApiClient api, RowMap row) {
    final value = row['snapshot_url'];
    if (value == null || '$value'.isEmpty) return null;
    final text = '$value';
    if (text.startsWith('http://') || text.startsWith('https://')) {
      return text;
    }
    return api.uri(text).toString();
  }
}

class _SnapshotPreview extends StatelessWidget {
  const _SnapshotPreview({required this.url, required this.token});

  final String? url;
  final String? token;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AspectRatio(
      aspectRatio: 16 / 9,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(16),
        child: Container(
          color: Colors.black.withValues(alpha: 0.25),
          child: url == null
              ? const _SnapshotFallback(text: 'Snapshot не сохранён')
              : Image.network(
                  url!,
                  fit: BoxFit.cover,
                  headers: token == null
                      ? null
                      : {'Authorization': 'Bearer $token'},
                  errorBuilder: (context, error, stackTrace) {
                    return const _SnapshotFallback(
                      text: 'Не удалось открыть фото',
                    );
                  },
                  loadingBuilder: (context, child, loadingProgress) {
                    if (loadingProgress == null) return child;
                    return Center(
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: colors.primaryAccent,
                      ),
                    );
                  },
                ),
        ),
      ),
    );
  }
}

class _SnapshotFallback extends StatelessWidget {
  const _SnapshotFallback({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.image_not_supported_rounded, color: colors.muted),
          const SizedBox(height: 8),
          Text(text, style: TextStyle(color: colors.muted, fontSize: 12)),
        ],
      ),
    );
  }
}

class _Detail {
  const _Detail(this.label, this.value);

  final String label;
  final String value;
}

class _DetailPill extends StatelessWidget {
  const _DetailPill({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            label,
            style: TextStyle(
              color: colors.muted,
              fontSize: 11,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            value,
            style: TextStyle(
              color: colors.textStrong,
              fontSize: 13,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
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
              segmentedCode: true,
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
          if (data == null && _loading)
            const _LoadingReportPanel()
          else if (data == null && !_loading)
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
                  'Размер архива',
                  formatCell(archive['total_bytes'], keyHint: 'bytes'),
                ),
                MetricItem(
                  'Online камер',
                  '${formatCell(_countOnline(listFrom(data['cameras'])))} / ${formatCell(listFrom(data['cameras']).length)}',
                ),
                MetricItem(
                  'Пользователей',
                  formatCell(security['total_users']),
                ),
              ],
            ),
            const SizedBox(height: 14),
            LayoutBuilder(
              builder: (context, constraints) {
                final compact = constraints.maxWidth < 860;
                final cards = [
                  _ReportSummary(
                    title: 'События и ревью',
                    rows: {
                      'Всего событий': events['total_events'],
                      'Распознано': events['recognized_events'],
                      'Неизвестные': events['unknown_events'],
                      'Движение': events['motion_events'],
                      'Персоны': events['person_events'],
                      'Ожидают ревью': events['pending_reviews'],
                      'Подтверждено': events['approved_reviews'],
                      'Отклонено': events['rejected_reviews'],
                      'Среднее время ревью, сек':
                          events['average_review_seconds'],
                    },
                  ),
                  _ReportSummary(
                    title: 'Безопасность',
                    rows: {
                      'Пользователей': security['total_users'],
                      'TOTP включён': security['totp_enabled_users'],
                      'Покрытие TOTP, %': security['totp_coverage_percent'],
                      'API ключей всего': security['api_keys_total'],
                      'API ключей активно': security['api_keys_active'],
                      'Успешные входы': security['successful_logins'],
                      'Ошибки входа': security['failed_logins'],
                    },
                  ),
                ];
                if (compact) {
                  return Column(
                    children: [cards[0], const SizedBox(height: 14), cards[1]],
                  );
                }
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: cards[0]),
                    const SizedBox(width: 14),
                    Expanded(child: cards[1]),
                  ],
                );
              },
            ),
            const SizedBox(height: 14),
            ReportTable(
              title: 'Группы камер',
              rows: listFrom(data['groups']),
              columns: const [
                ModuleColumn('Группа', ['name'], width: 170),
                ModuleColumn('Камер', ['camera_count'], width: 75),
                ModuleColumn('Online', ['online_cameras'], width: 80),
                ModuleColumn('Offline', ['offline_cameras'], width: 80),
                ModuleColumn('События', ['event_count'], width: 90),
                ModuleColumn('Распознано', ['recognized_count'], width: 105),
                ModuleColumn('Ревью', ['pending_reviews'], width: 80),
                ModuleColumn('Записей', ['recordings_count'], width: 85),
                ModuleColumn('Размер', ['recordings_size_bytes'], width: 100),
              ],
            ),
            const SizedBox(height: 14),
            ReportTable(
              title: 'Камеры',
              rows: listFrom(data['cameras']),
              columns: const [
                ModuleColumn('Камера', ['name'], width: 180),
                ModuleColumn('Группа', ['group_name'], width: 150),
                ModuleColumn('Локация', ['location'], width: 150),
                ModuleColumn('Тип', ['connection_kind'], width: 90),
                ModuleColumn('Processor', ['assigned_processor'], width: 150),
                ModuleColumn('Online', ['is_online'], width: 80),
                ModuleColumn('PTZ', ['supports_ptz'], width: 70),
                ModuleColumn('Детекция', ['detection_enabled'], width: 90),
                ModuleColumn('События', ['event_count'], width: 95),
                ModuleColumn('Распознано', ['recognized_count'], width: 105),
                ModuleColumn('Неизв.', ['unknown_count'], width: 80),
                ModuleColumn('Движение', ['motion_count'], width: 90),
                ModuleColumn('Ревью', ['pending_reviews'], width: 90),
                ModuleColumn('Записи', ['recordings_count'], width: 90),
                ModuleColumn('Размер', ['recordings_size_bytes'], width: 100),
                ModuleColumn('Последнее', ['last_event_ts'], width: 145),
              ],
            ),
            const SizedBox(height: 14),
            ReportTable(
              title: 'Processor',
              rows: listFrom(data['processors']),
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
            const SizedBox(height: 14),
            ReportTable(
              title: 'Архив по камерам',
              rows: listFrom(archive['by_camera']),
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
            const SizedBox(height: 14),
            ReportTable(
              title: 'Хранилища',
              rows: listFrom(archive['by_storage']),
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
            const SizedBox(height: 14),
            LayoutBuilder(
              builder: (context, constraints) {
                final compact = constraints.maxWidth < 900;
                final tables = [
                  ReportTable(
                    title: 'Действия пользователей',
                    rows: listFrom(userActions['top_users']),
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
                    rows: listFrom(userActions['recent_actions']),
                    columns: const [
                      ModuleColumn('Время', [
                        'created_at',
                        'event_ts',
                      ], width: 145),
                      ModuleColumn('Пользователь', [
                        'login',
                        'user_name',
                      ], width: 160),
                      ModuleColumn('Действие', ['action'], width: 170),
                      ModuleColumn('Объект', ['entity', 'target'], width: 150),
                    ],
                  ),
                ];
                if (compact) {
                  return Column(
                    children: [
                      tables[0],
                      const SizedBox(height: 14),
                      tables[1],
                    ],
                  );
                }
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: tables[0]),
                    const SizedBox(width: 14),
                    Expanded(child: tables[1]),
                  ],
                );
              },
            ),
            const SizedBox(height: 14),
            LayoutBuilder(
              builder: (context, constraints) {
                final compact = constraints.maxWidth < 900;
                final tables = [
                  ReportTable(
                    title: 'Типы событий',
                    rows: listFrom(events['events_by_type']),
                    columns: const [
                      ModuleColumn('Тип', ['event_type', 'type'], width: 150),
                      ModuleColumn('Количество', ['count'], width: 105),
                    ],
                  ),
                  ReportTable(
                    title: 'Ревьюеры',
                    rows: listFrom(events['top_reviewers']),
                    columns: const [
                      ModuleColumn('Пользователь', [
                        'login',
                        'user_name',
                      ], width: 170),
                      ModuleColumn('Ревью', ['review_count'], width: 90),
                      ModuleColumn('Среднее, сек', [
                        'average_seconds',
                      ], width: 110),
                    ],
                  ),
                  ReportTable(
                    title: 'Ошибки входа',
                    rows: listFrom(security['recent_failures']),
                    columns: const [
                      ModuleColumn('Время', [
                        'created_at',
                        'event_ts',
                      ], width: 145),
                      ModuleColumn('Логин', ['login'], width: 150),
                      ModuleColumn('IP', ['ip_address'], width: 130),
                      ModuleColumn('Причина', ['reason'], width: 180),
                    ],
                  ),
                ];
                if (compact) {
                  return Column(
                    children: [
                      tables[0],
                      const SizedBox(height: 14),
                      tables[1],
                      const SizedBox(height: 14),
                      tables[2],
                    ],
                  );
                }
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: tables[0]),
                    const SizedBox(width: 14),
                    Expanded(child: tables[1]),
                    const SizedBox(width: 14),
                    Expanded(child: tables[2]),
                  ],
                );
              },
            ),
            const SizedBox(height: 24),
          ],
        ],
      ),
    );
  }
}

class _LoadingReportPanel extends StatelessWidget {
  const _LoadingReportPanel();

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Формирую отчёт',
            style: TextStyle(
              color: colors.textStrong,
              fontWeight: FontWeight.w900,
              fontSize: 16,
            ),
          ),
          const SizedBox(height: 14),
          SizedBox(
            height: 90,
            child: Row(
              children: [
                for (var index = 0; index < 4; index++) ...[
                  Expanded(
                    child: _ReportPulseBlock(
                      delay: Duration(milliseconds: index * 90),
                    ),
                  ),
                  if (index < 3) const SizedBox(width: 12),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ReportPulseBlock extends StatefulWidget {
  const _ReportPulseBlock({required this.delay});

  final Duration delay;

  @override
  State<_ReportPulseBlock> createState() => _ReportPulseBlockState();
}

class _ReportPulseBlockState extends State<_ReportPulseBlock>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _opacity;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    );
    _opacity = Tween<double>(
      begin: 0.36,
      end: 0.88,
    ).animate(CurvedAnimation(parent: _controller, curve: Curves.easeInOut));
    Future<void>.delayed(widget.delay, () {
      if (mounted) _controller.repeat(reverse: true);
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return FadeTransition(
      opacity: _opacity,
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(18),
          color: colors.surfaceMuted,
          border: Border.all(color: colors.border),
        ),
      ),
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

    return RefreshIndicator(
      onRefresh: _load,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: Column(
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
                if (_error != null)
                  ErrorPanel(message: _error!, onRetry: _load),
                if (_error != null) const SizedBox(height: 14),
              ],
            ),
          ),
          if (_loading && _items.isEmpty)
            const _LoadingRowsSliver(count: 7)
          else if (filtered.isEmpty && !_loading)
            SliverToBoxAdapter(
              child: EmptyPanel(
                message: _items.isEmpty
                    ? 'Данных пока нет.'
                    : 'Ничего не найдено.',
              ),
            )
          else
            SliverList.builder(
              itemCount: filtered.length,
              itemBuilder: (context, index) {
                final row = filtered[index];
                return Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: _ModuleRowTile(
                    row: row,
                    columns: widget.columns,
                    commands: widget.rowCommands,
                    onCommand: (command) => _runRowCommand(command, row),
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

class _ModuleRowTile extends StatelessWidget {
  const _ModuleRowTile({
    required this.row,
    required this.columns,
    required this.commands,
    required this.onCommand,
  });

  final RowMap row;
  final List<ModuleColumn> columns;
  final List<RowCommand> commands;
  final ValueChanged<RowCommand> onCommand;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final visibleCommands = commands
        .where((command) => command.visible(row))
        .toList(growable: false);
    return RepaintBoundary(
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(18),
          color: colors.surfaceMuted,
          border: Border.all(color: colors.border),
        ),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final compact = constraints.maxWidth < 600;
            final cells = Wrap(
              spacing: compact ? 10 : 14,
              runSpacing: 10,
              children: [
                for (final column in columns)
                  SizedBox(
                    width: compact
                        ? (constraints.maxWidth >= 340
                              ? (constraints.maxWidth - 10) / 2
                              : constraints.maxWidth)
                        : column.width.clamp(82, 260).toDouble(),
                    child: _ModuleCell(column: column, row: row),
                  ),
              ],
            );
            final actions = Wrap(
              spacing: 2,
              runSpacing: 2,
              children: [
                for (final command in visibleCommands)
                  IconButton(
                    tooltip: command.tooltip,
                    onPressed: () => onCommand(command),
                    icon: Icon(
                      command.icon,
                      size: 19,
                      color: command.color(context),
                    ),
                  ),
              ],
            );

            if (compact) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  cells,
                  if (visibleCommands.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    actions,
                  ],
                ],
              );
            }

            return Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Expanded(child: cells),
                if (visibleCommands.isNotEmpty) ...[
                  const SizedBox(width: 10),
                  actions,
                ],
              ],
            );
          },
        ),
      ),
    );
  }
}

class _ModuleCell extends StatelessWidget {
  const _ModuleCell({required this.column, required this.row});

  final ModuleColumn column;
  final RowMap row;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          column.label,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            color: colors.muted,
            fontSize: 11,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          column.read(row),
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            color: colors.textStrong,
            fontSize: 13,
            fontWeight: FontWeight.w700,
            height: 1.25,
          ),
        ),
      ],
    );
  }
}

class _LoadingRowsSliver extends StatefulWidget {
  const _LoadingRowsSliver({required this.count});

  final int count;

  @override
  State<_LoadingRowsSliver> createState() => _LoadingRowsSliverState();
}

class _LoadingRowsSliverState extends State<_LoadingRowsSliver>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _opacity;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 820),
    )..repeat(reverse: true);
    _opacity = Tween<double>(
      begin: 0.46,
      end: 0.9,
    ).animate(CurvedAnimation(parent: _controller, curve: Curves.easeInOut));
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return SliverList.builder(
      itemCount: widget.count,
      itemBuilder: (context, index) {
        return Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: FadeTransition(
            opacity: _opacity,
            child: Container(
              height: index == 0 ? 96 : 74,
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(18),
                color: colors.surfaceMuted,
                border: Border.all(color: colors.border),
              ),
              child: Row(
                children: [
                  _SkeletonBlock(width: 96, height: 42, color: colors.border),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _SkeletonBlock(
                          width: double.infinity,
                          height: 12,
                          color: colors.border,
                        ),
                        const SizedBox(height: 10),
                        FractionallySizedBox(
                          widthFactor: index.isEven ? 0.72 : 0.48,
                          child: _SkeletonBlock(
                            width: double.infinity,
                            height: 12,
                            color: colors.border,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

class _SkeletonBlock extends StatelessWidget {
  const _SkeletonBlock({
    required this.width,
    required this.height,
    required this.color,
  });

  final double width;
  final double height;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: color.withValues(alpha: 0.42),
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
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 600;
        final titleBlock = Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: compact ? 40 : 46,
              height: compact ? 40 : 46,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(compact ? 14 : 16),
                color: colors.surfaceMuted,
                border: Border.all(color: colors.border),
              ),
              child: Icon(
                icon,
                color: colors.primaryAccent,
                size: compact ? 20 : 22,
              ),
            ),
            SizedBox(width: compact ? 10 : 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
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
                    subtitle,
                    maxLines: compact ? 3 : 2,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: colors.muted,
                      fontSize: compact ? 13 : 14,
                      height: 1.25,
                    ),
                  ),
                ],
              ),
            ),
          ],
        );

        if (compact) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              titleBlock,
              if (trailing != null) ...[
                const SizedBox(height: 12),
                SizedBox(width: double.infinity, child: trailing!),
              ],
            ],
          );
        }

        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: titleBlock),
            if (trailing != null) ...[
              const SizedBox(width: 12),
              Flexible(
                flex: 0,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 520),
                  child: trailing!,
                ),
              ),
            ],
          ],
        );
      },
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
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _ReportRow(columns: columns, row: const {}, isHeader: true),
                  for (final row in rows.take(24))
                    _ReportRow(columns: columns, row: row),
                  if (rows.length > 24)
                    Padding(
                      padding: const EdgeInsets.only(top: 8, left: 8),
                      child: Text(
                        'Показано 24 из ${rows.length}. Используйте профильные разделы для полного списка.',
                        style: TextStyle(color: colors.muted, fontSize: 12),
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

class _ReportRow extends StatelessWidget {
  const _ReportRow({
    required this.columns,
    required this.row,
    this.isHeader = false,
  });

  final List<ModuleColumn> columns;
  final RowMap row;
  final bool isHeader;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      margin: EdgeInsets.only(bottom: isHeader ? 6 : 4),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 9),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        color: isHeader ? colors.surfaceMuted : Colors.transparent,
        border: isHeader ? Border.all(color: colors.border) : null,
      ),
      child: Row(
        children: [
          for (final column in columns)
            Padding(
              padding: const EdgeInsets.only(right: 12),
              child: SizedBox(
                width: column.width,
                child: Text(
                  isHeader ? column.label : column.read(row),
                  maxLines: isHeader ? 1 : 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: isHeader ? colors.muted : colors.text,
                    fontSize: isHeader ? 12 : 13,
                    fontWeight: isHeader ? FontWeight.w900 : FontWeight.w600,
                    height: 1.25,
                  ),
                ),
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
  bool segmentedCode = false,
}) {
  return showDialog<void>(
    context: context,
    builder: (dialogContext) {
      final colors = dialogContext.colors;
      return AlertDialog(
        title: Text(title),
        content: segmentedCode
            ? SizedBox(
                width: 420,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    SegmentedCodeDisplay(
                      value: value,
                      length: value.isEmpty ? 8 : value.length,
                    ),
                    if (note != null && note.isNotEmpty) ...[
                      const SizedBox(height: 14),
                      Text(
                        note,
                        textAlign: TextAlign.center,
                        style: TextStyle(color: colors.muted, fontSize: 13),
                      ),
                    ],
                  ],
                ),
              )
            : SelectableText(
                [
                  value,
                  if (note != null && note.isNotEmpty) '\n$note',
                ].join('\n'),
                style: TextStyle(
                  color: colors.textStrong,
                  fontSize: 15,
                  fontWeight: FontWeight.w800,
                ),
              ),
        actions: [
          OutlinedButton.icon(
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: value));
              if (!dialogContext.mounted) return;
              ScaffoldMessenger.of(dialogContext).showSnackBar(
                const SnackBar(
                  content: Text('Скопировано'),
                  behavior: SnackBarBehavior.floating,
                ),
              );
            },
            icon: const Icon(Icons.copy_rounded, size: 18),
            label: const Text('Скопировать'),
          ),
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

int _countOnline(List<RowMap> rows) {
  return rows.where((row) => rowBool(row, 'is_online')).length;
}

bool alwaysVisible(RowMap row) => true;

Color defaultRowCommandColor(BuildContext context) => context.colors.textStrong;

void showErrorSnack(BuildContext context, String message) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
}
