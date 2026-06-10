import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';
import '../../shared/widgets/glass_panel.dart';

class HelpScreen extends StatefulWidget {
  const HelpScreen({super.key});

  @override
  State<HelpScreen> createState() => _HelpScreenState();
}

class _HelpScreenState extends State<HelpScreen> {
  final _searchController = TextEditingController();
  var _activeTab = _helpTabs.first.id;

  @override
  void initState() {
    super.initState();
    _searchController.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final query = _searchController.text.trim();
    final activeTab = _helpTabs.firstWhere((tab) => tab.id == _activeTab);
    final visibleSections = query.isEmpty
        ? activeTab.sections
              .map(
                (section) =>
                    _SearchableHelpSection(tab: activeTab, section: section),
              )
              .toList()
        : _searchSections(query);

    return CustomScrollView(
      slivers: [
        SliverToBoxAdapter(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _HelpHeader(
                queryController: _searchController,
                resultCount: query.isEmpty ? null : visibleSections.length,
              ),
              const SizedBox(height: 14),
              _HelpTabs(
                activeTabId: _activeTab,
                tabs: _helpTabs,
                onSelect: (id) {
                  setState(() {
                    _activeTab = id;
                    _searchController.clear();
                  });
                },
              ),
              const SizedBox(height: 10),
              Text(
                query.isEmpty
                    ? activeTab.description
                    : 'Поиск идёт по заголовкам, описаниям, пунктам и тегам.',
                style: TextStyle(color: context.colors.muted, fontSize: 13),
              ),
              const SizedBox(height: 14),
            ],
          ),
        ),
        if (visibleSections.isEmpty)
          const SliverToBoxAdapter(child: EmptyHelpPanel())
        else
          SliverList.builder(
            itemCount: visibleSections.length,
            itemBuilder: (context, index) {
              return Padding(
                padding: const EdgeInsets.only(bottom: 14),
                child: _HelpSectionCard(section: visibleSections[index]),
              );
            },
          ),
        const SliverToBoxAdapter(child: SizedBox(height: 24)),
      ],
    );
  }

  List<_SearchableHelpSection> _searchSections(String query) {
    final normalizedQuery = _normalize(query);
    final words = normalizedQuery
        .split(RegExp(r'\s+'))
        .where((word) => word.length >= 2)
        .toList();
    if (words.isEmpty) return const [];

    final matches = <_SearchableHelpSection>[];
    for (final tab in _helpTabs) {
      for (final section in tab.sections) {
        final haystack = _normalize(
          [
            tab.label,
            section.title,
            section.summary,
            ...section.bullets,
            ...section.previewLines,
            ...section.tags,
          ].join(' '),
        );
        if (words.every(haystack.contains)) {
          matches.add(_SearchableHelpSection(tab: tab, section: section));
        }
      }
    }
    return matches;
  }
}

class _HelpHeader extends StatelessWidget {
  const _HelpHeader({required this.queryController, required this.resultCount});

  final TextEditingController queryController;
  final int? resultCount;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(18),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 760;
          final title = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Справка',
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  color: colors.textStrong,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                'Краткие инструкции по вкладкам Консоли, диагностике и типовым операциям.',
                style: TextStyle(color: colors.muted, fontSize: 13),
              ),
              if (resultCount != null) ...[
                const SizedBox(height: 8),
                Text(
                  'Найдено тем: $resultCount',
                  style: TextStyle(
                    color: colors.primaryAccent,
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ],
            ],
          );
          final search = TextField(
            controller: queryController,
            decoration: InputDecoration(
              labelText: 'Поиск по справке',
              hintText: 'Эфир, ONVIF, отчёты, Процессор, 2FA...',
              prefixIcon: const Icon(Icons.search_rounded),
              suffixIcon: queryController.text.isEmpty
                  ? null
                  : IconButton(
                      onPressed: queryController.clear,
                      icon: const Icon(Icons.close_rounded),
                    ),
            ),
          );

          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [title, const SizedBox(height: 14), search],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: title),
              const SizedBox(width: 18),
              SizedBox(width: 390, child: search),
            ],
          );
        },
      ),
    );
  }
}

class _HelpTabs extends StatelessWidget {
  const _HelpTabs({
    required this.activeTabId,
    required this.tabs,
    required this.onSelect,
  });

  final String activeTabId;
  final List<_HelpTab> tabs;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          for (final tab in tabs)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: _TabButton(
                label: tab.label,
                active: tab.id == activeTabId,
                onTap: () => onSelect(tab.id),
              ),
            ),
        ],
      ),
    );
  }
}

