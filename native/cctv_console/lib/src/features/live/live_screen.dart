// ignore_for_file: use_build_context_synchronously

import 'dart:async';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'package:window_manager/window_manager.dart';

import '../../core/models/models.dart';
import '../../core/network/api_client.dart';
import '../../core/refresh/refresh_bus.dart';
import '../../core/theme/app_theme.dart';
import '../../core/theme/theme_controller.dart';
import '../../shared/widgets/glass_panel.dart';
import '../../shared/widgets/mjpeg_stream_view.dart';
import '../../shared/widgets/page_header.dart';
import '../auth/auth_controller.dart';

enum _LiveMode { standard, grid }

enum _LiveSort { priority, location, name }

enum _GridPreset { twoByTwo, threeByThree, fourByFour, custom }

class _GridShape {
  const _GridShape(this.rows, this.columns);

  final int rows;
  final int columns;

  int get slotCount => rows * columns;
}

class _GridDragPayload {
  const _GridDragPayload({required this.cameraId, this.sourceSlot});

  final int cameraId;
  final int? sourceSlot;
}

class _FullscreenRestore {
  const _FullscreenRestore({required this.wasDesktopFullscreen});

  final bool? wasDesktopFullscreen;
}

Future<_FullscreenRestore> _enterPlatformFullscreen() async {
  if (!kIsWeb && (Platform.isWindows || Platform.isLinux || Platform.isMacOS)) {
    final wasFullscreen = await windowManager.isFullScreen();
    await windowManager.setTitleBarStyle(TitleBarStyle.hidden);
    if (!wasFullscreen) {
      await windowManager.setFullScreen(true);
    }
    await Future<void>.delayed(const Duration(milliseconds: 120));
    return _FullscreenRestore(wasDesktopFullscreen: wasFullscreen);
  }
  await SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
  return const _FullscreenRestore(wasDesktopFullscreen: null);
}

Future<void> _exitPlatformFullscreen(_FullscreenRestore restore) async {
  final wasDesktopFullscreen = restore.wasDesktopFullscreen;
  if (!kIsWeb &&
      wasDesktopFullscreen != null &&
      (Platform.isWindows || Platform.isLinux || Platform.isMacOS)) {
    await windowManager.setFullScreen(wasDesktopFullscreen);
    await windowManager.setTitleBarStyle(TitleBarStyle.normal);
    return;
  }
  await SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
}

class LiveScreen extends StatefulWidget {
  const LiveScreen({super.key});

  @override
  State<LiveScreen> createState() => _LiveScreenState();
}

