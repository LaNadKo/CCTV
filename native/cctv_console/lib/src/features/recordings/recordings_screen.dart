import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';
import 'package:open_filex/open_filex.dart';
import 'package:provider/provider.dart';

import '../../core/models/models.dart';
import '../../core/network/api_client.dart';
import '../../core/theme/app_theme.dart';
import '../../shared/widgets/glass_panel.dart';
import '../auth/auth_controller.dart';
import '../modules/module_screens.dart'
    show EmptyPanel, ErrorPanel, ModuleHeader, RefreshButton;

const _daySeconds = 24 * 60 * 60;
const _maxDayClips = 2000;

class ArchiveRecordingsScreen extends StatefulWidget {
  const ArchiveRecordingsScreen({super.key});

  @override
  State<ArchiveRecordingsScreen> createState() =>
      _ArchiveRecordingsScreenState();
}

class _ArchiveRecordingsScreenState extends State<ArchiveRecordingsScreen> {
  late final Player _player;
  late final VideoController _videoController;
  StreamSubscription<bool>? _completedSub;

  var _loading = false;
  String? _error;
  List<CameraSummary> _cameras = const [];
  List<_RecordingClip> _records = const [];
  List<_TimelineEvent> _events = const [];
  int? _cameraId;
  int? _selectedId;
  int? _selectedHour;
  DateTime _selectedDate = _dateOnly(DateTime.now());
  bool _chainPlayback = false;
  String _eventTypeFilter = 'all';

  @override
  void initState() {
    super.initState();
    _player = Player();
    _videoController = VideoController(_player);
    _completedSub = _player.stream.completed.listen((completed) {
      if (completed && _chainPlayback && mounted) {
        _playNextClip();
      }
    });
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _completedSub?.cancel();
    unawaited(_player.dispose());
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

      final cameras = await api.listCameras(token);
      final activeCameraId = _cameraId ?? cameras.firstOrNull?.cameraId;
      final dateKey = _dateKey(_selectedDate);
      final query = <String, String?>{
        if (activeCameraId != null) 'camera_id': '$activeCameraId',
        'date_from': '${dateKey}T00:00:00',
        'date_to': '${dateKey}T23:59:59',
        'limit': '$_maxDayClips',
      };

      final results = await Future.wait([
        api.getJsonList('/recordings', token: token, query: query),
        api.getJsonList('/detections/timeline', token: token, query: query),
      ]);

      final records =
          results[0]
              .map(_RecordingClip.fromJson)
              .where((record) => record.fileKind == 'video')
              .toList()
            ..sort((left, right) => left.startedAt.compareTo(right.startedAt));
      final events = results[1].map(_TimelineEvent.fromJson).toList()
        ..sort((left, right) => left.ts.compareTo(right.ts));

      final currentSelected = _selectedId;
      final selected = records.any((record) => record.id == currentSelected)
          ? currentSelected
          : records.lastOrNull?.id;
      final selectedRecord = selected == null
          ? null
          : records.firstWhere((record) => record.id == selected);

      if (!mounted) return;
      setState(() {
        _cameras = cameras;
        _cameraId = activeCameraId;
        _records = records;
        _events = events;
        _selectedId = selected;
        _selectedHour = selectedRecord?.hour ?? _selectedHour;
      });

      if (selectedRecord != null) {
        await _openClip(selectedRecord, play: false, keepChain: false);
      } else {
        await _player.stop();
      }
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Map<int, List<_RecordingClip>> get _recordsByHour {
    final map = {
      for (var hour = 0; hour < 24; hour++) hour: <_RecordingClip>[],
    };
    for (final record in _records) {
      map[record.hour]!.add(record);
    }
    return map;
  }

  _RecordingClip? get _selectedRecord {
    final id = _selectedId;
    if (id == null) return null;
    return _records.where((record) => record.id == id).firstOrNull;
  }

  List<_TimelineEvent> get _visibleEvents {
    if (_eventTypeFilter == 'all') return _events;
    return _events
        .where((event) => event.type == _eventTypeFilter)
        .toList(growable: false);
  }

  Future<void> _openClip(
    _RecordingClip record, {
    required bool play,
    bool keepChain = true,
  }) async {
    if (!mounted) return;
    if (!keepChain) _chainPlayback = false;
    setState(() {
      _selectedId = record.id;
      _selectedHour = record.hour;
    });
    await _ensureMediaToken();
    await _player.open(Media(_recordingUri(record).toString()), play: play);
  }

  Future<void> _playFrom(_RecordingClip record) async {
    _chainPlayback = true;
    await _openClip(record, play: true);
  }

  Future<void> _playWholeDay() async {
    final first = _records.firstOrNull;
    if (first == null) return;
    await _playFrom(first);
  }

  Future<void> _playSelectedHour() async {
    final hour = _selectedHour;
    if (hour == null) return;
    final first = _recordsByHour[hour]?.firstOrNull;
    if (first == null) return;
    await _playFrom(first);
  }

  Future<void> _playNextClip() async {
    final selected = _selectedRecord;
    if (selected == null) return;
    final index = _records.indexWhere((record) => record.id == selected.id);
    if (index < 0 || index >= _records.length - 1) {
      _chainPlayback = false;
      return;
    }
    await _openClip(_records[index + 1], play: true);
  }

  Future<void> _ensureMediaToken() async {
    final auth = context.read<AuthController>();
    if ((auth.mediaToken ?? '').isNotEmpty) return;
    await auth.refreshMediaToken();
  }

  Uri _recordingUri(_RecordingClip record) {
    final token = context.read<AuthController>().mediaToken ?? '';
    return context.read<ApiClient>().uri('/recordings/file/${record.id}', {
      'token': token,
    });
  }

  Uri _snapshotUri(_RecordingClip record) {
    final token = context.read<AuthController>().mediaToken ?? '';
    final ts = (record.durationSeconds ?? 60) <= 2
        ? 1
        : ((record.durationSeconds ?? 60) / 2).round();
    return context.read<ApiClient>().uri('/recordings/snapshot/${record.id}', {
      'token': token,
      'ts': '$ts',
    });
  }

  List<_TimelineEvent> _eventsForClip(_RecordingClip record) {
    return _visibleEvents
        .where((event) {
          return !event.ts.isBefore(record.startedAt) &&
              !event.ts.isAfter(record.endAt);
        })
        .toList(growable: false);
  }

  List<_TimelineEvent> _eventsForHour(int hour) {
    return _visibleEvents
        .where((event) => event.ts.hour == hour)
        .toList(growable: false);
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _selectedDate,
      firstDate: DateTime(2020),
      lastDate: DateTime.now(),
    );
    if (picked == null) return;
    setState(() => _selectedDate = _dateOnly(picked));
    await _load();
  }