class _TabButton extends StatelessWidget {
  const _TabButton({
    required this.label,
    required this.active,
    required this.onTap,
  });

  final String label;
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
              label,
              style: TextStyle(
                color: active ? const Color(0xFF07111F) : colors.muted,
                fontSize: 13,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _HelpSectionCard extends StatelessWidget {
  const _HelpSectionCard({required this.section});

  final _SearchableHelpSection section;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(18),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 820;
          final body = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 9,
                      vertical: 5,
                    ),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(999),
                      color: colors.primaryAccent.withValues(alpha: 0.12),
                    ),
                    child: Text(
                      section.tab.label,
                      style: TextStyle(
                        color: colors.primaryAccent,
                        fontSize: 11,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Text(
                section.section.title,
                style: TextStyle(
                  color: colors.textStrong,
                  fontSize: 17,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                section.section.summary,
                style: TextStyle(
                  color: colors.muted,
                  fontSize: 13,
                  height: 1.45,
                ),
              ),
              const SizedBox(height: 12),
              for (final bullet in section.section.bullets)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Container(
                        width: 6,
                        height: 6,
                        margin: const EdgeInsets.only(top: 8, right: 9),
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: colors.primaryAccent,
                        ),
                      ),
                      Expanded(
                        child: Text(
                          bullet,
                          style: TextStyle(
                            color: colors.text,
                            fontSize: 13,
                            height: 1.42,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
            ],
          );
          final preview = _PreviewPanel(section: section.section);

          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [body, const SizedBox(height: 14), preview],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(flex: 6, child: body),
              const SizedBox(width: 18),
              Expanded(flex: 4, child: preview),
            ],
          );
        },
      ),
    );
  }
}

class _PreviewPanel extends StatelessWidget {
  const _PreviewPanel({required this.section});

  final _HelpSection section;

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
          Text(
            section.previewTitle,
            style: TextStyle(
              color: colors.textStrong,
              fontSize: 14,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 10),
          for (var index = 0; index < section.previewLines.length; index++)
            Container(
              width: double.infinity,
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(12),
                color: index == 0
                    ? colors.primaryAccent.withValues(alpha: 0.13)
                    : colors.surfaceElevated.withValues(alpha: 0.35),
                border: Border.all(color: colors.border),
              ),
              child: Text(
                section.previewLines[index],
                style: TextStyle(
                  color: index == 0 ? colors.textStrong : colors.text,
                  fontSize: 12,
                  fontWeight: index == 0 ? FontWeight.w800 : FontWeight.w600,
                  height: 1.35,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class EmptyHelpPanel extends StatelessWidget {
  const EmptyHelpPanel({super.key});

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Совпадений не найдено',
            style: TextStyle(
              color: colors.textStrong,
              fontSize: 16,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'Попробуйте более короткий запрос, название вкладки или тип операции.',
            style: TextStyle(color: colors.muted, fontSize: 13),
          ),
        ],
      ),
    );
  }
}

class _SearchableHelpSection {
  const _SearchableHelpSection({required this.tab, required this.section});

  final _HelpTab tab;
  final _HelpSection section;
}

class _HelpTab {
  const _HelpTab({
    required this.id,
    required this.label,
    required this.description,
    required this.sections,
  });

  final String id;
  final String label;
  final String description;
  final List<_HelpSection> sections;
}

class _HelpSection {
  const _HelpSection({
    required this.id,
    required this.title,
    required this.summary,
    required this.bullets,
    required this.previewTitle,
    required this.previewLines,
    required this.tags,
  });

  final String id;
  final String title;
  final String summary;
  final List<String> bullets;
  final String previewTitle;
  final List<String> previewLines;
  final List<String> tags;
}

String _normalize(String value) => value.toLowerCase().replaceAll('ё', 'е');

