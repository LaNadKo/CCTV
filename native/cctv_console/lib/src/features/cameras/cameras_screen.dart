import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/network/api_client.dart';
import '../../core/theme/app_theme.dart';
import '../../shared/widgets/glass_panel.dart';
import '../auth/auth_controller.dart';

class CameraManagementScreen extends StatefulWidget {
  const CameraManagementScreen({super.key});

  @override
  State<CameraManagementScreen> createState() => _CameraManagementScreenState();
}

class _CameraManagementScreenState extends State<CameraManagementScreen> {
  final _host = TextEditingController();
  final _port = TextEditingController();
  final _username = TextEditingController();
  final _password = TextEditingController();
  final _name = TextEditingController();
  final _location = TextEditingController();

  bool _useHttps = false;
  bool _busy = false;
  String? _error;
  List<Map<String, dynamic>> _cameras = const [];
  List<Map<String, dynamic>> _devices = const [];
  Map<String, dynamic>? _probe;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _host.dispose();
    _port.dispose();
    _username.dispose();
    _password.dispose();
    _name.dispose();
    _location.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    await _run(() async {
      final (api, token) = _deps();
      _cameras = await api.getJsonList('/cameras', token: token);
    });
  }

  Future<void> _scan() async {
    await _run(() async {
      final (api, token) = _deps();
      _devices = await api.post<List<Map<String, dynamic>>>(
        '/admin/cameras/discovery/scan',
        token: token,
        body: {'timeout': 4},
        decoder: (json) => _mapList(json),
      );
    });
  }

  Future<void> _probeCamera() async {
    final host = _host.text.trim();
    if (host.isEmpty) {
      _toast('Укажите Host / IP камеры');
      return;
    }
    await _run(() async {
      final (api, token) = _deps();
      final result = await api.postJson(
        '/admin/cameras/discovery/probe',
        token: token,
        body: {
          'host': host,
          'username': _emptyToNull(_username.text),
          'password': _emptyToNull(_password.text),
          'port': int.tryParse(_port.text.trim()),
          'use_https': _useHttps,
          'timeout': 6,
        },
      );
      _probe = result;
      if (_name.text.trim().isEmpty && result['name'] != null) {
        _name.text = '${result['name']}';
      }
    });
  }

  Future<void> _createCamera() async {
    final probe = _probe;
    if (probe == null) {
      _toast('Сначала выполните определение протоколов');
      return;
    }
    await _run(() async {
      final (api, token) = _deps();
      final endpoints = _mapList(probe['endpoints']);
      final rtsp = endpoints.cast<Map<String, dynamic>?>().firstWhere(
        (endpoint) => endpoint?['endpoint_kind'] == 'rtsp',
        orElse: () => null,
      );
      await api.postJson(
        '/admin/cameras',
        token: token,
        body: {
          'name':
              _emptyToNull(_name.text) ?? probe['name'] ?? _host.text.trim(),
          'location': _emptyToNull(_location.text),
          'ip_address': probe['ip_address'] ?? _host.text.trim(),
          'stream_url': rtsp?['endpoint_url'],
          'detection_enabled': true,
          'recording_mode': 'event',
          'connection_kind': probe['connection_kind'] ?? 'manual',
          'supports_ptz': probe['supports_ptz'] == true,
          'onvif_profile_token': probe['onvif_profile_token'],
          'device_metadata': probe['device_metadata'],
          'endpoints': [
            for (final endpoint in endpoints)
              {
                'endpoint_kind': endpoint['endpoint_kind'],
                'endpoint_url': endpoint['endpoint_url'],
                'username': _emptyToNull(_username.text),
                'password_secret': _emptyToNull(_password.text),
                'is_primary': endpoint['is_primary'] == true,
              },
          ],
        },
      );
      _probe = null;
      _devices = const [];
      _toast('Камера добавлена');
      await _load();
    });
  }

  Future<void> _refreshOnvif(int cameraId) async {
    await _run(() async {
      final (api, token) = _deps();
      await api.postJson(
        '/admin/cameras/$cameraId/onvif/refresh',
        token: token,
      );
      _toast('ONVIF данные обновлены');
      await _load();
    });
  }

  Future<void> _deleteCamera(int cameraId) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Удалить камеру?'),
        content: const Text(
          'Камера будет скрыта из системы и отвязана от Processor.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Отмена'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Удалить'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    await _run(() async {
      final (api, token) = _deps();
      await api.deleteVoid('/admin/cameras/$cameraId', token: token);
      await _load();
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

  void _selectDevice(Map<String, dynamic> device) {
    setState(() {
      _host.text = '${device['host'] ?? ''}';
      _port.text = '${device['port'] ?? ''}';
      _useHttps = device['use_https'] == true;
      if (_name.text.trim().isEmpty && device['name'] != null) {
        _name.text = '${device['name']}';
      }
    });
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), behavior: SnackBarBehavior.floating),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final onvifCount = _cameras
        .where((item) => item['onvif_enabled'] == true)
        .length;
    final ptzCount = _cameras
        .where((item) => item['supports_ptz'] == true)
        .length;

    return RefreshIndicator(
      onRefresh: _load,
      child: CustomScrollView(
        slivers: [
          SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _Header(
                  title: 'Камеры',
                  subtitle:
                      'Автоопределение протоколов управления и видеопотока: ONVIF, RTSP, HTTP.',
                  busy: _busy,
                  onRefresh: _load,
                ),
                const SizedBox(height: 14),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    _Metric(label: 'Всего камер', value: '${_cameras.length}'),
                    _Metric(label: 'ONVIF', value: '$onvifCount'),
                    _Metric(label: 'PTZ', value: '$ptzCount'),
                  ],
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  _InlineError(message: _error!),
                ],
                const SizedBox(height: 14),
                _DiscoveryPanel(
                  host: _host,
                  port: _port,
                  username: _username,
                  password: _password,
                  name: _name,
                  location: _location,
                  useHttps: _useHttps,
                  busy: _busy,
                  devices: _devices,
                  probe: _probe,
                  onUseHttpsChanged: (value) =>
                      setState(() => _useHttps = value),
                  onScan: _scan,
                  onProbe: _probeCamera,
                  onCreate: _createCamera,
                  onSelectDevice: _selectDevice,
                ),
                const SizedBox(height: 14),
              ],
            ),
          ),
          if (_cameras.isEmpty)
            SliverToBoxAdapter(
              child: GlassPanel(
                padding: const EdgeInsets.all(18),
                child: Text(
                  'Камеры пока не добавлены.',
                  style: TextStyle(color: colors.muted),
                ),
              ),
            )
          else
            SliverList.separated(
              itemCount: _cameras.length,
              separatorBuilder: (_, _) => const SizedBox(height: 10),
              itemBuilder: (context, index) {
                final camera = _cameras[index];
                return _CameraCard(
                  camera: camera,
                  onRefreshOnvif: () =>
                      _refreshOnvif(camera['camera_id'] as int),
                  onDelete: () => _deleteCamera(camera['camera_id'] as int),
                );
              },
            ),
          const SliverToBoxAdapter(child: SizedBox(height: 24)),
        ],
      ),
    );
  }
}

