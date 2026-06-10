import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../../core/theme/app_theme.dart';
import '../../shared/input/human_name.dart';
import '../../shared/widgets/glass_panel.dart';
import '../../shared/widgets/segmented_code_field.dart';
import '../auth/auth_controller.dart';

class ProfileSecurityPanel extends StatefulWidget {
  const ProfileSecurityPanel({super.key});

  @override
  State<ProfileSecurityPanel> createState() => _ProfileSecurityPanelState();
}

class _ProfileSecurityPanelState extends State<ProfileSecurityPanel> {
  final _lastName = TextEditingController();
  final _firstName = TextEditingController();
  final _middleName = TextEditingController();
  final _currentPassword = TextEditingController();
  final _newPassword = TextEditingController();
  final _repeatPassword = TextEditingController();
  bool _obscurePasswords = true;
  bool _busy = false;
  int? _loadedUserId;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final user = context.watch<AuthController>().user;
    if (user != null && user.userId != _loadedUserId) {
      _loadedUserId = user.userId;
      _lastName.text = user.lastName ?? '';
      _firstName.text = user.firstName ?? '';
      _middleName.text = user.middleName ?? '';
    }
  }

  @override
  void dispose() {
    _lastName.dispose();
    _firstName.dispose();
    _middleName.dispose();
    _currentPassword.dispose();
    _newPassword.dispose();
    _repeatPassword.dispose();
    super.dispose();
  }

  Future<void> _saveProfile() async {
    final fields = {
      'Фамилия': _lastName.text,
      'Имя': _firstName.text,
      'Отчество': _middleName.text,
    };
    for (final entry in fields.entries) {
      final error = validateOptionalHumanName(entry.key, entry.value);
      if (error != null) {
        _toast(error);
        return;
      }
    }
    await _run(() async {
      await context.read<AuthController>().updateProfile(
        lastName: normalizeHumanName(_lastName.text),
        firstName: normalizeHumanName(_firstName.text),
        middleName: normalizeHumanName(_middleName.text),
      );
      _toast('Профиль сохранён');
    });
  }

  Future<void> _changePassword() async {
    if (_newPassword.text.length < 8) {
      _toast('Новый пароль должен быть не короче 8 символов');
      return;
    }
    if (_newPassword.text != _repeatPassword.text) {
      _toast('Новый пароль и повтор не совпадают');
      return;
    }
    await _run(() async {
      final auth = context.read<AuthController>();
      final token = auth.accessToken;
      if (token == null) return;
      await auth.apiClient.changePassword(
        token,
        currentPassword: _currentPassword.text,
        newPassword: _newPassword.text,
      );
      _currentPassword.clear();
      _newPassword.clear();
      _repeatPassword.clear();
      _toast('Пароль изменён');
    });
  }

  Future<void> _setupTotp() async {
    await _run(() async {
      final auth = context.read<AuthController>();
      final token = auth.accessToken;
      if (token == null) return;
      final payload = await auth.apiClient.setupTotp(token);
      if (!mounted) return;
      final activated = await showDialog<bool>(
        context: context,
        barrierDismissible: false,
        builder: (_) => _TotpSetupDialog(
          secret: '${payload['secret'] ?? ''}',
          provisioningUri: '${payload['provisioning_uri'] ?? ''}',
          onActivate: (code) async {
            await auth.apiClient.activateTotp(token, code);
            await auth.reloadUser();
          },
        ),
      );
      if (activated == true) _toast('Двухфакторная аутентификация включена');
    });
  }

  Future<void> _disableTotp() async {
    final payload = await showDialog<_TotpDisablePayload>(
      context: context,
      barrierDismissible: false,
      builder: (_) => const _TotpDisableDialog(),
    );
    if (payload == null) return;
    await _run(() async {
      final auth = context.read<AuthController>();
      final token = auth.accessToken;
      if (token == null) return;
      await auth.apiClient.disableTotp(
        token,
        currentPassword: payload.currentPassword,
        code: payload.code,
      );
      await auth.reloadUser();
      _toast('Двухфакторная аутентификация отключена');
    });
  }

  Future<void> _run(Future<void> Function() action) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await action();
    } catch (error) {
      _toast('$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), behavior: SnackBarBehavior.floating),
    );
  }

  @override
  Widget build(BuildContext context) {
    final user = context.watch<AuthController>().user;
    final colors = context.colors;
    if (user == null) return const SizedBox.shrink();

    return GlassPanel(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _SectionTitle(
            title: 'Профиль и безопасность',
            subtitle: '',
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              _StatusPill(label: 'Логин', value: user.login),
              _StatusPill(label: 'Роль', value: user.roleLabel),
              _StatusPill(
                label: '2FA',
                value: user.totpEnabled ? 'включена' : 'выключена',
                color: user.totpEnabled ? colors.success : colors.warning,
              ),
            ],
          ),
          const SizedBox(height: 16),
          LayoutBuilder(
            builder: (context, constraints) {
              final narrow = constraints.maxWidth < 760;
              final profile = _ProfileForm(
                lastName: _lastName,
                firstName: _firstName,
                middleName: _middleName,
                busy: _busy,
                onSave: _saveProfile,
              );
              final security = _PasswordAndTotpForm(
                currentPassword: _currentPassword,
                newPassword: _newPassword,
                repeatPassword: _repeatPassword,
                obscure: _obscurePasswords,
                busy: _busy,
                totpEnabled: user.totpEnabled,
                onToggleObscure: () =>
                    setState(() => _obscurePasswords = !_obscurePasswords),
                onChangePassword: _changePassword,
                onSetupTotp: _setupTotp,
                onDisableTotp: _disableTotp,
              );
              if (narrow) {
                return Column(
                  children: [profile, const SizedBox(height: 14), security],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: profile),
                  const SizedBox(width: 14),
                  Expanded(child: security),
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

class _ProfileForm extends StatelessWidget {
  const _ProfileForm({
    required this.lastName,
    required this.firstName,
    required this.middleName,
    required this.busy,
    required this.onSave,
  });

  final TextEditingController lastName;
  final TextEditingController firstName;
  final TextEditingController middleName;
  final bool busy;
  final VoidCallback onSave;

  @override
  Widget build(BuildContext context) {
    return _InnerCard(
      title: 'Данные профиля',
      child: Column(
        children: [
          TextField(
            controller: lastName,
            inputFormatters: humanNameInputFormatters(),
            textCapitalization: TextCapitalization.words,
            textInputAction: TextInputAction.next,
            decoration: const InputDecoration(labelText: 'Фамилия'),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: firstName,
            inputFormatters: humanNameInputFormatters(),
            textCapitalization: TextCapitalization.words,
            textInputAction: TextInputAction.next,
            decoration: const InputDecoration(labelText: 'Имя'),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: middleName,
            inputFormatters: humanNameInputFormatters(),
            textCapitalization: TextCapitalization.words,
            textInputAction: TextInputAction.done,
            decoration: const InputDecoration(labelText: 'Отчество'),
          ),
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerRight,
            child: ElevatedButton.icon(
              onPressed: busy ? null : onSave,
              icon: const Icon(Icons.save_rounded, size: 18),
              label: const Text('Сохранить профиль'),
            ),
          ),
        ],
      ),
    );
  }
}

class _PasswordAndTotpForm extends StatelessWidget {
  const _PasswordAndTotpForm({
    required this.currentPassword,
    required this.newPassword,
    required this.repeatPassword,
    required this.obscure,
    required this.busy,
    required this.totpEnabled,
    required this.onToggleObscure,
    required this.onChangePassword,
    required this.onSetupTotp,
    required this.onDisableTotp,
  });

  final TextEditingController currentPassword;
  final TextEditingController newPassword;
  final TextEditingController repeatPassword;
  final bool obscure;
  final bool busy;
  final bool totpEnabled;
  final VoidCallback onToggleObscure;
  final VoidCallback onChangePassword;
  final VoidCallback onSetupTotp;
  final VoidCallback onDisableTotp;

  @override
  Widget build(BuildContext context) {
    return _InnerCard(
      title: 'Пароль и 2FA',
      child: Column(
        children: [
          TextField(
            controller: currentPassword,
            obscureText: obscure,
            decoration: InputDecoration(
              labelText: 'Текущий пароль',
              suffixIcon: IconButton(
                onPressed: onToggleObscure,
                icon: Icon(
                  obscure
                      ? Icons.visibility_rounded
                      : Icons.visibility_off_rounded,
                ),
              ),
            ),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: newPassword,
            obscureText: obscure,
            decoration: const InputDecoration(labelText: 'Новый пароль'),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: repeatPassword,
            obscureText: obscure,
            decoration: const InputDecoration(
              labelText: 'Повтор нового пароля',
            ),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            alignment: WrapAlignment.end,
            children: [
              OutlinedButton.icon(
                onPressed: busy ? null : onChangePassword,
                icon: const Icon(Icons.lock_reset_rounded, size: 18),
                label: const Text('Сменить пароль'),
              ),
              ElevatedButton.icon(
                onPressed: busy
                    ? null
                    : (totpEnabled ? onDisableTotp : onSetupTotp),
                icon: Icon(
                  totpEnabled
                      ? Icons.phonelink_erase_rounded
                      : Icons.qr_code_2_rounded,
                  size: 18,
                ),
                label: Text(totpEnabled ? 'Отключить 2FA' : 'Настроить 2FA'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _TotpDisablePayload {
  const _TotpDisablePayload({
    required this.currentPassword,
    required this.code,
  });

  final String currentPassword;
  final String code;
}

class _TotpDisableDialog extends StatefulWidget {
  const _TotpDisableDialog();

  @override
  State<_TotpDisableDialog> createState() => _TotpDisableDialogState();
}

class _TotpDisableDialogState extends State<_TotpDisableDialog> {
  final _password = TextEditingController();
  final _code = TextEditingController();

  @override
  void initState() {
    super.initState();
    _password.addListener(_refresh);
    _code.addListener(_refresh);
  }

  @override
  void dispose() {
    _password.removeListener(_refresh);
    _code.removeListener(_refresh);
    _password.dispose();
    _code.dispose();
    super.dispose();
  }

  bool get _canSubmit =>
      _password.text.trim().isNotEmpty && _code.text.trim().length == 6;

  void _refresh() => setState(() {});

  void _submit() {
    if (!_canSubmit) return;
    Navigator.of(context).pop(
      _TotpDisablePayload(
        currentPassword: _password.text,
        code: _code.text.trim(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AlertDialog(
      backgroundColor: colors.surfaceElevated,
      surfaceTintColor: Colors.transparent,
      title: const Text('Отключение 2FA'),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _password,
              obscureText: true,
              autofocus: true,
              textInputAction: TextInputAction.next,
              decoration: const InputDecoration(labelText: 'Текущий пароль'),
            ),
            const SizedBox(height: 12),
            SegmentedCodeField(
              controller: _code,
              length: 6,
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              onCompleted: (_) => _submit(),
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
          onPressed: _canSubmit ? _submit : null,
          child: const Text('Отключить'),
        ),
      ],
    );
  }
}

class _TotpSetupDialog extends StatefulWidget {
  const _TotpSetupDialog({
    required this.secret,
    required this.provisioningUri,
    required this.onActivate,
  });

  final String secret;
  final String provisioningUri;
  final Future<void> Function(String code) onActivate;

  @override
  State<_TotpSetupDialog> createState() => _TotpSetupDialogState();
}

class _TotpSetupDialogState extends State<_TotpSetupDialog> {
  final _code = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _code.addListener(_refresh);
  }

  @override
  void dispose() {
    _code.removeListener(_refresh);
    _code.dispose();
    super.dispose();
  }

  void _refresh() => setState(() {});

  Future<void> _activate() async {
    if (_code.text.trim().length != 6) {
      setState(() => _error = 'Введите 6 цифр из приложения-аутентификатора');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.onActivate(_code.text.trim());
      if (mounted) Navigator.of(context).pop(true);
    } catch (error) {
      setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AlertDialog(
      backgroundColor: colors.surfaceElevated,
      surfaceTintColor: Colors.transparent,
      title: const Text('Настройка двухфакторной аутентификации'),
      content: SizedBox(
        width: 430,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Center(
                child: Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(18),
                  ),
                  child: QrImageView(
                    data: widget.provisioningUri,
                    size: 210,
                    backgroundColor: Colors.white,
                  ),
                ),
              ),
              const SizedBox(height: 14),
              Text(
                'Если QR не сканируется, добавьте ключ вручную:',
                style: TextStyle(color: colors.muted, fontSize: 13),
              ),
              const SizedBox(height: 8),
              TextFormField(
                initialValue: widget.secret,
                readOnly: true,
                decoration: InputDecoration(
                  labelText: 'Секретный ключ',
                  suffixIcon: IconButton(
                    tooltip: 'Скопировать ключ',
                    onPressed: () {
                      Clipboard.setData(ClipboardData(text: widget.secret));
                    },
                    icon: const Icon(Icons.copy_rounded),
                  ),
                ),
              ),
              const SizedBox(height: 14),
              SegmentedCodeField(
                controller: _code,
                length: 6,
                autofocus: true,
                keyboardType: TextInputType.number,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                onCompleted: (_) => _activate(),
              ),
              if (_error != null) ...[
                const SizedBox(height: 10),
                Text(
                  _error!,
                  style: TextStyle(
                    color: colors.danger,
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
          onPressed: _busy ? null : () => Navigator.of(context).pop(false),
          child: const Text('Отмена'),
        ),
        ElevatedButton(
          onPressed: _busy || _code.text.trim().length != 6 ? null : _activate,
          child: _busy
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Включить'),
        ),
      ],
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
          style: Theme.of(context).textTheme.titleLarge?.copyWith(
            color: colors.textStrong,
            fontWeight: FontWeight.w900,
          ),
        ),
      ],
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({required this.label, required this.value, this.color});

  final String label;
  final String value;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final effectiveColor = color ?? colors.primaryAccent;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: effectiveColor.withValues(alpha: 0.12),
        border: Border.all(color: effectiveColor.withValues(alpha: 0.3)),
      ),
      child: Text(
        '$label: $value',
        style: TextStyle(
          color: colors.textStrong,
          fontSize: 12,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class _InnerCard extends StatelessWidget {
  const _InnerCard({required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: TextStyle(
              color: colors.textStrong,
              fontSize: 15,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 12),
          child,
        ],
      ),
    );
  }
}
