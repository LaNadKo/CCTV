import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../core/models/models.dart';
import '../../core/network/api_client.dart';
import '../../core/refresh/refresh_bus.dart';
import '../../core/theme/app_theme.dart';
import '../../core/theme/theme_controller.dart';
import '../../shared/widgets/glass_panel.dart';
import '../../shared/widgets/mjpeg_stream_view.dart';
import '../auth/auth_controller.dart';

class LiveScreen extends StatefulWidget {
  const LiveScreen({super.key});

  @override
  State<LiveScreen> createState() => _LiveScreenState();
}

class _LiveScreenState extends State<LiveScreen>
    with RouteRefreshState<LiveScreen> {
  bool _loading = false;
  String? _error;
  List<CameraSummary> _cameras = const [];
  List<ProcessorOut> _processors = const [];
  List<PendingEvent> _pending = const [];
  bool _annotate = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  String get refreshRoute => '/live';

  @override
  Future<void> onRefreshRequested() {
    if (_loading) return Future<void>.value();
    return _load();
  }

  Future<void> _load() async {
    final auth = context.read<AuthController>();
    final api = context.read<ApiClient>();
    final token = auth.accessToken;
    if (token == null) return;

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final camerasFuture = api.listCameras(token);
      final processorsFuture = (auth.user?.isAdmin ?? false)
          ? api.listProcessors(token)
          : Future<List<ProcessorOut>>.value(const []);
      final pendingFuture = (auth.user?.canReview ?? false)
          ? api.listPendingEvents(token)
          : Future<List<PendingEvent>>.value(const []);
      final result = await Future.wait([
        camerasFuture,
        processorsFuture,
        pendingFuture,
      ]);
      if (!mounted) return;
      setState(() {
        _cameras = result[0] as List<CameraSummary>;
        _processors = result[1] as List<ProcessorOut>;
        _pending = result[2] as List<PendingEvent>;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final onlineProcessors = _processors.where((item) => item.online).length;
    final settings = context.watch<ThemeController>();
    final density = settings.liveDensity;
    final cameras = _orderedCameras(_cameras, settings.liveCameraOrder);
    final crossAxisCount = _gridColumns(
      MediaQuery.sizeOf(context).width,
      density,
      settings.liveGridColumns,
    );

    return RefreshIndicator(
      onRefresh: _load,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _LiveHeader(loading: _loading, onRefresh: _load),
                const SizedBox(height: 18),
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 14),
                    child: _ErrorBanner(message: _error!, onRetry: _load),
                  ),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final compact = constraints.maxWidth < 760;
                    final cards = [
                      StatCard(
                        label: 'Камер в системе',
                        value: '${_cameras.length}',
                        icon: Icons.videocam_rounded,
                        compact: compact,
                      ),
                      StatCard(
                        label: 'Processor online',
                        value: '$onlineProcessors / ${_processors.length}',
                        icon: Icons.memory_rounded,
                        accent: onlineProcessors > 0
                            ? colors.success
                            : colors.warning,
                        compact: compact,
                      ),
                      StatCard(
                        label: 'Ожидают ревью',
                        value: '${_pending.length}',
                        icon: Icons.fact_check_rounded,
                        accent: _pending.isEmpty
                            ? colors.success
                            : colors.warning,
                        compact: compact,
                      ),
                    ];
                    if (compact) {
                      final tileWidth = constraints.maxWidth >= 330
                          ? (constraints.maxWidth - 8) / 2
                          : constraints.maxWidth;
                      return Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          for (final card in cards)
                            SizedBox(width: tileWidth, child: card),
                        ],
                      );
                    }
                    return Row(
                      children: cards
                          .map(
                            (card) => Expanded(
                              child: Padding(
                                padding: const EdgeInsets.only(right: 12),
                                child: card,
                              ),
                            ),
                          )
                          .toList(),
                    );
                  },
                ),
                const SizedBox(height: 18),
                _GridControls(
                  columns: settings.liveGridColumns,
                  annotate: _annotate,
                  onColumnsChanged: settings.setLiveGridColumns,
                  onAnnotateChanged: (value) =>
                      setState(() => _annotate = value),
                  onResetOrder: cameras.length < 2
                      ? null
                      : () => settings.setLiveCameraOrder(const []),
                ),
                const SizedBox(height: 18),
              ],
            ),
          ),
          if (cameras.isEmpty && !_loading)
            SliverFillRemaining(
              hasScrollBody: false,
              child: Center(
                child: GlassPanel(
                  child: Text(
                    'Камер пока нет или backend вернул пустой список.',
                    style: TextStyle(color: colors.muted),
                  ),
                ),
              ),
            )
          else
            SliverGrid(
              delegate: SliverChildBuilderDelegate((context, index) {
                final camera = cameras[index];
                return _DraggableCameraTile(
                  camera: camera,
                  annotate: _annotate,
                  onMoveBefore: _reorderCameras,
                );
              }, childCount: cameras.length),
              gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: crossAxisCount,
                crossAxisSpacing: 16,
                mainAxisSpacing: 16,
                childAspectRatio: density == LiveDensity.compact ? 1.25 : 1.04,
              ),
            ),
        ],
      ),
    );
  }

  List<CameraSummary> _orderedCameras(
    List<CameraSummary> cameras,
    List<int> order,
  ) {
    if (order.isEmpty || cameras.length < 2) return cameras;
    final byId = {for (final camera in cameras) camera.cameraId: camera};
    final result = <CameraSummary>[];
    for (final id in order) {
      final camera = byId.remove(id);
      if (camera != null) result.add(camera);
    }
    result.addAll(byId.values);
    return result;
  }

  void _reorderCameras(int draggedId, int targetId) {
    if (draggedId == targetId) return;
    final settings = context.read<ThemeController>();
    final ordered = _orderedCameras(
      _cameras,
      settings.liveCameraOrder,
    ).map((camera) => camera.cameraId).toList();
    final draggedIndex = ordered.indexOf(draggedId);
    final targetIndex = ordered.indexOf(targetId);
    if (draggedIndex < 0 || targetIndex < 0) return;
    final dragged = ordered.removeAt(draggedIndex);
    final insertIndex = ordered.indexOf(targetId);
    ordered.insert(insertIndex < 0 ? targetIndex : insertIndex, dragged);
    settings.setLiveCameraOrder(ordered);
  }

  int _gridColumns(double width, LiveDensity density, int forcedColumns) {
    if (width < 600) return 1;
    if (forcedColumns > 0) return forcedColumns;
    if (density == LiveDensity.focus) return 1;
    if (width >= 1240) return density == LiveDensity.compact ? 3 : 2;
    if (width >= 780) return 2;
    return 1;
  }
}

