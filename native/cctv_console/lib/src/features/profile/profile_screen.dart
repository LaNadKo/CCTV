import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';
import '../settings/profile_security_panel.dart';

class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return CustomScrollView(
      slivers: [
        SliverToBoxAdapter(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Профиль',
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  color: colors.textStrong,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                'Личные данные, пароль и двухфакторная аутентификация.',
                style: TextStyle(color: colors.muted, fontSize: 13),
              ),
              const SizedBox(height: 16),
              const ProfileSecurityPanel(),
              const SizedBox(height: 24),
            ],
          ),
        ),
      ],
    );
  }
}