  Future<void> _shiftDate(int days) async {
    final next = _dateOnly(_selectedDate.add(Duration(days: days)));
    if (next.isAfter(_dateOnly(DateTime.now()))) return;
    setState(() => _selectedDate = next);
    await _load();
  }

  Future<void> _downloadSelected() async {
    final record = _selectedRecord;
    final token = context.read<AuthController>().accessToken;
    if (record == null || token == null) return;
    try {
      final file = await context.read<ApiClient>().downloadRecordingFile(
        token,
        record.id,
      );
      await OpenFilex.open(file.path);
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('$error')));
    }
  }

  Future<void> _showMjpegFallback() async {
    final record = _selectedRecord;
    if (record == null) return;
    await _ensureMediaToken();
    if (!mounted) return;
    final token = context.read<AuthController>().mediaToken ?? '';
    final uri = context.read<ApiClient>().recordingMjpegUri(record.id, token);
    await showDialog<void>(
      context: context,
      builder: (context) => _MjpegFallbackDialog(uri: uri.toString()),
    );
  }

  @override
  Widget build(BuildContext context) {
    final selectedRecord = _selectedRecord;
    final byHour = _recordsByHour;
    final visibleEvents = _visibleEvents;
    final selectedHourRecords = _selectedHour == null
        ? const <_RecordingClip>[]
        : byHour[_selectedHour] ?? const <_RecordingClip>[];

    return RefreshIndicator(
      onRefresh: _load,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: Column(
              children: [
                ModuleHeader(
                  title: 'Записи',
                  subtitle:
                      'Архив воспроизводится как единая суточная лента: файлы режутся по 60 секунд, группируются по дням и часам.',
                  icon: Icons.video_library_rounded,
                  trailing: Wrap(
                    spacing: 10,
                    runSpacing: 8,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      ElevatedButton.icon(
                        onPressed: _records.isEmpty ? null : _playWholeDay,
                        icon: const Icon(Icons.play_circle_rounded, size: 18),
                        label: const Text('Воспроизвести день'),
                      ),
                      OutlinedButton.icon(
                        onPressed: selectedHourRecords.isEmpty
                            ? null
                            : _playSelectedHour,
                        icon: const Icon(Icons.playlist_play_rounded, size: 18),
                        label: const Text('Воспроизвести час'),
                      ),
                      RefreshButton(loading: _loading, onPressed: _load),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                _ArchiveControls(
                  cameras: _cameras,
                  cameraId: _cameraId,
                  selectedDate: _selectedDate,
                  loading: _loading,
                  onCameraChanged: (value) async {
                    setState(() => _cameraId = value);
                    await _load();
                  },
                  onDateTap: _pickDate,
                  onPrevDay: () => _shiftDate(-1),
                  onNextDay: () => _shiftDate(1),
                  eventTypeFilter: _eventTypeFilter,
                  onEventTypeChanged: (value) =>
                      setState(() => _eventTypeFilter = value),
                ),
                const SizedBox(height: 14),
                if (_error != null) ...[
                  ErrorPanel(message: _error!, onRetry: _load),
                  const SizedBox(height: 14),
                ],
                if (_loading && _records.isEmpty) ...[
                  const _ArchiveSkeleton(),
                  const SizedBox(height: 14),
                ],
                if (!_loading && _records.isEmpty)
                  const EmptyPanel(
                    message:
                        'За выбранный день записей нет. Проверьте назначение камеры на Processor и режим записи.',
                  )
                else
                  _PlayerPanel(
                    controller: _videoController,
                    record: selectedRecord,
                    chainPlayback: _chainPlayback,
                    events: selectedRecord == null
                        ? const []
                        : _eventsForClip(selectedRecord),
                    onDownload: selectedRecord == null
                        ? null
                        : _downloadSelected,
                    onMjpegFallback: selectedRecord == null
                        ? null
                        : _showMjpegFallback,
                  ),
                const SizedBox(height: 14),
                if (_records.isNotEmpty)
                  _DayTimeline(
                    records: _records,
                    events: visibleEvents,
                    selectedId: _selectedId,
                    onSelect: (record) => _openClip(record, play: false),
                  ),
                const SizedBox(height: 14),
                if (_records.isNotEmpty)
                  _SummaryRail(
                    records: _records,
                    events: visibleEvents,
                    selectedDate: _selectedDate,
                  ),
                const SizedBox(height: 14),
              ],
            ),
          ),
          if (_records.isNotEmpty)
            SliverGrid(
              delegate: SliverChildBuilderDelegate((context, index) {
                final hour = 23 - index;
                final records = byHour[hour] ?? const <_RecordingClip>[];
                final events = _eventsForHour(hour);
                return _HourFolderCard(
                  hour: hour,
                  records: records,
                  events: events,
                  active: _selectedHour == hour,
                  snapshotUri: records.isEmpty
                      ? null
                      : _snapshotUri(records.last).toString(),
                  onTap: records.isEmpty
                      ? null
                      : () {
                          setState(() {
                            _selectedHour = hour;
                            _selectedId = records.first.id;
                          });
                        },
                );
              }, childCount: 24),
              gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                maxCrossAxisExtent: 230,
                mainAxisExtent: 178,
                mainAxisSpacing: 12,
                crossAxisSpacing: 12,
              ),
            ),
          if (_records.isNotEmpty && _selectedHour != null)
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.only(top: 18, bottom: 12),
                child: _SectionTitle(
                  title: 'Клипы ${_selectedHour.toString().padLeft(2, '0')}:00',
                  subtitle:
                      '${selectedHourRecords.length} сегментов по минутам. Нажмите клип, чтобы открыть его в основном плеере.',
                ),
              ),
            ),
          if (_records.isNotEmpty && _selectedHour != null)
            SliverGrid(
              delegate: SliverChildBuilderDelegate((context, index) {
                final record = selectedHourRecords[index];
                return _MinuteClipCard(
                  record: record,
                  active: record.id == _selectedId,
                  snapshotUri: _snapshotUri(record).toString(),
                  events: _eventsForClip(record),
                  onTap: () => _openClip(record, play: false),
                  onPlay: () => _playFrom(record),
                );
              }, childCount: selectedHourRecords.length),
              gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                maxCrossAxisExtent: 280,
                mainAxisExtent: 215,
                mainAxisSpacing: 12,
                crossAxisSpacing: 12,
              ),
            ),
          const SliverToBoxAdapter(child: SizedBox(height: 24)),
        ],
      ),
    );
  }
}