class _LiveScreenState extends State<LiveScreen>
    with RouteRefreshState<LiveScreen> {
  static const _standardActiveLimit = 3;

  bool _loading = false;
  String? _error;
  List<CameraSummary> _cameras = const [];
  List<ProcessorOut> _processors = const [];
  List<PendingEvent> _pending = const [];
  _LiveMode _mode = _LiveMode.standard;
  _LiveSort _sort = _LiveSort.priority;
  String? _locationFilter;
  _GridPreset _gridPreset = _GridPreset.twoByTwo;
  int _customRows = 2;
  int _customColumns = 2;
  final Set<int> _standardActive = <int>{};
  final Set<int> _standardAnnotateDisabled = <int>{};
  List<int?> _gridSlots = List<int?>.filled(4, null);
  final Set<int> _activeGridSlots = <int>{};
  final Set<int> _gridAnnotateDisabledSlots = <int>{};

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
        _pruneLiveState();
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
    final width = MediaQuery.sizeOf(context).width;
    final ordered = _orderedCameras(_cameras, settings.liveCameraOrder);
    final cameras = _filterAndSortCameras(ordered);
    final locations = _locations(_cameras);
    final gridShape = _gridShape();
    _ensureGridSlotCount(gridShape.slotCount);
    final cameraById = {for (final camera in _cameras) camera.cameraId: camera};
    final assignedGridIds = _assignedGridIds();
    final gridSourceCameras = cameras
        .where((camera) => !assignedGridIds.contains(camera.cameraId))
        .toList();
    final standardCrossAxisCount = _gridColumns(
      width,
      density,
      settings.liveGridColumns,
    );
    final gridCrossAxisCount = _gridCrossAxisCount(width, gridShape);

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
                        label: 'Процессор онлайн',
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
                SizedBox(
                  width: double.infinity,
                  child: _LiveControls(
                    mode: _mode,
                    sort: _sort,
                    locations: locations,
                    selectedLocation: _locationFilter,
                    standardActiveCount: _standardActive.length,
                    standardActiveLimit: _standardActiveLimit,
                    standardColumns: settings.liveGridColumns,
                    gridPreset: _gridPreset,
                    customRows: _customRows,
                    customColumns: _customColumns,
                    canOpenFullscreenGrid:
                        _mode == _LiveMode.grid && assignedGridIds.isNotEmpty,
                    onModeChanged: (value) => setState(() => _mode = value),
                    onSortChanged: (value) => setState(() => _sort = value),
                    onLocationChanged: (value) =>
                        setState(() => _locationFilter = value),
                    onColumnsChanged: settings.setLiveGridColumns,
                    onGridPresetChanged: _setGridPreset,
                    onCustomRowsChanged: _setCustomRows,
                    onCustomColumnsChanged: _setCustomColumns,
                    onOpenFullscreenGrid: _openGridFullscreen,
                    onResetOrder: ordered.length < 2
                        ? null
                        : () => settings.setLiveCameraOrder(const []),
                  ),
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
                    _cameras.isEmpty
                        ? 'Камер пока нет или backend вернул пустой список.'
                        : 'Под выбранный фильтр камер нет.',
                    style: TextStyle(color: colors.muted),
                  ),
                ),
              ),
            )
          else if (_mode == _LiveMode.standard)
            SliverGrid(
              delegate: SliverChildBuilderDelegate((context, index) {
                final camera = cameras[index];
                return _DraggableCameraTile(
                  camera: camera,
                  annotate: _standardAnnotateFor(camera.cameraId),
                  active: _standardActive.contains(camera.cameraId),
                  onActivate: () => _activateStandard(camera.cameraId),
                  onDeactivate: () => _deactivateStandard(camera.cameraId),
                  onAnnotateChanged: (value) =>
                      _setStandardAnnotate(camera.cameraId, value),
                  onMoveBefore: _reorderCameras,
                );
              }, childCount: cameras.length),
              gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: standardCrossAxisCount,
                crossAxisSpacing: 16,
                mainAxisSpacing: 16,
                childAspectRatio: density == LiveDensity.compact ? 1.25 : 1.04,
              ),
            )
          else ...[
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: SizedBox(
                  width: double.infinity,
                  child: _GridCameraPicker(
                    cameras: gridSourceCameras,
                    onQuickAdd: _assignCameraToFirstFree,
                  ),
                ),
              ),
            ),
            SliverGrid(
              delegate: SliverChildBuilderDelegate((context, index) {
                final cameraId = _gridSlots[index];
                final camera = cameraId == null ? null : cameraById[cameraId];
                return _GridSlotTile(
                  index: index,
                  camera: camera,
                  annotate: _gridAnnotateFor(index),
                  active: _activeGridSlots.contains(index),
                  onCameraDropped: (payload) =>
                      _dropGridCamera(index, payload),
                  onActivate: camera == null
                      ? null
                      : () => _activateGridSlot(index),
                  onDeactivate: camera == null
                      ? null
                      : () => _deactivateGridSlot(index),
                  onAnnotateChanged: camera == null
                      ? null
                      : (value) => _setGridSlotAnnotate(index, value),
                  onRemove: camera == null ? null : () => _clearGridSlot(index),
                );
              }, childCount: _gridSlots.length),
              gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: gridCrossAxisCount,
                crossAxisSpacing: 16,
                mainAxisSpacing: 16,
                childAspectRatio: width < 600 ? 0.9 : 1.04,
              ),
            ),
          ],
        ],
      ),
    );
  }

  List<String> _locations(List<CameraSummary> cameras) {
    final values = cameras
        .map(_cameraLocation)
        .where((value) => value.isNotEmpty)
        .toSet()
        .toList()
      ..sort((a, b) => a.toLowerCase().compareTo(b.toLowerCase()));
    return values;
  }

  String _cameraLocation(CameraSummary camera) {
    return (camera.location?.trim().isNotEmpty ?? false)
        ? camera.location!.trim()
        : 'Без локации';
  }

  List<CameraSummary> _filterAndSortCameras(List<CameraSummary> cameras) {
    var result = cameras;
    final location = _locationFilter;
    if (location != null) {
      result = result
          .where((camera) => _cameraLocation(camera) == location)
          .toList();
    }
    final sorted = [...result];
    sorted.sort((a, b) {
      switch (_sort) {
        case _LiveSort.location:
          final byLocation = _cameraLocation(
            a,
          ).toLowerCase().compareTo(_cameraLocation(b).toLowerCase());
          if (byLocation != 0) return byLocation;
          return a.name.toLowerCase().compareTo(b.name.toLowerCase());
        case _LiveSort.name:
          return a.name.toLowerCase().compareTo(b.name.toLowerCase());
        case _LiveSort.priority:
          final byScore = _livePriority(b).compareTo(_livePriority(a));
          if (byScore != 0) return byScore;
          return a.cameraId.compareTo(b.cameraId);
      }
    });
    return sorted;
  }

  _GridShape _gridShape() {
    return switch (_gridPreset) {
      _GridPreset.twoByTwo => const _GridShape(2, 2),
      _GridPreset.threeByThree => const _GridShape(3, 3),
      _GridPreset.fourByFour => const _GridShape(4, 4),
      _GridPreset.custom => _GridShape(_customRows, _customColumns),
    };
  }

  void _ensureGridSlotCount(int count) {
    if (_gridSlots.length == count) return;
    final next = List<int?>.filled(count, null);
    for (var index = 0; index < math.min(count, _gridSlots.length); index++) {
      next[index] = _gridSlots[index];
    }
    _gridSlots = next;
    _activeGridSlots.removeWhere(
      (index) => index >= count || _gridSlots[index] == null,
    );
    _gridAnnotateDisabledSlots.removeWhere((index) => index >= count);
  }

  Set<int> _assignedGridIds() {
    return _gridSlots.whereType<int>().toSet();
  }

  bool _standardAnnotateFor(int cameraId) {
    return !_standardAnnotateDisabled.contains(cameraId);
  }

  bool _gridAnnotateFor(int index) {
    return !_gridAnnotateDisabledSlots.contains(index);
  }

  void _setStandardAnnotate(int cameraId, bool value) {
    setState(() {
      if (value) {
        _standardAnnotateDisabled.remove(cameraId);
      } else {
        _standardAnnotateDisabled.add(cameraId);
      }
    });
  }

  void _setGridSlotAnnotate(int index, bool value) {
    setState(() {
      if (value) {
        _gridAnnotateDisabledSlots.remove(index);
      } else {
        _gridAnnotateDisabledSlots.add(index);
      }
    });
  }

  void _activateStandard(int cameraId) {
    if (_standardActive.contains(cameraId)) return;
    if (_standardActive.length >= _standardActiveLimit) {
      _showSnack('В стандартном режиме можно открыть не более 3 потоков.');
      return;
    }
    setState(() => _standardActive.add(cameraId));
  }

  void _deactivateStandard(int cameraId) {
    setState(() => _standardActive.remove(cameraId));
  }

  void _assignCameraToFirstFree(int cameraId) {
    final index = _gridSlots.indexWhere((slot) => slot == null);
    if (index < 0) {
      _showSnack('В сетке нет свободных ячеек.');
      return;
    }
    _assignGridSlot(index, cameraId);
  }

  void _dropGridCamera(int index, _GridDragPayload payload) {
    final sourceSlot = payload.sourceSlot;
    if (sourceSlot == null) {
      _assignGridSlot(index, payload.cameraId);
      return;
    }
    _moveGridSlot(sourceSlot, index);
  }

  void _moveGridSlot(int sourceIndex, int targetIndex) {
    if (sourceIndex == targetIndex) return;
    if (sourceIndex < 0 ||
        sourceIndex >= _gridSlots.length ||
        targetIndex < 0 ||
        targetIndex >= _gridSlots.length) {
      return;
    }
    setState(() {
      final sourceCamera = _gridSlots[sourceIndex];
      if (sourceCamera == null) return;
      final targetCamera = _gridSlots[targetIndex];
      final sourceActive = _activeGridSlots.contains(sourceIndex);
      final targetActive = _activeGridSlots.contains(targetIndex);
      final sourceAnnotateDisabled = _gridAnnotateDisabledSlots.contains(
        sourceIndex,
      );
      final targetAnnotateDisabled = _gridAnnotateDisabledSlots.contains(
        targetIndex,
      );

      _gridSlots[targetIndex] = sourceCamera;
      _gridSlots[sourceIndex] = targetCamera;
      _setGridSlotFlags(
        targetIndex,
        active: sourceActive,
        annotateDisabled: sourceAnnotateDisabled,
      );
      if (targetCamera == null) {
        _activeGridSlots.remove(sourceIndex);
        _gridAnnotateDisabledSlots.remove(sourceIndex);
      } else {
        _setGridSlotFlags(
          sourceIndex,
          active: targetActive,
          annotateDisabled: targetAnnotateDisabled,
        );
      }
    });
  }

  void _assignGridSlot(int index, int cameraId) {
    setState(() {
      final oldIndex = _gridSlots.indexOf(cameraId);
      final wasActive = oldIndex >= 0 && _activeGridSlots.contains(oldIndex);
      final wasAnnotateDisabled =
          oldIndex >= 0 && _gridAnnotateDisabledSlots.contains(oldIndex);
      if (oldIndex >= 0) {
        _gridSlots[oldIndex] = null;
        _activeGridSlots.remove(oldIndex);
        _gridAnnotateDisabledSlots.remove(oldIndex);
      }
      _gridSlots[index] = cameraId;
      _setGridSlotFlags(
        index,
        active: oldIndex < 0 || wasActive,
        annotateDisabled: wasAnnotateDisabled,
      );
    });
  }

  void _setGridSlotFlags(
    int index, {
    required bool active,
    required bool annotateDisabled,
  }) {
    if (active) {
      _activeGridSlots.add(index);
    } else {
      _activeGridSlots.remove(index);
    }
    if (annotateDisabled) {
      _gridAnnotateDisabledSlots.add(index);
    } else {
      _gridAnnotateDisabledSlots.remove(index);
    }
  }

  void _activateGridSlot(int index) {
    setState(() => _activeGridSlots.add(index));
  }

  void _deactivateGridSlot(int index) {
    setState(() => _activeGridSlots.remove(index));
  }

  void _clearGridSlot(int index) {
    setState(() {
      _gridSlots[index] = null;
      _activeGridSlots.remove(index);
      _gridAnnotateDisabledSlots.remove(index);
    });
  }

  void _setGridPreset(_GridPreset preset) {
    setState(() {
      _gridPreset = preset;
      _ensureGridSlotCount(_gridShape().slotCount);
    });
  }

  void _setCustomRows(int value) {
    setState(() {
      _gridPreset = _GridPreset.custom;
      _customRows = value.clamp(1, 6);
      _ensureGridSlotCount(_gridShape().slotCount);
    });
  }

  void _setCustomColumns(int value) {
    setState(() {
      _gridPreset = _GridPreset.custom;
      _customColumns = value.clamp(1, 6);
      _ensureGridSlotCount(_gridShape().slotCount);
    });
  }

  int _gridCrossAxisCount(double width, _GridShape shape) {
    if (width < 700) return 1;
    final maxByWidth = math.max(1, ((width + 16) / (340.0 + 16)).floor());
    return math.min(shape.columns, maxByWidth);
  }

  Future<void> _openGridFullscreen() async {
    final cameraById = {for (final camera in _cameras) camera.cameraId: camera};
    final activeSlots = Set<int>.from(_activeGridSlots);
    setState(_activeGridSlots.clear);
    final fullscreenRestore = await _enterPlatformFullscreen();
    if (!mounted) {
      await _exitPlatformFullscreen(fullscreenRestore);
      return;
    }
    try {
      await showDialog<void>(
        context: context,
        builder: (_) => _GridFullscreenDialog(
          slots: List<int?>.from(_gridSlots),
          camerasById: cameraById,
          activeSlots: activeSlots,
          annotateBySlot: [
            for (var index = 0; index < _gridSlots.length; index++)
              _gridAnnotateFor(index),
          ],
        ),
      );
    } finally {
      await _exitPlatformFullscreen(fullscreenRestore);
      if (mounted) {
        setState(() {
          _activeGridSlots
            ..clear()
            ..addAll(activeSlots);
        });
      }
    }
  }

  void _showSnack(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }

  void _pruneLiveState() {
    final cameraIds = _cameras.map((camera) => camera.cameraId).toSet();
    _standardActive.removeWhere((id) => !cameraIds.contains(id));
    _gridSlots = [
      for (final id in _gridSlots) id != null && cameraIds.contains(id) ? id : null,
    ];
    _activeGridSlots.removeWhere(
      (index) => index >= _gridSlots.length || _gridSlots[index] == null,
    );
    if (_locationFilter != null && !_locations(_cameras).contains(_locationFilter)) {
      _locationFilter = null;
    }
  }

  List<CameraSummary> _orderedCameras(
    List<CameraSummary> cameras,
    List<int> order,
  ) {
    if (cameras.length < 2) return cameras;
    final defaultOrder = _sortCamerasForLive(cameras);
    if (order.isEmpty) return defaultOrder;
    final byId = {for (final camera in cameras) camera.cameraId: camera};
    final result = <CameraSummary>[];
    for (final id in order) {
      final camera = byId.remove(id);
      if (camera != null) result.add(camera);
    }
    for (final camera in defaultOrder) {
      if (byId.remove(camera.cameraId) != null) result.add(camera);
    }
    return result;
  }

  List<CameraSummary> _sortCamerasForLive(List<CameraSummary> cameras) {
    final sorted = [...cameras];
    sorted.sort((a, b) {
      final byScore = _livePriority(b).compareTo(_livePriority(a));
      if (byScore != 0) return byScore;
      return a.cameraId.compareTo(b.cameraId);
    });
    return sorted;
  }

  int _livePriority(CameraSummary camera) {
    var score = 0;
    final searchable =
        '${camera.name} ${camera.location ?? ''} ${camera.streamUrl ?? ''}'
            .toLowerCase();
    if (searchable.contains('demo')) score -= 100;
    if (camera.onvifEnabled) score += 40;
    if (camera.supportsPtz) score += 20;
    if (camera.endpointKinds.contains('rtsp')) score += 12;
    if (camera.endpointKinds.contains('http')) score += 6;
    if ((camera.streamUrl ?? '').trim().isNotEmpty) score += 4;
    if (camera.connectionKind != 'manual') score += 3;
    return score;
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
    if (width < 700) return 1;
    final minTileWidth = density == LiveDensity.compact ? 380.0 : 460.0;
    final maxByWidth = math.max(1, ((width + 16) / (minTileWidth + 16)).floor());
    if (forcedColumns > 0) return math.min(forcedColumns, maxByWidth);
    if (density == LiveDensity.focus) return 1;
    final preferred = density == LiveDensity.compact ? 4 : 3;
    return math.min(preferred, maxByWidth);
  }
}

