import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

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
  final _loginController = TextEditingController();
  final _passwordController = TextEditingController();
  final _totpController = TextEditingController();
  bool _obscurePassword = true;
  bool _serverSettingsOpen = false;

  @override
  void initState() {
    super.initState();
    final settings = context.read<ThemeController>();
    _apiUrlController = TextEditingController(text: settings.apiBaseUrl);
  }

  @override
  void dispose() {
    _apiUrlController.dispose();
    _loginController.dispose();
    _passwordController.dispose();
    _totpController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    final settings = context.read<ThemeController>();
    final auth = context.read<AuthController>();

    await settings.setApiBaseUrl(_apiUrlController.text);
    if (!mounted) return;

    try {
      await auth.login(
        login: _loginController.text.trim(),
        password: _passwordController.text,
        totpCode: _totpController.text.trim(),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('$error')));
    }
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
              padding: const EdgeInsets.all(32),
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
                      validator: (value) {
                        if ((value ?? '').trim().isEmpty) return 'Укажи логин';
                        return null;
                      },
                    ),
                    const SizedBox(height: 14),
                    TextFormField(
                      controller: _passwordController,
                      obscureText: _obscurePassword,
                      decoration: InputDecoration(
                        labelText: 'Пароль',
                        suffixIcon: IconButton(
                          onPressed: () {
                            setState(
                              () => _obscurePassword = !_obscurePassword,
                            );
                          },
                          icon: Icon(
                            _obscurePassword
                                ? Icons.visibility_rounded
                                : Icons.visibility_off_rounded,
                          ),
                        ),
                      ),
                      onFieldSubmitted: (_) => _submit(),
                      validator: (value) {
                        if ((value ?? '').isEmpty) return 'Укажи пароль';
                        return null;
                      },
                    ),
                    const SizedBox(height: 14),
                    TextFormField(
                      controller: _totpController,
                      decoration: const InputDecoration(
                        labelText: 'TOTP код',
                        hintText: 'Если включён',
                      ),
                      keyboardType: TextInputType.number,
                      textInputAction: TextInputAction.done,
                      onFieldSubmitted: (_) => _submit(),
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
                      onTap: () {
                        setState(
                          () => _serverSettingsOpen = !_serverSettingsOpen,
                        );
                      },
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
                                  hintText: 'http://127.0.0.1:8000',
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