class _DiscoveryPanel extends StatelessWidget {
  const _DiscoveryPanel({
    required this.host,
    required this.port,
    required this.username,
    required this.password,
    required this.name,
    required this.location,
    required this.useHttps,
    required this.busy,
    required this.devices,
    required this.probe,
    required this.onUseHttpsChanged,
    required this.onScan,
    required this.onProbe,
    required this.onCreate,
    required this.onSelectDevice,
  });

  final TextEditingController host;
  final TextEditingController port;
  final TextEditingController username;
  final TextEditingController password;
  final TextEditingController name;
  final TextEditingController location;
  final bool useHttps;
  final bool busy;
  final List<Map<String, dynamic>> devices;
  final Map<String, dynamic>? probe;
  final ValueChanged<bool> onUseHttpsChanged;
  final VoidCallback onScan;
  final VoidCallback onProbe;
  final VoidCallback onCreate;
  final ValueChanged<Map<String, dynamic>> onSelectDevice;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: _SectionTitle(
                  title: 'Мастер подключения камеры',
                  subtitle:
                      'Поиск ONVIF в сети и probe по IP: определяем управление, поток и PTZ.',
                ),
              ),
              OutlinedButton.icon(
                onPressed: busy ? null : onScan,
                icon: const Icon(Icons.radar_rounded, size: 18),
                label: Text(busy ? 'Поиск...' : 'Поиск в сети'),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              _SizedField(
                width: 210,
                child: TextField(
                  controller: host,
                  decoration: const InputDecoration(labelText: 'Host / IP'),
                ),
              ),
              _SizedField(
                width: 120,
                child: TextField(
                  controller: port,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: 'Порт'),
                ),
              ),
              _SizedField(
                width: 180,
                child: TextField(
                  controller: username,
                  decoration: const InputDecoration(labelText: 'Логин'),
                ),
              ),
              _SizedField(
                width: 180,
                child: TextField(
                  controller: password,
                  obscureText: true,
                  decoration: const InputDecoration(labelText: 'Пароль'),
                ),
              ),
              _SizedField(
                width: 210,
                child: TextField(
                  controller: name,
                  decoration: const InputDecoration(labelText: 'Название'),
                ),
              ),
              _SizedField(
                width: 210,
                child: TextField(
                  controller: location,
                  decoration: const InputDecoration(labelText: 'Локация'),
                ),
              ),
              FilterChip(
                selected: useHttps,
                onSelected: busy ? null : onUseHttpsChanged,
                label: const Text('HTTPS'),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              ElevatedButton.icon(
                onPressed: busy ? null : onProbe,
                icon: const Icon(Icons.manage_search_rounded, size: 18),
                label: Text(busy ? 'Проверка...' : 'Определить протоколы'),
              ),
              OutlinedButton.icon(
                onPressed: busy || probe == null ? null : onCreate,
                icon: const Icon(Icons.add_rounded, size: 18),
                label: const Text('Добавить камеру'),
              ),
            ],
          ),
          if (devices.isNotEmpty) ...[
            const SizedBox(height: 14),
            Text(
              'Найдено в сети',
              style: TextStyle(
                color: colors.textStrong,
                fontWeight: FontWeight.w900,
              ),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final device in devices)
                  ActionChip(
                    onPressed: () => onSelectDevice(device),
                    label: Text(
                      '${device['name'] ?? device['host']} : ${device['port'] ?? '-'}',
                    ),
                  ),
              ],
            ),
          ],
          if (probe != null) ...[
            const SizedBox(height: 14),
            _ProbeResult(probe: probe!),
          ],
        ],
      ),
    );
  }
}

