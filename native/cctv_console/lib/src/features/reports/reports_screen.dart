import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';
import 'package:provider/provider.dart';

import '../../core/network/api_client.dart';
import '../../core/theme/app_theme.dart';
import '../../shared/widgets/glass_panel.dart';
import '../auth/auth_controller.dart';

class ReportsDashboardScreen extends StatefulWidget {
  const ReportsDashboardScreen({super.key});

  @override
  State<ReportsDashboardScreen> createState() => _ReportsDashboardScreenState();
}

class _ReportsDashboardScreenState extends State<ReportsDashboardScreen> {
  final _dateFrom = TextEditingController();
  final _dateTo = TextEditingController();
  final _personId = TextEditingController();

  bool _busy = false;
  String? _error;
  Map<String, dynamic>? _dashboard;
  Map<String, dynamic>? _appearances;

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
  void dispose() {
    _dateFrom.dispose();
    _dateTo.dispose();
    _personId.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    await _run(() async {
      final (api, token) = _deps();
      _dashboard = await api
          .getJson(
            '/reports/dashboard',
            token: token,
            query: {
              'date_from': _clean(_dateFrom.text),
              'date_to': _clean(_dateTo.text),
            },
          )
          .then(_map);
      _appearances = await api
          .getJson(
            '/reports/appearances',
            token: token,
            query: {
              'date_from': _clean(_dateFrom.text),
              'date_to': _clean(_dateTo.text),
              'person_id': _clean(_personId.text),
            },
          )
          .then(_map);
    });
  }

  Future<void> _export(_ReportSection section, String format) async {
    await _run(() async {
      final (api, token) = _deps();
      final file = section.id == 'appearances'
          ? await api.downloadAppearanceReport(
              token,
              format: format,
              personId: int.tryParse(_personId.text.trim()),
              dateFrom: _clean(_dateFrom.text),
              dateTo: _clean(_dateTo.text),
            )
          : await api.downloadReportSection(
              token,
              section: section.id,
              format: format,
              dateFrom: _clean(_dateFrom.text),
              dateTo: _clean(_dateTo.text),
            );
      await OpenFilex.open(file.path);
      _toast('Отчёт сохранён: ${file.path}');
    });
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
        slivers: [
          SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _Header(busy: _busy, onRefresh: _load),
                const SizedBox(height: 14),
                _Filters(
                  dateFrom: _dateFrom,
                  dateTo: _dateTo,
                  personId: _personId,
                  busy: _busy,
                  onApply: _load,
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
                const SizedBox(height: 24),
              ],
            ),
          ),
        ],
      ),
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
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Отчёты',
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  color: colors.textStrong,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                'Сводка по пользователям, камерам, Processor, событиям, архиву и безопасности.',
                style: TextStyle(color: colors.muted, fontSize: 13),
              ),
            ],
          ),
        ),
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
    );
  }
}

class _Filters extends StatelessWidget {
  const _Filters({
    required this.dateFrom,
    required this.dateTo,
    required this.personId,
    required this.busy,
    required this.onApply,
  });

  final TextEditingController dateFrom;
  final TextEditingController dateTo;
  final TextEditingController personId;
  final bool busy;
  final VoidCallback onApply;

  @override
  Widget build(BuildContext context) {
    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Wrap(
        spacing: 10,
        runSpacing: 10,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          _SizedField(
            width: 220,
            child: TextField(
              controller: dateFrom,
              decoration: const InputDecoration(
                labelText: 'Дата/время от',
                hintText: '2026-05-20T00:00:00',
              ),
            ),
          ),
          _SizedField(
            width: 220,
            child: TextField(
              controller: dateTo,
              decoration: const InputDecoration(
                labelText: 'Дата/время до',
                hintText: '2026-05-20T23:59:59',
              ),
            ),
          ),
          _SizedField(
            width: 160,
            child: TextField(
              controller: personId,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'ID персоны'),
            ),
          ),
          ElevatedButton.icon(
            onPressed: busy ? null : onApply,
            icon: const Icon(Icons.filter_alt_rounded, size: 18),
            label: const Text('Применить'),
          ),
        ],
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
          for (final item in items.take(10))
            ListTile(
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

class _SizedField extends StatelessWidget {
  const _SizedField({required this.width, required this.child});

  final double width;
  final Widget child;

  @override
  Widget build(BuildContext context) => SizedBox(width: width, child: child);
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

String? _clean(String value) {
  final text = value.trim();
  return text.isEmpty ? null : text;
}