class _GridControls extends StatelessWidget {
  const _GridControls({
    required this.columns,
    required this.annotate,
    required this.onColumnsChanged,
    required this.onAnnotateChanged,
    required this.onResetOrder,
  });

  final int columns;
  final bool annotate;
  final ValueChanged<int> onColumnsChanged;
  final ValueChanged<bool> onAnnotateChanged;
  final VoidCallback? onResetOrder;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final compact = MediaQuery.sizeOf(context).width < 600;
    return GlassPanel(
      padding: EdgeInsets.all(compact ? 10 : 12),
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          Text(
            'Сетка Live',
            style: TextStyle(
              color: colors.textStrong,
              fontWeight: FontWeight.w900,
              fontSize: 13,
            ),
          ),
          _GridChoice(
            label: 'Авто',
            selected: columns == 0,
            onTap: () => onColumnsChanged(0),
          ),
          _GridChoice(
            label: '1 x 1',
            selected: columns == 1,
            onTap: () => onColumnsChanged(1),
          ),
          _GridChoice(
            label: '2 x 2',
            selected: columns == 2,
            onTap: () => onColumnsChanged(2),
          ),
          _GridChoice(
            label: '3 x 3',
            selected: columns == 3,
            onTap: () => onColumnsChanged(3),
          ),
          OutlinedButton.icon(
            onPressed: onResetOrder,
            icon: const Icon(Icons.restart_alt_rounded, size: 18),
            label: const Text('Сбросить порядок'),
          ),
          FilterChip(
            selected: annotate,
            onSelected: onAnnotateChanged,
            label: const Text('Overlay детекции'),
            avatar: Icon(
              annotate
                  ? Icons.visibility_rounded
                  : Icons.visibility_off_rounded,
              size: 18,
            ),
          ),
          if (!compact)
            Text(
              'Перетаскивайте карточки долгим нажатием.',
              style: TextStyle(color: colors.muted, fontSize: 12),
            ),
        ],
      ),
    );
  }
}

