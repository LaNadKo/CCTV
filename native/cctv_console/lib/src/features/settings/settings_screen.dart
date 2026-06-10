// ignore_for_file: use_build_context_synchronously

import 'package:flex_color_picker/flex_color_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/profiles/connection_profiles.dart';
import '../../core/server/server_features_controller.dart';
import '../../core/theme/app_theme.dart';
import '../../core/theme/theme_controller.dart';
import '../../shared/widgets/glass_panel.dart';
import '../../shared/widgets/motion.dart';
import '../../shared/widgets/page_header.dart';
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

  Future<void> _saveConnection() async {
    final profiles = context.read<ConnectionProfilesController>();
    final active = profiles.activeProfile;
    final profile = await profiles.saveProfile(
      id: active?.id,
      name: active?.name ?? 'CCTV Server',
      baseUrl: _apiUrlController.text,
      login: active?.login,
      makeActive: true,
    );
    await context.read<ThemeController>().setApiBaseUrl(profile.baseUrl);
  }

  @override
  void dispose() {
    _apiUrlController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final settings = context.watch<ThemeController>();

    return CustomScrollView(
      slivers: [
        SliverToBoxAdapter(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const PageHeader(title: 'Настройки', icon: Icons.tune_rounded),
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
                  const _SectionTitle(title: 'Подключение'),
                  const SizedBox(height: 14),
                  LayoutBuilder(
                    builder: (context, constraints) {
                      final compact = constraints.maxWidth < 560;
                      final field = TextField(
                        controller: _apiUrlController,
                        decoration: const InputDecoration(
                          labelText: 'Адрес сервера',
                          hintText: 'http://127.0.0.1:8001',
                        ),
                      );
                      final button = ElevatedButton(
                        onPressed: _saveConnection,
                        child: const Text('Сохранить'),
                      );
                      if (compact) {
                        return Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            field,
                            const SizedBox(height: 10),
                            Align(
                              alignment: Alignment.centerLeft,
                              child: button,
                            ),
                          ],
                        );
                      }
                      return Row(
                        children: [
                          Expanded(child: field),
                          const SizedBox(width: 10),
                          button,
                        ],
                      );
                    },
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
                  const _SectionTitle(title: 'Оформление'),
                  const SizedBox(height: 14),
                  _PalettePresets(
                    onSelect: settings.setAccentPreset,
                    selectedPrimary: settings.primaryAccent,
                    selectedSecondary: settings.secondaryAccent,
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
                  const _SectionTitle(title: 'Эфир'),
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
                  const SizedBox(height: 14),
                  Wrap(
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      _ChoiceChipButton(
                        label: 'Сетка авто',
                        selected: settings.liveGridColumns == 0,
                        onTap: () => settings.setLiveGridColumns(0),
                      ),
                      _ChoiceChipButton(
                        label: '1 x 1',
                        selected: settings.liveGridColumns == 1,
                        onTap: () => settings.setLiveGridColumns(1),
                      ),
                      _ChoiceChipButton(
                        label: '2 x 2',
                        selected: settings.liveGridColumns == 2,
                        onTap: () => settings.setLiveGridColumns(2),
                      ),
                      _ChoiceChipButton(
                        label: '3 x 3',
                        selected: settings.liveGridColumns == 3,
                        onTap: () => settings.setLiveGridColumns(3),
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
    _NavOption('/live', 'Эфир'),
    _NavOption('/recordings', 'Записи'),
    _NavOption('/reviews', 'Ревью', reviewOnly: true),
    _NavOption('/reports', 'Отчёты', reviewOnly: true),
    _NavOption('/cameras', 'Камеры', adminOnly: true),
    _NavOption('/groups', 'Группы'),
    _NavOption('/persons', 'Персоны', adminOnly: true),
    _NavOption('/processors', 'Процессор', adminOnly: true),
    _NavOption(
      '/setup',
      'Настройка',
      adminOnly: true,
      setupOnly: true,
    ),
    _NavOption('/users', 'Пользователи', adminOnly: true),
    _NavOption('/api-keys', 'API ключи', adminOnly: true),
    _NavOption('/profile', 'Профиль'),
    _NavOption('/settings', 'Настройки'),
    _NavOption('/help', 'Справка'),
  ];

  @override
  Widget build(BuildContext context) {
    final settings = context.watch<ThemeController>();
    final user = context.watch<AuthController>().user;
    final features = context.watch<ServerFeaturesController>();
    final colors = context.colors;
    final allowed = _allOptions.where((option) {
      if (option.setupOnly && !features.setupAvailable) return false;
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
          const _SectionTitle(title: 'Верхнее меню'),
          const SizedBox(height: 14),
          ReorderableListView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            buildDefaultDragHandles: false,
            itemCount: selected.length,
            proxyDecorator: (child, index, animation) {
              return AnimatedBuilder(
                animation: animation,
                builder: (context, child) {
                  final value = Curves.easeOutCubic.transform(animation.value);
                  return Transform.scale(
                    scale: 1 + value * 0.018,
                    child: Opacity(opacity: 0.96, child: child),
                  );
                },
                child: child,
              );
            },
            onReorderItem: (oldIndex, newIndex) => settings.setPrimaryNav(
              _move(effectiveRoutes, oldIndex, newIndex),
            ),
            itemBuilder: (context, index) {
              final option = selected[index];
              return Padding(
                key: ValueKey(option.route),
                padding: const EdgeInsets.only(bottom: 8),
                child: _NavOrderRow(
                  index: index,
                  option: option,
                  canRemove: selected.length > 1,
                  onRemove: () => settings.setPrimaryNav(
                    effectiveRoutes
                        .where((route) => route != option.route)
                        .toList(),
                  ),
                ),
              );
            },
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
    required this.canRemove,
    required this.onRemove,
  });

  final int index;
  final _NavOption option;
  final bool canRemove;
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
          ReorderableDragStartListener(
            index: index,
            child: Icon(
              Icons.drag_indicator_rounded,
              color: colors.muted,
              size: 22,
            ),
          ),
          const SizedBox(width: 8),
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
    this.setupOnly = false,
  });

  final String route;
  final String label;
  final bool adminOnly;
  final bool reviewOnly;
  final bool setupOnly;
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
    return PressScale(
      child: AnimatedContainer(
        duration: CctvMotion.fast,
        curve: CctvMotion.curve,
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
      ),
    );
  }
}

class _PalettePresets extends StatelessWidget {
  const _PalettePresets({
    required this.onSelect,
    required this.selectedPrimary,
    required this.selectedSecondary,
  });

  final Future<void> Function(Color primary, Color secondary) onSelect;
  final Color selectedPrimary;
  final Color selectedSecondary;

  static const _presets = [
    _PalettePreset('Glacier Ops', Color(0xFF8EDBFF), Color(0xFF2F80ED)),
    _PalettePreset('CCTV Cyan', Color(0xFF5EF0FF), Color(0xFF6F7BFF)),
    _PalettePreset('Nights', Color(0xFFE0264F), Color(0xFF001B2E)),
    _PalettePreset('Arctic', Color(0xFFCFE6FF), Color(0xFF1D6EEA)),
    _PalettePreset('Dusk', Color(0xFFE83FB7), Color(0xFF6028FF)),
    _PalettePreset('Solar Flare', Color(0xFFFFB000), Color(0xFFFF2E55)),
    _PalettePreset('Vault Gold', Color(0xFFD0AF67), Color(0xFF141417)),
    _PalettePreset('Amber Ops', Color(0xFFFFC857), Color(0xFFFF6B35)),
    _PalettePreset('Forest Lab', Color(0xFF4ADE80), Color(0xFF22D3EE)),
    _PalettePreset('Mono Blue', Color(0xFF93C5FD), Color(0xFF64748B)),
  ];

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Готовые палитры',
          style: TextStyle(
            color: colors.textStrong,
            fontSize: 13,
            fontWeight: FontWeight.w900,
          ),
        ),
        const SizedBox(height: 10),
        LayoutBuilder(
          builder: (context, constraints) {
            const spacing = 10.0;
            final maxWidth = constraints.maxWidth;
            final columns = maxWidth < 520
                ? 1
                : maxWidth < 820
                ? 2
                : maxWidth < 1160
                ? 3
                : 4;
            final itemWidth =
                ((maxWidth - spacing * (columns - 1)) / columns)
                    .clamp(174.0, double.infinity)
                    .toDouble();
            return Wrap(
              spacing: spacing,
              runSpacing: spacing,
              children: [
                for (final preset in _presets)
                  _PalettePresetButton(
                    width: itemWidth,
                    preset: preset,
                    selected:
                        preset.primary.toARGB32() ==
                            selectedPrimary.toARGB32() &&
                        preset.secondary.toARGB32() ==
                            selectedSecondary.toARGB32(),
                    onTap: () => onSelect(preset.primary, preset.secondary),
                  ),
              ],
            );
          },
        ),
      ],
    );
  }
}

