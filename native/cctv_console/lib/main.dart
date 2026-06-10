import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:media_kit/media_kit.dart';
import 'package:provider/provider.dart';
import 'package:window_manager/window_manager.dart';

import 'src/app.dart';
import 'src/core/network/api_client.dart';
import 'src/core/profiles/connection_profiles.dart';
import 'src/core/refresh/refresh_bus.dart';
import 'src/core/server/server_features_controller.dart';
import 'src/core/theme/theme_controller.dart';
import 'src/features/auth/auth_controller.dart';

const _desktopMinimumWindowSize = Size(1280, 760);

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  MediaKit.ensureInitialized();
  if (!kIsWeb && (Platform.isWindows || Platform.isLinux || Platform.isMacOS)) {
    await windowManager.ensureInitialized();
    await windowManager.setMinimumSize(_desktopMinimumWindowSize);
    final size = await windowManager.getSize();
    if (size.width < _desktopMinimumWindowSize.width ||
        size.height < _desktopMinimumWindowSize.height) {
      await windowManager.setSize(
        Size(
          size.width < _desktopMinimumWindowSize.width
              ? _desktopMinimumWindowSize.width
              : size.width,
          size.height < _desktopMinimumWindowSize.height
              ? _desktopMinimumWindowSize.height
              : size.height,
        ),
      );
      await windowManager.center();
    }
  }

  final settings = ThemeController();
  await settings.load();

  final profiles = ConnectionProfilesController();
  await profiles.load(fallbackBaseUrl: settings.apiBaseUrl);
  final activeProfile = profiles.activeProfile;
  if (activeProfile != null && activeProfile.baseUrl != settings.apiBaseUrl) {
    await settings.setApiBaseUrl(activeProfile.baseUrl);
  }

  final apiClient = ApiClient(baseUrlProvider: () => settings.apiBaseUrl);

  final auth = AuthController(
    apiClient: apiClient,
    sessionScopeProvider: () => profiles.activeProfileId ?? 'default',
  );
  await auth.restoreSession();

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: settings),
        ChangeNotifierProvider.value(value: profiles),
        Provider.value(value: apiClient),
        ChangeNotifierProvider.value(value: auth),
        ChangeNotifierProvider(create: (_) => ServerFeaturesController()),
        ChangeNotifierProvider(create: (_) => RefreshBus()),
      ],
      child: const CctvConsoleApp(),
    ),
  );
}
