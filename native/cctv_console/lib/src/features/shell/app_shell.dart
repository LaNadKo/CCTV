import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/models/models.dart';
import '../../core/network/api_client.dart';
import '../../core/refresh/refresh_bus.dart';
import '../../core/theme/app_theme.dart';
import '../../core/theme/theme_controller.dart';
import '../../shared/widgets/app_backdrop.dart';
import '../../shared/widgets/glass_panel.dart';
import '../admin/admin_screens.dart';
import '../auth/auth_controller.dart';
import '../cameras/cameras_screen.dart';
import '../help/help_screen.dart';
import '../live/live_screen.dart';
import '../persons/persons_screen.dart';
import '../profile/profile_screen.dart';
import '../recordings/recordings_screen.dart';
import '../reports/reports_screen.dart';
import '../setup/setup_screen.dart';
import '../settings/settings_screen.dart';

const _changePollInterval = Duration(seconds: 5);
const _changePollTimeout = Duration(seconds: 5);
const _activeRefreshInterval = Duration(seconds: 15);
const _activeAutoRefreshRoutes = <String>{
  '/live',
  '/recordings',
  '/reviews',
  '/reports',
  '/cameras',
  '/groups',
  '/persons',
  '/processors',
  '/users',
  '/api-keys',
  '/setup',
};
const _changeSectionRoutes = <String, List<String>>{
  'cameras': ['/live', '/cameras', '/recordings', '/reports', '/processors'],
  'groups': ['/live', '/groups', '/cameras', '/reports'],
  'persons': ['/persons', '/reviews', '/reports'],
  'recordings': ['/recordings', '/reports'],
  'events': ['/live', '/recordings', '/reviews', '/reports'],
  'processors': ['/live', '/processors', '/reports'],
  'users': ['/users', '/profile', '/reports'],
  'api_keys': ['/api-keys', '/processors', '/reports'],
};

