import 'package:flex_color_picker/flex_color_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_theme.dart';
import '../../core/theme/theme_controller.dart';
import '../../shared/widgets/glass_panel.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _apiUrlController;

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
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final settings = context.watch<ThemeController>();
    final colors = context.colors;

    return CustomScrollView(
      slivers: [
        SliverToBoxAdapter(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Настройки',
                style: Theme.of(context).textTheme.displaySmall?.copyWith(
                  color: colors.textStrong,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                'Кастомизация клиента, адрес backend и плотность Live.',
                style: TextStyle(color: colors.muted),
              ),
              const SizedBox(height: 18),
            ],
          ),
        ),
        SliverList.list(
          children: [
            GlassPanel(
              padding: const EdgeInsets.all(22),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _SectionTitle(
                    title: 'Подключение',
                    subtitle:
                        'Адрес backend, к которому подключается нативное приложение.',
                  ),
                  const SizedBox(height: 16),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _apiUrlController,
                          decoration: const InputDecoration(
                            labelText: 'Backend URL',
                            hintText: 'http://127.0.0.1:8000',
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      ElevatedButton(
                        onPressed: () =>
                            settings.setApiBaseUrl(_apiUrlController.text),
                        child: const Text('Сохранить'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            GlassPanel(
              padding: const EdgeInsets.all(22),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _SectionTitle(
                    title: 'Оформление',
                    subtitle:
                        'Тема повторяет веб-консоль, но цвета можно менять без правки кода.',
                  ),
                  const SizedBox(height: 18),
                  Wrap(
                    spacing: 12,
                    runSpacing: 12,
                    children: [
                      _ChoiceChipButton(
                        label: 'Системная',
                        selected: settings.themeMode == CctvThemeMode.system,
                        onTap: () =>
                            settings.setThemeMode(CctvThemeMode.system),
                      ),
                      _ChoiceChipButton(
                        label: 'Тёмная',
                        selected: settings.themeMode == CctvThemeMode.dark,
                        onTap: () => settings.setThemeMode(CctvThemeMode.dark),
                      ),
                      _ChoiceChipButton(
                        label: 'Светлая',
                        selected: settings.themeMode == CctvThemeMode.light,
                        onTap: () => settings.setThemeMode(CctvThemeMode.light),
                      ),
                    ],
                  ),
                  const SizedBox(height: 24),
                  LayoutBuilder(
                    builder: (context, constraints) {
                      final compact = constraints.maxWidth < 780;
                      final pickers = [
                        _ColorEditor(
                          title: 'Основной акцент',
                          color: settings.primaryAccent,
                          onChanged: settings.setPrimaryAccent,
                        ),
                        _ColorEditor(
                          title: 'Второй акцент',
                          color: settings.secondaryAccent,
                          onChanged: settings.setSecondaryAccent,
                        ),
                      ];
                      return compact
                          ? Column(
                              children: pickers
                                  .map(
                                    (picker) => Padding(
                                      padding: const EdgeInsets.only(
                                        bottom: 16,
                                      ),
                                      child: picker,
                                    ),
                                  )
                                  .toList(),
                            )
                          : Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Expanded(child: pickers[0]),
                                const SizedBox(width: 16),
                                Expanded(child: pickers[1]),
                              ],
                            );
                    },
                  ),
                  const SizedBox(height: 8),
                  OutlinedButton.icon(
                    onPressed: settings.resetAppearance,
                    icon: const Icon(Icons.restart_alt_rounded),
                    label: const Text('Сбросить оформление'),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            GlassPanel(
              padding: const EdgeInsets.all(22),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _SectionTitle(
                    title: 'Live',
                    subtitle:
                        'Плотность сетки камер. На демонстрационном стенде удобно переключаться.',
                  ),
                  const SizedBox(height: 16),
                  Wrap(
                    spacing: 12,
                    runSpacing: 12,
                    children: [
                      _ChoiceChipButton(
                        label: 'Компактно',
                        selected: settings.liveDensity == LiveDensity.compact,
                        onTap: () =>
                            settings.setLiveDensity(LiveDensity.compact),
                      ),
                      _ChoiceChipButton(
                        label: 'Комфортно',
                        selected:
                            settings.liveDensity == LiveDensity.comfortable,
                        onTap: () =>
                            settings.setLiveDensity(LiveDensity.comfortable),
                      ),
                      _ChoiceChipButton(
                        label: 'Фокус',
                        selected: settings.liveDensity == LiveDensity.focus,
                        onTap: () => settings.setLiveDensity(LiveDensity.focus),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),
          ],
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
        const SizedBox(height: 4),
        Text(subtitle, style: TextStyle(color: colors.muted)),
      ],
    );
  }
}

class _ChoiceChipButton extends StatelessWidget {
  const _ChoiceChipButton({
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
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(999),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 11),
            child: Text(
              label,
              style: TextStyle(
                color: selected ? const Color(0xFF07111F) : colors.muted,
                fontWeight: FontWeight.w900,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ColorEditor extends StatelessWidget {
  const _ColorEditor({
    required this.title,
    required this.color,
    required this.onChanged,
  });

  final String title;
  final Color color;
  final ValueChanged<Color> onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: color,
                  shape: BoxShape.circle,
                  border: Border.all(color: colors.borderStrong),
                  boxShadow: [
                    BoxShadow(
                      color: color.withValues(alpha: 0.28),
                      blurRadius: 18,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  title,
                  style: TextStyle(
                    color: colors.textStrong,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
              Text(
                ThemeController.colorToHex(color),
                style: TextStyle(
                  color: colors.muted,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          ColorPicker(
            color: color,
            onColorChanged: onChanged,
            pickersEnabled: const {
              ColorPickerType.primary: true,
              ColorPickerType.accent: true,
              ColorPickerType.wheel: true,
            },
            enableShadesSelection: false,
            showColorCode: true,
            colorCodeHasColor: true,
            copyPasteBehavior: const ColorPickerCopyPasteBehavior(
              copyButton: true,
              pasteButton: true,
              longPressMenu: true,
            ),
          ),
        ],
      ),
    );
  }
}
