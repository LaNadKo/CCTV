import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../core/models/models.dart';
import '../../core/network/api_client.dart';
import '../../core/theme/app_theme.dart';
import '../../core/theme/theme_controller.dart';
import '../../shared/widgets/glass_panel.dart';
import '../auth/auth_controller.dart';

class LiveScreen extends StatefulWidget {
  const LiveScreen({super.key});

  @override
  State<LiveScreen> createState() => _LiveScreenState();
}

class _LiveScreenState extends State<LiveScreen> {
  bool _loading = false;
  String? _error;
  List<CameraSummary> _cameras = const [];
  List<ProcessorOut> _processors = const [];
  List<PendingEvent> _pending = const [];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
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
      final result = await Future.wait([
        api.listCameras(token),
        api.listProcessors(token),
        api.listPendingEvents(token),
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
                Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Live',
                            style: Theme.of(context).textTheme.displaySmall
                                ?.copyWith(
                                  color: colors.textStrong,
                                  fontWeight: FontWeight.w900,
                                ),
                          ),
                          Text(
                            'Камеры, Processor и быстрые ONVIF-команды',
                            style: TextStyle(color: colors.muted),
                          ),
                        ],
                      ),
                    ),
                    OutlinedButton.icon(
                      onPressed: _loading ? null : _load,
                      icon: _loading
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.refresh_rounded),
                      label: const Text('Обновить'),
                    ),
                  ],
                ),
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
                      ),
                      StatCard(
                        label: 'Processor online',
                        value: '$onlineProcessors / ${_processors.length}',
                        icon: Icons.memory_rounded,
                        accent: onlineProcessors > 0
                            ? colors.success
                            : colors.warning,
                      ),
                      StatCard(
                        label: 'Ожидают ревью',
                        value: '${_pending.length}',
                        icon: Icons.fact_check_rounded,
                        accent: _pending.isEmpty
                            ? colors.success
                            : colors.warning,
                      ),
                    ];
                    if (compact) {
                      return Column(
                        children: cards
                            .map(
                              (card) => Padding(
                                padding: const EdgeInsets.only(bottom: 12),
                                child: card,
                              ),
                            )
                            .toList(),
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
                  onColumnsChanged: settings.setLiveGridColumns,
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
    required this.onColumnsChanged,
    required this.onResetOrder,
  });

  final int columns;
  final ValueChanged<int> onColumnsChanged;
  final VoidCallback? onResetOrder;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(12),
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
          Text(
            'Перетаскивайте карточки долгим нажатием.',
            style: TextStyle(color: colors.muted, fontSize: 12),
          ),
        ],
      ),
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
    required this.onMoveBefore,
  });

  final CameraSummary camera;
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
              child: _CameraTile(camera: widget.camera),
            ),
            child: _CameraTile(camera: widget.camera),
          ),
        );
      },
    );
  }
}

class _CameraTile extends StatefulWidget {
  const _CameraTile({required this.camera});

  final CameraSummary camera;

  @override
  State<_CameraTile> createState() => _CameraTileState();
}

class _CameraTileState extends State<_CameraTile> {
  bool _ptzBusy = false;

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

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final auth = context.watch<AuthController>();
    final api = context.read<ApiClient>();
    final token = auth.accessToken;
    final camera = widget.camera;
    final canControlPtz = camera.supportsPtz && (auth.user?.isAdmin ?? false);

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
                    Image.network(
                      api.cameraStreamUri(camera.cameraId).toString(),
                      headers: {'Authorization': 'Bearer $token'},
                      fit: BoxFit.cover,
                      gaplessPlayback: true,
                      errorBuilder: (context, error, stackTrace) {
                        return _NoStream(
                          camera: camera,
                          message: 'Нет live-потока',
                        );
                      },
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
                ],
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
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
                    onUp: () => _ptz(tilt: 0.18),
                    onDown: () => _ptz(tilt: -0.18),
                    onLeft: () => _ptz(pan: -0.18),
                    onRight: () => _ptz(pan: 0.18),
                    onZoomIn: () => _ptz(zoom: 0.15),
                    onZoomOut: () => _ptz(zoom: -0.15),
                    onHome: () => _ptz(home: true),
                    onStop: () => _ptz(stop: true),
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
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.videocam_off_rounded, color: colors.muted, size: 34),
            const SizedBox(height: 10),
            Text(
              message,
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
        ),
        _PtzButton(
          icon: Icons.keyboard_arrow_down_rounded,
          onPressed: busy ? null : onDown,
        ),
        _PtzButton(
          icon: Icons.keyboard_arrow_left_rounded,
          onPressed: busy ? null : onLeft,
        ),
        _PtzButton(
          icon: Icons.keyboard_arrow_right_rounded,
          onPressed: busy ? null : onRight,
        ),
        if (canZoom)
          _PtzButton(
            icon: Icons.zoom_in_rounded,
            onPressed: busy ? null : onZoomIn,
          ),
        if (canZoom)
          _PtzButton(
            icon: Icons.zoom_out_rounded,
            onPressed: busy ? null : onZoomOut,
          ),
        if (canHome)
          _PtzButton(icon: Icons.home_rounded, onPressed: busy ? null : onHome),
        _PtzButton(icon: Icons.stop_rounded, onPressed: busy ? null : onStop),
      ],
    );
  }
}

class _PtzButton extends StatelessWidget {
  const _PtzButton({required this.icon, required this.onPressed});

  final IconData icon;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 38,
      height: 34,
      child: OutlinedButton(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          padding: EdgeInsets.zero,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
        child: Icon(icon, size: 19),
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