class _LiveHeader extends StatelessWidget {
  const _LiveHeader({required this.loading, required this.onRefresh});

  final bool loading;
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
              'Live',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style:
                  (compact
                          ? Theme.of(context).textTheme.headlineMedium
                          : Theme.of(context).textTheme.displaySmall)
                      ?.copyWith(
                        color: colors.textStrong,
                        fontWeight: FontWeight.w900,
                        height: 1.05,
                      ),
            ),
            const SizedBox(height: 4),
            Text(
              'Камеры, Processor и быстрые ONVIF-команды',
              maxLines: compact ? 2 : 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: colors.muted,
                fontSize: compact ? 13 : null,
              ),
            ),
          ],
        );
        final refresh = OutlinedButton.icon(
          onPressed: loading ? null : onRefresh,
          icon: loading
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.refresh_rounded),
          label: const Text('Обновить'),
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
            const SizedBox(width: 12),
            refresh,
          ],
        );
      },
    );
  }
}

class _GridChoice extends StatelessWidget {
  const _GridChoice({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 160),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        gradient: selected
            ? LinearGradient(
                colors: [colors.primaryAccent, colors.secondaryAccent],
              )
            : null,
        color: selected ? null : colors.surfaceMuted,
        border: Border.all(
          color: selected ? Colors.transparent : colors.border,
        ),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
          child: Text(
            label,
            style: TextStyle(
              color: selected ? const Color(0xFF07111F) : colors.muted,
              fontWeight: FontWeight.w800,
              fontSize: 13,
            ),
          ),
        ),
      ),
    );
  }
}

class _DraggableCameraTile extends StatefulWidget {
  const _DraggableCameraTile({
    required this.camera,
    required this.annotate,
    required this.onMoveBefore,
  });

  final CameraSummary camera;
  final bool annotate;
  final void Function(int draggedId, int targetId) onMoveBefore;

  @override
  State<_DraggableCameraTile> createState() => _DraggableCameraTileState();
}

class _DraggableCameraTileState extends State<_DraggableCameraTile> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return DragTarget<int>(
      onWillAcceptWithDetails: (details) {
        final accept = details.data != widget.camera.cameraId;
        if (accept) setState(() => _hovered = true);
        return accept;
      },
      onLeave: (_) => setState(() => _hovered = false),
      onAcceptWithDetails: (details) {
        setState(() => _hovered = false);
        widget.onMoveBefore(details.data, widget.camera.cameraId);
      },
      builder: (context, candidateData, rejectedData) {
        return AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppTheme.radiusLg),
            border: Border.all(
              color: _hovered ? colors.primaryAccent : Colors.transparent,
              width: 2,
            ),
          ),
          child: LongPressDraggable<int>(
            data: widget.camera.cameraId,
            feedback: Material(
              color: Colors.transparent,
              child: Container(
                width: 220,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(18),
                  color: colors.surfaceElevated,
                  border: Border.all(color: colors.borderStrong),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.28),
                      blurRadius: 22,
                      offset: const Offset(0, 14),
                    ),
                  ],
                ),
                child: Text(
                  widget.camera.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: colors.textStrong,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
            ),
            childWhenDragging: Opacity(
              opacity: 0.42,
              child: _CameraTile(
                camera: widget.camera,
                annotate: widget.annotate,
              ),
            ),
            child: _CameraTile(
              camera: widget.camera,
              annotate: widget.annotate,
            ),
          ),
        );
      },
    );
  }
}

class _CameraTile extends StatefulWidget {
  const _CameraTile({required this.camera, required this.annotate});

  final CameraSummary camera;
  final bool annotate;

  @override
  State<_CameraTile> createState() => _CameraTileState();
}

