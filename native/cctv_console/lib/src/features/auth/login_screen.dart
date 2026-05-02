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
  final _loginController = TextEditingController(text: 'admin');
  final _passwordController = TextEditingController();
  final _totpController = TextEditingController();
  bool _obscurePassword = true;

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
    final colors = context.colors;
    final auth = context.watch<AuthController>();
    final width = MediaQuery.sizeOf(context).width;
    final compact = width < 880;

    return AppBackdrop(
      child: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1120),
            child: compact
                ? Column(
                    children: [
                      _HeroPanel(colors: colors),
                      const SizedBox(height: 16),
                      _LoginPanel(
                        formKey: _formKey,
                        apiUrlController: _apiUrlController,
                        loginController: _loginController,
                        passwordController: _passwordController,
                        totpController: _totpController,
                        obscurePassword: _obscurePassword,
                        onTogglePassword: () {
                          setState(() => _obscurePassword = !_obscurePassword);
                        },
                        onSubmit: _submit,
                        isLoading: auth.isLoading,
                      ),
                    ],
                  )
                : Row(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Expanded(flex: 6, child: _HeroPanel(colors: colors)),
                      const SizedBox(width: 20),
                      Expanded(
                        flex: 4,
                        child: _LoginPanel(
                          formKey: _formKey,
                          apiUrlController: _apiUrlController,
                          loginController: _loginController,
                          passwordController: _passwordController,
                          totpController: _totpController,
                          obscurePassword: _obscurePassword,
                          onTogglePassword: () {
                            setState(
                              () => _obscurePassword = !_obscurePassword,
                            );
                          },
                          onSubmit: _submit,
                          isLoading: auth.isLoading,
                        ),
                      ),
                    ],
                  ),
          ),
        ),
      ),
    );
  }
}

class _HeroPanel extends StatelessWidget {
  const _HeroPanel({required this.colors});

  final AppColors colors;

  @override
  Widget build(BuildContext context) {
    return GlassPanel(
      padding: const EdgeInsets.all(32),
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 520),
        child: Stack(
          children: [
            Positioned(
              right: -70,
              top: -90,
              child: _GlowOrb(color: colors.primaryAccent, size: 260),
            ),
            Positioned(
              left: -80,
              bottom: -90,
              child: _GlowOrb(color: colors.secondaryAccent, size: 230),
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Row(
                  children: [
                    const _BrandMark(),
                    const SizedBox(width: 16),
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'CCTV Console',
                          style: Theme.of(context).textTheme.headlineSmall
                              ?.copyWith(
                                fontWeight: FontWeight.w800,
                                color: colors.textStrong,
                              ),
                        ),
                        Text(
                          'Нативный клиент для backend и Processor',
                          style: TextStyle(color: colors.muted),
                        ),
                      ],
                    ),
                  ],
                ),
                const SizedBox(height: 80),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Единое управление системой видеонаблюдения',
                      style: Theme.of(context).textTheme.displaySmall?.copyWith(
                        fontWeight: FontWeight.w800,
                        letterSpacing: -1.2,
                        color: colors.textStrong,
                      ),
                    ),
                    const SizedBox(height: 18),
                    Text(
                      'Дизайн повторяет текущий веб, но вынесен в полноценную тему: '
                      'цвета, режим оформления и плотность Live можно менять без переписывания экранов.',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: colors.muted,
                        height: 1.45,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 36),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: const [
                    _FeaturePill(label: 'Windows'),
                    _FeaturePill(label: 'Android'),
                    _FeaturePill(label: 'ONVIF'),
                    _FeaturePill(label: 'Live'),
                    _FeaturePill(label: 'Custom theme'),
                  ],
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _LoginPanel extends StatelessWidget {
  const _LoginPanel({
    required this.formKey,
    required this.apiUrlController,
    required this.loginController,
    required this.passwordController,
    required this.totpController,
    required this.obscurePassword,
    required this.onTogglePassword,
    required this.onSubmit,
    required this.isLoading,
  });

  final GlobalKey<FormState> formKey;
  final TextEditingController apiUrlController;
  final TextEditingController loginController;
  final TextEditingController passwordController;
  final TextEditingController totpController;
  final bool obscurePassword;
  final VoidCallback onTogglePassword;
  final Future<void> Function() onSubmit;
  final bool isLoading;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;

    return GlassPanel(
      padding: const EdgeInsets.all(28),
      child: Form(
        key: formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Вход',
              style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                fontWeight: FontWeight.w800,
                color: colors.textStrong,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              'Укажи адрес backend и войди под пользователем системы.',
              style: TextStyle(color: colors.muted),
            ),
            const SizedBox(height: 28),
            TextFormField(
              controller: apiUrlController,
              decoration: const InputDecoration(
                labelText: 'Backend URL',
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
            const SizedBox(height: 14),
            TextFormField(
              controller: loginController,
              decoration: const InputDecoration(labelText: 'Логин'),
              textInputAction: TextInputAction.next,
              validator: (value) {
                if ((value ?? '').trim().isEmpty) return 'Укажи логин';
                return null;
              },
            ),
            const SizedBox(height: 14),
            TextFormField(
              controller: passwordController,
              obscureText: obscurePassword,
              decoration: InputDecoration(
                labelText: 'Пароль',
                suffixIcon: IconButton(
                  onPressed: onTogglePassword,
                  icon: Icon(
                    obscurePassword ? Icons.visibility : Icons.visibility_off,
                  ),
                ),
              ),
              onFieldSubmitted: (_) => onSubmit(),
              validator: (value) {
                if ((value ?? '').isEmpty) return 'Укажи пароль';
                return null;
              },
            ),
            const SizedBox(height: 14),
            TextFormField(
              controller: totpController,
              decoration: const InputDecoration(
                labelText: 'TOTP код',
                hintText: 'Если включён',
              ),
              keyboardType: TextInputType.number,
              onFieldSubmitted: (_) => onSubmit(),
            ),
            const SizedBox(height: 24),
            ElevatedButton(
              onPressed: isLoading ? null : onSubmit,
              child: isLoading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Войти'),
            ),
          ],
        ),
      ),
    );
  }
}

class _BrandMark extends StatelessWidget {
  const _BrandMark();

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      width: 58,
      height: 58,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(19),
        gradient: LinearGradient(
          colors: [
            colors.primaryAccent.withValues(alpha: 0.16),
            colors.secondaryAccent.withValues(alpha: 0.22),
          ],
        ),
        border: Border.all(color: colors.borderStrong),
      ),
      child: Text(
        'CCTV',
        style: TextStyle(
          color: colors.textStrong,
          fontWeight: FontWeight.w900,
          letterSpacing: 1.8,
          fontSize: 12,
        ),
      ),
    );
  }
}

class _FeaturePill extends StatelessWidget {
  const _FeaturePill({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 9),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Text(
        label,
        style: TextStyle(color: colors.textStrong, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class _GlowOrb extends StatelessWidget {
  const _GlowOrb({required this.color, required this.size});

  final Color color;
  final double size;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: color.withValues(alpha: 0.14),
        boxShadow: [
          BoxShadow(
            color: color.withValues(alpha: 0.24),
            blurRadius: 80,
            spreadRadius: 10,
          ),
        ],
      ),
    );
  }
}