class _LiveControls extends StatelessWidget {
  const _LiveControls({
    required this.mode,
    required this.sort,
    required this.locations,
    required this.selectedLocation,
    required this.standardActiveCount,
    required this.standardActiveLimit,
    required this.standardColumns,
    required this.gridPreset,
    required this.customRows,
    required this.customColumns,
    required this.canOpenFullscreenGrid,
    required this.onModeChanged,
    required this.onSortChanged,
    required this.onLocationChanged,
    required this.onColumnsChanged,
    required this.onGridPresetChanged,
    required this.onCustomRowsChanged,
    required this.onCustomColumnsChanged,
    required this.onOpenFullscreenGrid,
    required this.onResetOrder,
  });

  final _LiveMode mode;
  final _LiveSort sort;
  final List<String> locations;
  final String? selectedLocation;
  final int standardActiveCount;
  final int standardActiveLimit;
  final int standardColumns;
  final _GridPreset gridPreset;
  final int customRows;
  final int customColumns;
  final bool canOpenFullscreenGrid;
  final ValueChanged<_LiveMode> onModeChanged;
  final ValueChanged<_LiveSort> onSortChanged;
  final ValueChanged<String?> onLocationChanged;
  final ValueChanged<int> onColumnsChanged;
  final ValueChanged<_GridPreset> onGridPresetChanged;
  final ValueChanged<int> onCustomRowsChanged;
  final ValueChanged<int> onCustomColumnsChanged;
  final VoidCallback onOpenFullscreenGrid;
  final VoidCallback? onResetOrder;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final compact = MediaQuery.sizeOf(context).width < 700;
    final dropdownStyle = TextStyle(
      color: colors.textStrong,
      fontWeight: FontWeight.w800,
      fontSize: 13,
    );