class _CameraTileState extends State<_CameraTile> {
  static const _ptzSafetyStopDelay = Duration(milliseconds: 900);

  bool _ptzBusy = false;
  Timer? _ptzSafetyStopTimer;
  String? _activePtzMoveKey;

  @override
  void dispose() {
    _ptzSafetyStopTimer?.cancel();
    super.dispose();
  }

  Future<void> _ptz({
    double pan = 0,
    double tilt = 0,
    double zoom = 0,
    bool home = false,
    bool stop = false,
  }) async {
    final auth = context.read<AuthController>();
    final api = context.read<ApiClient>();
    final token = auth.accessToken;
    if (token == null) return;

    setState(() => _ptzBusy = true);
    try {
      if (home) {
        await api.ptzHome(token, widget.camera.cameraId);
      } else if (stop) {
        await api.ptzStop(token, widget.camera.cameraId);
      } else {
        await api.ptzRelative(
          token,
          widget.camera.cameraId,
          pan: pan,
          tilt: tilt,
          zoom: zoom,
        );
      }
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => _ptzBusy = false);
    }
  }

  Future<void> _startPtzHold({
    double pan = 0,
    double tilt = 0,
    double zoom = 0,
  }) async {
    final auth = context.read<AuthController>();
    final api = context.read<ApiClient>();
    final token = auth.accessToken;
    if (token == null) return;
    final moveKey = '$pan:$tilt:$zoom';
    if (_activePtzMoveKey == moveKey) return;
    _ptzSafetyStopTimer?.cancel();
    if (_activePtzMoveKey != null) {
      unawaited(_stopPtzHold());
    }
    _activePtzMoveKey = moveKey;
    try {
      await api.ptzContinuous(
        token,
        widget.camera.cameraId,
        pan: pan,
        tilt: tilt,
        zoom: zoom,
      );
      _ptzSafetyStopTimer = Timer(_ptzSafetyStopDelay, () {
        if (!mounted) return;
        unawaited(_stopPtzHold());
      });
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('$error')));
    }
  }

  Future<void> _stopPtzHold() async {
    _ptzSafetyStopTimer?.cancel();
    _ptzSafetyStopTimer = null;
    _activePtzMoveKey = null;
    await _ptz(stop: true);
  }

  Future<void> _openPresets() async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => _PresetsSheet(camera: widget.camera),
    );
  }

  Future<void> _openFullscreen() async {
    await showDialog<void>(
      context: context,
      builder: (_) => _FullscreenCameraDialog(
        camera: widget.camera,
        annotate: widget.annotate,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final auth = context.watch<AuthController>();
    final api = context.read<ApiClient>();
    final token = auth.accessToken;
    final camera = widget.camera;
    final canControlPtz = camera.supportsPtz && (auth.user?.isAdmin ?? false);
    final compact = MediaQuery.sizeOf(context).width < 600;

    return GlassPanel(
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(
            child: ClipRRect(
              borderRadius: const BorderRadius.vertical(
                top: Radius.circular(AppTheme.radiusLg),
              ),
              child: Stack(
                fit: StackFit.expand,
                children: [
                  if (token != null)
                    InteractiveViewer(
                      minScale: 1,
                      maxScale: 5,
                      child: MjpegStreamView(
                        uri: api.cameraStreamUri(
                          camera.cameraId,
                          annotate: widget.annotate,
                          maxFps: MediaQuery.sizeOf(context).width < 600
                              ? 12
                              : 20,
                        ),
                        headers: {'Authorization': 'Bearer $token'},
                        fit: BoxFit.cover,
                        errorBuilder: (context, error) => _NoStream(
                          camera: camera,
                          message: 'Нет live-потока: $error',
                        ),
                      ),
                    )
                  else
                    _NoStream(camera: camera, message: 'Нет авторизации'),
                  Positioned(
                    left: 12,
                    top: 12,
                    child: _CameraBadge(
                      text: camera.connectionKind.toUpperCase(),
                      active:
                          camera.onvifEnabled ||
                          camera.connectionKind != 'manual',
                    ),
                  ),
                  Positioned(
                    right: 12,
                    top: 12,
                    child: _CameraBadge(
                      text: camera.detectionEnabled ? 'DETECT' : 'VIEW',
                      active: camera.detectionEnabled,
                    ),
                  ),
                  Positioned(
                    right: 12,
                    bottom: 12,
                    child: IconButton.filledTonal(
                      tooltip: 'Во весь экран',
                      onPressed: _openFullscreen,
                      icon: const Icon(Icons.fullscreen_rounded),
                    ),
                  ),
                ],
              ),
            ),
          ),
          Padding(
            padding: EdgeInsets.all(compact ? 12 : 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        camera.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.titleLarge?.copyWith(
                          color: colors.textStrong,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ),
                    if (canControlPtz)
                      Icon(
                        Icons.open_with_rounded,
                        color: colors.primaryAccent,
                        size: 20,
                      ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  camera.location?.isNotEmpty == true
                      ? camera.location!
                      : 'Локация не указана',
                  style: TextStyle(color: colors.muted),
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    _InfoPill(label: camera.ipAddress ?? 'IP не указан'),
                    _InfoPill(label: 'Запись: ${camera.recordingMode}'),
                    if (camera.fps != null)
                      _InfoPill(label: '${camera.fps!.toStringAsFixed(0)} FPS'),
                  ],
                ),
                if (canControlPtz) ...[
                  const SizedBox(height: 14),
                  _PtzControls(
                    busy: _ptzBusy,
                    canZoom: camera.ptzCapabilities.zoom,
                    canHome: camera.ptzCapabilities.home,
                    onUp: () => _startPtzHold(tilt: 0.35),
                    onDown: () => _startPtzHold(tilt: -0.35),
                    onLeft: () => _startPtzHold(pan: -0.35),
                    onRight: () => _startPtzHold(pan: 0.35),
                    onZoomIn: () => _startPtzHold(zoom: 0.28),
                    onZoomOut: () => _startPtzHold(zoom: -0.28),
                    onHome: () => _ptz(home: true),
                    onStop: _stopPtzHold,
                    onPresets: _openPresets,
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _NoStream extends StatelessWidget {
  const _NoStream({required this.camera, required this.message});

  final CameraSummary camera;
  final String message;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      color: Colors.black.withValues(alpha: 0.2),
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.videocam_off_rounded, color: colors.muted, size: 34),
              const SizedBox(height: 10),
              Text(
                message,
                maxLines: 4,
                overflow: TextOverflow.ellipsis,
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: colors.textStrong,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 6),
              Text(camera.name, style: TextStyle(color: colors.muted)),
            ],
          ),
        ),
      ),
    );
  }
}