class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  String _selectedRoute = '/live';
  bool _routeRestored = false;
  bool _hasChangeSnapshot = false;
  bool _changePollInFlight = false;
  Timer? _changePollTimer;
  Timer? _activeRefreshTimer;
  Map<String, String> _sectionRevisions = const {};
  final Set<String> _visitedRoutes = {'/live'};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      unawaited(_pollChanges());
      _changePollTimer = Timer.periodic(
        _changePollInterval,
        (_) => unawaited(_pollChanges()),
      );
      _activeRefreshTimer = Timer.periodic(
        _activeRefreshInterval,
        (_) => _refreshActiveRoute(),
      );
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_routeRestored) return;
    _routeRestored = true;
    _selectedRoute = context.read<ThemeController>().lastRoute;
  }

  @override
  void dispose() {
    _changePollTimer?.cancel();
    _activeRefreshTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    final tabs = _tabsFor(auth.user);
    if (!tabs.any((tab) => tab.route == _selectedRoute)) {
      _selectedRoute = tabs.first.route;
    }
    final allowedRoutes = tabs.map((tab) => tab.route).toSet();
    _visitedRoutes.removeWhere((route) => !allowedRoutes.contains(route));
    _visitedRoutes.add(_selectedRoute);
    final selected = tabs.firstWhere((tab) => tab.route == _selectedRoute);
    final compact = MediaQuery.sizeOf(context).width < 820;
    final body = _ShellBody(
      tabs: tabs,
      selectedRoute: selected.route,
      visitedRoutes: Set.unmodifiable(_visitedRoutes),
    );

    return AppBackdrop(
      child: SafeArea(
        child: compact
            ? _MobileShell(
                tabs: tabs,
                selected: selected,
                onSelect: _selectRoute,
                child: body,
              )
            : _DesktopShell(
                tabs: tabs,
                selected: selected,
                onSelect: _selectRoute,
                child: body,
              ),
      ),
    );
  }

  void _selectRoute(String route) {
    setState(() {
      _selectedRoute = route;
      _visitedRoutes.add(route);
    });
    context.read<ThemeController>().setLastRoute(route);
  }

  Future<void> _pollChanges() async {
    if (!mounted || _changePollInFlight) return;
    final auth = context.read<AuthController>();
    final token = auth.accessToken;
    if (token == null || token.isEmpty) return;

    _changePollInFlight = true;
    try {
      final raw = await context.read<ApiClient>().getJson(
        '/system/changes',
        token: token,
        timeout: _changePollTimeout,
      );
      if (!mounted) return;
      final root = raw is Map ? raw : null;
      final sections = root?['sections'];
      if (sections is! Map) return;
      final next = <String, String>{
        for (final entry in sections.entries) '${entry.key}': '${entry.value}',
      };
      if (next.isEmpty) return;

      if (!_hasChangeSnapshot) {
        _sectionRevisions = next;
        _hasChangeSnapshot = true;
        return;
      }

      final changedSections = <String>{
        for (final entry in next.entries)
          if (_sectionRevisions[entry.key] != entry.value) entry.key,
        for (final section in _sectionRevisions.keys)
          if (!next.containsKey(section)) section,
      };
      _sectionRevisions = next;
      if (changedSections.isEmpty) return;

      final routes = <String>{
        for (final section in changedSections)
          ...?_changeSectionRoutes[section],
      };
      if (routes.isNotEmpty) {
        context.read<RefreshBus>().markStale(routes);
      }
    } catch (_) {
      // Polling is an optimization. Connection errors must not break navigation.
    } finally {
      _changePollInFlight = false;
    }
  }

  void _refreshActiveRoute() {
    if (!mounted || !_activeAutoRefreshRoutes.contains(_selectedRoute)) {
      return;
    }
    final token = context.read<AuthController>().accessToken;
    if (token == null || token.isEmpty) return;
    context.read<RefreshBus>().markStale([_selectedRoute]);
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
        builder: (_) => const ArchiveRecordingsScreen(),
      ),
      if (canReview)
        _ShellTab(
          route: '/reviews',
          label: 'Ревью',
          icon: Icons.fact_check_rounded,
          builder: (_) => const ReviewsManagementScreen(),
        ),
      if (canReview)
        _ShellTab(
          route: '/reports',
          label: 'Отчёты',
          icon: Icons.analytics_rounded,
          builder: (_) => const ReportsDashboardScreen(),
        ),
      if (isAdmin)
        _ShellTab(
          route: '/cameras',
          label: 'Камеры',
          icon: Icons.videocam_rounded,
          builder: (_) => const CameraManagementScreen(),
        ),
      _ShellTab(
        route: '/groups',
        label: 'Группы',
        icon: Icons.account_tree_rounded,
        builder: (_) => const GroupsManagementScreen(),
      ),
      if (isAdmin)
        _ShellTab(
          route: '/persons',
          label: 'Персоны',
          icon: Icons.badge_rounded,
          builder: (_) => const PersonsManagementScreen(),
        ),
      if (isAdmin)
        _ShellTab(
          route: '/processors',
          label: 'Processor',
          icon: Icons.memory_rounded,
          builder: (_) => const ProcessorsManagementScreen(),
        ),
      if (isAdmin)
        _ShellTab(
          route: '/users',
          label: 'Пользователи',
          icon: Icons.manage_accounts_rounded,
          builder: (_) => const UsersManagementScreen(),
        ),
      if (isAdmin)
        _ShellTab(
          route: '/api-keys',
          label: 'API ключи',
          icon: Icons.vpn_key_rounded,
          builder: (_) => const ApiKeysManagementScreen(),
        ),
      if (isAdmin)
        _ShellTab(
          route: '/setup',
          label: 'Setup',
          icon: Icons.settings_applications_rounded,
          builder: (_) => const SetupScreen(),
        ),
      _ShellTab(
        route: '/profile',
        label: 'Профиль',
        icon: Icons.person_rounded,
        builder: (_) => const ProfileScreen(),
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
                padding: const EdgeInsets.symmetric(
                  horizontal: 14,
                  vertical: 10,
                ),
                child: SizedBox(
                  height: 58,
                  child: LayoutBuilder(
                    builder: (context, constraints) {
                      final compact = constraints.maxWidth < 980;
                      return Row(
                        children: [
                          ConstrainedBox(
                            constraints: BoxConstraints(
                              maxWidth: compact ? 180 : 340,
                            ),
                            child: _Brand(compact: compact),
                          ),
                          SizedBox(width: compact ? 8 : 16),
                          Expanded(
                            child: ClipRect(
                              child: SingleChildScrollView(
                                scrollDirection: Axis.horizontal,
                                child: Row(
                                  mainAxisAlignment: MainAxisAlignment.center,
                                  children: [
                                    for (final tab in primaryTabs)
                                      Padding(
                                        padding: const EdgeInsets.only(
                                          right: 9,
                                        ),
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
                          ),
                          SizedBox(width: compact ? 8 : 16),
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const _ThemeToggleButton(),
                              const SizedBox(width: 8),
                              if (secondaryTabs.isNotEmpty) ...[
                                _DesktopMenu(
                                  tabs: secondaryTabs,
                                  active: menuActive,
                                  onSelect: onSelect,
                                ),
                                const SizedBox(width: 12),
                              ],
                              if (user != null)
                                ConstrainedBox(
                                  constraints: BoxConstraints(
                                    maxWidth: compact ? 270 : 390,
                                  ),
                                  child: _UserChip(
                                    user: user,
                                    onLogout: auth.logout,
                                  ),
                                ),
                            ],
                          ),
                        ],
                      );
                    },
                  ),
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
        padding: const EdgeInsets.fromLTRB(10, 8, 10, 6),
        child: Column(
          children: [
            GlassPanel(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
              child: Row(
                children: [
                  const Expanded(child: _Brand(compact: true)),
                  const SizedBox(width: 6),
                  const _ThemeToggleButton(compact: true),
                  const SizedBox(width: 6),
                  PopupMenuButton<String>(
                    tooltip: 'Меню',
                    color: colors.surfaceElevated,
                    surfaceTintColor: Colors.transparent,
                    onSelected: onSelect,
                    itemBuilder: (context) => [
                      for (final tab in tabs)
                        PopupMenuItem(value: tab.route, child: Text(tab.label)),
                    ],
                    child: _MobileIconChip(
                      icon: Icons.menu_rounded,
                      active: !visibleTabs.contains(selected),
                    ),
                  ),
                  const SizedBox(width: 6),
                  IconButton.filledTonal(
                    onPressed: context.read<AuthController>().logout,
                    tooltip: 'Выйти',
                    style: IconButton.styleFrom(
                      fixedSize: const Size.square(36),
                      minimumSize: const Size.square(36),
                      padding: EdgeInsets.zero,
                    ),
                    iconSize: 19,
                    icon: const Icon(Icons.logout_rounded),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 8),
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
          height: 58,
          backgroundColor: Colors.transparent,
          labelBehavior: NavigationDestinationLabelBehavior.onlyShowSelected,
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

class _ShellBody extends StatelessWidget {
  const _ShellBody({
    required this.tabs,
    required this.selectedRoute,
    required this.visitedRoutes,
  });

  final List<_ShellTab> tabs;
  final String selectedRoute;
  final Set<String> visitedRoutes;

  @override
  Widget build(BuildContext context) {
    final selectedIndex = tabs.indexWhere((tab) => tab.route == selectedRoute);
    return IndexedStack(
      index: selectedIndex < 0 ? 0 : selectedIndex,
      sizing: StackFit.expand,
      children: [
        for (final tab in tabs)
          if (visitedRoutes.contains(tab.route))
            KeyedSubtree(
              key: PageStorageKey<String>('shell-page:${tab.route}'),
              child: tab.builder(context),
            )
          else
            SizedBox.shrink(
              key: ValueKey<String>('shell-placeholder:${tab.route}'),
            ),
      ],
    );
  }
}

class _Brand extends StatelessWidget {
  const _Brand({this.compact = false});

  final bool compact;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final size = compact ? 36.0 : 50.0;
    return SizedBox(
      height: size,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Container(
            width: size,
            height: size,
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
          SizedBox(width: compact ? 8 : 12),
          Flexible(
            child: SizedBox(
              height: size,
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Console',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.w900,
                      color: colors.textStrong,
                      fontSize: compact ? 16 : 19,
                      height: 1.08,
                    ),
                  ),
                  if (!compact) ...[
                    const SizedBox(height: 3),
                    Text(
                      'Единый клиент для backend и Processor',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: colors.muted,
                        fontSize: 12,
                        height: 1.1,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
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
      constraints: const BoxConstraints(maxWidth: 390),
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 7),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Flexible(
            child: ConstrainedBox(
              constraints: const BoxConstraints(minWidth: 72, maxWidth: 250),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    user.displayName,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
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
            ),
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

class _MobileIconChip extends StatelessWidget {
  const _MobileIconChip({required this.icon, required this.active});

  final IconData icon;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 160),
      width: 36,
      height: 36,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: active
            ? LinearGradient(
                colors: [colors.primaryAccent, colors.secondaryAccent],
              )
            : null,
        color: active ? null : colors.surfaceMuted,
        border: Border.all(color: active ? Colors.transparent : colors.border),
      ),
      alignment: Alignment.center,
      child: Icon(
        icon,
        size: 19,
        color: active ? const Color(0xFF07111F) : colors.muted,
      ),
    );
  }
}

class _DesktopMenu extends StatefulWidget {
  const _DesktopMenu({
    required this.tabs,
    required this.active,
    required this.onSelect,
  });

  final List<_ShellTab> tabs;
  final bool active;
  final ValueChanged<String> onSelect;

  @override
  State<_DesktopMenu> createState() => _DesktopMenuState();
}

class _DesktopMenuState extends State<_DesktopMenu>
    with SingleTickerProviderStateMixin {
  final _link = LayerLink();
  OverlayEntry? _entry;
  late final AnimationController _controller;
  late final Animation<double> _opacity;
  late final Animation<double> _scale;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 170),
      reverseDuration: const Duration(milliseconds: 120),
    );
    final curve = CurvedAnimation(
      parent: _controller,
      curve: Curves.easeOutCubic,
      reverseCurve: Curves.easeInCubic,
    );
    _opacity = Tween<double>(begin: 0, end: 1).animate(curve);
    _scale = Tween<double>(begin: 0.96, end: 1).animate(curve);
  }

  @override
  void dispose() {
    _entry?.remove();
    _controller.dispose();
    super.dispose();
  }

  void _toggle() {
    if (_entry == null) {
      _open();
    } else {
      _close();
    }
  }

  void _open() {
    final overlay = Overlay.of(context);
    _entry = OverlayEntry(
      builder: (context) {
        return Stack(
          children: [
            Positioned.fill(
              child: GestureDetector(
                behavior: HitTestBehavior.translucent,
                onTap: _close,
                child: const SizedBox.expand(),
              ),
            ),
            CompositedTransformFollower(
              link: _link,
              showWhenUnlinked: false,
              targetAnchor: Alignment.bottomLeft,
              followerAnchor: Alignment.topRight,
              offset: const Offset(-10, 10),
              child: Material(
                color: Colors.transparent,
                child: FadeTransition(
                  opacity: _opacity,
                  child: ScaleTransition(
                    scale: _scale,
                    alignment: Alignment.topRight,
                    child: _DesktopMenuPanel(
                      tabs: widget.tabs,
                      onSelect: (route) {
                        _close();
                        widget.onSelect(route);
                      },
                    ),
                  ),
                ),
              ),
            ),
          ],
        );
      },
    );
    overlay.insert(_entry!);
    _controller.forward(from: 0);
    setState(() {});
  }

  Future<void> _close() async {
    final entry = _entry;
    if (entry == null) return;
    await _controller.reverse();
    entry.remove();
    if (mounted && identical(_entry, entry)) {
      setState(() => _entry = null);
    } else if (identical(_entry, entry)) {
      _entry = null;
    }
  }

  @override
  Widget build(BuildContext context) {
    return CompositedTransformTarget(
      link: _link,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: _toggle,
        child: _MenuChip(active: widget.active || _entry != null),
      ),
    );
  }
}

class _ThemeToggleButton extends StatelessWidget {
  const _ThemeToggleButton({this.compact = false});

  final bool compact;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final settings = context.watch<ThemeController>();
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final nextMode = isDark ? CctvThemeMode.light : CctvThemeMode.dark;
    return Tooltip(
      message: isDark ? 'Включить светлую тему' : 'Включить тёмную тему',
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: () => settings.setThemeMode(nextMode),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          width: compact ? 36 : 42,
          height: compact ? 36 : 42,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: colors.surfaceMuted,
            border: Border.all(color: colors.border),
          ),
          child: Icon(
            isDark ? Icons.dark_mode_rounded : Icons.wb_sunny_rounded,
            color: isDark ? colors.secondaryAccent : colors.warning,
            size: compact ? 18 : 20,
          ),
        ),
      ),
    );
  }
}

class _DesktopMenuPanel extends StatelessWidget {
  const _DesktopMenuPanel({required this.tabs, required this.onSelect});

  final List<_ShellTab> tabs;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      width: 246,
      constraints: const BoxConstraints(maxHeight: 420),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: colors.surfaceElevated,
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: colors.borderStrong),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.32),
            blurRadius: 28,
            offset: const Offset(0, 18),
          ),
        ],
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (final tab in tabs)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: _DesktopMenuItem(tab: tab, onTap: onSelect),
              ),
          ],
        ),
      ),
    );
  }
}

class _DesktopMenuItem extends StatelessWidget {
  const _DesktopMenuItem({required this.tab, required this.onTap});

  final _ShellTab tab;
  final ValueChanged<String> onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () => onTap(tab.route),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
          child: Row(
            children: [
              Icon(tab.icon, size: 18, color: colors.primaryAccent),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  tab.label,
                  style: TextStyle(
                    color: colors.textStrong,
                    fontSize: 13,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              Icon(Icons.chevron_right_rounded, color: colors.muted, size: 18),
            ],
          ),
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
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
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