    return GlassPanel(
      padding: EdgeInsets.all(compact ? 10 : 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              _GridChoice(
                label: 'Стандартный',
                selected: mode == _LiveMode.standard,
                onTap: () => onModeChanged(_LiveMode.standard),
              ),
              _GridChoice(
                label: 'Сетка',
                selected: mode == _LiveMode.grid,
                onTap: () => onModeChanged(_LiveMode.grid),
              ),
              _ControlChip(
                icon: Icons.play_circle_rounded,
                label: '$standardActiveCount / $standardActiveLimit потоков',
              ),
              OutlinedButton.icon(
                onPressed: onResetOrder,
                icon: const Icon(Icons.restart_alt_rounded, size: 18),
                label: const Text('Сбросить порядок'),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              _CompactDropdown<String?>(
                value: selectedLocation,
                style: dropdownStyle,
                hint: 'Все локации',
                items: [
                  const DropdownMenuItem<String?>(
                    value: null,
                    child: Text('Все локации'),
                  ),
                  for (final location in locations)
                    DropdownMenuItem<String?>(
                      value: location,
                      child: Text(location),
                    ),
                ],
                onChanged: onLocationChanged,
              ),
              _CompactDropdown<_LiveSort>(
                value: sort,
                style: dropdownStyle,
                items: const [
                  DropdownMenuItem(
                    value: _LiveSort.priority,
                    child: Text('Сначала рабочие'),
                  ),
                  DropdownMenuItem(
                    value: _LiveSort.location,
                    child: Text('По локации'),
                  ),
                  DropdownMenuItem(
                    value: _LiveSort.name,
                    child: Text('По названию'),
                  ),
                ],
                onChanged: (value) {
                  if (value != null) onSortChanged(value);
                },
              ),
              if (mode == _LiveMode.standard) ...[
                _GridChoice(
                  label: 'Авто',
                  selected: standardColumns == 0,
                  onTap: () => onColumnsChanged(0),
                ),
                _GridChoice(
                  label: '1',
                  selected: standardColumns == 1,
                  onTap: () => onColumnsChanged(1),
                ),
                _GridChoice(
                  label: '2',
                  selected: standardColumns == 2,
                  onTap: () => onColumnsChanged(2),
                ),
                _GridChoice(
                  label: '3',
                  selected: standardColumns == 3,
                  onTap: () => onColumnsChanged(3),
                ),
              ] else ...[
                _GridChoice(
                  label: '2 x 2',
                  selected: gridPreset == _GridPreset.twoByTwo,
                  onTap: () => onGridPresetChanged(_GridPreset.twoByTwo),
                ),
                _GridChoice(
                  label: '3 x 3',
                  selected: gridPreset == _GridPreset.threeByThree,
                  onTap: () => onGridPresetChanged(_GridPreset.threeByThree),
                ),
                _GridChoice(
                  label: '4 x 4',
                  selected: gridPreset == _GridPreset.fourByFour,
                  onTap: () => onGridPresetChanged(_GridPreset.fourByFour),
                ),
                _StepperChip(
                  label: 'Строки',
                  value: customRows,
                  selected: gridPreset == _GridPreset.custom,
                  onChanged: onCustomRowsChanged,
                ),
                _StepperChip(
                  label: 'Колонки',
                  value: customColumns,
                  selected: gridPreset == _GridPreset.custom,
                  onChanged: onCustomColumnsChanged,
                ),
                OutlinedButton.icon(
                  onPressed:
                      canOpenFullscreenGrid ? onOpenFullscreenGrid : null,
                  icon: const Icon(Icons.open_in_full_rounded, size: 18),
                  label: const Text('Полноэкранная сетка'),
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }
}

class _CompactDropdown<T> extends StatelessWidget {
  const _CompactDropdown({
    required this.value,
    required this.items,
    required this.onChanged,
    required this.style,
    this.hint,
  });

  final T value;
  final List<DropdownMenuItem<T>> items;
  final ValueChanged<T?> onChanged;
  final TextStyle style;
  final String? hint;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      constraints: const BoxConstraints(minWidth: 150, maxWidth: 240),
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(
        color: colors.surfaceMuted,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: colors.border),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<T>(
          value: value,
          hint: hint == null ? null : Text(hint!, style: style),
          isExpanded: true,
          dropdownColor: colors.surfaceElevated,
          style: style,
          icon: const Icon(Icons.expand_more_rounded),
          items: items,
          onChanged: onChanged,
        ),
      ),
    );
  }
}

class _ControlChip extends StatelessWidget {
  const _ControlChip({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 17, color: colors.primaryAccent),
          const SizedBox(width: 7),
          Text(
            label,
            style: TextStyle(
              color: colors.muted,
              fontWeight: FontWeight.w800,
              fontSize: 13,
            ),
          ),
        ],
      ),
    );
  }
}