class _PtzControls extends StatelessWidget {
  const _PtzControls({
    required this.busy,
    required this.canZoom,
    required this.canHome,
    required this.onUp,
    required this.onDown,
    required this.onLeft,
    required this.onRight,
    required this.onZoomIn,
    required this.onZoomOut,
    required this.onHome,
    required this.onStop,
    required this.onPresets,
  });

  final bool busy;
  final bool canZoom;
  final bool canHome;
  final VoidCallback onUp;
  final VoidCallback onDown;
  final VoidCallback onLeft;
  final VoidCallback onRight;
  final VoidCallback onZoomIn;
  final VoidCallback onZoomOut;
  final VoidCallback onHome;
  final VoidCallback onStop;
  final VoidCallback onPresets;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        _PtzButton(
          icon: Icons.keyboard_arrow_up_rounded,
          onPressed: busy ? null : onUp,
          onReleased: onStop,
        ),
        _PtzButton(
          icon: Icons.keyboard_arrow_down_rounded,
          onPressed: busy ? null : onDown,
          onReleased: onStop,
        ),
        _PtzButton(
          icon: Icons.keyboard_arrow_left_rounded,
          onPressed: busy ? null : onLeft,
          onReleased: onStop,
        ),
        _PtzButton(
          icon: Icons.keyboard_arrow_right_rounded,
          onPressed: busy ? null : onRight,
          onReleased: onStop,
        ),
        if (canZoom)
          _PtzButton(
            icon: Icons.zoom_in_rounded,
            onPressed: busy ? null : onZoomIn,
            onReleased: onStop,
          ),
        if (canZoom)
          _PtzButton(
            icon: Icons.zoom_out_rounded,
            onPressed: busy ? null : onZoomOut,
            onReleased: onStop,
          ),
        if (canHome)
          _PtzButton(icon: Icons.home_rounded, onPressed: busy ? null : onHome),
        _PtzButton(icon: Icons.stop_rounded, onPressed: busy ? null : onStop),
        _PtzButton(
          icon: Icons.bookmarks_rounded,
          onPressed: busy ? null : onPresets,
        ),
      ],
    );
  }
}