const _helpTabs = [
  _HelpTab(
    id: 'overview',
    label: 'Общее',
    description:
        'Вход в систему, 2FA, настройки клиента, профиль пользователя и принципы работы Консоли.',
    sections: [
      _HelpSection(
        id: 'start',
        title: 'Быстрый старт',
        summary:
            'После входа проверьте подключение к серверу, затем откройте Эфир, Записи или другой рабочий раздел.',
        bullets: [
          'Если интерфейс пустой, сначала откройте Настройки и проверьте адрес сервера.',
          'Если для учётной записи включена 2FA, код двухфакторной аутентификации вводится отдельным окном после проверки логина и пароля.',
          'Роль пользователя определяет доступ к админ-разделам и управлению оборудованием.',
        ],
        previewTitle: 'Что проверить сначала',
        previewLines: [
          'Адрес сервера и состояние входа',
          'Доступные вкладки в верхней панели',
          'Статус камер и Процессора перед демонстрацией',
        ],
        tags: ['старт', 'вход', 'сервер', 'доступ', 'роль'],
      ),
      _HelpSection(
        id: 'profile-security',
        title: 'Профиль и 2FA',
        summary:
            'Профиль вынесен в отдельную вкладку: там меняются личные данные, пароль и двухфакторная аутентификация.',
        bullets: [
          'Фамилия, имя и отчество сохраняются в карточке текущего пользователя и используются в интерфейсе.',
          'Смена пароля требует текущий пароль, новый пароль и повтор нового пароля.',
          'Настройка 2FA показывает QR-код и ручной секрет, после чего нужно подтвердить кодом из приложения-аутентификатора.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Логин, роль и статус 2FA',
          'Форма личных данных',
          'Смена пароля, включение и отключение 2FA',
        ],
        tags: ['профиль', '2fa', 'пароль', 'безопасность', 'totp'],
      ),
      _HelpSection(
        id: 'settings',
        title: 'Настройки',
        summary:
            'В настройках меняются адрес сервера, акцентные цвета, плотность эфира и состав верхнего меню.',
        bullets: [
          'Адрес сервера сохраняется локально для текущего клиента.',
          'Верхнее меню поддерживает до пяти быстрых вкладок, остальные остаются в меню.',
          'Сброс оформления возвращает стандартные цвета, плотность эфира и порядок меню; тема переключается отдельной кнопкой в шапке.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Адрес сервера и кнопка сохранения',
          'Акцентные цвета и плотность эфира',
          'Порядок вкладок верхнего меню',
        ],
        tags: ['настройки', 'сервер', 'тема', 'меню', 'эфир'],
      ),
      _HelpSection(
        id: 'help',
        title: 'Справка',
        summary:
            'Справка разбита на тематические вкладки и поддерживает поиск по ключевым словам.',
        bullets: [
          'Ищите по названию вкладки, типу операции, роли, ONVIF, Процессору или отчётам.',
          'Если точная формулировка неизвестна, достаточно ввести часть слова.',
          'При пустом поиске показываются темы активной вкладки.',
        ],
        previewTitle: 'Как пользоваться',
        previewLines: [
          'Выберите тематическую вкладку',
          'Введите короткий запрос при необходимости',
          'Откройте карточку с нужным сценарием',
        ],
        tags: ['справка', 'поиск', 'подсказки', 'вкладки'],
      ),
    ],
  ),
  _HelpTab(
    id: 'monitoring',
    label: 'Мониторинг',
    description: 'Эфирные потоки, архив записей, ревью событий и отчётность.',
    sections: [
      _HelpSection(
        id: 'live',
        title: 'Эфир',
        summary:
            'Эфир показывает сетку камер, состояние потоков и быстрые ONVIF/PTZ команды.',
        bullets: [
          'Сетка камер поддерживает перетаскивание, выбор колонок, overlay детекции и цифровой zoom.',
          'ONVIF/PTZ доступен администраторам: кнопки можно удерживать, fullscreen понимает WASD/стрелки и Q/E для zoom.',
          'Пресеты камеры можно синхронизировать, создать из текущего ракурса, открыть или удалить.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Карточки камер с потоками и fullscreen',
          'Overlay детекции, zoom и статус записи',
          'PTZ continuous и ONVIF-пресеты',
        ],
        tags: ['live', 'потоки', 'ptz', 'onvif', 'камера'],
      ),
      _HelpSection(
        id: 'recordings',
        title: 'Записи',
        summary:
            'Записи показывают архив файлов, которые сервер получил или зарегистрировал от Процессора.',
        bullets: [
          'Архив сгруппирован как день → час → минутный клип и может воспроизводиться непрерывной лентой.',
          'Фильтр меток помогает оставить на таймлайне только нужный тип события.',
          'Если обычный плеер не открыл файл, используйте резервный MJPEG или кнопку открытия файла.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Суточный медиаплеер',
          'Папки часов и карточки минутных клипов',
          'Метки событий, скачивание/открытие и резервный MJPEG',
        ],
        tags: ['записи', 'архив', 'процессор', 'файлы', 'камера'],
      ),
      _HelpSection(
        id: 'reviews',
        title: 'Ревью событий',
        summary:
            'Ревью используется для подтверждения или отклонения неизвестных событий распознавания.',
        bullets: [
          'Карточка события показывает снимок, камеру, время, уверенность и связанную запись.',
          'Перед подтверждением можно выбрать существующую персону, чтобы review записал person_id.',
          'Из снимка или записи можно создать новую персону и сразу привязать её к событию.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Фото события и видеофрагмент',
          'Выбор персоны и обучение из кадра',
          'Подтвердить, отклонить или отклонить всё',
        ],
        tags: ['ревью', 'снимок', 'события', 'подтверждение', 'детекция'],
      ),
      _HelpSection(
        id: 'reports',
        title: 'Отчёты',
        summary:
            'Отчёты собирают состояние камер, Процессора, событий, архива и безопасности.',
        bullets: [
          'Фильтры по датам, группам, камерам, Процессору, пользователям и персонам применяются к экрану и экспорту.',
          'На экране есть детальные таблицы камер, групп, Процессора, архива, безопасности, ревьюеров и появлений персон.',
          'Экспорт PDF, Excel и Word формируется сервером по текущему разделу и активным фильтрам.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'KPI по событиям, ревью и архиву',
          'Сводные таблицы камер и Процессора',
          'Безопасность и действия пользователей',
        ],
        tags: ['отчёты', 'dashboard', 'архив', 'безопасность', 'процессор'],
      ),
    ],
  ),
  _HelpTab(
    id: 'management',
    label: 'Оборудование',
    description: 'Персоны, группы камер, камеры и Процессор.',
    sections: [
      _HelpSection(
        id: 'persons',
        title: 'Персоны',
        summary:
            'База персон хранит карточки людей и обучающие эмбеддинги для распознавания.',
        bullets: [
          'Карточка персоны содержит ФИО, количество эмбеддингов и историю появлений.',
          'Эмбеддинг можно добавить из файла или из текущего кадра выбранной камеры.',
          'Новую персону можно создать вручную или сразу из фотографии с извлечением лица на сервере.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Список персон с ФИО',
          'Эмбеддинги, кадр из эфира и история появлений',
          'Создание, редактирование и удаление карточек',
        ],
        tags: ['персоны', 'лица', 'эмбеддинги', 'распознавание'],
      ),
      _HelpSection(
        id: 'groups',
        title: 'Группы камер',
        summary:
            'Группы объединяют камеры по аудиториям, зонам или демонстрационным стендам.',
        bullets: [
          'Группы доступны всем пользователям для просмотра состава камер.',
          'Администратор может создавать, редактировать, удалять группы и назначать/отвязывать камеры.',
          'Группы используются в отчётах и как логический слой для демонстрационных зон.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Список групп',
          'Количество камер',
          'Описание зоны наблюдения',
        ],
        tags: ['группы', 'камеры', 'фильтр', 'зоны'],
      ),
      _HelpSection(
        id: 'cameras',
        title: 'Камеры',
        summary:
            'Камеры содержат параметры подключения, ONVIF/RTSP/HTTP данные и режимы обработки.',
        bullets: [
          'Мастер подключения ищет ONVIF, а ручное добавление подходит для RTSP/HTTP без discovery.',
          'В карточке камеры редактируются endpoint-адреса, режим записи, детекция, PTZ и трекинг.',
          'ROI зоны задают include/exclude области для будущей фильтрации детекции.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Автопоиск и ручное добавление',
          'Редактирование endpoint-адресов и режимов',
          'ONVIF refresh, ROI зоны и удаление',
        ],
        tags: ['камеры', 'onvif', 'rtsp', 'ptz', 'endpoint'],
      ),
      _HelpSection(
        id: 'processors',
        title: 'Процессор',
        summary:
            'Процессор обрабатывает видеопотоки, создаёт события, пишет архив и отдаёт телеметрию.',
        bullets: [
          'Камера должна быть назначена на Процессор для live, событий и архива.',
          'Dashboard показывает CPU/RAM/GPU, heartbeat, pending/running команды и назначенные камеры.',
          'Администратор может назначать камеры, генерировать код подключения и отправлять remote-команды.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Статус узла, IP и метрики',
          'Назначение камер',
          'Код подключения и история команд',
        ],
        tags: ['процессор', 'gpu', 'heartbeat', 'узел', 'код'],
      ),
    ],
  ),
  _HelpTab(
    id: 'admin',
    label: 'Администрирование',
    description: 'Пользователи, API-ключи и типовые проверки при сбоях.',
    sections: [
      _HelpSection(
        id: 'users',
        title: 'Пользователи',
        summary:
            'Администратор создаёт учётные записи, назначает роли и контролирует доступ.',
        bullets: [
          'Роль выбирается из списка: администратор, оператор или смотрящий.',
          'Для демонстрации лучше иметь отдельного оператора без лишних прав администратора.',
          'Текущего пользователя нельзя удалить из интерфейса, а временный пароль принудительно меняется при входе.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Логин и роль',
          'ФИО пользователя',
          'Создание и удаление учёток',
        ],
        tags: ['пользователи', 'роли', 'доступ', 'админ'],
      ),
      _HelpSection(
        id: 'api-keys',
        title: 'API ключи',
        summary: 'API-ключи используются для Процессора и сервисных интеграций.',
        bullets: [
          'Полное значение нового ключа показывается только при создании.',
          'Права, описание, активность и срок действия можно редактировать после создания.',
          'Неиспользуемые ключи лучше отключать или удалять.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Описание ключа',
          'Права и активность',
          'Создание и удаление',
        ],
        tags: ['api', 'ключи', 'scopes', 'процессор', 'безопасность'],
      ),
      _HelpSection(
        id: 'setup',
        title: 'CCTV Настройка',
        summary:
            'Раздел настройки задаёт публичный домен, nginx, Let’s Encrypt и профиль подключения Консоли без ручного редактирования конфигов.',
        bullets: [
          'Домен должен указывать на этот сервер, а порты 80 и 443 должны быть доступны для HTTP-01 проверки Let’s Encrypt.',
          'Мастер записывает DOMAIN, SSL_EMAIL, ALLOWED_HOSTS и CORS_ORIGINS в .env, генерирует недостающие секреты production-режима и поднимает nginx в bootstrap-режиме.',
          'После выпуска сертификата включается HTTPS, запускается certbot renew и создаётся профиль подключения Консоли на https://домен.',
          'На Android запуск Docker недоступен: команда копируется, а выполнять её нужно на серверной Windows/Linux машине из папки проекта.',
        ],
        previewTitle: 'Порядок настройки',
        previewLines: [
          'Указать домен и email',
          'Проверить DNS и сервер',
          'Запустить настройку или скопировать команду',
        ],
        tags: ['настройка', 'https', 'nginx', 'letsencrypt', 'домен'],
      ),
      _HelpSection(
        id: 'setup',
        title: 'CCTV Setup',
        summary:
            'Setup настраивает публичный домен, nginx, Let’s Encrypt и профиль подключения Console без ручного редактирования конфигов.',
        bullets: [
          'Домен должен указывать на этот сервер, а порты 80 и 443 должны быть доступны для HTTP-01 проверки Let’s Encrypt.',
          'Мастер записывает DOMAIN, SSL_EMAIL, ALLOWED_HOSTS и CORS_ORIGINS в .env, генерирует недостающие секреты production-режима и поднимает nginx в bootstrap-режиме.',
          'После выпуска сертификата включается HTTPS, запускается certbot renew и создаётся профиль подключения Console на https://домен.',
          'На Android запуск Docker недоступен: команда копируется, а выполнять её нужно на серверной Windows/Linux машине из папки проекта.',
        ],
        previewTitle: 'Порядок настройки',
        previewLines: [
          'Указать домен и email',
          'Проверить DNS и backend',
          'Запустить настройку или скопировать команду',
        ],
        tags: ['setup', 'https', 'nginx', 'letsencrypt', 'домен'],
      ),
      _HelpSection(
        id: 'troubleshooting',
        title: 'Типовые проблемы',
        summary:
            'Перед глубокой диагностикой проверьте связку сервера, Процессора, камеры и права пользователя.',
        bullets: [
          'Нет эфира: проверьте сервер, Процессор, назначение камеры и URL потока.',
          'Нет PTZ: проверьте ONVIF endpoint, логин/пароль и реальные возможности камеры.',
          'Нет фото в ревью: проверьте, сохраняет ли Процессор снимки для неизвестных событий.',
        ],
        previewTitle: 'Порядок проверки',
        previewLines: [
          'Backend и авторизация',
          'Процессор и поток камеры',
          'ONVIF, архив и снимки',
        ],
        tags: ['ошибки', 'диагностика', 'эфир', 'ptz', 'снимок'],
      ),
    ],
  ),
];
