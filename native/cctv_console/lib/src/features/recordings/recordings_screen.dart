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

const _archivePageSize = 220;
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
  List<_TimelineEvent> _events = const [];
  int? _cameraId;
  int? _selectedId;
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

  Future<void> _load({bool append = false}) async {
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

      final cameras = await api.listCameras(token);
      final activeCameraId = _cameraId;
      final offset = append ? _records.length : 0;
      final query = <String, String?>{
        if (activeCameraId != null) 'camera_id': '$activeCameraId',
        'limit': '$_archivePageSize',
        'offset': '$offset',
      };

      final page = await api.getJsonList(
        '/recordings',
        token: token,
        query: query,
      );

      final pageRecords = page
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
      final selectedRecord = selected == null
          ? null
          : combined.firstWhere((record) => record.id == selected);

      if (!mounted) return;
      setState(() {
        _cameras = cameras;
        _cameraId = activeCameraId;
        _records = combined;
        _events = events;
        _selectedId = selected;
        _hasMore = pageRecords.length >= _archivePageSize;
      });

      if (!append && selectedRecord != null) {
        await _openClip(selectedRecord, play: false, keepChain: false);
      } else if (!append) {
        await _player.stop();
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
                  subtitle:
                      'Единая архивная лента по всем сохранённым видео. Старые сегменты подгружаются при прокрутке.',
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
                      _hasMore = true;
                    });
                    await _load();
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
                    title: 'Все клипы',
                    subtitle:
                        '${_records.length} загружено. Прокрутите ниже, чтобы подгрузить более старые записи.',
                  ),
                const SizedBox(height: 12),
              ],
            ),
          ),
          if (_records.isNotEmpty)
            SliverList.builder(
              itemCount: clipList.length + (_hasMore ? 1 : 0),
              itemBuilder: (context, index) {
                if (index >= clipList.length) {
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: Center(
                      child: _loadingMore
                          ? const CircularProgressIndicator(strokeWidth: 2)
                          : OutlinedButton.icon(
                              onPressed: () => _load(append: true),
                              icon: const Icon(Icons.expand_more_rounded),
                              label: const Text('Загрузить более старые'),
                            ),
                    ),
                  );
                }
                final record = clipList[index];
                return Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: _ArchiveClipRow(
                    record: record,
                    active: record.id == _selectedId,
                    snapshotUri: _snapshotUri(record).toString(),
                    events: _eventsForClip(record),
                    onTap: () => _openClip(record, play: false),
                    onPlay: () => _playFrom(record),
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
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: colors.surfaceMuted,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: colors.border),
            ),
            child: Text(
              'Структура: единая лента → минутные клипы → метки событий',
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
    final titleBlock = Column(
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
              label: const Text('MJPEG fallback'),
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
                  child: MjpegStreamView(
                    uri: Uri.parse(uri),
                    fit: BoxFit.contain,
                    errorBuilder: (_, _) => Center(
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
          const _SectionTitle(
            title: 'Архивная лента',
            subtitle:
                'Единая шкала по загруженным записям: каждый час отмечен, цветные риски - события.',
          ),
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
          Text(
            selected == null
                ? 'Выберите позицию на шкале.'
                : 'Текущий клип: ${DateFormat('dd.MM.yyyy HH:mm:ss').format(selected.startedAt)}',
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

class _ArchiveClipRow extends StatelessWidget {
  const _ArchiveClipRow({
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
    Widget snapshot({double? width, double? height, bool expanded = false}) {
      final image = Image.network(
        snapshotUri,
        fit: BoxFit.cover,
        errorBuilder: (context, error, stackTrace) => Container(
          color: colors.surfaceMuted,
          child: Icon(Icons.broken_image_rounded, color: colors.muted),
        ),
      );
      return ClipRRect(
        borderRadius: BorderRadius.circular(15),
        child: expanded
            ? AspectRatio(aspectRatio: 16 / 9, child: image)
            : SizedBox(width: width, height: height, child: image),
      );
    }

    final details = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          DateFormat('dd.MM.yyyy HH:mm:ss').format(record.startedAt),
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
            color: colors.textStrong,
            fontWeight: FontWeight.w900,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          '${_timeRange(record)} · ${_formatDuration(record.durationSeconds)} · ${_formatBytes(record.sizeBytes)}',
          style: TextStyle(color: colors.muted, fontSize: 12),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            if (events.isEmpty)
              _EventBadge(
                label: 'без меток',
                icon: Icons.radio_button_unchecked_rounded,
                color: colors.muted,
              )
            else
              for (final event in events.take(3))
                _EventBadge(
                  label:
                      '${_eventLabel(event.type)} ${DateFormat('HH:mm:ss').format(event.ts)}',
                  icon: _eventIcon(event.type),
                  color: _eventColor(context, event.type),
                ),
          ],
        ),
      ],
    );

    final playButton = IconButton.filled(
      onPressed: onPlay,
      icon: const Icon(Icons.play_arrow_rounded),
      tooltip: 'Играть отсюда',
    );

    return RepaintBoundary(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: colors.surface,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(
              color: active ? colors.primaryAccent : colors.border,
            ),
          ),
          child: LayoutBuilder(
            builder: (context, constraints) {
              final compact = constraints.maxWidth < 420;
              if (compact) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    snapshot(expanded: true),
                    const SizedBox(height: 10),
                    details,
                    const SizedBox(height: 8),
                    Align(alignment: Alignment.centerRight, child: playButton),
                  ],
                );
              }

              return Row(
                children: [
                  snapshot(width: 148, height: 84),
                  const SizedBox(width: 14),
                  Expanded(child: details),
                  const SizedBox(width: 10),
                  playButton,
                ],
              );
            },
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
