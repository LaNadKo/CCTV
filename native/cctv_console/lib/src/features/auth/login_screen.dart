import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/network/api_client.dart';
import '../../core/theme/app_theme.dart';
import '../../core/theme/theme_controller.dart';
import '../../shared/widgets/app_backdrop.dart';
import '../../shared/widgets/glass_panel.dart';
import 'auth_controller.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _apiUrlController;
  final _loginController = TextEditingController(text: 'admin');
  final _passwordController = TextEditingController();
  bool _obscurePassword = true;
  bool _serverSettingsOpen = false;

  @override
  void initState() {
    super.initState();
    _apiUrlController = TextEditingController(
      text: context.read<ThemeController>().apiBaseUrl,
    );
  }

  @override
  void dispose() {
    _apiUrlController.dispose();
    _loginController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit({String? totpCode}) async {
    if (!_formKey.currentState!.validate()) return;
    final settings = context.read<ThemeController>();
    final auth = context.read<AuthController>();

    await settings.setApiBaseUrl(_apiUrlController.text);
    if (!mounted) return;

    try {
      await auth.login(
        login: _loginController.text.trim(),
        password: _passwordController.text,
        totpCode: totpCode,
      );
      if (!mounted) return;
      if (auth.user?.mustChangePassword == true) {
        final changed = await showDialog<bool>(
          context: context,
          barrierDismissible: false,
          builder: (_) =>
              _ForcedPasswordDialog(currentPassword: _passwordController.text),
        );
        if (changed != true) {
          await auth.logout();
        }
      }
    } on ApiException catch (error) {
      if (!mounted) return;
      if (error.statusCode == 400 &&
          error.message.toLowerCase().contains('totp')) {
        final code = await showDialog<String>(
          context: context,
          barrierDismissible: false,
          builder: (_) => const _TwoFactorDialog(),
        );
        if (code != null && code.isNotEmpty) {
          await _submit(totpCode: code);
        }
        return;
      }
      _showError(error.message);
    } catch (error) {
      if (!mounted) return;
      _showError('$error');
    }
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), behavior: SnackBarBehavior.floating),
    );
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();

    return AppBackdrop(
      child: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 460),
            child: GlassPanel(
              radius: 28,
              padding: const EdgeInsets.all(30),
              child: Form(
                key: _formKey,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const _LoginHeader(),
                    const SizedBox(height: 24),
                    TextFormField(
                      controller: _loginController,
                      autofocus: true,
                      textInputAction: TextInputAction.next,
                      decoration: const InputDecoration(labelText: 'Логин'),
                      validator: (value) =>
                          (value ?? '').trim().isEmpty ? 'Укажите логин' : null,
                    ),
                    const SizedBox(height: 14),
                    TextFormField(
                      controller: _passwordController,
                      obscureText: _obscurePassword,
                      decoration: InputDecoration(
                        labelText: 'Пароль',
                        suffixIcon: IconButton(
                          tooltip: _obscurePassword
                              ? 'Показать пароль'
                              : 'Скрыть пароль',
                          onPressed: () => setState(
                            () => _obscurePassword = !_obscurePassword,
                          ),
                          icon: Icon(
                            _obscurePassword
                                ? Icons.visibility_rounded
                                : Icons.visibility_off_rounded,
                          ),
                        ),
                      ),
                      onFieldSubmitted: (_) => _submit(),
                      validator: (value) =>
                          (value ?? '').isEmpty ? 'Укажите пароль' : null,
                    ),
                    if (auth.error != null) ...[
                      const SizedBox(height: 14),
                      _InlineError(message: auth.error!),
                    ],
                    const SizedBox(height: 18),
                    ElevatedButton(
                      onPressed: auth.isLoading ? null : _submit,
                      child: auth.isLoading
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('Войти'),
                    ),
                    const SizedBox(height: 14),
                    _ServerSettingsToggle(
                      open: _serverSettingsOpen,
                      onTap: () => setState(
                        () => _serverSettingsOpen = !_serverSettingsOpen,
                      ),
                    ),
                    AnimatedSwitcher(
                      duration: const Duration(milliseconds: 180),
                      child: _serverSettingsOpen
                          ? Padding(
                              key: const ValueKey('server-settings'),
                              padding: const EdgeInsets.only(top: 12),
                              child: TextFormField(
                                controller: _apiUrlController,
                                decoration: const InputDecoration(
                                  labelText: 'URL backend',
                                  hintText: 'http://127.0.0.1:8001',
                                ),
                                validator: (value) {
                                  final text = value?.trim() ?? '';
                                  if (!text.startsWith('http://') &&
                                      !text.startsWith('https://')) {
                                    return 'Нужен URL с http:// или https://';
                                  }
                                  return null;
                                },
                              ),
                            )
                          : const SizedBox.shrink(),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ForcedPasswordDialog extends StatefulWidget {
  const _ForcedPasswordDialog({required this.currentPassword});

  final String currentPassword;

  @override
  State<_ForcedPasswordDialog> createState() => _ForcedPasswordDialogState();
}

class _ForcedPasswordDialogState extends State<_ForcedPasswordDialog> {
  final _formKey = GlobalKey<FormState>();
  final _newPassword = TextEditingController();
  final _repeatPassword = TextEditingController();
  var _busy = false;
  String? _error;

  @override
  void dispose() {
    _newPassword.dispose();
    _repeatPassword.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.read<AuthController>().changePassword(
        currentPassword: widget.currentPassword,
        newPassword: _newPassword.text,
      );
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } catch (error) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = '$error';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AlertDialog(
      backgroundColor: colors.surfaceElevated,
      surfaceTintColor: Colors.transparent,
      title: const Text('Требуется смена пароля'),
      content: SizedBox(
        width: 390,
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Учётная запись помечена как временная. Перед продолжением задайте новый пароль.',
                style: TextStyle(color: colors.muted, fontSize: 13),
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _newPassword,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'Новый пароль'),
                validator: (value) {
                  final text = value ?? '';
                  if (text.length < 8) return 'Минимум 8 символов';
                  if (text == widget.currentPassword) {
                    return 'Новый пароль должен отличаться от временного';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _repeatPassword,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'Повтор пароля'),
                validator: (value) =>
                    value == _newPassword.text ? null : 'Пароли не совпадают',
                onFieldSubmitted: (_) => _submit(),
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(
                  _error!,
                  style: TextStyle(
                    color: colors.danger,
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy
              ? null
              : () async {
                  await context.read<AuthController>().logout();
                  if (context.mounted) Navigator.of(context).pop(false);
                },
          child: const Text('Выйти'),
        ),
        ElevatedButton(
          onPressed: _busy ? null : _submit,
          child: _busy
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Сменить пароль'),
        ),
      ],
    );
  }
}

class _TwoFactorDialog extends StatefulWidget {
  const _TwoFactorDialog();

  @override
  State<_TwoFactorDialog> createState() => _TwoFactorDialogState();
}

class _TwoFactorDialogState extends State<_TwoFactorDialog> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AlertDialog(
      backgroundColor: colors.surfaceElevated,
      surfaceTintColor: Colors.transparent,
      title: const Text('Двухфакторная аутентификация'),
      content: SizedBox(
        width: 360,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Введите код из приложения-аутентификатора.',
              style: TextStyle(color: colors.muted, fontSize: 13),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _controller,
              autofocus: true,
              keyboardType: TextInputType.number,
              maxLength: 8,
              decoration: const InputDecoration(
                labelText: 'Код двухфакторной аутентификации',
                counterText: '',
              ),
              onSubmitted: (_) =>
                  Navigator.of(context).pop(_controller.text.trim()),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        ElevatedButton(
          onPressed: () => Navigator.of(context).pop(_controller.text.trim()),
          child: const Text('Подтвердить'),
        ),
      ],
    );
  }
}

class _LoginHeader extends StatelessWidget {
  const _LoginHeader();

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(999),
            color: colors.surfaceMuted,
            border: Border.all(color: colors.border),
          ),
          child: Text(
            'CCTV Console',
            style: TextStyle(
              color: colors.text,
              fontWeight: FontWeight.w800,
              fontSize: 12,
            ),
          ),
        ),
        const SizedBox(height: 12),
        Text(
          'Вход в систему',
          style: Theme.of(context).textTheme.headlineLarge?.copyWith(
            color: colors.textStrong,
            fontWeight: FontWeight.w900,
            fontSize: 26,
            letterSpacing: -1.2,
          ),
        ),
      ],
    );
  }
}

class _ServerSettingsToggle extends StatelessWidget {
  const _ServerSettingsToggle({required this.open, required this.onTap});

  final bool open;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Row(
          children: [
            Icon(
              open ? Icons.expand_less_rounded : Icons.expand_more_rounded,
              color: colors.muted,
            ),
            const SizedBox(width: 6),
            Text(
              'Параметры сервера',
              style: TextStyle(
                color: colors.muted,
                fontSize: 14,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
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
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
        color: colors.danger.withValues(alpha: 0.1),
        border: Border.all(color: colors.border),
      ),
      child: Text(
        message,
        style: TextStyle(
          color: colors.danger,
          fontSize: 14,
          height: 1.35,
          fontWeight: FontWeight.w700,
          decoration: TextDecoration.none,
        ),
      ),
    );
  }
}