class _StepperChip extends StatelessWidget {
  const _StepperChip({
    required this.label,
    required this.value,
    required this.selected,
    required this.onChanged,
  });

  final String label;
  final int value;
  final bool selected;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: selected
            ? colors.primaryAccent.withValues(alpha: 0.16)
            : colors.surfaceMuted,
        border: Border.all(
          color: selected ? colors.primaryAccent : colors.border,
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '$label: $value',
            style: TextStyle(
              color: selected ? colors.primaryAccent : colors.muted,
              fontWeight: FontWeight.w900,
              fontSize: 12,
            ),
          ),
          const SizedBox(width: 5),
          _MiniIconButton(
            icon: Icons.remove_rounded,
            onPressed: value <= 1 ? null : () => onChanged(value - 1),
          ),
          _MiniIconButton(
            icon: Icons.add_rounded,
            onPressed: value >= 6 ? null : () => onChanged(value + 1),
          ),
        ],
      ),
    );
  }
}

class _MiniIconButton extends StatelessWidget {
  const _MiniIconButton({required this.icon, this.onPressed});

  final IconData icon;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 28,
      height: 28,
      child: IconButton(
        padding: EdgeInsets.zero,
        visualDensity: VisualDensity.compact,
        onPressed: onPressed,
        icon: Icon(icon, size: 16),
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
    return PageHeader(
      title: 'Эфир',
      icon: Icons.live_tv_rounded,
      trailing: PageActions(
        children: [
          OutlinedButton.icon(
          onPressed: loading ? null : onRefresh,
          icon: loading
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

class _GridCameraPicker extends StatefulWidget {
  const _GridCameraPicker({required this.cameras, required this.onQuickAdd});

  final List<CameraSummary> cameras;
  final ValueChanged<int> onQuickAdd;

  @override
  State<_GridCameraPicker> createState() => _GridCameraPickerState();
}

class _GridCameraPickerState extends State<_GridCameraPicker> {
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
    final compact = MediaQuery.sizeOf(context).width < 700;
    final filtered = _filterGridPickerCameras(widget.cameras, _query.text);
    return GlassPanel(
      padding: const EdgeInsets.all(12),
      child: widget.cameras.isEmpty
          ? Text(
              'Все камеры уже размещены в сетке.',
              style: TextStyle(color: colors.muted),
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextField(
                  controller: _query,
                  decoration: const InputDecoration(
                    prefixIcon: Icon(Icons.search_rounded),
                    labelText: 'Поиск камер для сетки',
                  ),
                ),
                const SizedBox(height: 10),
                if (filtered.isEmpty)
                  Text(
                    'Под фильтр камер нет.',
                    style: TextStyle(color: colors.muted),
                  )
                else if (compact)
                  _CompactGridCameraPicker(
                    cameras: filtered,
                    onQuickAdd: widget.onQuickAdd,
                  )
                else
                  _WideGridCameraPicker(
                    cameras: filtered,
                    onQuickAdd: widget.onQuickAdd,
                  ),
              ],
            ),
    );
  }
}

class _CompactGridCameraPicker extends StatelessWidget {
  const _CompactGridCameraPicker({
    required this.cameras,
    required this.onQuickAdd,
  });

  final List<CameraSummary> cameras;
  final ValueChanged<int> onQuickAdd;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _ControlChip(
          icon: Icons.drag_indicator_rounded,
          label: 'Камеры для сетки',
        ),
        const SizedBox(height: 10),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: [
              for (final camera in cameras)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: _CameraDragChip(
                    camera: camera,
                    onQuickAdd: onQuickAdd,
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class _WideGridCameraPicker extends StatelessWidget {
  const _WideGridCameraPicker({
    required this.cameras,
    required this.onQuickAdd,
  });

  final List<CameraSummary> cameras;
  final ValueChanged<int> onQuickAdd;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        _ControlChip(
          icon: Icons.drag_indicator_rounded,
          label: 'Камеры для сетки',
        ),
        for (final camera in cameras)
          _CameraDragChip(camera: camera, onQuickAdd: onQuickAdd),
      ],
    );
  }
}

List<CameraSummary> _filterGridPickerCameras(
  List<CameraSummary> cameras,
  String rawQuery,
) {
  final query = rawQuery.trim().toLowerCase();
  if (query.isEmpty) return cameras;
  final ipLike = RegExp(r'^[0-9.]+$').hasMatch(query);
  return cameras.where((camera) {
    final ip = (camera.ipAddress ?? '').toLowerCase();
    if (ipLike) {
      return ip.contains(query) ||
          (camera.streamUrl ?? '').toLowerCase().contains(query);
    }
    final text =
        '${camera.name} ${camera.location ?? ''} ${camera.connectionKind}'
            .toLowerCase();
    return _looseContains(text, query);
  }).toList(growable: false);
}

bool _looseContains(String text, String query) {
  if (text.contains(query)) return true;
  final parts = query
      .split(RegExp(r'\s+'))
      .where((part) => part.isNotEmpty)
      .toList(growable: false);
  if (parts.isEmpty) return true;
  return parts.every((part) {
    if (text.contains(part)) return true;
    return text.split(RegExp(r'\s+')).any((word) => _editDistance(word, part) <= 1);
  });
}

int _editDistance(String a, String b) {
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

class _CameraDragChip extends StatelessWidget {
  const _CameraDragChip({required this.camera, required this.onQuickAdd});

  final CameraSummary camera;
  final ValueChanged<int> onQuickAdd;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final label = camera.location?.trim().isNotEmpty == true
        ? '${camera.name} - ${camera.location}'
        : camera.name;
    final chip = ActionChip(
      avatar: const Icon(Icons.videocam_rounded, size: 18),
      label: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 210),
        child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis),
      ),
      onPressed: () => onQuickAdd(camera.cameraId),
    );
    return LongPressDraggable<_GridDragPayload>(
      data: _GridDragPayload(cameraId: camera.cameraId),
      feedback: Material(
        color: Colors.transparent,
        child: Container(
          constraints: const BoxConstraints(maxWidth: 240),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(999),
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
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              color: colors.textStrong,
              fontWeight: FontWeight.w900,
            ),
          ),
        ),
      ),
      childWhenDragging: Opacity(opacity: 0.45, child: chip),
      child: chip,
    );
  }
}