class _PtzButton extends StatefulWidget {
  const _PtzButton({
    required this.icon,
    required this.onPressed,
    this.onReleased,
  });

  final IconData icon;
  final VoidCallback? onPressed;
  final VoidCallback? onReleased;

  @override
  State<_PtzButton> createState() => _PtzButtonState();
}

class _PtzButtonState extends State<_PtzButton> {
  bool _holding = false;

  @override
  void dispose() {
    if (_holding) {
      widget.onReleased?.call();
    }
    super.dispose();
  }

  void _press() {
    if (widget.onPressed == null) return;
    _holding = true;
    widget.onPressed!();
  }

  void _release() {
    if (!_holding) return;
    _holding = false;
    widget.onReleased?.call();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    if (widget.onReleased == null) {
      return SizedBox(
        width: 38,
        height: 34,
        child: OutlinedButton(
          onPressed: widget.onPressed,
          style: OutlinedButton.styleFrom(
            padding: EdgeInsets.zero,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
            ),
          ),
          child: Icon(widget.icon, size: 19),
        ),
      );
    }
    return Listener(
      behavior: HitTestBehavior.opaque,
      onPointerDown: widget.onPressed == null ? null : (_) => _press(),
      onPointerUp: (_) => _release(),
      onPointerCancel: (_) => _release(),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 120),
        width: 38,
        height: 34,
        decoration: BoxDecoration(
          color: widget.onPressed == null
              ? colors.surfaceMuted
              : (_holding
                    ? colors.primaryAccent.withValues(alpha: 0.18)
                    : Colors.transparent),
          border: Border.all(color: colors.border),
          borderRadius: BorderRadius.circular(12),
        ),
        alignment: Alignment.center,
        child: Icon(widget.icon, size: 19, color: colors.text),
      ),
    );
  }
}

class _CameraBadge extends StatelessWidget {
  const _CameraBadge({required this.text, required this.active});

  final String text;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: Colors.black.withValues(alpha: 0.5),
        border: Border.all(
          color: active
              ? colors.primaryAccent.withValues(alpha: 0.6)
              : colors.border,
        ),
      ),
      child: Text(
        text,
        style: TextStyle(
          color: active ? colors.primaryAccent : colors.muted,
          fontWeight: FontWeight.w900,
          fontSize: 11,
        ),
      ),
    );
  }
}

