import 'package:flex_color_picker/flex_color_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_theme.dart';
import '../../core/theme/theme_controller.dart';
import '../../shared/widgets/glass_panel.dart';
import '../auth/auth_controller.dart';

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
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  color: colors.textStrong,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                'Backend, оформление, верхнее меню и плотность Live.',
                style: TextStyle(color: colors.muted, fontSize: 13),
              ),
              const SizedBox(height: 16),
            ],
          ),
        ),
        SliverList.list(
          children: [
            GlassPanel(
              padding: const EdgeInsets.all(18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const _SectionTitle(
                    title: 'Подключение',
                    subtitle: 'Адрес backend для нативного клиента.',
                  ),
                  const SizedBox(height: 14),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _apiUrlController,
                          decoration: const InputDecoration(
                            labelText: 'Backend URL',
                            hintText: 'http://127.0.0.1:8001',
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),
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
            const SizedBox(height: 14),
            GlassPanel(
              padding: const EdgeInsets.all(18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const _SectionTitle(
                    title: 'Оформление',
                    subtitle: 'Тема и акцентные цвета интерфейса.',
                  ),
                  const SizedBox(height: 14),
                  Wrap(
                    spacing: 10,
                    runSpacing: 10,
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
                  const SizedBox(height: 18),
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
                              children: [
                                pickers[0],
                                const SizedBox(height: 14),
                                pickers[1],
                              ],
                            )
                          : Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Expanded(child: pickers[0]),
                                const SizedBox(width: 14),
                                Expanded(child: pickers[1]),
                              ],
                            );
                    },
                  ),
                  const SizedBox(height: 10),
                  OutlinedButton.icon(
                    onPressed: settings.resetAppearance,
                    icon: const Icon(Icons.restart_alt_rounded, size: 18),
                    label: const Text('Сбросить оформление'),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 14),
            const _NavigationSettings(),
            const SizedBox(height: 14),
            GlassPanel(
              padding: const EdgeInsets.all(18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const _SectionTitle(
                    title: 'Live',
                    subtitle: 'Плотность сетки камер на экране Live.',
                  ),
                  const SizedBox(height: 14),
                  Wrap(
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      _ChoiceChipButton(
                        label: 'Компактно',
                        selected: settings.liveDensity == LiveDensity.compact,
                        onTap: () =>
                            settings.setLiveDensity(LiveDensity.compact),
                      ),
                      _ChoiceChipButton(
                        label: 'Стандартно',
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

class _NavigationSettings extends StatelessWidget {
  const _NavigationSettings();

  static const _allOptions = [
    _NavOption('/live', 'Live'),
    _NavOption('/recordings', 'Записи'),
    _NavOption('/reviews', 'Ревью', reviewOnly: true),
    _NavOption('/reports', 'Отчёты', reviewOnly: true),
    _NavOption('/cameras', 'Камеры', adminOnly: true),
    _NavOption('/groups', 'Группы', adminOnly: true),
    _NavOption('/persons', 'Персоны', adminOnly: true),
    _NavOption('/processors', 'Processor', adminOnly: true),
    _NavOption('/users', 'Пользователи', adminOnly: true),
    _NavOption('/api-keys', 'API ключи', adminOnly: true),
    _NavOption('/settings', 'Настройки'),
    _NavOption('/help', 'Справка'),
  ];

  @override
  Widget build(BuildContext context) {
    final settings = context.watch<ThemeController>();
    final user = context.watch<AuthController>().user;
    final colors = context.colors;
    final allowed = _allOptions.where((option) {
      if (option.adminOnly) return user?.isAdmin ?? false;
      if (option.reviewOnly) return user?.canReview ?? false;
      return true;
    }).toList();
    final allowedRoutes = allowed.map((option) => option.route).toSet();
    final selectedRoutes = settings.primaryNav
        .where(allowedRoutes.contains)
        .take(ThemeController.maxPrimaryNavItems)
        .toList();
    final effectiveRoutes = selectedRoutes.isEmpty
        ? ThemeController.defaultPrimaryNav
              .where(allowedRoutes.contains)
              .toList()
        : selectedRoutes;
    final selected = effectiveRoutes
        .map((route) => allowed.firstWhere((option) => option.route == route))
        .toList();
    final available = allowed
        .where((option) => !effectiveRoutes.contains(option.route))
        .toList();

    return GlassPanel(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _SectionTitle(
            title: 'Верхнее меню',
            subtitle:
                'До пяти вкладок в шапке. Остальные разделы остаются в меню.',
          ),
          const SizedBox(height: 14),
          Column(
            children: [
              for (var index = 0; index < selected.length; index++)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: _NavOrderRow(
                    index: index,
                    option: selected[index],
                    canMoveUp: index > 0,
                    canMoveDown: index < selected.length - 1,
                    canRemove: selected.length > 1,
                    onMoveUp: () => settings.setPrimaryNav(
                      _move(effectiveRoutes, index, index - 1),
                    ),
                    onMoveDown: () => settings.setPrimaryNav(
                      _move(effectiveRoutes, index, index + 1),
                    ),
                    onRemove: () => settings.setPrimaryNav(
                      effectiveRoutes
                          .where((route) => route != selected[index].route)
                          .toList(),
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            'Добавить в верхнюю панель',
            style: TextStyle(
              color: colors.textStrong,
              fontSize: 13,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final option in available)
                OutlinedButton.icon(
                  onPressed:
                      effectiveRoutes.length >=
                          ThemeController.maxPrimaryNavItems
                      ? null
                      : () => settings.setPrimaryNav([
                          ...effectiveRoutes,
                          option.route,
                        ]),
                  icon: const Icon(Icons.add_rounded, size: 18),
                  label: Text(option.label),
                ),
            ],
          ),
          if (effectiveRoutes.length >= ThemeController.maxPrimaryNavItems) ...[
            const SizedBox(height: 8),
            Text(
              'Достигнут лимит главных вкладок. Уберите одну, чтобы добавить новую.',
              style: TextStyle(color: colors.muted, fontSize: 12),
            ),
          ],
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: settings.resetPrimaryNav,
            icon: const Icon(Icons.restart_alt_rounded, size: 18),
            label: const Text('Сбросить меню'),
          ),
        ],
      ),
    );
  }

  static List<String> _move(List<String> routes, int from, int to) {
    final next = List<String>.from(routes);
    final item = next.removeAt(from);
    next.insert(to, item);
    return next;
  }
}

class _NavOrderRow extends StatelessWidget {
  const _NavOrderRow({
    required this.index,
    required this.option,
    required this.canMoveUp,
    required this.canMoveDown,
    required this.canRemove,
    required this.onMoveUp,
    required this.onMoveDown,
    required this.onRemove,
  });

  final int index;
  final _NavOption option;
  final bool canMoveUp;
  final bool canMoveDown;
  final bool canRemove;
  final VoidCallback onMoveUp;
  final VoidCallback onMoveDown;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Row(
        children: [
          Container(
            width: 28,
            height: 28,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(999),
              color: colors.primaryAccent.withValues(alpha: 0.14),
            ),
            child: Text(
              '${index + 1}',
              style: TextStyle(
                color: colors.primaryAccent,
                fontSize: 12,
                fontWeight: FontWeight.w900,
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              option.label,
              style: TextStyle(
                color: colors.textStrong,
                fontSize: 14,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
          IconButton(
            tooltip: 'Выше',
            onPressed: canMoveUp ? onMoveUp : null,
            icon: const Icon(Icons.keyboard_arrow_up_rounded, size: 20),
          ),
          IconButton(
            tooltip: 'Ниже',
            onPressed: canMoveDown ? onMoveDown : null,
            icon: const Icon(Icons.keyboard_arrow_down_rounded, size: 20),
          ),
          IconButton(
            tooltip: 'Убрать',
            onPressed: canRemove ? onRemove : null,
            icon: Icon(
              Icons.close_rounded,
              size: 19,
              color: canRemove ? colors.danger : colors.muted,
            ),
          ),
        ],
      ),
    );
  }
}

class _NavOption {
  const _NavOption(
    this.route,
    this.label, {
    this.adminOnly = false,
    this.reviewOnly = false,
  });

  final String route;
  final String label;
  final bool adminOnly;
  final bool reviewOnly;
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
        const SizedBox(height: 3),
        Text(subtitle, style: TextStyle(color: colors.muted, fontSize: 13)),
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
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
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
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: color,
                  shape: BoxShape.circle,
                  border: Border.all(color: colors.borderStrong),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  title,
                  style: TextStyle(
                    color: colors.textStrong,
                    fontSize: 14,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
              Text(
                ThemeController.colorToHex(color),
                style: TextStyle(
                  color: colors.muted,
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
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
