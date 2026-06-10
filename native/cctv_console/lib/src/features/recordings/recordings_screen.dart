import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';
import 'package:open_filex/open_filex.dart';
import 'package:provider/provider.dart';

import '../../core/models/models.dart';
import '../../core/network/api_client.dart';
import '../../core/refresh/refresh_bus.dart';
import '../../core/theme/app_theme.dart';
import '../../shared/widgets/glass_panel.dart';
import '../../shared/widgets/mjpeg_stream_view.dart';
import '../auth/auth_controller.dart';
import '../modules/module_screens.dart'
    show EmptyPanel, ErrorPanel, ModuleHeader, RefreshButton;

const _archivePageSize = 60;
const _maxTimelineEvents = 10000;

class ArchiveRecordingsScreen extends StatefulWidget {
  const ArchiveRecordingsScreen({super.key});

  @override
  State<ArchiveRecordingsScreen> createState() =>
      _ArchiveRecordingsScreenState();
}

class _ArchiveRecordingsScreenState extends State<ArchiveRecordingsScreen>
    with RouteRefreshState<ArchiveRecordingsScreen> {
  late final Player _player;
  late final VideoController _videoController;
  late final ScrollController _scrollController;
  StreamSubscription<bool>? _completedSub;

  var _loading = false;
  String? _error;
  List<CameraSummary> _cameras = const [];
  List<_RecordingClip> _records = const [];
  List<_ArchiveDay> _archiveDays = const [];
  List<_TimelineEvent> _events = const [];
  int? _cameraId;
  DateTime? _selectedDay;
  int? _selectedHour;
  int _selectedHourTotal = 0;
  int? _selectedId;
  int? _openedClipId;
  bool _chainPlayback = false;
  String _eventTypeFilter = 'all';
  bool _loadingMore = false;
  bool _hasMore = true;

  @override
  void initState() {
    super.initState();
    _player = Player();
    _videoController = VideoController(_player);
    _scrollController = ScrollController()..addListener(_maybeLoadMore);
    _completedSub = _player.stream.completed.listen((completed) {
      if (completed && _chainPlayback && mounted) {
        _playNextClip();
      }
    });
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  String get refreshRoute => '/recordings';

  @override
  Future<void> onRefreshRequested() {
    if (_loading) return Future<void>.value();
    return _load();
  }

  @override
  void dispose() {
    _scrollController.dispose();
    _completedSub?.cancel();
    unawaited(_player.dispose());
    super.dispose();
  }

  Future<void> _load({
    bool append = false,
    bool preservePlayback = true,
  }) async {
    final auth = context.read<AuthController>();
    final token = auth.accessToken;
    final api = context.read<ApiClient>();
    if (token == null) return;
    if (append && (!_hasMore || _loadingMore || _loading)) return;

    setState(() {
      if (append) {
        _loadingMore = true;
      } else {
        _loading = true;
      }
      _error = null;
    });

    try {
      if ((auth.mediaToken ?? '').isEmpty) {
        await auth.refreshMediaToken();
      }

      final activeCameraId = _cameraId;
      var archiveDays = _archiveDays;
      var selectedDay = _selectedDay;
      var selectedHour = _selectedHour;
      var cameras = _cameras;
      if (!append) {
        final results = await Future.wait<Object?>([
          api.listCameras(token),
          api.getJson(
            '/recordings/timeline',
            token: token,
            query: {
              if (activeCameraId != null) 'camera_id': '$activeCameraId',
              'day_limit': '62',
            },
          ),
        ]);
        cameras = results[0] as List<CameraSummary>;
        final timeline = Map<String, dynamic>.from(
          results[1] as Map<dynamic, dynamic>,
        );
        archiveDays = (timeline['days'] as List<dynamic>? ?? const [])
            .whereType<Map<dynamic, dynamic>>()
            .map((item) => _ArchiveDay.fromJson(Map<String, dynamic>.from(item)))
            .toList();
        final selectedStillExists = archiveDays.any(
          (day) =>
              _sameDay(day.date, selectedDay) &&
              day.hours.any((hour) => hour.hour == selectedHour),
        );
        if (!selectedStillExists) {
          selectedDay = archiveDays.firstOrNull?.date;
          selectedHour = archiveDays.firstOrNull?.hours.firstOrNull?.hour;
        }
      }

      final bounds = _selectedHourBounds(selectedDay, selectedHour);
      final offset = append ? _records.length : 0;
      final query = <String, String?>{
        if (activeCameraId != null) 'camera_id': '$activeCameraId',
        'limit': '$_archivePageSize',
        'offset': '$offset',
        if (bounds != null) 'date_from': bounds.$1.toIso8601String(),
        if (bounds != null) 'date_to': bounds.$2.toIso8601String(),
      };

      final pagePayload = await api.getJson(
        '/recordings/page',
        token: token,
        query: query,
      );
      final page = Map<String, dynamic>.from(
        pagePayload as Map<dynamic, dynamic>,
      );
      final total = (page['total'] as num?)?.toInt() ?? 0;
      final pageItems = (page['items'] as List<dynamic>? ?? const [])
          .whereType<Map<dynamic, dynamic>>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();

      final pageRecords = pageItems
          .map(_RecordingClip.fromJson)
          .where((record) => record.fileKind == 'video')
          .toList();
      final combined = append
          ? _mergeRecords(_records, pageRecords)
          : pageRecords;
      combined.sort((left, right) => left.startedAt.compareTo(right.startedAt));

      final eventQuery = <String, String?>{
        if (activeCameraId != null) 'camera_id': '$activeCameraId',
        'limit': '$_maxTimelineEvents',
        if (combined.isNotEmpty)
          'date_from': combined.first.startedAt.toIso8601String(),
        if (combined.isNotEmpty)
          'date_to': combined.last.endAt.toIso8601String(),
      };
      final events = combined.isEmpty
          ? <_TimelineEvent>[]
          : await api
                .getJsonList(
                  '/detections/timeline',
                  token: token,
                  query: eventQuery,
                )
                .then(
                  (items) =>
                      items.map(_TimelineEvent.fromJson).toList()
                        ..sort((left, right) => left.ts.compareTo(right.ts)),
                );

      final currentSelected = _selectedId;
      final selected = combined.any((record) => record.id == currentSelected)
          ? currentSelected
          : combined.lastOrNull?.id;
      if (!mounted) return;
      setState(() {
        _cameras = cameras;
        _cameraId = activeCameraId;
        _archiveDays = archiveDays;
        _selectedDay = selectedDay;
        _selectedHour = selectedHour;
        _selectedHourTotal = total;
        _records = combined;
        _events = events;
        _selectedId = selected;
        _hasMore = combined.length < total;
      });

      if (!append) {
        final openedClipStillExists =
            _openedClipId != null &&
            combined.any((record) => record.id == _openedClipId);
        if (!preservePlayback || !openedClipStillExists) {
          _openedClipId = null;
          _chainPlayback = false;
          await _player.stop();
        }
      }
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = '$error');
    } finally {
      if (mounted) {
        setState(() {
          _loading = false;
          _loadingMore = false;
        });
      }
    }
  }

  Future<void> _selectArchiveHour(DateTime day, int hour) async {
    if (_loading || (_sameDay(day, _selectedDay) && hour == _selectedHour)) {
      return;
    }
    setState(() {
      _selectedDay = day;
      _selectedHour = hour;
      _selectedId = null;
      _records = const [];
      _events = const [];
      _hasMore = true;
    });
    await _load(preservePlayback: false);
  }

  List<_RecordingClip> _mergeRecords(
    List<_RecordingClip> current,
    List<_RecordingClip> page,
  ) {
    final byId = <int, _RecordingClip>{
      for (final record in current) record.id: record,
    };
    for (final record in page) {
      byId[record.id] = record;
    }
    return byId.values.toList();
  }

  void _maybeLoadMore() {
    if (!_scrollController.hasClients ||
        !_hasMore ||
        _loadingMore ||
        _loading) {
      return;
    }
    final position = _scrollController.position;
    if (position.pixels >= position.maxScrollExtent - 900) {
      unawaited(_load(append: true));
    }
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
    Duration? seekTo,
  }) async {
    if (!mounted) return;
    if (!keepChain) _chainPlayback = false;
    setState(() {
      _selectedId = record.id;
    });
    await _ensureMediaToken();
    await _player.open(Media(_recordingUri(record).toString()), play: play);
    _openedClipId = record.id;
    if (seekTo != null && seekTo > Duration.zero) {
      await _player.seek(seekTo);
    }
  }

  Future<void> _openArchivePosition(
    DateTime position, {
    bool play = false,
  }) async {
    if (_records.isEmpty) return;
    _RecordingClip? target;
    for (final record in _records) {
      if (!position.isBefore(record.startedAt) &&
          position.isBefore(record.endAt)) {
        target = record;
        break;
      }
    }
    target ??= _records.lastWhere(
      (record) => !record.startedAt.isAfter(position),
      orElse: () => _records.first,
    );
    final offset = position.difference(target.startedAt);
    final boundedOffset = offset.isNegative
        ? Duration.zero
        : offset > target.duration
        ? target.duration
        : offset;
    await _openClip(target, play: play, seekTo: boundedOffset);
  }

  Future<void> _playFrom(_RecordingClip record) async {
    _chainPlayback = true;
    await _openClip(record, play: true);
  }

  Future<void> _playArchive() async {
    final first = _records.firstOrNull;
    if (first == null) return;
    _chainPlayback = true;
    await _openClip(first, play: true);
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
    return _snapshotUriById(record.id);
  }

  Uri _snapshotUriById(int recordingId) {
    final token = context.read<AuthController>().mediaToken ?? '';
    return context.read<ApiClient>().uri('/recordings/snapshot/$recordingId', {
      'token': token,
      'ts': '0',
      'max_width': '640',
      'quality': '70',
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
    final visibleEvents = _visibleEvents;
    final clipList = _records.reversed.toList(growable: false);

    return RefreshIndicator(
      onRefresh: _load,
      child: CustomScrollView(
        controller: _scrollController,
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: Column(
              children: [
                ModuleHeader(
                  title: 'Записи',
                  icon: Icons.video_library_rounded,
                  trailing: Wrap(
                    spacing: 10,
                    runSpacing: 8,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      ElevatedButton.icon(
                        onPressed: _records.isEmpty ? null : _playArchive,
                        icon: const Icon(Icons.play_circle_rounded, size: 18),
                        label: const Text('Воспроизвести архив'),
                      ),
                      RefreshButton(loading: _loading, onPressed: _load),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                _ArchiveControls(
                  cameras: _cameras,
                  cameraId: _cameraId,
                  loading: _loading,
                  onCameraChanged: (value) async {
                    setState(() {
                      _cameraId = value;
                      _selectedId = null;
                      _selectedDay = null;
                      _selectedHour = null;
                      _archiveDays = const [];
                      _records = const [];
                      _hasMore = true;
                    });
                    await _load(preservePlayback: false);
                  },
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
                    message: 'За выбранный день записей нет.',
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
                if (_archiveDays.isNotEmpty)
                  _ArchiveBrowser(
                    days: _archiveDays,
                    selectedDay: _selectedDay,
                    selectedHour: _selectedHour,
                    snapshotUri: (recordingId) =>
                        _snapshotUriById(recordingId).toString(),
                    onSelectHour: _selectArchiveHour,
                  ),
                if (_archiveDays.isNotEmpty) const SizedBox(height: 14),
                if (_records.isNotEmpty)
                  _ArchiveTimelineSlider(
                    records: _records,
                    events: visibleEvents,
                    selectedId: _selectedId,
                    onSelectRecord: (record) => _openClip(record, play: false),
                    onSelectPosition: (position) =>
                        _openArchivePosition(position),
                  ),
                const SizedBox(height: 14),
                if (_records.isNotEmpty)
                  _SummaryRail(records: _records, events: visibleEvents),
                const SizedBox(height: 14),
                if (_records.isNotEmpty)
                  _SectionTitle(
                    title:
                        'Клипы ${_selectedDay == null ? '' : DateFormat('dd.MM.yyyy').format(_selectedDay!)} ${_selectedHour == null ? '' : '${_selectedHour!.toString().padLeft(2, '0')}:00'}',
                  ),
                const SizedBox(height: 12),
              ],
            ),
          ),
          if (_records.isNotEmpty)
            SliverGrid.builder(
              gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                maxCrossAxisExtent: 300,
                mainAxisExtent: 224,
                crossAxisSpacing: 10,
                mainAxisSpacing: 10,
              ),
              itemCount: clipList.length + (_hasMore ? 1 : 0),
              itemBuilder: (context, index) {
                if (index >= clipList.length) {
                  return Center(
                    child: _loadingMore
                        ? const CircularProgressIndicator(strokeWidth: 2)
                        : OutlinedButton.icon(
                            onPressed: () => _load(append: true),
                            icon: const Icon(Icons.expand_more_rounded),
                            label: Text(
                              'Ещё ${(_selectedHourTotal - _records.length).clamp(0, _archivePageSize)}',
                            ),
                          ),
                  );
                }
                final record = clipList[index];
                return _ArchiveClipCard(
                  record: record,
                  active: record.id == _selectedId,
                  snapshotUri: _snapshotUri(record).toString(),
                  events: _eventsForClip(record),
                  onTap: () => _openClip(record, play: false),
                  onPlay: () => _playFrom(record),
                );
              },
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
    required this.loading,
    required this.onCameraChanged,
    required this.eventTypeFilter,
    required this.onEventTypeChanged,
  });

  final List<CameraSummary> cameras;
  final int? cameraId;
  final bool loading;
  final ValueChanged<int?> onCameraChanged;
  final String eventTypeFilter;
  final ValueChanged<String> onEventTypeChanged;

  @override
  Widget build(BuildContext context) {
    return GlassPanel(
      padding: const EdgeInsets.all(14),
      child: Wrap(
        spacing: 12,
        runSpacing: 12,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          SizedBox(
            width: 280,
            child: DropdownButtonFormField<int?>(
              initialValue: cameras.any((camera) => camera.cameraId == cameraId)
                  ? cameraId
                  : null,
              isExpanded: true,
              decoration: const InputDecoration(
                labelText: 'Камера',
                prefixIcon: Icon(Icons.videocam_rounded),
              ),
              items: [
                const DropdownMenuItem<int?>(
                  value: null,
                  child: Text('Все камеры'),
                ),
                for (final camera in cameras)
                  DropdownMenuItem<int?>(
                    value: camera.cameraId,
                    child: Text('${camera.name} (#${camera.cameraId})'),
                  ),
              ],
              onChanged: loading ? null : onCameraChanged,
            ),
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
    final details = current == null
        ? null
        : '${_formatDuration(current.durationSeconds)} · ${_formatBytes(current.sizeBytes)} · ${chainPlayback ? 'непрерывное воспроизведение' : 'одиночный просмотр'}';
    final titleBlock = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          current == null
              ? 'Архивный медиаплеер'
              : 'Клип ${_timeRange(current)}',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        if (details != null) ...[
          const SizedBox(height: 4),
          Text(details, style: TextStyle(color: colors.muted, fontSize: 13)),
        ],
      ],
    );
    final headerActions = current == null
        ? const <Widget>[]
        : <Widget>[
            _EventBadge(
              label: '${events.length} меток',
              icon: Icons.sell_rounded,
              color: colors.primaryAccent,
            ),
            OutlinedButton.icon(
              onPressed: onDownload,
              icon: const Icon(Icons.download_rounded, size: 18),
              label: const Text('Открыть файл'),
            ),
            OutlinedButton.icon(
              onPressed: onMjpegFallback,
              icon: const Icon(Icons.video_file_rounded, size: 18),
              label: const Text('Резервный MJPEG'),
            ),
          ];
    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          LayoutBuilder(
            builder: (context, constraints) {
              final compact = constraints.maxWidth < 620;
              if (compact) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    titleBlock,
                    if (headerActions.isNotEmpty) ...[
                      const SizedBox(height: 10),
                      Wrap(spacing: 8, runSpacing: 8, children: headerActions),
                    ],
                  ],
                );
              }

              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: titleBlock),
                  if (headerActions.isNotEmpty) ...[
                    const SizedBox(width: 10),
                    Flexible(
                      child: Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        alignment: WrapAlignment.end,
                        children: headerActions,
                      ),
                    ),
                  ],
                ],
              );
            },
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
      title: const Text('Резервный просмотр'),
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
                  child: MjpegStreamView(
                    uri: Uri.parse(uri),
                    fit: BoxFit.contain,
                    errorBuilder: (_, _) => Center(
                      child: Text(
                        'Резервный поток не открылся. Проверьте запись или повторите позже.',
                        style: TextStyle(color: colors.muted),
                      ),
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 10),
            Text(
              'Если обычное видео не воспроизводится на устройстве, этот режим показывает архив покадрово.',
              style: TextStyle(color: colors.muted, fontSize: 12),
              textAlign: TextAlign.center,
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

class _ArchiveTimelineSlider extends StatefulWidget {
  const _ArchiveTimelineSlider({
    required this.records,
    required this.events,
    required this.selectedId,
    required this.onSelectRecord,
    required this.onSelectPosition,
  });

  final List<_RecordingClip> records;
  final List<_TimelineEvent> events;
  final int? selectedId;
  final ValueChanged<_RecordingClip> onSelectRecord;
  final ValueChanged<DateTime> onSelectPosition;

  @override
  State<_ArchiveTimelineSlider> createState() => _ArchiveTimelineSliderState();
}

class _ArchiveTimelineSliderState extends State<_ArchiveTimelineSlider> {
  double? _dragValue;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final records = widget.records;
    final start = records.first.startedAt;
    final end = records.last.endAt.isAfter(start)
        ? records.last.endAt
        : start.add(const Duration(minutes: 1));
    final totalMs = end
        .difference(start)
        .inMilliseconds
        .clamp(1, 1 << 53)
        .toInt();
    final selected = records
        .where((record) => record.id == widget.selectedId)
        .firstOrNull;
    final selectedMs = selected == null
        ? totalMs.toDouble()
        : selected.startedAt
              .difference(start)
              .inMilliseconds
              .clamp(0, totalMs)
              .toDouble();
    final value = (_dragValue ?? selectedMs)
        .clamp(0.0, totalMs.toDouble())
        .toDouble();

    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _SectionTitle(title: 'Архивная лента'),
          const SizedBox(height: 12),
          LayoutBuilder(
            builder: (context, constraints) {
              final hours = end.difference(start).inHours + 2;
              final width = (hours * 92.0)
                  .clamp(constraints.maxWidth, 16000.0)
                  .toDouble();
              return SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: SizedBox(
                  width: width,
                  height: 100,
                  child: Stack(
                    children: [
                      Positioned(
                        left: 0,
                        right: 0,
                        top: 20,
                        height: 38,
                        child: CustomPaint(
                          painter: _ArchiveTimelinePainter(
                            records: records,
                            events: widget.events,
                            selectedId: widget.selectedId,
                            start: start,
                            totalMs: totalMs,
                            colors: colors,
                          ),
                        ),
                      ),
                      Positioned(
                        left: 0,
                        right: 0,
                        top: 0,
                        child: SliderTheme(
                          data: SliderTheme.of(context).copyWith(
                            trackHeight: 0,
                            activeTrackColor: Colors.transparent,
                            inactiveTrackColor: Colors.transparent,
                            overlayShape: SliderComponentShape.noOverlay,
                            thumbColor: colors.secondaryAccent,
                          ),
                          child: Slider(
                            min: 0,
                            max: totalMs.toDouble(),
                            value: value,
                            onChanged: (next) =>
                                setState(() => _dragValue = next),
                            onChangeEnd: (next) {
                              setState(() => _dragValue = null);
                              widget.onSelectPosition(
                                start.add(Duration(milliseconds: next.round())),
                              );
                            },
                          ),
                        ),
                      ),
                      for (final tick in _hourTicks(start, end))
                        Positioned(
                          left:
                              width *
                              tick.difference(start).inMilliseconds /
                              totalMs,
                          top: 63,
                          child: Text(
                            DateFormat('dd.MM HH:00').format(tick),
                            style: TextStyle(
                              color: colors.muted,
                              fontSize: 10,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                      for (final record in records)
                        Positioned(
                          left:
                              width *
                              record.startedAt
                                  .difference(start)
                                  .inMilliseconds /
                              totalMs,
                          top: 20,
                          width:
                              (width * record.duration.inMilliseconds / totalMs)
                                  .clamp(5.0, 140.0)
                                  .toDouble(),
                          height: 38,
                          child: Tooltip(
                            message: _timeRange(record),
                            child: InkWell(
                              borderRadius: BorderRadius.circular(999),
                              onTap: () => widget.onSelectRecord(record),
                              child: const SizedBox.expand(),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              );
            },
          ),
          const SizedBox(height: 8),
          if (selected != null)
            Text(
              'Текущий клип: ${DateFormat('dd.MM.yyyy HH:mm:ss').format(selected.startedAt)}',
              style: TextStyle(color: colors.muted, fontSize: 12),
            ),
        ],
      ),
    );
  }
}

class _ArchiveTimelinePainter extends CustomPainter {
  const _ArchiveTimelinePainter({
    required this.records,
    required this.events,
    required this.selectedId,
    required this.start,
    required this.totalMs,
    required this.colors,
  });

  final List<_RecordingClip> records;
  final List<_TimelineEvent> events;
  final int? selectedId;
  final DateTime start;
  final int totalMs;
  final AppColors colors;

  @override
  void paint(Canvas canvas, Size size) {
    final basePaint = Paint()
      ..color = colors.surfaceMuted
      ..style = PaintingStyle.fill;
    final borderPaint = Paint()
      ..color = colors.border
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    final rect = RRect.fromRectAndRadius(
      Offset.zero & size,
      const Radius.circular(999),
    );
    canvas.drawRRect(rect, basePaint);
    canvas.drawRRect(rect, borderPaint);

    final end = start.add(Duration(milliseconds: totalMs));
    final tickPaint = Paint()
      ..color = colors.border
      ..strokeWidth = 1;
    for (final tick in _hourTicks(start, end)) {
      final x = size.width * tick.difference(start).inMilliseconds / totalMs;
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), tickPaint);
    }

    for (final record in records) {
      final left =
          size.width *
          record.startedAt.difference(start).inMilliseconds /
          totalMs;
      final width = (size.width * record.duration.inMilliseconds / totalMs)
          .clamp(4.0, size.width)
          .toDouble();
      final paint = Paint()
        ..shader = LinearGradient(
          colors: record.id == selectedId
              ? [colors.primaryAccent, colors.secondaryAccent]
              : [
                  colors.primaryAccent.withValues(alpha: 0.70),
                  colors.secondaryAccent.withValues(alpha: 0.45),
                ],
        ).createShader(Rect.fromLTWH(left, 7, width, size.height - 14));
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTWH(left, 7, width, size.height - 14),
          const Radius.circular(999),
        ),
        paint,
      );
    }

    for (final event in events) {
      final diff = event.ts.difference(start).inMilliseconds;
      if (diff < 0 || diff > totalMs) continue;
      final x = size.width * diff / totalMs;
      final paint = Paint()
        ..color = _eventColorByName(colors, event.type)
        ..strokeWidth = 4
        ..strokeCap = StrokeCap.round;
      canvas.drawLine(Offset(x, 4), Offset(x, size.height - 4), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _ArchiveTimelinePainter oldDelegate) {
    return oldDelegate.records != records ||
        oldDelegate.events != events ||
        oldDelegate.selectedId != selectedId ||
        oldDelegate.start != start ||
        oldDelegate.totalMs != totalMs ||
        oldDelegate.colors != colors;
  }
}

class _SummaryRail extends StatelessWidget {
  const _SummaryRail({required this.records, required this.events});

  final List<_RecordingClip> records;
  final List<_TimelineEvent> events;

  @override
  Widget build(BuildContext context) {
    final hours = records.map((record) => record.hour).toSet().length;
    final range = records.isEmpty
        ? '-'
        : '${DateFormat('dd.MM HH:mm').format(records.first.startedAt)} - ${DateFormat('dd.MM HH:mm').format(records.last.endAt)}';
    final totalBytes = records.fold<int>(
      0,
      (sum, record) => sum + (record.sizeBytes ?? 0),
    );
    return Wrap(
      spacing: 12,
      runSpacing: 12,
      children: [
        _MetricPill(label: 'Диапазон', value: range),
        _MetricPill(label: 'Клипы', value: '${records.length}'),
        _MetricPill(label: 'Часы с архивом', value: '$hours'),
        _MetricPill(label: 'Метки', value: '${events.length}'),
        _MetricPill(label: 'Объём', value: _formatBytes(totalBytes)),
      ],
    );
  }
}

class _ArchiveBrowser extends StatelessWidget {
  const _ArchiveBrowser({
    required this.days,
    required this.selectedDay,
    required this.selectedHour,
    required this.snapshotUri,
    required this.onSelectHour,
  });

  final List<_ArchiveDay> days;
  final DateTime? selectedDay;
  final int? selectedHour;
  final String Function(int recordingId) snapshotUri;
  final Future<void> Function(DateTime day, int hour) onSelectHour;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final activeDay =
        days.where((day) => _sameDay(day.date, selectedDay)).firstOrNull ??
        days.first;
    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _SectionTitle(title: 'Архив по времени'),
          const SizedBox(height: 12),
          ScrollConfiguration(
            behavior: ScrollConfiguration.of(
              context,
            ).copyWith(scrollbars: false),
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  for (final day in days)
                    Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ChoiceChip(
                        selected: _sameDay(day.date, activeDay.date),
                        label: Text(
                          '${_dayLabel(day.date)} · ${day.clipCount}',
                        ),
                        onSelected: (_) {
                          final hour = day.hours.firstOrNull?.hour;
                          if (hour != null) {
                            unawaited(onSelectHour(day.date, hour));
                          }
                        },
                      ),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 14),
          GridView.builder(
            shrinkWrap: true,
            primary: false,
            physics: const NeverScrollableScrollPhysics(),
            gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
              maxCrossAxisExtent: 230,
              mainAxisExtent: 146,
              crossAxisSpacing: 10,
              mainAxisSpacing: 10,
            ),
            itemCount: activeDay.hours.length,
            itemBuilder: (context, index) {
              final hour = activeDay.hours[index];
              final selected =
                  _sameDay(activeDay.date, selectedDay) &&
                  hour.hour == selectedHour;
              return Material(
                color: Colors.transparent,
                child: InkWell(
                  onTap: () =>
                      unawaited(onSelectHour(activeDay.date, hour.hour)),
                  borderRadius: BorderRadius.circular(16),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 160),
                    decoration: BoxDecoration(
                      color: colors.surfaceMuted,
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(
                        color: selected
                            ? colors.primaryAccent
                            : colors.border,
                        width: selected ? 2 : 1,
                      ),
                    ),
                    clipBehavior: Clip.antiAlias,
                    child: Stack(
                      fit: StackFit.expand,
                      children: [
                        Image.network(
                          snapshotUri(hour.previewRecordingId),
                          fit: BoxFit.cover,
                          errorBuilder: (_, _, _) => ColoredBox(
                            color: colors.surfaceMuted,
                            child: Icon(
                              Icons.video_library_rounded,
                              color: colors.muted,
                            ),
                          ),
                        ),
                        const DecoratedBox(
                          decoration: BoxDecoration(
                            gradient: LinearGradient(
                              begin: Alignment.topCenter,
                              end: Alignment.bottomCenter,
                              colors: [Colors.transparent, Colors.black87],
                            ),
                          ),
                        ),
                        Positioned(
                          left: 10,
                          right: 10,
                          bottom: 9,
                          child: Row(
                            children: [
                              const Icon(
                                Icons.play_circle_fill_rounded,
                                color: Colors.white,
                                size: 18,
                              ),
                              const SizedBox(width: 7),
                              Expanded(
                                child: Text(
                                  '${hour.hour.toString().padLeft(2, '0')}:00',
                                  style: const TextStyle(
                                    color: Colors.white,
                                    fontWeight: FontWeight.w900,
                                  ),
                                ),
                              ),
                              Text(
                                '${hour.clipCount}',
                                style: const TextStyle(
                                  color: Colors.white70,
                                  fontSize: 12,
                                  fontWeight: FontWeight.w800,
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
          ),
        ],
      ),
    );
  }
}

class _ArchiveClipCard extends StatelessWidget {
  const _ArchiveClipCard({
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
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(18),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          decoration: BoxDecoration(
            color: colors.surface,
            borderRadius: BorderRadius.circular(18),
            border: Border.all(
              color: active ? colors.primaryAccent : colors.border,
              width: active ? 2 : 1,
            ),
          ),
          clipBehavior: Clip.antiAlias,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    Image.network(
                      snapshotUri,
                      fit: BoxFit.cover,
                      errorBuilder: (_, _, _) =>
                          _ArchiveSnapshotPlaceholder(record: record),
                    ),
                    Positioned(
                      right: 8,
                      bottom: 8,
                      child: IconButton.filled(
                        tooltip: 'Воспроизвести',
                        onPressed: onPlay,
                        icon: const Icon(Icons.play_arrow_rounded),
                      ),
                    ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 10, 12, 11),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      DateFormat('HH:mm:ss').format(record.startedAt),
                      style: TextStyle(
                        color: colors.textStrong,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${_formatDuration(record.durationSeconds)} · ${_formatBytes(record.sizeBytes)} · меток ${events.length}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: colors.muted, fontSize: 12),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ArchiveSnapshotPlaceholder extends StatelessWidget {
  const _ArchiveSnapshotPlaceholder({required this.record});

  final _RecordingClip record;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      color: colors.surfaceMuted,
      alignment: Alignment.center,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.movie_filter_rounded, color: colors.primaryAccent),
          const SizedBox(height: 4),
          Text(
            DateFormat('HH:mm').format(record.startedAt),
            style: TextStyle(
              color: colors.text,
              fontSize: 12,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
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
  const _SectionTitle({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: Theme.of(context).textTheme.headlineSmall),
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

class _ArchiveDay {
  const _ArchiveDay({
    required this.date,
    required this.clipCount,
    required this.durationSeconds,
    required this.sizeBytes,
    required this.hours,
  });

  final DateTime date;
  final int clipCount;
  final double durationSeconds;
  final int sizeBytes;
  final List<_ArchiveHour> hours;

  factory _ArchiveDay.fromJson(Map<String, dynamic> json) {
    return _ArchiveDay(
      date: DateTime.tryParse('${json['date']}') ?? DateTime.now(),
      clipCount: (json['clip_count'] as num?)?.toInt() ?? 0,
      durationSeconds: (json['duration_seconds'] as num?)?.toDouble() ?? 0,
      sizeBytes: (json['size_bytes'] as num?)?.toInt() ?? 0,
      hours: (json['hours'] as List<dynamic>? ?? const [])
          .whereType<Map<dynamic, dynamic>>()
          .map(
            (item) =>
                _ArchiveHour.fromJson(Map<String, dynamic>.from(item)),
          )
          .toList(),
    );
  }
}

class _ArchiveHour {
  const _ArchiveHour({
    required this.hour,
    required this.clipCount,
    required this.durationSeconds,
    required this.sizeBytes,
    required this.previewRecordingId,
  });

  final int hour;
  final int clipCount;
  final double durationSeconds;
  final int sizeBytes;
  final int previewRecordingId;

  factory _ArchiveHour.fromJson(Map<String, dynamic> json) {
    return _ArchiveHour(
      hour: (json['hour'] as num?)?.toInt() ?? 0,
      clipCount: (json['clip_count'] as num?)?.toInt() ?? 0,
      durationSeconds: (json['duration_seconds'] as num?)?.toDouble() ?? 0,
      sizeBytes: (json['size_bytes'] as num?)?.toInt() ?? 0,
      previewRecordingId:
          (json['preview_recording_id'] as num?)?.toInt() ?? 0,
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
  Duration get duration {
    final milliseconds =
        ((durationSeconds ?? endAt.difference(startedAt).inSeconds) * 1000)
            .round()
            .clamp(1000, 24 * 60 * 60 * 1000);
    return Duration(milliseconds: milliseconds);
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

bool _sameDay(DateTime? left, DateTime? right) {
  return left != null &&
      right != null &&
      left.year == right.year &&
      left.month == right.month &&
      left.day == right.day;
}

(DateTime, DateTime)? _selectedHourBounds(DateTime? day, int? hour) {
  if (day == null || hour == null) return null;
  final start = DateTime(day.year, day.month, day.day, hour);
  return (
    start,
    start.add(const Duration(hours: 1)).subtract(const Duration(milliseconds: 1)),
  );
}

String _dayLabel(DateTime day) {
  final now = DateTime.now();
  final today = DateTime(now.year, now.month, now.day);
  final value = DateTime(day.year, day.month, day.day);
  if (value == today) return 'Сегодня';
  if (value == today.subtract(const Duration(days: 1))) return 'Вчера';
  return DateFormat('dd.MM.yyyy').format(day);
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
  return _eventColorByName(colors, type);
}

Color _eventColorByName(AppColors colors, String type) {
  return switch (type) {
    'face_recognized' => colors.success,
    'face_unknown' => colors.warning,
    'person_detected' => colors.primaryAccent,
    'motion_detected' => colors.secondaryAccent,
    _ => colors.muted,
  };
}

List<DateTime> _hourTicks(DateTime start, DateTime end) {
  var tick = DateTime(start.year, start.month, start.day, start.hour);
  if (tick.isBefore(start)) {
    tick = tick.add(const Duration(hours: 1));
  }
  final ticks = <DateTime>[];
  while (!tick.isAfter(end)) {
    ticks.add(tick);
    tick = tick.add(const Duration(hours: 1));
  }
  return ticks;
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