class _GridSlotTile extends StatefulWidget {
  const _GridSlotTile({
    required this.index,
    required this.camera,
    required this.annotate,
    required this.active,
    required this.onCameraDropped,
    required this.onActivate,
    required this.onDeactivate,
    required this.onAnnotateChanged,
    required this.onRemove,
  });

  final int index;
  final CameraSummary? camera;
  final bool annotate;
  final bool active;
  final ValueChanged<_GridDragPayload> onCameraDropped;
  final VoidCallback? onActivate;
  final VoidCallback? onDeactivate;
  final ValueChanged<bool>? onAnnotateChanged;
  final VoidCallback? onRemove;

  @override
  State<_GridSlotTile> createState() => _GridSlotTileState();
}

class _GridSlotTileState extends State<_GridSlotTile> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return DragTarget<_GridDragPayload>(
      onWillAcceptWithDetails: (_) {
        setState(() => _hovered = true);
        return true;
      },
      onLeave: (_) => setState(() => _hovered = false),
      onAcceptWithDetails: (details) {
        setState(() => _hovered = false);
        widget.onCameraDropped(details.data);
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
          child: widget.camera == null
              ? _EmptyGridSlot(index: widget.index)
              : LongPressDraggable<_GridDragPayload>(
                  data: _GridDragPayload(
                    cameraId: widget.camera!.cameraId,
                    sourceSlot: widget.index,
                  ),
                  feedback: Material(
                    color: Colors.transparent,
                    child: _GridDragPreview(camera: widget.camera!),
                  ),
                  childWhenDragging: Opacity(
                    opacity: 0.45,
                    child: _CameraTile(
                      camera: widget.camera!,
                      annotate: widget.annotate,
                      active: widget.active,
                      onActivate: widget.onActivate!,
                      onDeactivate: widget.onDeactivate!,
                      onAnnotateChanged: widget.onAnnotateChanged,
                      onRemove: widget.onRemove,
                    ),
                  ),
                  child: _CameraTile(
                    camera: widget.camera!,
                    annotate: widget.annotate,
                    active: widget.active,
                    onActivate: widget.onActivate!,
                    onDeactivate: widget.onDeactivate!,
                    onAnnotateChanged: widget.onAnnotateChanged,
                    onRemove: widget.onRemove,
                  ),
                ),
        );
      },
    );
  }
}

class _GridDragPreview extends StatelessWidget {
  const _GridDragPreview({required this.camera});

  final CameraSummary camera;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      constraints: const BoxConstraints(maxWidth: 260),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
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
        camera.name,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(
          color: colors.textStrong,
          fontWeight: FontWeight.w900,
        ),
      ),
    );
  }
}

class _EmptyGridSlot extends StatelessWidget {
  const _EmptyGridSlot({required this.index});

  final int index;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(18),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.add_to_queue_rounded,
              size: 34,
              color: colors.primaryAccent,
            ),
            const SizedBox(height: 10),
            Text(
              'Ячейка ${index + 1}',
              style: TextStyle(
                color: colors.textStrong,
                fontWeight: FontWeight.w900,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              'Перетащите камеру сюда',
              textAlign: TextAlign.center,
              style: TextStyle(color: colors.muted),
            ),
          ],
        ),
      ),
    );
  }
}

class _DraggableCameraTile extends StatefulWidget {
  const _DraggableCameraTile({
    required this.camera,
    required this.annotate,
    required this.active,
    required this.onActivate,
    required this.onDeactivate,
    required this.onAnnotateChanged,
    required this.onMoveBefore,
  });

  final CameraSummary camera;
  final bool annotate;
  final bool active;
  final VoidCallback onActivate;
  final VoidCallback onDeactivate;
  final ValueChanged<bool> onAnnotateChanged;
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
                active: widget.active,
                onActivate: widget.onActivate,
                onDeactivate: widget.onDeactivate,
                onAnnotateChanged: widget.onAnnotateChanged,
              ),
            ),
            child: _CameraTile(
              camera: widget.camera,
              annotate: widget.annotate,
              active: widget.active,
              onActivate: widget.onActivate,
              onDeactivate: widget.onDeactivate,
              onAnnotateChanged: widget.onAnnotateChanged,
            ),
          ),
        );
      },
    );
  }
}

class _CameraTile extends StatefulWidget {
  const _CameraTile({
    required this.camera,
    required this.annotate,
    required this.active,
    required this.onActivate,
    required this.onDeactivate,
    this.onAnnotateChanged,
    this.onRemove,
  });

