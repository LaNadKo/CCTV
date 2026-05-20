import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'src/app.dart';
import 'src/core/network/api_client.dart';
import 'src/core/theme/theme_controller.dart';
import 'src/features/auth/auth_controller.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

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
      ],
      child: const CctvConsoleApp(),
    ),
  );
}
