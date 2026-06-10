import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../core/network/api_client.dart';
import '../../core/profiles/connection_profiles.dart';
import '../../core/theme/app_theme.dart';
import '../../core/theme/theme_controller.dart';
import '../../shared/widgets/glass_panel.dart';

class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key});

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  late final TextEditingController _domainController;
  late final TextEditingController _emailController;
  bool _staging = false;
  bool _busy = false;
  String _status = '';
  String _log = '';

  @override
  void initState() {
    super.initState();
    final apiUrl = context.read<ThemeController>().apiBaseUrl;
    final uri = Uri.tryParse(apiUrl);
    final host = uri?.host ?? '';
    _domainController = TextEditingController(
      text: _isDomain(host) ? host : '',
    );
    _emailController = TextEditingController();
  }

  @override
  void dispose() {
    _domainController.dispose();
    _emailController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final compact = MediaQuery.sizeOf(context).width < 760;
    final command = _commandPreview();

    return CustomScrollView(
      slivers: [
        SliverToBoxAdapter(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'CCTV Настройка',
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  color: colors.textStrong,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 16),
            ],
          ),
        ),
        SliverList.list(
          children: [
            GlassPanel(
              padding: EdgeInsets.all(compact ? 14 : 18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const _SectionTitle(title: 'HTTPS'),
                  const SizedBox(height: 14),
                  compact
                      ? Column(children: _fields(spacing: 10))
                      : Row(
                          children: [
                            Expanded(child: _domainField()),
                            const SizedBox(width: 10),
                            Expanded(child: _emailField()),
                          ],
                        ),
                  const SizedBox(height: 10),
                  SwitchListTile.adaptive(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    value: _staging,
                    onChanged: _busy
                        ? null
                        : (value) => setState(() => _staging = value),
                    title: const Text('Тестовый сертификат'),
                  ),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      OutlinedButton.icon(
                        onPressed: _busy ? null : _checkDomain,
                        icon: const Icon(
                          Icons.travel_explore_rounded,
                          size: 18,
                        ),
                        label: const Text('Проверить DNS'),
                      ),
                      OutlinedButton.icon(
                        onPressed: _busy ? null : _checkBackend,
                        icon: const Icon(Icons.favorite_rounded, size: 18),
                        label: const Text('Проверить backend'),
                      ),
                      OutlinedButton.icon(
                        onPressed: () => _copy(command),
                        icon: const Icon(Icons.copy_rounded, size: 18),
                        label: const Text('Скопировать команду'),
                      ),
                      ElevatedButton.icon(
                        onPressed: _busy ? null : _runSetup,
                        icon: _busy
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Icon(Icons.play_arrow_rounded, size: 20),
                        label: const Text('Запустить настройку'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            if (_status.isNotEmpty || _log.isNotEmpty) ...[
              const SizedBox(height: 14),
              GlassPanel(
                padding: const EdgeInsets.all(18),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (_status.isNotEmpty)
                      Text(
                        _status,
                        style: TextStyle(
                          color: colors.textStrong,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    if (_log.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      SelectableText(
                        _log,
                        style: TextStyle(
                          color: colors.muted,
                          fontFamily: 'monospace',
                          fontSize: 12,
                          height: 1.35,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
            const SizedBox(height: 24),
          ],
        ),
      ],
    );
  }

  List<Widget> _fields({double spacing = 0}) {
    return [
      _domainField(),
      if (spacing > 0) SizedBox(height: spacing),
      _emailField(),
    ];
  }

  Widget _domainField() {
    return TextField(
      controller: _domainController,
      enabled: !_busy,
      textInputAction: TextInputAction.next,
      decoration: _setupInputDecoration(
        labelText: 'Домен',
        hintText: 'cctv.example.com',
      ),
    );
  }

  Widget _emailField() {
    return TextField(
      controller: _emailController,
      enabled: !_busy,
      keyboardType: TextInputType.emailAddress,
      textInputAction: TextInputAction.done,
      decoration: _setupInputDecoration(
        labelText: 'Email Let’s Encrypt',
        hintText: 'admin@example.com',
      ),
    );
  }

  InputDecoration _setupInputDecoration({
    required String labelText,
    required String hintText,
  }) {
    return InputDecoration(
      labelText: labelText,
      hintText: hintText,
      contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 18),
    );
  }

  Future<void> _checkDomain() async {
    final domain = _domainController.text.trim();
    if (!_isDomain(domain)) {
      setState(() => _status = 'Укажите реальный домен, не IP и не localhost.');
      return;
    }
    setState(() {
      _busy = true;
      _status = 'Проверяю DNS...';
      _log = '';
    });
    try {
      final result = await InternetAddress.lookup(domain);
      setState(() {
        _status = 'DNS отвечает.';
        _log = result
            .map((item) => '${item.type.name}: ${item.address}')
            .join('\n');
      });
    } catch (error) {
      setState(() {
        _status = 'DNS-проверка не прошла.';
        _log = '$error';
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _checkBackend() async {
    setState(() {
      _busy = true;
      _status = 'Проверяю backend...';
      _log = '';
    });
    try {
      final response = await context.read<ApiClient>().getJson('/health');
      setState(() {
        _status = 'Backend отвечает.';
        _log = const JsonEncoder.withIndent('  ').convert(response);
      });
    } catch (error) {
      setState(() {
        _status = 'Backend недоступен из текущего профиля.';
        _log = '$error';
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _runSetup() async {
    if (Platform.isAndroid) {
      await _copy(_commandPreview());
      setState(() {
        _status = 'На Android запуск Docker недоступен. Команда скопирована.';
      });
      return;
    }
    final script = _findSetupScript();
    if (script == null) {
      setState(() {
        _status =
            'Не найден scripts/setup_public_https.py рядом с приложением.';
        _log = 'Скопируйте команду и выполните ее из папки проекта.';
      });
      return;
    }

    setState(() {
      _busy = true;
      _status = 'Запускаю настройку HTTPS...';
      _log = '';
    });
    final executable = Platform.isWindows ? 'py' : 'python3';
    final args = Platform.isWindows
        ? [
            '-3.11',
            script.path,
            '--domain',
            _domainController.text.trim(),
            '--email',
            _emailController.text.trim(),
          ]
        : [
            script.path,
            '--domain',
            _domainController.text.trim(),
            '--email',
            _emailController.text.trim(),
          ];
    if (_staging) args.add('--staging');

    try {
      final process = await Process.start(
        executable,
        args,
        workingDirectory: script.parent.parent.path,
      );
      process.stdout.transform(utf8.decoder).listen(_appendLog);
      process.stderr.transform(utf8.decoder).listen(_appendLog);
      final code = await process.exitCode;
      if (code == 0) {
        await _saveHttpsProfile();
      }
      if (mounted) {
        setState(() {
          _status = code == 0
              ? 'HTTPS настроен.'
              : 'Настройка завершилась с ошибкой $code.';
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _status = 'Не удалось запустить мастер.';
          _log = '$error';
        });
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _saveHttpsProfile() async {
    final domain = _domainController.text.trim().toLowerCase();
    final url = 'https://$domain';
    final profiles = context.read<ConnectionProfilesController>();
    final settings = context.read<ThemeController>();
    final profile = await profiles.saveProfile(
      name: domain,
      baseUrl: url,
      makeActive: true,
    );
    await settings.setApiBaseUrl(profile.baseUrl);
  }

  void _appendLog(String chunk) {
    if (!mounted || chunk.isEmpty) return;
    setState(() {
      final lines = (_log + chunk).split('\n');
      final start = lines.length > 200 ? lines.length - 200 : 0;
      _log = lines.sublist(start).join('\n');
    });
  }

  Future<void> _copy(String text) async {
    await Clipboard.setData(ClipboardData(text: text));
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Скопировано'),
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  String _commandPreview() {
    final script = Platform.isWindows ? r'py -3.11' : 'python3';
    final staging = _staging ? ' --staging' : '';
    return '$script scripts/setup_public_https.py --domain ${_domainController.text.trim()} --email ${_emailController.text.trim()}$staging';
  }

  File? _findSetupScript() {
    final roots = <Directory>[
      Directory.current,
      File(Platform.resolvedExecutable).parent,
      File(Platform.resolvedExecutable).parent.parent,
    ];
    final envRoot = Platform.environment['CCTV_PROJECT_ROOT'];
    if (envRoot != null && envRoot.trim().isNotEmpty) {
      roots.add(Directory(envRoot.trim()));
    }

    final checked = <String>{};
    for (final root in roots) {
      for (final dir in _selfAndParents(root)) {
        final candidate = File(
          '${dir.path}${Platform.pathSeparator}scripts${Platform.pathSeparator}setup_public_https.py',
        );
        if (!checked.add(candidate.path)) continue;
        if (candidate.existsSync()) return candidate;
      }
    }
    return null;
  }

  Iterable<Directory> _selfAndParents(Directory start) sync* {
    var current = start.absolute;
    for (var depth = 0; depth < 6; depth++) {
      yield current;
      final parent = current.parent;
      if (parent.path == current.path) break;
      current = parent;
    }
  }

  static bool _isDomain(String value) {
    final clean = value.trim().toLowerCase();
    if (clean.isEmpty || clean == 'localhost') return false;
    if (RegExp(r'^\d{1,3}(\.\d{1,3}){3}$').hasMatch(clean)) return false;
    return RegExp(r'^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}$').hasMatch(clean);
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: Theme.of(context).textTheme.titleLarge?.copyWith(
            color: colors.textStrong,
            fontWeight: FontWeight.w900,
          ),
        ),
      ],
    );
  }
}