  final CameraSummary camera;
  final bool annotate;
  final bool active;
  final VoidCallback onActivate;
  final VoidCallback onDeactivate;
  final ValueChanged<bool>? onAnnotateChanged;
  final VoidCallback? onRemove;

  @override
  State<_CameraTile> createState() => _CameraTileState();
}

class _CameraTileState extends State<_CameraTile> {
  static const _ptzSafetyStopDelay = Duration(milliseconds: 420);

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
        await api.ptzContinuous(
          token,
          widget.camera.cameraId,
          pan: pan,
          tilt: tilt,
          zoom: zoom,
          timeoutSeconds: 0.25,
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
                  if (token != null && widget.active)
                    InteractiveViewer(
                      minScale: 1,
                      maxScale: 5,
                      child: _ResolvedCameraStreamView(
                        api: api,
                        token: token,
                        cameraId: camera.cameraId,
                        annotate: widget.annotate,
                        maxFps: MediaQuery.sizeOf(context).width < 600
                            ? 30
                            : 60,
                        fit: BoxFit.cover,
                        errorBuilder: (context, error) => _NoStream(
                          camera: camera,
                          message: 'Нет эфирного потока: $error',
                          actionLabel: 'Повторить',
                          onAction: _restartStream,
                        ),
                      ),
                    )
                  else
                    _NoStream(
                      camera: camera,
                      message: token == null
                          ? 'Нет авторизации'
                          : 'Поток не открыт',
                      actionLabel: token == null ? null : 'Открыть поток',
                      onAction: token == null ? null : widget.onActivate,
                    ),
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
                      text: camera.detectionEnabled ? 'ДЕТЕКЦИЯ' : 'ПРОСМОТР',
                      active: camera.detectionEnabled,
                    ),
                  ),
                  Positioned(
                    right: 12,
                    bottom: 12,
                    child: Wrap(
                      spacing: 8,
                      children: [
                        IconButton.filledTonal(
                          tooltip: widget.annotate
                              ? 'Отключить оверлей'
                              : 'Включить оверлей',
                          onPressed: widget.onAnnotateChanged == null
                              ? null
                              : () => widget.onAnnotateChanged!(
                                    !widget.annotate,
                                  ),
                          icon: Icon(
                            widget.annotate
                                ? Icons.visibility_rounded
                                : Icons.visibility_off_rounded,
                          ),
                        ),
                        if (widget.active)
                          IconButton.filledTonal(
                            tooltip: 'Остановить поток',
                            onPressed: widget.onDeactivate,
                            icon: const Icon(Icons.stop_rounded),
                          ),
                        if (widget.onRemove != null)
                          IconButton.filledTonal(
                            tooltip: 'Убрать из сетки',
                            onPressed: widget.onRemove,
                            icon: const Icon(Icons.close_rounded),
                          ),
                        IconButton.filledTonal(
                          tooltip: 'Во весь экран',
                          onPressed: _openFullscreen,
                          icon: const Icon(Icons.fullscreen_rounded),
                        ),
                      ],
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
                    onUp: () => _startPtzHold(tilt: 0.22),
                    onDown: () => _startPtzHold(tilt: -0.22),
                    onLeft: () => _startPtzHold(pan: -0.22),
                    onRight: () => _startPtzHold(pan: 0.22),
                    onZoomIn: () => _startPtzHold(zoom: 0.18),
                    onZoomOut: () => _startPtzHold(zoom: -0.18),
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

  void _restartStream() {
    widget.onDeactivate();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) widget.onActivate();
    });
  }
}

class _ResolvedCameraStreamView extends StatefulWidget {
  const _ResolvedCameraStreamView({
    required this.api,
    required this.token,
    required this.cameraId,
    required this.annotate,
    required this.maxFps,
    required this.fit,
    this.errorBuilder,
  });

  final ApiClient api;
  final String token;
  final int cameraId;
  final bool annotate;
  final int maxFps;
  final BoxFit fit;
  final Widget Function(BuildContext context, Object error)? errorBuilder;

  @override
  State<_ResolvedCameraStreamView> createState() =>
      _ResolvedCameraStreamViewState();
}

class _ResolvedCameraStreamViewState extends State<_ResolvedCameraStreamView> {
  List<CameraStreamSource> _sources = const [];
  bool _loading = true;
  int _sourceIndex = 0;
  int _generation = 0;
  bool _fallbackQueued = false;

  @override
  void initState() {
    super.initState();
    _reloadSources();
  }

