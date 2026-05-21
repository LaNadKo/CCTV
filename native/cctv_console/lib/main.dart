import 'package:flutter/material.dart';
import 'package:media_kit/media_kit.dart';
import 'package:provider/provider.dart';

import 'src/app.dart';
import 'src/core/network/api_client.dart';
import 'src/core/refresh/refresh_bus.dart';
import 'src/core/theme/theme_controller.dart';
import 'src/features/auth/auth_controller.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  MediaKit.ensureInitialized();

  final settings = ThemeController();
  await settings.load();

  final apiClient = ApiClient(baseUrlProvider: () => settings.apiBaseUrl);

  final auth = AuthController(apiClient: apiClient);
  await auth.restoreSession();

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: settings),
        Provider.value(value: apiClient),
        ChangeNotifierProvider.value(value: auth),
        ChangeNotifierProvider(create: (_) => RefreshBus()),
      ],
      child: const CctvConsoleApp(),
    ),
  );
}
