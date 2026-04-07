import { useMemo, useState } from "react";
import { fuzzyFilter } from "../lib/fuzzy";

type HelpSection = {
  id: string;
  title: string;
  summary: string;
  bullets: string[];
  previewTitle: string;
  previewLines: string[];
  tags: string[];
};

type HelpTab = {
  id: string;
  label: string;
  description: string;
  sections: HelpSection[];
};

type SearchableSection = HelpSection & {
  tabId: string;
  tabLabel: string;
};

const HELP_TABS: HelpTab[] = [
  {
    id: "overview",
    label: "Общее",
    description: "Вход в систему, настройки клиента, профиль пользователя и основные принципы работы Console.",
    sections: [
      {
        id: "start",
        title: "Быстрый старт",
        summary: "После входа в систему проверьте подключение к backend, затем откройте Live, Записи или другие рабочие вкладки.",
        bullets: [
          "Если интерфейс пустой, сначала откройте Настройки и проверьте адрес backend.",
          "Роль пользователя определяет доступ к административным разделам и управлению оборудованием.",
          "Основные ошибки подключения обычно связаны с недоступным backend, Processor или неверной ролью.",
        ],
        previewTitle: "Что важно проверить сначала",
        previewLines: [
          "Адрес backend и состояние входа в систему",
          "Доступные вкладки в верхней панели",
          "Статус камер и Processor перед началом работы",
        ],
        tags: ["старт", "вход", "backend", "доступ", "роль", "подключение"],
      },
      {
        id: "settings",
        title: "Настройки",
        summary: "Во вкладке Настройки меняются профиль, двухфакторная авторизация, адрес backend и параметры интерфейса.",
        bullets: [
          "В профиле хранятся только фамилия, имя и отчество пользователя.",
          "TOTP подключается через QR-код и подтверждается одноразовым кодом из приложения-аутентификатора.",
          "Изменение адреса backend применяется локально только для текущего клиента Console.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Карточка профиля с ФИО пользователя",
          "Блок двухфакторной авторизации с QR-кодом и секретом",
          "Параметры темы, плотности Live и быстрых ссылок",
        ],
        tags: ["настройки", "профиль", "totp", "2fa", "backend", "тема"],
      },
      {
        id: "help",
        title: "Справка",
        summary: "Справка разбита на тематические вкладки и поддерживает неточный поиск по названиям разделов, действиям и ключевым словам.",
        bullets: [
          "Поиск можно использовать по названию вкладки, типу отчёта, роли или действию.",
          "Если точная формулировка неизвестна, достаточно ввести часть слова или короткий запрос.",
          "Когда поиск пустой, показываются только темы активной вкладки справки.",
        ],
        previewTitle: "Как пользоваться справкой",
        previewLines: [
          "Откройте нужную тематическую вкладку",
          "При необходимости используйте строку поиска",
          "Ориентируйтесь на краткие карточки без длинной непрерывной страницы",
        ],
        tags: ["справка", "поиск", "подсказки", "вкладки", "навигация"],
      },
    ],
  },
  {
    id: "monitoring",
    label: "Мониторинг",
    description: "Live-потоки, архив записей, ревью событий и сводная отчётность.",
    sections: [
      {
        id: "live",
        title: "Live",
        summary: "Страница Live показывает сетку камер, фильтр по группам и полноэкранный режим для одной камеры.",
        bullets: [
          "Плотность и размер сетки можно менять кнопками Авто, 1x1, 2x2 и 3x3.",
          "Позиции камер в фиксированной сетке можно переставлять перетаскиванием.",
          "В полноэкранном режиме для ONVIF-камер доступны PTZ, точки патруля и цифровой zoom через Ctrl + колесо мыши.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Фильтр по группе камер закреплён справа в панели Live",
          "Карточки потоков с названиями, статусом ONVIF и кнопкой разворота",
          "Полноэкранный режим с отдельной панелью управления камерой",
        ],
        tags: ["live", "потоки", "группа камер", "ptz", "onvif", "fullscreen", "сетка"],
      },
      {
        id: "recordings",
        title: "Записи",
        summary: "Записи открывают архив по дням, часам и клипам, которые доступны через назначенный Processor.",
        bullets: [
          "Если записей нет, сначала проверьте назначение камеры на Processor и режим записи камеры.",
          "Таймлайн дня показывает заполненные интервалы и позволяет быстро переходить к нужному часу.",
          "Доступность архива зависит от состояния Processor и фактического наличия файлов записи.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Выбор камеры и даты",
          "Таймлайн суток с переходом по часу",
          "Список доступных клипов за выбранный интервал",
        ],
        tags: ["записи", "архив", "таймлайн", "processor", "клипы", "дата"],
      },
      {
        id: "reviews",
        title: "Ревью событий",
        summary: "Ревью используется для подтверждения, отклонения и уточнения событий распознавания и детекции.",
        bullets: [
          "Поиск по персонам поддерживает неполные совпадения по ФИО и ID.",
          "На событие можно назначить существующую персону или создать новую карточку по кадру.",
          "Очередь ревью помогает быстро разбирать неподтверждённые события без перехода в другие разделы.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Список событий с кадром, временем и типом детекции",
          "Быстрые действия подтверждения и отклонения",
          "Окно выбора существующей персоны по поиску",
        ],
        tags: ["ревью", "события", "подтверждение", "персона", "поиск", "snapshot"],
      },
      {
        id: "reports",
        title: "Отчёты",
        summary: "Отчёты собраны в отдельные подвкладки по пользователям, камерам, процессорам, архиву, безопасности и подтверждённым появлениям.",
        bullets: [
          "Фильтры периода, группы, камеры, процессора и пользователя применяются ко всему dashboard.",
          "Для каждого раздела доступны экспорты PDF, XLSX и DOCX.",
          "Таблицы в экспортируемых файлах автоматически подгоняются под содержимое и ширину страницы.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Подвкладки отчётов без длинной непрерывной страницы",
          "KPI-карточки и диаграммы по активной теме",
          "Экспорт отдельного раздела в три формата",
        ],
        tags: ["отчёты", "dashboard", "экспорт", "pdf", "xlsx", "docx", "диаграммы"],
      },
    ],
  },
  {
    id: "management",
    label: "Оборудование",
    description: "Персоны, группы камер, камеры и Processor.",
    sections: [
      {
        id: "persons",
        title: "Персоны",
        summary: "База персон хранит карточки людей и эмбеддинги, используемые для распознавания.",
        bullets: [
          "Поиск по персонам допускает неполные совпадения и небольшие опечатки.",
          "Карточка персоны может пополняться снимками и эмбеддингами из live-потока.",
          "Результат распознавания в ревью и отчётах опирается на актуальные данные этой базы.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Список карточек с ФИО и количеством эмбеддингов",
          "Форма создания и редактирования персоны",
          "Инструменты для добавления ракурсов из live-потока",
        ],
        tags: ["персоны", "распознавание", "эмбеддинги", "поиск", "лицо", "галерея"],
      },
      {
        id: "groups",
        title: "Группы камер",
        summary: "Группы объединяют камеры по объектам, зонам или задачам наблюдения.",
        bullets: [
          "Группы используются как фильтр в Live и в отчётах.",
          "Состав группы помогает быстро работать с нужным набором камер без ручного выбора каждой камеры.",
          "Изменение состава группы влияет на отображение камер в связанных разделах интерфейса.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Список групп с количеством камер",
          "Выбранная группа и её состав",
          "Добавление и удаление камер из группы",
        ],
        tags: ["группы", "камеры", "фильтр", "live", "отчёты"],
      },
      {
        id: "cameras",
        title: "Камеры",
        summary: "Во вкладке Камеры настраиваются параметры камеры, endpoint-ы, ONVIF-метаданные, ROI и режимы записи.",
        bullets: [
          "Добавление камеры поддерживает probe по IP с логином и паролем для ONVIF, RTSP и HTTP.",
          "Во вкладке Камеры отображается информация о подключении, но PTZ-управление вынесено в полноэкранный Live.",
          "Если камера не поддерживает отдельные ONVIF-функции, лишние кнопки и элементы управления не показываются.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Карточка камеры с endpoint-ами и статусом ONVIF",
          "Настройки детекции, записи и отслеживания",
          "Синхронизация метаданных и пресетов камеры",
        ],
        tags: ["камеры", "onvif", "rtsp", "roi", "детекция", "запись", "probe"],
      },
      {
        id: "processors",
        title: "Процессоры",
        summary: "Processor обрабатывает видеопотоки, хранит архив и отчитывается backend о состоянии и назначениях.",
        bullets: [
          "Камера должна быть назначена на Processor, чтобы появились live-поток, события и архив.",
          "Во вкладке можно проверить heartbeat, системные метрики и текущее распределение камер.",
          "Ошибки открытия потока и проблемы обработки обычно сначала видны именно здесь.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Карточки Processor с метриками и статусом",
          "Список назначенных камер",
          "Инструменты регистрации и переподключения Processor",
        ],
        tags: ["processor", "метрики", "heartbeat", "назначение", "архив", "потоки"],
      },
    ],
  },
  {
    id: "admin",
    label: "Администрирование",
    description: "Пользователи, API-ключи и типовые проверки при сбоях.",
    sections: [
      {
        id: "users",
        title: "Пользователи",
        summary: "Администратор создаёт пользователей, назначает роли и управляет обязательной сменой пароля.",
        bullets: [
          "Профиль пользователя содержит только ФИО, логин и системные параметры доступа.",
          "Роль определяет доступ к административным разделам и операциям управления оборудованием.",
          "Действия пользователей попадают в отчёты и журнал событий безопасности.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Список пользователей и их ролей",
          "Форма создания учётной записи",
          "Управление ролью и обязательной сменой пароля",
        ],
        tags: ["пользователи", "роли", "администратор", "доступ", "пароль"],
      },
      {
        id: "api-keys",
        title: "API-ключи",
        summary: "Сервисные ключи используются для Processor и внутренних интеграций.",
        bullets: [
          "Полное значение нового ключа показывается только в момент создания.",
          "Для Processor предусмотрены преднастроенные scopes и сценарий регистрации через код подключения.",
          "Неиспользуемые ключи лучше отключать, а не хранить активными без необходимости.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Создание ключа с набором прав",
          "Список активных и отключённых ключей",
          "Пресеты для Processor и сервисных интеграций",
        ],
        tags: ["api-ключи", "processor", "scopes", "интеграции", "безопасность"],
      },
      {
        id: "troubleshooting",
        title: "Типовые проблемы",
        summary: "Перед глубокой диагностикой обычно достаточно проверить связку backend, Processor, камеру и права пользователя.",
        bullets: [
          "Если не открывается Live, проверьте backend, назначение камеры на Processor и доступность её потока.",
          "Если не работает PTZ, проверьте ONVIF endpoint, логин/пароль камеры и реальные возможности PTZ.",
          "Если в отчётах или настройках видны старые строки, перезапустите portable Console после обновления frontend.",
        ],
        previewTitle: "С чего начинать проверку",
        previewLines: [
          "Сначала backend и авторизация",
          "Затем Processor и поток камеры",
          "После этого ONVIF, архив и отчёты",
        ],
        tags: ["ошибки", "диагностика", "live", "ptz", "backend", "processor"],
      },
    ],
  },
];