  @override
  void didUpdateWidget(covariant _ResolvedCameraStreamView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.api != widget.api ||
        oldWidget.token != widget.token ||
        oldWidget.cameraId != widget.cameraId ||
        oldWidget.annotate != widget.annotate ||
        oldWidget.maxFps != widget.maxFps) {
      _reloadSources();
    }
  }

  void _reloadSources() {
    _generation += 1;
    final generation = _generation;
    setState(() {
      _loading = true;
      _sourceIndex = 0;
      _fallbackQueued = false;
      _sources = const [];
    });
    unawaited(
      widget.api
          .cameraStreamSources(
            widget.token,
            widget.cameraId,
            annotate: widget.annotate,
            maxFps: widget.maxFps,
          )
          .catchError((_) {
            return [
              CameraStreamSource(
                uri: widget.api.cameraStreamUri(
                  widget.cameraId,
                  annotate: widget.annotate,
                  maxFps: widget.maxFps,
                ),
                headers: const {},
                kind: 'backend_proxy',
              ),
            ];
          })
          .then((sources) {
            if (!mounted || generation != _generation) return;
            setState(() {
              _sources = sources;
              _sourceIndex = 0;
              _loading = false;
            });
          }),
    );
  }

  void _tryNextSource(Object error) {
    if (_fallbackQueued || _sourceIndex + 1 >= _sources.length) return;
    _fallbackQueued = true;
    scheduleMicrotask(() {
      if (!mounted || _sourceIndex + 1 >= _sources.length) return;
      setState(() {
        _sourceIndex += 1;
        _fallbackQueued = false;
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator(strokeWidth: 2));
    }
    if (_sources.isEmpty) {
      return widget.errorBuilder?.call(context, 'Источник потока не найден') ??
          const SizedBox.shrink();
    }

    final source = _sources[math.min(_sourceIndex, _sources.length - 1)];
    return MjpegStreamView(
      key: ValueKey('${source.kind}:${source.uri}:$_sourceIndex'),
      uri: source.uri,
      headers: {
        ...source.headers,
        'Authorization': 'Bearer ${widget.token}',
      },
      fit: widget.fit,
      errorBuilder: widget.errorBuilder,
      onError: _tryNextSource,
    );
  }
}

class _NoStream extends StatelessWidget {
  const _NoStream({
    required this.camera,
    required this.message,
    this.actionLabel,
    this.onAction,
  });

  final CameraSummary camera;
  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;

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
              if (actionLabel != null && onAction != null) ...[
                const SizedBox(height: 12),
                ElevatedButton.icon(
                  onPressed: onAction,
                  icon: const Icon(Icons.play_arrow_rounded),
                  label: Text(actionLabel!),
                ),
              ],
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
    if (_holding) return;
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

class _GridFullscreenDialog extends StatelessWidget {
  const _GridFullscreenDialog({
    required this.slots,
    required this.camerasById,
    required this.activeSlots,
    required this.annotateBySlot,
  });

  final List<int?> slots;
  final Map<int, CameraSummary> camerasById;
  final Set<int> activeSlots;
  final List<bool> annotateBySlot;

  @override
  Widget build(BuildContext context) {
    final token = context.watch<AuthController>().accessToken;
    final api = context.read<ApiClient>();
    final slotCount = slots.isEmpty ? 1 : slots.length;
    final columns = math.max(1, math.sqrt(slotCount).ceil());
    return Dialog.fullscreen(
      backgroundColor: Colors.black,
      child: Stack(
        children: [
          Positioned.fill(
            child: GridView.builder(
              padding: const EdgeInsets.all(12),
              gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: columns,
                crossAxisSpacing: 8,
                mainAxisSpacing: 8,
                childAspectRatio: 16 / 9,
              ),
              itemCount: slots.length,
              itemBuilder: (context, index) {
                final cameraId = slots[index];
                final camera =
                    cameraId == null ? null : camerasById[cameraId];
                if (camera == null || token == null || !activeSlots.contains(index)) {
                  return Container(
                    color: Colors.white.withValues(alpha: 0.06),
                    alignment: Alignment.center,
                    child: Text(
                      camera?.name ?? 'Свободная ячейка',
                      style: const TextStyle(color: Colors.white70),
                    ),
                  );
                }
                return Stack(
                  fit: StackFit.expand,
                  children: [
                    _ResolvedCameraStreamView(
                      api: api,
                      token: token,
                      cameraId: camera.cameraId,
                      annotate: index < annotateBySlot.length
                          ? annotateBySlot[index]
                          : true,
                      maxFps: 30,
                      fit: BoxFit.cover,
                      errorBuilder: (context, error) => Center(
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Text(
                            'Нет эфирного потока: $error',
                            maxLines: 4,
                            overflow: TextOverflow.ellipsis,
                            textAlign: TextAlign.center,
                            style: const TextStyle(color: Colors.white70),
                          ),
                        ),
                      ),
                    ),
                    Positioned(
                      left: 10,
                      top: 10,
                      child: _CameraBadge(text: camera.name, active: true),
                    ),
                  ],
                );
              },
            ),
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
        ],
      ),
    );
  }
}

// ignore: unused_element
class _FullscreenGridCell extends StatelessWidget {
  const _FullscreenGridCell({
    required this.index,
    required this.slots,
    required this.camerasById,
    required this.activeSlots,
    required this.annotateBySlot,
    required this.api,
    required this.token,
  });

  final int index;
  final List<int?> slots;
  final Map<int, CameraSummary> camerasById;
  final Set<int> activeSlots;
  final List<bool> annotateBySlot;
  final ApiClient api;
  final String? token;

  @override
  Widget build(BuildContext context) {
    final cameraId = index < slots.length ? slots[index] : null;
    final camera = cameraId == null ? null : camerasById[cameraId];
    if (camera == null || token == null || !activeSlots.contains(index)) {
      return Container(
        color: Colors.white.withValues(alpha: 0.06),
        alignment: Alignment.center,
        child: Text(
          camera?.name ?? 'Свободная ячейка',
          style: const TextStyle(color: Colors.white70),
        ),
      );
    }
    return Stack(
      fit: StackFit.expand,
      children: [
        _ResolvedCameraStreamView(
          api: api,
          token: token!,
          cameraId: camera.cameraId,
          annotate: index < annotateBySlot.length ? annotateBySlot[index] : true,
          maxFps: 30,
          fit: BoxFit.contain,
          errorBuilder: (context, error) => Center(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Text(
                'Нет эфирного потока: $error',
                maxLines: 4,
                overflow: TextOverflow.ellipsis,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white70),
              ),
            ),
          ),
        ),
        Positioned(
          left: 10,
          top: 10,
          child: _CameraBadge(text: camera.name, active: true),
        ),
      ],
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
  static const _ptzSafetyStopDelay = Duration(milliseconds: 420);

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
        timeoutSeconds: 0.25,
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
      _move(tilt: 0.22);
    } else if (key == LogicalKeyboardKey.keyS ||
        key == LogicalKeyboardKey.arrowDown) {
      _move(tilt: -0.22);
    } else if (key == LogicalKeyboardKey.keyA ||
        key == LogicalKeyboardKey.arrowLeft) {
      _move(pan: -0.22);
    } else if (key == LogicalKeyboardKey.keyD ||
        key == LogicalKeyboardKey.arrowRight) {
      _move(pan: 0.22);
    } else if (key == LogicalKeyboardKey.keyQ) {
      _move(zoom: -0.18);
    } else if (key == LogicalKeyboardKey.keyE) {
      _move(zoom: 0.18);
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
                      child: _ResolvedCameraStreamView(
                        api: api,
                        token: token,
                        cameraId: widget.camera.cameraId,
                        annotate: widget.annotate,
                        maxFps: 60,
                        fit: BoxFit.contain,
                        errorBuilder: (context, error) => Center(
                          child: Padding(
                            padding: const EdgeInsets.all(24),
                            child: Text(
                              'Нет эфирного потока: $error',
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