class _ArchiveControls extends StatelessWidget {
  const _ArchiveControls({
    required this.cameras,
    required this.cameraId,
    required this.selectedDate,
    required this.loading,
    required this.onCameraChanged,
    required this.onDateTap,
    required this.onPrevDay,
    required this.onNextDay,
    required this.eventTypeFilter,
    required this.onEventTypeChanged,
  });

  final List<CameraSummary> cameras;
  final int? cameraId;
  final DateTime selectedDate;
  final bool loading;
  final ValueChanged<int?> onCameraChanged;
  final VoidCallback onDateTap;
  final VoidCallback onPrevDay;
  final VoidCallback onNextDay;
  final String eventTypeFilter;
  final ValueChanged<String> onEventTypeChanged;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(14),
      child: Wrap(
        spacing: 12,
        runSpacing: 12,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          SizedBox(
            width: 280,
            child: DropdownButtonFormField<int>(
              initialValue: cameras.any((camera) => camera.cameraId == cameraId)
                  ? cameraId
                  : null,
              isExpanded: true,
              decoration: const InputDecoration(
                labelText: 'Камера',
                prefixIcon: Icon(Icons.videocam_rounded),
              ),
              items: [
                for (final camera in cameras)
                  DropdownMenuItem(
                    value: camera.cameraId,
                    child: Text('${camera.name} (#${camera.cameraId})'),
                  ),
              ],
              onChanged: loading ? null : onCameraChanged,
            ),
          ),
          OutlinedButton.icon(
            onPressed: loading ? null : onPrevDay,
            icon: const Icon(Icons.chevron_left_rounded),
            label: const Text('День назад'),
          ),
          OutlinedButton.icon(
            onPressed: loading ? null : onDateTap,
            icon: const Icon(Icons.calendar_month_rounded),
            label: Text(_dayLabel(selectedDate)),
          ),
          OutlinedButton.icon(
            onPressed:
                loading ||
                    _dateOnly(
                      selectedDate,
                    ).isAtSameMomentAs(_dateOnly(DateTime.now()))
                ? null
                : onNextDay,
            icon: const Icon(Icons.chevron_right_rounded),
            label: const Text('День вперёд'),
          ),
          SizedBox(
            width: 230,
            child: DropdownButtonFormField<String>(
              initialValue: eventTypeFilter,
              decoration: const InputDecoration(
                labelText: 'Метки событий',
                prefixIcon: Icon(Icons.sell_rounded),
              ),
              items: const [
                DropdownMenuItem(value: 'all', child: Text('Все события')),
                DropdownMenuItem(
                  value: 'face_recognized',
                  child: Text('Распознанные лица'),
                ),
                DropdownMenuItem(
                  value: 'face_unknown',
                  child: Text('Неизвестные лица'),
                ),
                DropdownMenuItem(
                  value: 'person_detected',
                  child: Text('Человек'),
                ),
                DropdownMenuItem(
                  value: 'motion_detected',
                  child: Text('Движение'),
                ),
              ],
              onChanged: loading
                  ? null
                  : (value) => onEventTypeChanged(value ?? 'all'),
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: colors.surfaceMuted,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: colors.border),
            ),
            child: Text(
              'Структура: день → час → клип до 60 сек',
              style: TextStyle(color: colors.muted, fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }
}

class _PlayerPanel extends StatelessWidget {
  const _PlayerPanel({
    required this.controller,
    required this.record,
    required this.chainPlayback,
    required this.events,
    required this.onDownload,
    required this.onMjpegFallback,
  });

  final VideoController controller;
  final _RecordingClip? record;
  final bool chainPlayback;
  final List<_TimelineEvent> events;
  final VoidCallback? onDownload;
  final VoidCallback? onMjpegFallback;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final current = record;
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
                      current == null
                          ? 'Архивный медиаплеер'
                          : 'Клип ${_timeRange(current)}',
                      style: Theme.of(context).textTheme.headlineSmall,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      current == null
                          ? 'Выберите час или клип ниже.'
                          : '${_formatDuration(current.durationSeconds)} · ${_formatBytes(current.sizeBytes)} · ${chainPlayback ? 'склейка включена' : 'одиночный просмотр'}',
                      style: TextStyle(color: colors.muted, fontSize: 13),
                    ),
                  ],
                ),
              ),
              if (current != null)
                _EventBadge(
                  label: '${events.length} меток',
                  icon: Icons.sell_rounded,
                  color: colors.primaryAccent,
                ),
              if (current != null) ...[
                const SizedBox(width: 8),
                OutlinedButton.icon(
                  onPressed: onDownload,
                  icon: const Icon(Icons.download_rounded, size: 18),
                  label: const Text('Открыть файл'),
                ),
                const SizedBox(width: 8),
                OutlinedButton.icon(
                  onPressed: onMjpegFallback,
                  icon: const Icon(Icons.video_file_rounded, size: 18),
                  label: const Text('MJPEG fallback'),
                ),
              ],
            ],
          ),
          const SizedBox(height: 14),
          AspectRatio(
            aspectRatio: 16 / 9,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(20),
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: Colors.black.withValues(alpha: 0.72),
                ),
                child: current == null
                    ? Center(
                        child: Icon(
                          Icons.video_library_rounded,
                          color: colors.muted,
                          size: 54,
                        ),
                      )
                    : Video(controller: controller),
              ),
            ),
          ),
          if (events.isNotEmpty) ...[
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final event in events.take(8))
                  _EventBadge(
                    label:
                        '${_eventLabel(event.type)} · ${DateFormat('HH:mm:ss').format(event.ts)}',
                    icon: _eventIcon(event.type),
                    color: _eventColor(context, event.type),
                  ),
                if (events.length > 8)
                  _EventBadge(
                    label: '+${events.length - 8}',
                    icon: Icons.more_horiz_rounded,
                    color: colors.muted,
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _MjpegFallbackDialog extends StatelessWidget {
  const _MjpegFallbackDialog({required this.uri});

  final String uri;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AlertDialog(
      title: const Text('MJPEG fallback'),
      content: SizedBox(
        width: 760,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            AspectRatio(
              aspectRatio: 16 / 9,
              child: ClipRRect(
                borderRadius: BorderRadius.circular(18),
                child: Container(
                  color: Colors.black,
                  child: Image.network(
                    uri,
                    fit: BoxFit.contain,
                    gaplessPlayback: true,
                    errorBuilder: (_, _, _) => Center(
                      child: Text(
                        'MJPEG поток не открылся. URL можно проверить во внешнем плеере.',
                        style: TextStyle(color: colors.muted),
                      ),
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 10),
            SelectableText(
              uri,
              style: TextStyle(color: colors.muted, fontSize: 12),
            ),
          ],
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

class _DayTimeline extends StatelessWidget {
  const _DayTimeline({
    required this.records,
    required this.events,
    required this.selectedId,
    required this.onSelect,
  });

  final List<_RecordingClip> records;
  final List<_TimelineEvent> events;
  final int? selectedId;
  final ValueChanged<_RecordingClip> onSelect;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _SectionTitle(
            title: 'Суточная лента',
            subtitle:
                'Синие участки - сохранённые минутные сегменты, вертикальные метки - события распознавания и движения.',
          ),
          const SizedBox(height: 12),
          SizedBox(
            height: 42,
            child: LayoutBuilder(
              builder: (context, constraints) {
                final width = constraints.maxWidth;
                return Stack(
                  children: [
                    Positioned.fill(
                      child: DecoratedBox(
                        decoration: BoxDecoration(
                          color: colors.surfaceMuted,
                          borderRadius: BorderRadius.circular(999),
                          border: Border.all(color: colors.border),
                        ),
                      ),
                    ),
                    for (var hour = 1; hour < 24; hour++)
                      Positioned(
                        left: width * hour / 24,
                        top: 0,
                        bottom: 0,
                        child: Container(width: 1, color: colors.border),
                      ),
                    for (final record in records)
                      Positioned(
                        left: width * record.startSecond / _daySeconds,
                        top: 8,
                        width:
                            (width * record.durationForTimeline / _daySeconds)
                                .clamp(4.0, width),
                        bottom: 8,
                        child: Tooltip(
                          message: _timeRange(record),
                          child: InkWell(
                            borderRadius: BorderRadius.circular(999),
                            onTap: () => onSelect(record),
                            child: AnimatedContainer(
                              duration: const Duration(milliseconds: 180),
                              decoration: BoxDecoration(
                                borderRadius: BorderRadius.circular(999),
                                gradient: LinearGradient(
                                  colors: record.id == selectedId
                                      ? [
                                          colors.primaryAccent,
                                          colors.secondaryAccent,
                                        ]
                                      : [
                                          colors.primaryAccent.withValues(
                                            alpha: 0.72,
                                          ),
                                          colors.secondaryAccent.withValues(
                                            alpha: 0.48,
                                          ),
                                        ],
                                ),
                                boxShadow: record.id == selectedId
                                    ? [
                                        BoxShadow(
                                          color: colors.primaryAccent
                                              .withValues(alpha: 0.22),
                                          blurRadius: 18,
                                        ),
                                      ]
                                    : null,
                              ),
                            ),
                          ),
                        ),
                      ),
                    for (final event in events)
                      Positioned(
                        left: width * event.secondOfDay / _daySeconds,
                        top: 5,
                        bottom: 5,
                        child: Container(
                          width: 4,
                          decoration: BoxDecoration(
                            color: _eventColor(context, event.type),
                            borderRadius: BorderRadius.circular(999),
                          ),
                        ),
                      ),
                  ],
                );
              },
            ),
          ),
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              for (final label in const [
                '00:00',
                '06:00',
                '12:00',
                '18:00',
                '24:00',
              ])
                Text(
                  label,
                  style: TextStyle(color: colors.muted, fontSize: 11),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _SummaryRail extends StatelessWidget {
  const _SummaryRail({
    required this.records,
    required this.events,
    required this.selectedDate,
  });

  final List<_RecordingClip> records;
  final List<_TimelineEvent> events;
  final DateTime selectedDate;

  @override
  Widget build(BuildContext context) {
    final hours = records.map((record) => record.hour).toSet().length;
    final totalBytes = records.fold<int>(
      0,
      (sum, record) => sum + (record.sizeBytes ?? 0),
    );
    return Wrap(
      spacing: 12,
      runSpacing: 12,
      children: [
        _MetricPill(label: 'Дата', value: _dayLabel(selectedDate)),
        _MetricPill(label: 'Клипы', value: '${records.length}'),
        _MetricPill(label: 'Часы с архивом', value: '$hours / 24'),
        _MetricPill(label: 'Метки', value: '${events.length}'),
        _MetricPill(label: 'Объём', value: _formatBytes(totalBytes)),
      ],
    );
  }
}

class _HourFolderCard extends StatelessWidget {
  const _HourFolderCard({
    required this.hour,
    required this.records,
    required this.events,
    required this.active,
    required this.snapshotUri,
    required this.onTap,
  });

  final int hour;
  final List<_RecordingClip> records;
  final List<_TimelineEvent> events;
  final bool active;
  final String? snapshotUri;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final hasRecords = records.isNotEmpty;
    return RepaintBoundary(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: hasRecords ? colors.surface : colors.surfaceMuted,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(
              color: active ? colors.primaryAccent : colors.border,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(15),
                  child: snapshotUri == null
                      ? Container(
                          color: colors.surfaceMuted,
                          child: Center(
                            child: Text(
                              'Нет записей',
                              style: TextStyle(
                                color: colors.muted,
                                fontSize: 12,
                              ),
                            ),
                          ),
                        )
                      : Image.network(
                          snapshotUri!,
                          fit: BoxFit.cover,
                          width: double.infinity,
                          errorBuilder: (context, error, stackTrace) =>
                              Container(
                                color: colors.surfaceMuted,
                                child: Icon(
                                  Icons.broken_image_rounded,
                                  color: colors.muted,
                                ),
                              ),
                        ),
                ),
              ),
              const SizedBox(height: 10),
              Text(
                '${hour.toString().padLeft(2, '0')}:00',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 2),
              Text(
                hasRecords
                    ? '${records.length} клипов · ${events.length} меток'
                    : 'Пусто',
                style: TextStyle(color: colors.muted, fontSize: 12),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _MinuteClipCard extends StatelessWidget {
  const _MinuteClipCard({
    required this.record,
    required this.active,
    required this.snapshotUri,
    required this.events,
    required this.onTap,
    required this.onPlay,
  });

  final _RecordingClip record;
  final bool active;
  final String snapshotUri;
  final List<_TimelineEvent> events;
  final VoidCallback onTap;
  final VoidCallback onPlay;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return RepaintBoundary(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: colors.surface,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(
              color: active ? colors.primaryAccent : colors.border,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Stack(
                  children: [
                    Positioned.fill(
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(15),
                        child: Image.network(
                          snapshotUri,
                          fit: BoxFit.cover,
                          errorBuilder: (context, error, stackTrace) =>
                              Container(
                                color: colors.surfaceMuted,
                                child: Icon(
                                  Icons.broken_image_rounded,
                                  color: colors.muted,
                                ),
                              ),
                        ),
                      ),
                    ),
                    Positioned(
                      right: 8,
                      bottom: 8,
                      child: IconButton.filled(
                        onPressed: onPlay,
                        icon: const Icon(Icons.play_arrow_rounded),
                        tooltip: 'Играть отсюда',
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 10),
              Text(
                _timeRange(record),
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 4),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  _EventBadge(
                    label: _formatDuration(record.durationSeconds),
                    icon: Icons.schedule_rounded,
                    color: colors.primaryAccent,
                  ),
                  if (events.isEmpty)
                    _EventBadge(
                      label: 'без меток',
                      icon: Icons.radio_button_unchecked_rounded,
                      color: colors.muted,
                    )
                  else
                    for (final event in events.take(2))
                      _EventBadge(
                        label: _eventLabel(event.type),
                        icon: _eventIcon(event.type),
                        color: _eventColor(context, event.type),
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

class _EventBadge extends StatelessWidget {
  const _EventBadge({
    required this.label,
    required this.icon,
    required this.color,
  });

  final String label;
  final IconData icon;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.28)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: color, size: 14),
          const SizedBox(width: 5),
          Text(
            label,
            style: TextStyle(
              color: colors.text,
              fontSize: 11,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }
}

class _MetricPill extends StatelessWidget {
  const _MetricPill({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            value,
            style: Theme.of(
              context,
            ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w900),
          ),
          Text(label, style: TextStyle(color: colors.muted, fontSize: 12)),
        ],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.title, required this.subtitle});

  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 4),
        Text(subtitle, style: TextStyle(color: colors.muted, fontSize: 13)),
      ],
    );
  }
}

class _ArchiveSkeleton extends StatelessWidget {
  const _ArchiveSkeleton();

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        children: [
          for (var index = 0; index < 3; index++) ...[
            Container(
              height: index == 0 ? 220 : 54,
              decoration: BoxDecoration(
                color: colors.surfaceMuted,
                borderRadius: BorderRadius.circular(index == 0 ? 20 : 14),
              ),
            ),
            if (index < 2) const SizedBox(height: 12),
          ],
        ],
      ),
    );
  }
}

class _RecordingClip {
  const _RecordingClip({
    required this.id,
    required this.cameraId,
    required this.fileKind,
    required this.startedAt,
    required this.endAt,
    this.durationSeconds,
    this.sizeBytes,
  });

  final int id;
  final int cameraId;
  final String fileKind;
  final DateTime startedAt;
  final DateTime endAt;
  final double? durationSeconds;
  final int? sizeBytes;

  int get hour => startedAt.hour;
  int get startSecond =>
      startedAt.hour * 3600 + startedAt.minute * 60 + startedAt.second;
  double get durationForTimeline {
    final fromDates = endAt.difference(startedAt).inSeconds.toDouble();
    return (durationSeconds ?? fromDates).clamp(10.0, 60.0).toDouble();
  }

  factory _RecordingClip.fromJson(Map<String, dynamic> json) {
    final started = _parseDate(json['started_at']) ?? DateTime.now();
    final duration = (json['duration_seconds'] as num?)?.toDouble();
    final ended =
        _parseDate(json['ended_at']) ??
        started.add(Duration(milliseconds: ((duration ?? 60) * 1000).round()));
    return _RecordingClip(
      id: json['recording_file_id'] as int? ?? 0,
      cameraId: json['camera_id'] as int? ?? 0,
      fileKind: json['file_kind'] as String? ?? 'video',
      startedAt: started,
      endAt: ended,
      durationSeconds: duration,
      sizeBytes: json['file_size_bytes'] as int?,
    );
  }
}

class _TimelineEvent {
  const _TimelineEvent({
    required this.id,
    required this.cameraId,
    required this.ts,
    required this.type,
  });

  final int id;
  final int cameraId;
  final DateTime ts;
  final String type;

  int get secondOfDay => ts.hour * 3600 + ts.minute * 60 + ts.second;

  factory _TimelineEvent.fromJson(Map<String, dynamic> json) {
    return _TimelineEvent(
      id: json['event_id'] as int? ?? 0,
      cameraId: json['camera_id'] as int? ?? 0,
      ts: _parseDate(json['event_ts']) ?? DateTime.now(),
      type: json['event_type'] as String? ?? 'motion_detected',
    );
  }
}

DateTime? _parseDate(Object? value) {
  if (value == null) return null;
  return DateTime.tryParse('$value');
}

DateTime _dateOnly(DateTime value) =>
    DateTime(value.year, value.month, value.day);

String _dateKey(DateTime value) =>
    '${value.year.toString().padLeft(4, '0')}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';

String _dayLabel(DateTime value) {
  final today = _dateOnly(DateTime.now());
  final date = _dateOnly(value);
  if (date == today) return 'Сегодня';
  if (date == today.subtract(const Duration(days: 1))) return 'Вчера';
  return DateFormat('dd.MM.yyyy').format(value);
}

String _timeRange(_RecordingClip record) {
  final format = DateFormat('HH:mm:ss');
  return '${format.format(record.startedAt)} - ${format.format(record.endAt)}';
}

String _formatDuration(double? seconds) {
  final safe = (seconds ?? 60).round().clamp(1, 60);
  return safe < 60 ? '$safe сек' : '1 мин';
}

String _formatBytes(int? value) {
  final bytes = value ?? 0;
  if (bytes <= 0) return '-';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} КБ';
  if (bytes < 1024 * 1024 * 1024) {
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} МБ';
  }
  return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(2)} ГБ';
}

String _eventLabel(String type) {
  return switch (type) {
    'face_recognized' => 'известная персона',
    'face_unknown' => 'неизвестное лицо',
    'person_detected' => 'человек',
    'motion_detected' => 'движение',
    _ => type,
  };
}

IconData _eventIcon(String type) {
  return switch (type) {
    'face_recognized' => Icons.verified_user_rounded,
    'face_unknown' => Icons.person_search_rounded,
    'person_detected' => Icons.accessibility_new_rounded,
    'motion_detected' => Icons.bolt_rounded,
    _ => Icons.sell_rounded,
  };
}

Color _eventColor(BuildContext context, String type) {
  final colors = context.colors;
  return switch (type) {
    'face_recognized' => colors.success,
    'face_unknown' => colors.warning,
    'person_detected' => colors.primaryAccent,
    'motion_detected' => colors.secondaryAccent,
    _ => colors.muted,
  };
}

extension _NullableIterableItems<T> on Iterable<T> {
  T? get firstOrNull {
    final iterator = this.iterator;
    return iterator.moveNext() ? iterator.current : null;
  }

  T? get lastOrNull {
    final iterator = this.iterator;
    if (!iterator.moveNext()) return null;
    var value = iterator.current;
    while (iterator.moveNext()) {
      value = iterator.current;
    }
    return value;
  }
}