class _PalettePresetButton extends StatelessWidget {
  const _PalettePresetButton({
    required this.width,
    required this.preset,
    required this.selected,
    required this.onTap,
  });

  final double width;
  final _PalettePreset preset;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return PressScale(
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: onTap,
        child: AnimatedContainer(
          duration: CctvMotion.fast,
          curve: CctvMotion.curve,
          width: width,
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(18),
            color: colors.surfaceMuted,
            border: Border.all(
              color: selected ? colors.primaryAccent : colors.border,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  _ColorDot(color: preset.primary),
                  Transform.translate(
                    offset: const Offset(-5, 0),
                    child: _ColorDot(color: preset.secondary),
                  ),
                  const Spacer(),
                  if (selected)
                    Icon(
                      Icons.check_circle_rounded,
                      color: colors.primaryAccent,
                      size: 18,
                    ),
                ],
              ),
              const SizedBox(height: 9),
              Text(
                preset.label,
                style: TextStyle(
                  color: colors.textStrong,
                  fontSize: 13,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 8),
              Container(
                height: 26,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(999),
                  gradient: LinearGradient(
                    colors: [preset.primary, preset.secondary],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ColorDot extends StatelessWidget {
  const _ColorDot({required this.color});

  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 24,
      height: 24,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: color,
        border: Border.all(color: context.colors.borderStrong),
      ),
    );
  }
}

class _PalettePreset {
  const _PalettePreset(this.label, this.primary, this.secondary);

  final String label;
  final Color primary;
  final Color secondary;
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
