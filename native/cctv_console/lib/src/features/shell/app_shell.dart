import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/models/models.dart';
import '../../core/theme/app_theme.dart';
import '../../shared/widgets/app_backdrop.dart';
import '../../shared/widgets/glass_panel.dart';
import '../auth/auth_controller.dart';
import '../live/live_screen.dart';
import '../placeholder/placeholder_screen.dart';
import '../settings/settings_screen.dart';

class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  String _selectedRoute = '/live';

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    final user = auth.user;
    final tabs = _tabsFor(user);
    if (!tabs.any((tab) => tab.route == _selectedRoute)) {
      _selectedRoute = tabs.first.route;
    }
    final selected = tabs.firstWhere((tab) => tab.route == _selectedRoute);
    final width = MediaQuery.sizeOf(context).width;
    final compact = width < 820;

    return AppBackdrop(
      child: SafeArea(
        child: compact
            ? _MobileShell(
                tabs: tabs,
                selected: selected,
                onSelect: (route) => setState(() => _selectedRoute = route),
                child: selected.builder(context),
              )
            : _DesktopShell(
                tabs: tabs,
                selected: selected,
                onSelect: (route) => setState(() => _selectedRoute = route),
                child: selected.builder(context),
              ),
      ),
    );
  }

  List<_ShellTab> _tabsFor(CurrentUser? user) {
    final isAdmin = user?.isAdmin ?? false;
    final canReview = user?.canReview ?? false;
    return [
      _ShellTab(
        route: '/live',
        label: 'Live',
        icon: Icons.grid_view_rounded,
        builder: (_) => const LiveScreen(),
      ),
      _ShellTab(
        route: '/recordings',
        label: 'Записи',
        icon: Icons.video_library_rounded,
        builder: (_) => const PlaceholderScreen(
          title: 'Записи',
          subtitle: 'Следующий этап: архив, просмотр записей и экспорт.',
        ),
      ),
      if (canReview)
        _ShellTab(
          route: '/reviews',
          label: 'Ревью',
          icon: Icons.fact_check_rounded,
          builder: (_) => const PlaceholderScreen(
            title: 'Ревью',
            subtitle: 'Будет перенесён поток проверки детекций из веб-консоли.',
          ),
        ),
      if (canReview)
        _ShellTab(
          route: '/reports',
          label: 'Отчёты',
          icon: Icons.analytics_rounded,
          builder: (_) => const PlaceholderScreen(
            title: 'Отчёты',
            subtitle: 'Сводки, появление персон и экспорт PDF/XLSX/DOCX.',
          ),
        ),
      if (isAdmin)
        _ShellTab(
          route: '/persons',
          label: 'Персоны',
          icon: Icons.badge_rounded,
          builder: (_) => const PlaceholderScreen(
            title: 'Персоны',
            subtitle:
                'Управление карточками персон и эмбеддингами будет следующим модулем.',
          ),
        ),
      if (isAdmin)
        _ShellTab(
          route: '/cameras',
          label: 'Камеры',
          icon: Icons.videocam_rounded,
          builder: (_) => const PlaceholderScreen(
            title: 'Камеры',
            subtitle: 'ONVIF discovery, RTSP/HTTP endpoints и пресеты PTZ.',
          ),
        ),
      if (isAdmin)
        _ShellTab(
          route: '/processors',
          label: 'Процессоры',
          icon: Icons.memory_rounded,
          builder: (_) => const PlaceholderScreen(
            title: 'Процессоры',
            subtitle:
                'Подключение Processor, назначение камер и диагностика GPU.',
          ),
        ),
      _ShellTab(
        route: '/settings',
        label: 'Настройки',
        icon: Icons.tune_rounded,
        builder: (_) => const SettingsScreen(),
      ),
    ];
  }
}

class _DesktopShell extends StatelessWidget {
  const _DesktopShell({
    required this.tabs,
    required this.selected,
    required this.onSelect,
    required this.child,
  });

  final List<_ShellTab> tabs;
  final _ShellTab selected;
  final ValueChanged<String> onSelect;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final auth = context.watch<AuthController>();
    final user = auth.user;
    final primaryTabs = tabs
        .where(
          (tab) => const [
            '/live',
            '/recordings',
            '/reviews',
            '/reports',
          ].contains(tab.route),
        )
        .toList();
    final secondaryTabs = tabs
        .where((tab) => !primaryTabs.contains(tab))
        .toList();
    final menuActive = secondaryTabs.any((tab) => tab.route == selected.route);

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 1480),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 18, 24, 32),
          child: Column(
            children: [
              GlassPanel(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    const _Brand(),
                    const SizedBox(width: 18),
                    Expanded(
                      child: SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: primaryTabs
                              .map(
                                (tab) => Padding(
                                  padding: const EdgeInsets.only(right: 10),
                                  child: _NavChip(
                                    tab: tab,
                                    active: tab.route == selected.route,
                                    onTap: () => onSelect(tab.route),
                                  ),
                                ),
                              )
                              .toList(),
                        ),
                      ),
                    ),
                    if (secondaryTabs.isNotEmpty) ...[
                      const SizedBox(width: 8),
                      PopupMenuButton<String>(
                        tooltip: 'Меню',
                        color: colors.surfaceElevated,
                        surfaceTintColor: Colors.transparent,
                        onSelected: onSelect,
                        itemBuilder: (context) => [
                          for (final tab in secondaryTabs)
                            PopupMenuItem(
                              value: tab.route,
                              child: Text(tab.label),
                            ),
                        ],
                        child: _MenuChip(active: menuActive),
                      ),
                    ],
                    const SizedBox(width: 18),
                    if (user != null)
                      Container(
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(20),
                          color: colors.surfaceMuted,
                          border: Border.all(color: colors.border),
                        ),
                        child: Row(
                          children: [
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  user.displayName,
                                  style: TextStyle(
                                    color: colors.textStrong,
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                                const SizedBox(height: 4),
                                _RoleBadge(user: user),
                              ],
                            ),
                            const SizedBox(width: 12),
                            OutlinedButton(
                              onPressed: auth.logout,
                              child: const Text('Выйти'),
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 22),
              Expanded(child: child),
            ],
          ),
        ),
      ),
    );
  }
}

