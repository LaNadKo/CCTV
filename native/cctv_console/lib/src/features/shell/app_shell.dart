import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/models/models.dart';
import '../../core/theme/app_theme.dart';
import '../../core/theme/theme_controller.dart';
import '../../shared/widgets/app_backdrop.dart';
import '../../shared/widgets/glass_panel.dart';
import '../auth/auth_controller.dart';
import '../live/live_screen.dart';
import '../modules/module_screens.dart';
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
    final tabs = _tabsFor(auth.user);
    if (!tabs.any((tab) => tab.route == _selectedRoute)) {
      _selectedRoute = tabs.first.route;
    }
    final selected = tabs.firstWhere((tab) => tab.route == _selectedRoute);
    final compact = MediaQuery.sizeOf(context).width < 820;

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
        builder: (_) => const RecordingsScreen(),
      ),
      if (canReview)
        _ShellTab(
          route: '/reviews',
          label: 'Ревью',
          icon: Icons.fact_check_rounded,
          builder: (_) => const ReviewsScreen(),
        ),
      if (canReview)
        _ShellTab(
          route: '/reports',
          label: 'Отчёты',
          icon: Icons.analytics_rounded,
          builder: (_) => const ReportsScreen(),
        ),
      if (isAdmin)
        _ShellTab(
          route: '/cameras',
          label: 'Камеры',
          icon: Icons.videocam_rounded,
          builder: (_) => const CamerasScreen(),
        ),
      if (isAdmin)
        _ShellTab(
          route: '/groups',
          label: 'Группы',
          icon: Icons.account_tree_rounded,
          builder: (_) => const GroupsScreen(),
        ),
      if (isAdmin)
        _ShellTab(
          route: '/persons',
          label: 'Персоны',
          icon: Icons.badge_rounded,
          builder: (_) => const PersonsScreen(),
        ),
      if (isAdmin)
        _ShellTab(
          route: '/processors',
          label: 'Processor',
          icon: Icons.memory_rounded,
          builder: (_) => const ProcessorsScreen(),
        ),
      if (isAdmin)
        _ShellTab(
          route: '/users',
          label: 'Пользователи',
          icon: Icons.manage_accounts_rounded,
          builder: (_) => const UsersScreen(),
        ),
      if (isAdmin)
        _ShellTab(
          route: '/api-keys',
          label: 'API ключи',
          icon: Icons.vpn_key_rounded,
          builder: (_) => const ApiKeysScreen(),
        ),
      _ShellTab(
        route: '/settings',
        label: 'Настройки',
        icon: Icons.tune_rounded,
        builder: (_) => const SettingsScreen(),
      ),
      _ShellTab(
        route: '/help',
        label: 'Справка',
        icon: Icons.help_outline_rounded,
        builder: (_) => const HelpScreen(),
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
    final settings = context.watch<ThemeController>();
    final auth = context.watch<AuthController>();
    final user = auth.user;
    final primaryTabs = _resolvePrimaryTabs(tabs, settings.primaryNav);
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
                padding: const EdgeInsets.all(14),
                child: Row(
                  children: [
                    const _Brand(),
                    const SizedBox(width: 18),
                    Expanded(
                      child: SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            for (final tab in primaryTabs)
                              Padding(
                                padding: const EdgeInsets.only(right: 9),
                                child: _NavChip(
                                  tab: tab,
                                  active: tab.route == selected.route,
                                  onTap: () => onSelect(tab.route),
                                ),
                              ),
                          ],
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
                              child: Row(
                                children: [
                                  Icon(tab.icon, size: 18, color: colors.muted),
                                  const SizedBox(width: 10),
                                  Text(tab.label),
                                ],
                              ),
                            ),
                        ],
                        child: _MenuChip(active: menuActive),
                      ),
                    ],
                    const SizedBox(width: 16),
                    if (user != null)
                      _UserChip(user: user, onLogout: auth.logout),
                  ],
                ),
              ),
              const SizedBox(height: 20),
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
    final settings = context.watch<ThemeController>();
    final visibleTabs = _resolvePrimaryTabs(
      tabs,
      settings.primaryNav,
    ).take(5).toList();
    final selectedIndex = visibleTabs.indexWhere(
      (tab) => tab.route == selected.route,
    );

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 6),
        child: Column(
          children: [
            GlassPanel(
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  const _Brand(compact: true),
                  const Spacer(),
                  PopupMenuButton<String>(
                    tooltip: 'Меню',
                    color: colors.surfaceElevated,
                    surfaceTintColor: Colors.transparent,
                    onSelected: onSelect,
                    itemBuilder: (context) => [
                      for (final tab in tabs)
                        PopupMenuItem(value: tab.route, child: Text(tab.label)),
                    ],
                    child: _MenuChip(active: !visibleTabs.contains(selected)),
                  ),
                  const SizedBox(width: 8),
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
          height: 64,
          backgroundColor: Colors.transparent,
          selectedIndex: selectedIndex < 0 ? 0 : selectedIndex,
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
          width: compact ? 42 : 50,
          height: compact ? 42 : 50,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(17),
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
              fontSize: compact ? 10 : 11,
              letterSpacing: 1.4,
            ),
          ),
        ),
        const SizedBox(width: 12),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Console',
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                fontWeight: FontWeight.w900,
                color: colors.textStrong,
                fontSize: compact ? 17 : 19,
              ),
            ),
            if (!compact)
              Text(
                'Единый клиент для backend и Processor',
                style: TextStyle(color: colors.muted, fontSize: 12),
              ),
          ],
        ),
      ],
    );
  }
}

class _UserChip extends StatelessWidget {
  const _UserChip({required this.user, required this.onLogout});

  final CurrentUser user;
  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.all(9),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
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
                  fontSize: 13,
                ),
              ),
              const SizedBox(height: 4),
              _RoleBadge(user: user),
            ],
          ),
          const SizedBox(width: 10),
          OutlinedButton(onPressed: onLogout, child: const Text('Выйти')),
        ],
      ),
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
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(999),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            child: Text(
              tab.label,
              style: TextStyle(
                color: active ? const Color(0xFF07111F) : colors.muted,
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

class _MenuChip extends StatelessWidget {
  const _MenuChip({required this.active});

  final bool active;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 160),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
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
          fontSize: 13,
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

List<_ShellTab> _resolvePrimaryTabs(List<_ShellTab> tabs, List<String> routes) {
  final selected = <_ShellTab>[];
  for (final route in routes) {
    final index = tabs.indexWhere((tab) => tab.route == route);
    if (index >= 0 && !selected.contains(tabs[index])) {
      selected.add(tabs[index]);
    }
  }
  if (selected.isNotEmpty) return selected;
  return tabs
      .where(
        (tab) => const [
          '/live',
          '/recordings',
          '/reviews',
          '/reports',
        ].contains(tab.route),
      )
      .toList();
}