class _ProbeResult extends StatelessWidget {
  const _ProbeResult({required this.probe});

  final Map<String, dynamic> probe;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final endpoints = _mapList(probe['endpoints']);
    final protocols =
        (probe['protocols'] as List?)?.join(', ') ?? 'не определены';
    final warnings = (probe['warnings'] as List?)?.join(' ') ?? '';
    return Container(
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
            '${probe['name'] ?? probe['ip_address'] ?? 'Камера'}',
            style: TextStyle(
              color: colors.textStrong,
              fontWeight: FontWeight.w900,
              fontSize: 16,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'Протоколы: $protocols. PTZ: ${probe['supports_ptz'] == true ? 'да' : 'нет'}.',
            style: TextStyle(color: colors.muted, fontSize: 13),
          ),
          if (warnings.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(warnings, style: TextStyle(color: colors.warning)),
          ],
          const SizedBox(height: 10),
          for (final endpoint in endpoints)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text(
                '${endpoint['endpoint_kind']}: ${endpoint['endpoint_url']}',
                style: TextStyle(color: colors.text, fontSize: 12),
              ),
            ),
        ],
      ),
    );
  }
}

class _CameraCard extends StatelessWidget {
  const _CameraCard({
    required this.camera,
    required this.onRefreshOnvif,
    required this.onDelete,
  });

  final Map<String, dynamic> camera;
  final VoidCallback onRefreshOnvif;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final endpoints = _mapList(camera['endpoints']);
    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${camera['name'] ?? 'Камера'}',
                      style: TextStyle(
                        color: colors.textStrong,
                        fontSize: 17,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${camera['location'] ?? 'Локация не указана'} • ${camera['ip_address'] ?? 'IP не указан'}',
                      style: TextStyle(color: colors.muted, fontSize: 13),
                    ),
                  ],
                ),
              ),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                alignment: WrapAlignment.end,
                children: [
                  _Badge(
                    label: '${camera['connection_kind'] ?? 'manual'}',
                    color: colors.primaryAccent,
                  ),
                  if (camera['onvif_enabled'] == true)
                    _Badge(label: 'ONVIF', color: colors.success),
                  if (camera['supports_ptz'] == true)
                    _Badge(label: 'PTZ', color: colors.warning),
                ],
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (endpoints.isNotEmpty)
            for (final endpoint in endpoints.take(3))
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(
                  '${endpoint['endpoint_kind']}: ${endpoint['endpoint_url']}',
                  style: TextStyle(color: colors.muted, fontSize: 12),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              OutlinedButton.icon(
                onPressed: camera['onvif_enabled'] == true
                    ? onRefreshOnvif
                    : null,
                icon: const Icon(Icons.sync_rounded, size: 18),
                label: const Text('Синхронизировать ONVIF'),
              ),
              OutlinedButton.icon(
                onPressed: onDelete,
                icon: const Icon(Icons.delete_outline_rounded, size: 18),
                label: const Text('Удалить'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({
    required this.title,
    required this.subtitle,
    required this.busy,
    required this.onRefresh,
  });

  final String title;
  final String subtitle;
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
                title,
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  color: colors.textStrong,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                subtitle,
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
        Text(
          title,
          style: TextStyle(
            color: colors.textStrong,
            fontWeight: FontWeight.w900,
            fontSize: 16,
          ),
        ),
        const SizedBox(height: 3),
        Text(subtitle, style: TextStyle(color: colors.muted, fontSize: 13)),
      ],
    );
  }
}

class _SizedField extends StatelessWidget {
  const _SizedField({required this.width, required this.child});

  final double width;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return SizedBox(width: width, child: child);
  }
}

class _Badge extends StatelessWidget {
  const _Badge({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: color.withValues(alpha: 0.13),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 12,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
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

List<Map<String, dynamic>> _mapList(Object? value) {
  if (value is List) {
    return value
        .whereType<Map>()
        .map((item) => item.map((key, value) => MapEntry('$key', value)))
        .toList();
  }
  return const [];
}

String? _emptyToNull(String value) {
  final text = value.trim();
  return text.isEmpty ? null : text;
}