function flattenSections(tabs: HelpTab[]): SearchableSection[] {
  return tabs.flatMap((tab) =>
    tab.sections.map((section) => ({
      ...section,
      tabId: tab.id,
      tabLabel: tab.label,
    }))
  );
}

const HelpPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<string>(HELP_TABS[0].id);
  const [query, setQuery] = useState("");

  const allSections = useMemo(() => flattenSections(HELP_TABS), []);
  const activeSections = useMemo(
    () => allSections.filter((section) => section.tabId === activeTab),
    [activeTab, allSections]
  );

  const visibleSections = useMemo(() => {
    if (!query.trim()) {
      return activeSections;
    }

    return fuzzyFilter(
      allSections,
      query,
      (section) => [section.title, section.summary, section.tags.join(" "), section.bullets.join(" ")],
      0.28
    );
  }, [activeSections, allSections, query]);

  const activeTabMeta = HELP_TABS.find((tab) => tab.id === activeTab) || HELP_TABS[0];

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <section className="toolbar-card help-toolbar">
        <div className="stack" style={{ gap: 6 }}>
          <h2 className="title">Справка</h2>
          <div className="muted">
            Краткие инструкции по текущим вкладкам Console: без длинной простыни и с поиском по ключевым словам.
          </div>
        </div>

        <div className="help-toolbar__side">
          <label className="field" style={{ minWidth: 320 }}>
            <span className="label">Поиск по справке</span>
            <input
              className="input"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Live, ONVIF, отчёты, Processor, TOTP..."
            />
          </label>
        </div>
      </section>

      <section className="panel-card stack">
        <div className="help-tabs">
          {HELP_TABS.map((tab) => (
            <button
              key={tab.id}
              className={tab.id === activeTab && !query.trim() ? "tab active" : "tab"}
              onClick={() => setActiveTab(tab.id)}
              type="button"
            >
              {tab.label}
            </button>
          ))}
        </div>

        {!query.trim() && <div className="muted">{activeTabMeta.description}</div>}
        {query.trim() && (
          <div className="muted">
            Найдено тем: <strong>{visibleSections.length}</strong>. Поиск учитывает названия разделов, подсказки и ключевые слова.
          </div>
        )}
      </section>

      {visibleSections.length === 0 ? (
        <section className="panel-card stack">
          <h3 className="panel-card__title">Совпадений не найдено</h3>
          <div className="muted">Попробуйте более короткий запрос, название вкладки или тип операции.</div>
        </section>
      ) : (
        <section className="grid help-grid">
          {visibleSections.map((section) => (
            <article key={`${section.tabId}-${section.id}`} className="panel-card stack help-section">
              <div className="panel-card__header">
                <div>
                  {query.trim() && <div className="page-hero__eyebrow">{section.tabLabel}</div>}
                  <h3 className="panel-card__title">{section.title}</h3>
                  <div className="panel-card__lead">{section.summary}</div>
                </div>
              </div>

              <div className="help-points">
                {section.bullets.map((bullet) => (
                  <div key={bullet} className="help-point">
                    {bullet}
                  </div>
                ))}
              </div>

              <div className="help-preview">
                <div className="help-preview__title">{section.previewTitle}</div>
                <div className="help-preview__shell">
                  {section.previewLines.map((line, index) => (
                    <div key={line} className={`help-preview__line${index === 0 ? " help-preview__line--hero" : ""}`}>
                      {line}
                    </div>
                  ))}
                </div>
              </div>
            </article>
          ))}
        </section>
      )}
    </div>
  );
};

export default HelpPage;