class _InfoPill extends StatelessWidget {
  const _InfoPill({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: colors.muted,
          fontSize: 12,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class _FullscreenCameraDialog extends StatefulWidget {
  const _FullscreenCameraDialog({required this.camera, required this.annotate});

  final CameraSummary camera;
  final bool annotate;

  @override
  State<_FullscreenCameraDialog> createState() =>
      _FullscreenCameraDialogState();
}

class _FullscreenCameraDialogState extends State<_FullscreenCameraDialog> {
  static const _ptzSafetyStopDelay = Duration(milliseconds: 900);

  final _focusNode = FocusNode();
  Timer? _ptzSafetyStopTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => _focusNode.requestFocus(),
    );
  }

  @override
  void dispose() {
    unawaited(_stop());
    _ptzSafetyStopTimer?.cancel();
    _focusNode.dispose();
    super.dispose();
  }

  Future<void> _move({double pan = 0, double tilt = 0, double zoom = 0}) async {
    final token = context.read<AuthController>().accessToken;
    if (token == null) return;
    _ptzSafetyStopTimer?.cancel();
    try {
      await context.read<ApiClient>().ptzContinuous(
        token,
        widget.camera.cameraId,
        pan: pan,
        tilt: tilt,
        zoom: zoom,
      );
      _ptzSafetyStopTimer = Timer(_ptzSafetyStopDelay, () {
        if (!mounted) return;
        unawaited(_stop());
      });
    } catch (_) {
      // В fullscreen не спамим snackbar на каждое нажатие клавиши.
    }
  }

  Future<void> _stop() async {
    _ptzSafetyStopTimer?.cancel();
    _ptzSafetyStopTimer = null;
    final token = context.read<AuthController>().accessToken;
    if (token == null) return;
    try {
      await context.read<ApiClient>().ptzStop(token, widget.camera.cameraId);
    } catch (_) {}
  }

  void _handleKey(KeyEvent event) {
    if (event is KeyUpEvent) {
      _stop();
      return;
    }
    if (event is KeyRepeatEvent) return;
    if (event is! KeyDownEvent) return;
    final key = event.logicalKey;
    if (key == LogicalKeyboardKey.escape) {
      Navigator.of(context).pop();
    } else if (key == LogicalKeyboardKey.keyW ||
        key == LogicalKeyboardKey.arrowUp) {
      _move(tilt: 0.35);
    } else if (key == LogicalKeyboardKey.keyS ||
        key == LogicalKeyboardKey.arrowDown) {
      _move(tilt: -0.35);
    } else if (key == LogicalKeyboardKey.keyA ||
        key == LogicalKeyboardKey.arrowLeft) {
      _move(pan: -0.35);
    } else if (key == LogicalKeyboardKey.keyD ||
        key == LogicalKeyboardKey.arrowRight) {
      _move(pan: 0.35);
    } else if (key == LogicalKeyboardKey.keyQ) {
      _move(zoom: -0.25);
    } else if (key == LogicalKeyboardKey.keyE) {
      _move(zoom: 0.25);
    }
  }

  @override
  Widget build(BuildContext context) {
    final api = context.read<ApiClient>();
    final token = context.watch<AuthController>().accessToken;
    return Dialog.fullscreen(
      backgroundColor: Colors.black,
      child: KeyboardListener(
        focusNode: _focusNode,
        onKeyEvent: _handleKey,
        child: Stack(
          children: [
            Positioned.fill(
              child: token == null
                  ? const Center(child: Text('Нет авторизации'))
                  : InteractiveViewer(
                      minScale: 1,
                      maxScale: 8,
                      child: MjpegStreamView(
                        uri: api.cameraStreamUri(
                          widget.camera.cameraId,
                          annotate: widget.annotate,
                          maxFps: 24,
                        ),
                        headers: {'Authorization': 'Bearer $token'},
                        fit: BoxFit.contain,
                        errorBuilder: (context, error) => Center(
                          child: Padding(
                            padding: const EdgeInsets.all(24),
                            child: Text(
                              'Нет live-потока: $error',
                              maxLines: 5,
                              overflow: TextOverflow.ellipsis,
                              textAlign: TextAlign.center,
                              style: const TextStyle(color: Colors.white70),
                            ),
                          ),
                        ),
                      ),
                    ),
            ),
            Positioned(
              left: 18,
              top: 18,
              child: _CameraBadge(text: widget.camera.name, active: true),
            ),
            Positioned(
              right: 18,
              top: 18,
              child: IconButton.filled(
                tooltip: 'Закрыть',
                onPressed: () => Navigator.of(context).pop(),
                icon: const Icon(Icons.close_rounded),
              ),
            ),
            Positioned(
              left: 18,
              bottom: 18,
              child: _CameraBadge(
                text: 'WASD/стрелки - PTZ, Q/E - zoom, Esc - закрыть',
                active: true,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PresetsSheet extends StatefulWidget {
  const _PresetsSheet({required this.camera});

  final CameraSummary camera;

  @override
  State<_PresetsSheet> createState() => _PresetsSheetState();
}

class _PresetsSheetState extends State<_PresetsSheet> {
  bool _loading = false;
  String? _error;
  List<Map<String, dynamic>> _presets = const [];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final token = context.read<AuthController>().accessToken;
    if (token == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final presets = await context.read<ApiClient>().listCameraPresets(
        token,
        widget.camera.cameraId,
      );
      if (mounted) setState(() => _presets = presets);
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _refresh() async {
    final token = context.read<AuthController>().accessToken;
    if (token == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final presets = await context.read<ApiClient>().refreshCameraPresets(
        token,
        widget.camera.cameraId,
      );
      if (mounted) setState(() => _presets = presets);
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _create() async {
    final controller = TextEditingController();
    try {
      final name = await showDialog<String>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Сохранить текущий ракурс'),
          content: TextField(
            controller: controller,
            autofocus: true,
            decoration: const InputDecoration(labelText: 'Название пресета'),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Отмена'),
            ),
            ElevatedButton(
              onPressed: () => Navigator.pop(context, controller.text.trim()),
              child: const Text('Сохранить'),
            ),
          ],
        ),
      );
      if (name == null || name.isEmpty) return;
      final token = context.read<AuthController>().accessToken;
      if (token == null) return;
      await context.read<ApiClient>().createCameraPreset(
        token,
        widget.camera.cameraId,
        name: name,
        orderIndex: _presets.length,
      );
      await _load();
    } finally {
      controller.dispose();
    }
  }

  Future<void> _goto(Map<String, dynamic> preset) async {
    final token = context.read<AuthController>().accessToken;
    final id = preset['camera_preset_id'] as int?;
    if (token == null || id == null) return;
    try {
      await context.read<ApiClient>().gotoCameraPreset(
        token,
        widget.camera.cameraId,
        id,
      );
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
      }
    }
  }

  Future<void> _delete(Map<String, dynamic> preset) async {
    final token = context.read<AuthController>().accessToken;
    final id = preset['camera_preset_id'] as int?;
    if (token == null || id == null) return;
    try {
      await context.read<ApiClient>().deleteCameraPreset(
        token,
        widget.camera.cameraId,
        id,
      );
      await _load();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Padding(
      padding: const EdgeInsets.all(18),
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
                      'Пресеты ${widget.camera.name}',
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
              Wrap(
                spacing: 8,
                children: [
                  ElevatedButton.icon(
                    onPressed: _loading ? null : _create,
                    icon: const Icon(Icons.add_rounded, size: 18),
                    label: const Text('Сохранить ракурс'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _loading ? null : _refresh,
                    icon: const Icon(Icons.sync_rounded, size: 18),
                    label: const Text('Синхронизировать'),
                  ),
                ],
              ),
              if (_error != null) ...[
                const SizedBox(height: 10),
                Text(_error!, style: TextStyle(color: colors.danger)),
              ],
              const SizedBox(height: 12),
              Expanded(
                child: _presets.isEmpty
                    ? Center(
                        child: Text(
                          'Пресетов пока нет.',
                          style: TextStyle(color: colors.muted),
                        ),
                      )
                    : ListView.builder(
                        itemCount: _presets.length,
                        itemBuilder: (context, index) {
                          final preset = _presets[index];
                          return ListTile(
                            title: Text('${preset['name'] ?? 'Preset'}'),
                            subtitle: Text(
                              'token: ${preset['preset_token'] ?? '-'}',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                            leading: const Icon(Icons.bookmark_rounded),
                            trailing: Wrap(
                              spacing: 4,
                              children: [
                                IconButton(
                                  tooltip: 'Перейти',
                                  onPressed: () => _goto(preset),
                                  icon: const Icon(Icons.play_arrow_rounded),
                                ),
                                IconButton(
                                  tooltip: 'Удалить',
                                  onPressed: () => _delete(preset),
                                  icon: Icon(
                                    Icons.delete_outline_rounded,
                                    color: colors.danger,
                                  ),
                                ),
                              ],
                            ),
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

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Icon(Icons.warning_rounded, color: colors.warning),
          const SizedBox(width: 12),
          Expanded(
            child: Text(message, style: TextStyle(color: colors.text)),
          ),
          OutlinedButton(onPressed: onRetry, child: const Text('Повторить')),
        ],
      ),
    );
  }
}

String formatEventTime(DateTime value) {
  return DateFormat('dd.MM HH:mm:ss').format(value.toLocal());
}
