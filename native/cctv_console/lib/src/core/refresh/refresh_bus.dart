import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:provider/provider.dart';

class RefreshBus extends ChangeNotifier {
  final Map<String, int> _versions = <String, int>{};

  int versionOf(String route) => _versions[route] ?? 0;

  void markStale(Iterable<String> routes) {
    var changed = false;
    for (final route in routes.toSet()) {
      if (route.isEmpty) continue;
      _versions[route] = versionOf(route) + 1;
      changed = true;
    }
    if (changed) notifyListeners();
  }
}

mixin RouteRefreshState<T extends StatefulWidget> on State<T> {
  RefreshBus? _refreshBus;
  int _seenRefreshVersion = 0;

  String get refreshRoute;

  FutureOr<void> onRefreshRequested();

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final bus = context.read<RefreshBus>();
    if (identical(_refreshBus, bus)) return;
    _refreshBus?.removeListener(_handleRefresh);
    _refreshBus = bus;
    _seenRefreshVersion = bus.versionOf(refreshRoute);
    bus.addListener(_handleRefresh);
  }

  @override
  void dispose() {
    _refreshBus?.removeListener(_handleRefresh);
    super.dispose();
  }

  void _handleRefresh() {
    final bus = _refreshBus;
    if (!mounted || bus == null) return;
    final nextVersion = bus.versionOf(refreshRoute);
    if (nextVersion == _seenRefreshVersion) return;
    _seenRefreshVersion = nextVersion;
    final result = onRefreshRequested();
    if (result is Future<void>) {
      unawaited(result);
    }
  }
}