class _MobileShell extends StatelessWidget {
  const _MobileShell({
    required this.tabs,
    required this.selected,
    required this.onSelect,
    required this.child,
  });

  final List<_ShellTab> tabs;
  final _ShellTab selected;
  final ValueChanged<String> onSelect;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final visibleTabs = tabs.take(5).toList();

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 6),
        child: Column(
          children: [
            GlassPanel(
              padding: const EdgeInsets.all(14),
              child: Row(
                children: [
                  const _Brand(compact: true),
                  const Spacer(),
                  OutlinedButton(
                    onPressed: context.read<AuthController>().logout,
                    child: const Text('Выйти'),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),
            Expanded(child: child),
          ],
        ),
      ),
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          color: colors.surfaceElevated,
          border: Border(top: BorderSide(color: colors.border)),
        ),
        child: NavigationBar(
          backgroundColor: Colors.transparent,
          selectedIndex: visibleTabs
              .indexWhere((tab) => tab.route == selected.route)
              .clamp(0, visibleTabs.length - 1),
          onDestinationSelected: (index) => onSelect(visibleTabs[index].route),
          destinations: [
            for (final tab in visibleTabs)
              NavigationDestination(icon: Icon(tab.icon), label: tab.label),
          ],
        ),
      ),
    );
  }
}

class _Brand extends StatelessWidget {
  const _Brand({this.compact = false});

  final bool compact;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Row(
      children: [
        Container(
          width: compact ? 46 : 54,
          height: compact ? 46 : 54,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(18),
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
              fontSize: compact ? 11 : 12,
              letterSpacing: 1.6,
            ),
          ),
        ),
        const SizedBox(width: 14),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Console',
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                fontWeight: FontWeight.w900,
                color: colors.textStrong,
              ),
            ),
            if (!compact)
              Text(
                'Единый клиент для backend и Processor',
                style: TextStyle(color: colors.muted, fontSize: 13),
              ),
          ],
        ),
      ],
    );
  }
}

class _NavChip extends StatelessWidget {
  const _NavChip({
    required this.tab,
    required this.active,
    required this.onTap,
  });

  final _ShellTab tab;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 160),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        gradient: active
            ? LinearGradient(
                colors: [colors.primaryAccent, colors.secondaryAccent],
              )
            : null,
        color: active ? null : colors.surfaceMuted,
        border: Border.all(color: active ? Colors.transparent : colors.border),
        boxShadow: active
            ? [
                BoxShadow(
                  color: colors.primaryAccent.withValues(alpha: 0.24),
                  blurRadius: 24,
                  offset: const Offset(0, 10),
                ),
              ]
            : null,
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(999),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 11),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  tab.label,
                  style: TextStyle(
                    color: active ? const Color(0xFF07111F) : colors.muted,
                    fontWeight: FontWeight.w800,
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

class _MenuChip extends StatelessWidget {
  const _MenuChip({required this.active});

  final bool active;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 160),
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 11),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        gradient: active
            ? LinearGradient(
                colors: [colors.primaryAccent, colors.secondaryAccent],
              )
            : null,
        color: active ? null : colors.surfaceMuted,
        border: Border.all(color: active ? Colors.transparent : colors.border),
      ),
      child: Text(
        'Меню',
        style: TextStyle(
          color: active ? const Color(0xFF07111F) : colors.muted,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class _RoleBadge extends StatelessWidget {
  const _RoleBadge({required this.user});

  final CurrentUser user;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final roleColor = user.isAdmin
        ? colors.warning
        : user.roleId == 2
        ? colors.primaryAccent
        : colors.muted;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: roleColor.withValues(alpha: 0.14),
      ),
      child: Text(
        user.roleLabel,
        style: TextStyle(
          color: roleColor,
          fontWeight: FontWeight.w800,
          fontSize: 11,
        ),
      ),
    );
  }
}

class _ShellTab {
  const _ShellTab({
    required this.route,
    required this.label,
    required this.icon,
    required this.builder,
  });

  final String route;
  final String label;
  final IconData icon;
  final WidgetBuilder builder;
}
