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
                'Краткие инструкции по вкладкам Console, диагностике и типовым операциям.',
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
              hintText: 'Live, ONVIF, отчёты, Processor, TOTP...',
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
        'Вход в систему, настройки клиента, профиль пользователя и принципы работы Console.',
    sections: [
      _HelpSection(
        id: 'start',
        title: 'Быстрый старт',
        summary:
            'После входа проверьте подключение к backend, затем откройте Live, Записи или другой рабочий раздел.',
        bullets: [
          'Если интерфейс пустой, сначала откройте Настройки и проверьте адрес backend.',
          'Роль пользователя определяет доступ к админ-разделам и управлению оборудованием.',
          'Ошибки подключения чаще всего связаны с backend, Processor или недоступной камерой.',
        ],
        previewTitle: 'Что проверить сначала',
        previewLines: [
          'Адрес backend и состояние входа',
          'Доступные вкладки в верхней панели',
          'Статус камер и Processor перед демонстрацией',
        ],
        tags: ['старт', 'вход', 'backend', 'доступ', 'роль'],
      ),
      _HelpSection(
        id: 'settings',
        title: 'Настройки',
        summary:
            'В настройках меняются backend URL, тема, акцентные цвета, плотность Live и состав верхнего меню.',
        bullets: [
          'Адрес backend сохраняется локально для текущего клиента.',
          'Верхнее меню поддерживает до пяти быстрых вкладок, остальные остаются в меню.',
          'Сброс оформления возвращает стандартные цвета, тему и плотность Live.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Backend URL и кнопка сохранения',
          'Тема, цвета и плотность Live',
          'Порядок вкладок верхнего меню',
        ],
        tags: ['настройки', 'backend', 'тема', 'меню', 'live'],
      ),
      _HelpSection(
        id: 'help',
        title: 'Справка',
        summary:
            'Справка разбита на тематические вкладки и поддерживает поиск по ключевым словам.',
        bullets: [
          'Ищите по названию вкладки, типу операции, роли, ONVIF, Processor или отчётам.',
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
    description: 'Live-потоки, архив записей, ревью событий и отчётность.',
    sections: [
      _HelpSection(
        id: 'live',
        title: 'Live',
        summary:
            'Live показывает сетку камер, состояние потоков и быстрые ONVIF/PTZ команды.',
        bullets: [
          'Плотность сетки меняется в настройках клиента.',
          'ONVIF/PTZ доступен только для камер с поддержкой и правами администратора.',
          'Если нет live-потока, проверьте Processor, назначение камеры и доступность URL потока.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Карточки камер с потоками',
          'Статус ONVIF, DETECT и режим записи',
          'PTZ-кнопки для совместимых камер',
        ],
        tags: ['live', 'потоки', 'ptz', 'onvif', 'камера'],
      ),
      _HelpSection(
        id: 'recordings',
        title: 'Записи',
        summary:
            'Записи показывают архив файлов, которые backend получил или зарегистрировал от Processor.',
        bullets: [
          'Если записей нет, проверьте режим записи камеры и назначение на Processor.',
          'Размер файла помогает быстро отличить пустые или повреждённые записи.',
          'Фильтрацию по периоду и камере лучше добавлять после стабилизации базового архива.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'ID записи, камера и тип файла',
          'Время начала и длительность',
          'Размер и путь файла',
        ],
        tags: ['записи', 'архив', 'processor', 'файлы', 'камера'],
      ),
      _HelpSection(
        id: 'reviews',
        title: 'Ревью событий',
        summary:
            'Ревью используется для подтверждения или отклонения неизвестных событий распознавания.',
        bullets: [
          'Карточка события показывает кадр, камеру, время, тип и уверенность.',
          'Подтверждение оставляет событие как проверенное, отклонение убирает его из очереди.',
          'Если фото отсутствует, Processor или backend не сохранил snapshot для события.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Фото события из snapshot',
          'Камера, время и уверенность',
          'Кнопки подтвердить и отклонить',
        ],
        tags: ['ревью', 'snapshot', 'события', 'подтверждение', 'детекция'],
      ),
      _HelpSection(
        id: 'reports',
        title: 'Отчёты',
        summary:
            'Отчёты собирают состояние камер, Processor, событий, архива и безопасности.',
        bullets: [
          'Dashboard показывает ключевые показатели по системе за выбранный период backend.',
          'Камеры и Processor помогают быстро найти сбой обработки или записи.',
          'Раздел безопасности показывает пользователей, API-ключи и ошибки входа.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'KPI по событиям, ревью и архиву',
          'Сводные таблицы камер и Processor',
          'Безопасность и действия пользователей',
        ],
        tags: ['отчёты', 'dashboard', 'архив', 'безопасность', 'processor'],
      ),
    ],
  ),
  _HelpTab(
    id: 'management',
    label: 'Оборудование',
    description: 'Персоны, группы камер, камеры и Processor.',
    sections: [
      _HelpSection(
        id: 'persons',
        title: 'Персоны',
        summary:
            'База персон хранит карточки людей и обучающие эмбеддинги для распознавания.',
        bullets: [
          'Карточка персоны содержит ФИО и количество эмбеддингов.',
          'Качество распознавания зависит от актуальности и разнообразия обучающих кадров.',
          'Удаление персоны влияет на последующие события и ревью.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Список персон с ФИО',
          'Количество эмбеддингов',
          'Создание и удаление карточек',
        ],
        tags: ['персоны', 'лица', 'эмбеддинги', 'распознавание'],
      ),
      _HelpSection(
        id: 'groups',
        title: 'Группы камер',
        summary:
            'Группы объединяют камеры по аудиториям, зонам или демонстрационным стендам.',
        bullets: [
          'Группы используются как логический фильтр для Live и отчётов.',
          'Название группы должно быть понятным для демонстрации и обслуживания.',
          'Пустые группы не мешают работе, но могут путать операторов.',
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
          'ONVIF refresh обновляет метаданные камеры и её возможности.',
          'PTZ появляется только если камера и backend подтвердили поддержку.',
          'Если поток не открывается, проверьте IP, endpoint, логин, пароль и доступность камеры из сети backend.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Название, IP и локация',
          'ONVIF, PTZ и режим записи',
          'Обновление ONVIF и удаление',
        ],
        tags: ['камеры', 'onvif', 'rtsp', 'ptz', 'endpoint'],
      ),
      _HelpSection(
        id: 'processors',
        title: 'Processor',
        summary:
            'Processor обрабатывает видеопотоки, создаёт события, пишет архив и отдаёт телеметрию.',
        bullets: [
          'Камера должна быть назначена на Processor для live, событий и архива.',
          'Heartbeat показывает, что узел обработки жив и связан с backend.',
          'Код подключения нужен при первичной регистрации нового Processor.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Статус узла и IP',
          'Версия и последний heartbeat',
          'Код подключения Processor',
        ],
        tags: ['processor', 'gpu', 'heartbeat', 'узел', 'код'],
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
          'Роль определяет доступ к ревью, отчётам и админ-разделам.',
          'Для демонстрации лучше иметь отдельного оператора без лишних прав администратора.',
          'Обязательная смена пароля помогает безопасно выдавать временные учётки.',
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
        summary: 'API-ключи используются для Processor и сервисных интеграций.',
        bullets: [
          'Полное значение нового ключа показывается только при создании.',
          'Scopes ограничивают, какие действия может выполнять ключ.',
          'Неиспользуемые ключи лучше удалять или отключать.',
        ],
        previewTitle: 'Что видно на экране',
        previewLines: [
          'Описание ключа',
          'Scopes и активность',
          'Создание и удаление',
        ],
        tags: ['api', 'ключи', 'scopes', 'processor', 'безопасность'],
      ),
      _HelpSection(
        id: 'troubleshooting',
        title: 'Типовые проблемы',
        summary:
            'Перед глубокой диагностикой проверьте связку backend, Processor, камеры и права пользователя.',
        bullets: [
          'Нет Live: проверьте backend, Processor, назначение камеры и stream URL.',
          'Нет PTZ: проверьте ONVIF endpoint, логин/пароль и реальные возможности камеры.',
          'Нет фото в ревью: проверьте, сохраняет ли Processor snapshot_b64 для неизвестных событий.',
        ],
        previewTitle: 'Порядок проверки',
        previewLines: [
          'Backend и авторизация',
          'Processor и поток камеры',
          'ONVIF, архив и snapshot',
        ],
        tags: ['ошибки', 'диагностика', 'live', 'ptz', 'snapshot'],
      ),
    ],
  ),
];
