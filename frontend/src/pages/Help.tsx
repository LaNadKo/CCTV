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
    description: "Вход, настройки и сама справка.",
    sections: [
      {
        id: "help",
        title: "Справка",
        summary: "Раздел с вкладками по блокам, подсказками по интерфейсу и неточным поиском по темам.",
        bullets: [
          "Верхняя строка ищет темы по названиям вкладок, действиям и ключевым словам.",
          "Если ввести часть слова или допустить небольшую опечатку, поиск всё равно покажет близкие совпадения.",
          "Переключатели сверху делят справку на крупные блоки, чтобы длинный текст не превращался в одну бесконечную страницу.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Поиск по справке, вкладки разделов и карточки тем",
          "Краткое описание каждой страницы без перехода в другие окна",
          "Мини-макеты интерфейса для быстрого ориентирования",
        ],
        tags: ["справка", "поиск", "вкладки", "подсказки", "темы"],
      },
      {
        id: "settings",
        title: "Настройки",
        summary: "Здесь меняются адрес backend, тема, плотность Live и состав быстрого доступа в верхней панели.",
        bullets: [
          "Тема и плотность Live применяются сразу после выбора.",
          "Панель быстрого доступа собирается из выбранных вкладок и теперь поддерживает перестановку мест.",
          "Адрес backend сохраняется отдельно, потому что его смена обычно связана с переподключением клиента.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Карточки быстрого доступа с позициями, стрелками и перетаскиванием",
          "Переключатели темы и плотности Live",
          "Поле API URL и кнопки сохранения адреса",
        ],
        tags: ["настройки", "тема", "быстрый доступ", "live", "api url", "панель"],
      },
    ],
  },
  {
    id: "monitoring",
    label: "Мониторинг",
    description: "Live, записи, ревью и отчёты.",
    sections: [
      {
        id: "live",
        title: "Live",
        summary: "Живые MJPEG-потоки камер, фильтр по группе и полноэкранный режим для отдельной карточки.",
        bullets: [
          "Если поток недоступен, проверьте назначение камеры на Processor и его статус во вкладке «Процессоры».",
          "Плотность сетки Live берётся из настроек интерфейса.",
          "Кнопка в правом верхнем углу карточки разворачивает выбранную камеру на весь экран.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Фильтр по группе камер и счётчик выбранного среза",
          "Сетка live-карточек с названием, локацией и кнопкой fullscreen",
          "Пустая карточка с подсказкой, если поток не пришёл с Processor",
        ],
        tags: ["live", "поток", "камера", "fullscreen", "группа"],
      },
      {
        id: "recordings",
        title: "Записи",
        summary: "Архив по дням, лента суток с часовыми метками, переход к часам и просмотр минутных клипов.",
        bullets: [
          "Верхняя панель переключает камеру и день. Переход в будущие даты недоступен.",
          "Лента дня показывает отрезки записи и маркеры событий. Заполненные зоны можно кликать прямо на таймлайне.",
          "Нижняя часовая шкала даёт быстрый переход в нужный час архива.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Выбор камеры, даты и кнопка обновления",
          "Таймлайн дня с часовыми делениями и цветными маркерами событий",
          "Папки часов и карточки минутных клипов внутри выбранного часа",
        ],
        tags: ["записи", "архив", "таймлайн", "дата", "часы", "клипы"],
      },
      {
        id: "reviews",
        title: "Ревью",
        summary: "Очередь событий на подтверждение: snapshot, видеофрагмент, person_id и быстрые действия.",
        bullets: [
          "События с unknown face обычно попадают сюда автоматически и ждут решения оператора.",
          "Можно сразу создать новую персону из snapshot или назначить существующую карточку через всплывающее окно выбора.",
          "Кнопка «Отклонить всё» полезна, если очередь накопилась после шумного участка записи.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Сводка по очереди, snapshot и доступным видео",
          "Карточка события с кадром, confidence и кнопками одобрения",
          "Форма создания персоны прямо из кадра ревью",
        ],
        tags: ["ревью", "snapshot", "видео", "approve", "reject", "unknown face"],
      },
      {
        id: "reports",
        title: "Отчёты",
        summary: "Отчёт по подтверждённым появлениям с фильтрами по времени и персоне и экспортом в PDF/XLSX/DOCX.",
        bullets: [
          "Поиск персоны работает неточно, так же как и во вкладке «Персоны».",
          "Если фильтр по персоне пустой, отчёт строится по всем подтверждённым событиям в диапазоне.",
          "Экспорт формирует файл прямо с backend и отдаёт его на скачивание в браузер.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Фильтры по началу и концу периода",
          "Неточный поиск по персоне с выпадающим списком",
          "Таблица событий и кнопки экспорта в три формата",
        ],
        tags: ["отчёты", "экспорт", "pdf", "xlsx", "docx", "персона", "период"],
      },
    ],
  },
  {
    id: "management",
    label: "Управление",
    description: "Персоны, группы, камеры и процессоры.",
    sections: [
      {
        id: "persons",
        title: "Персоны",
        summary: "База людей для распознавания: поиск, редактирование карточки и пополнение эмбеддингов с live-потока.",
        bullets: [
          "Неточный поиск нормализует строку, убирает лишние символы и сравнивает слова по близости через расстояние Левенштейна.",
          "Live-сбор эмбеддингов поддерживает ручной capture и обычный автосбор без фиксированного сценария.",
          "Если снимок слишком похож на уже сохранённый ракурс, система пометит его как duplicate и не будет плодить копии.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Поиск по ФИО или ID и список карточек с числом эмбеддингов",
          "Редактирование текущей персоны и создание новой карточки",
          "Live-поток с рамкой лица, общей подсказкой и прогрессом автосбора",
        ],
        tags: ["персоны", "поиск", "эмбеддинги", "live", "ракурс", "левенштейн"],
      },
      {
        id: "groups",
        title: "Группы",
        summary: "Логическое объединение камер для фильтрации Live, архива и административных сценариев.",
        bullets: [
          "Администратор создаёт группу, редактирует её описание и управляет составом камер.",
          "Оператор и наблюдатель могут использовать группы как фильтр, даже если не редактируют их.",
          "Состав выбранной группы всегда виден справа без перехода на отдельную страницу.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Список групп с количеством камер",
          "Карточка выбранной группы и состав назначенных камер",
          "Форма добавления свободной камеры в текущую группу",
        ],
        tags: ["группы", "камеры", "состав", "фильтр", "назначение"],
      },
      {
        id: "cameras",
        title: "Камеры",
        summary: "Административная карточка камеры: базовые параметры, режим записи, PTZ-пресеты, ROI и трекинг.",
        bullets: [
          "Список слева группируется по локациям, чтобы быстрее находить нужную камеру.",
          "В правой колонке собраны базовые поля, а ниже отдельно идут PTZ, ROI и ONVIF-трекинг.",
          "Изменения в режиме записи и детекции влияют на поведение архива и событий.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Форма создания камеры и список по локациям",
          "Карточка выбранной камеры с режимами записи и детекции",
          "Отдельные блоки для PTZ-пресетов, ROI и ONVIF-трекинга",
        ],
        tags: ["камеры", "ptz", "roi", "onvif", "детекция", "запись"],
      },
      {
        id: "processors",
        title: "Процессоры",
        summary: "Подключение вычислительных узлов, мониторинг метрик и распределение камер по Processor.",
        bullets: [
          "Сначала генерируется код подключения, затем Processor обменивает его на постоянный API-ключ.",
          "Страница показывает heartbeat, системные метрики, версии и список назначенных камер.",
          "Если live или записи недоступны, обычно сначала стоит проверить именно эту вкладку.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Код подключения с сроком действия и кнопкой копирования",
          "Карточки Processor с CPU, RAM, GPU и сетевой активностью",
          "Список назначенных камер и блок свободных камер для назначения",
        ],
        tags: ["процессоры", "processor", "код", "метрики", "heartbeat", "назначение"],
      },
    ],
  },
  {
    id: "admin",
    label: "Администрирование",
    description: "Пользователи и сервисные ключи.",
    sections: [
      {
        id: "users",
        title: "Пользователи",
        summary: "Создание учётных записей, смена ролей и контроль флага обязательной смены пароля.",
        bullets: [
          "Нового пользователя создаёт только администратор.",
          "Роль текущего пользователя нельзя сменить из его же строки, чтобы не потерять доступ случайным кликом.",
          "Комбобокс роли подстраивается под тему интерфейса и не должен сливаться с фоном.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Форма создания пользователя с логином, паролем и ролью",
          "Таблица текущих учётных записей и статусов",
          "Комбобокс роли и кнопка удаления в строке пользователя",
        ],
        tags: ["пользователи", "роль", "логин", "пароль", "комбобокс"],
      },
      {
        id: "api-keys",
        title: "API-ключи",
        summary: "Сервисные ключи для Processor и других интеграций: presets, scopes, активация и отключение.",
        bullets: [
          "Preset «Processor» подставляет минимальный набор scopes для регистрации и heartbeat.",
          "Полное значение ключа показывается только один раз сразу после создания.",
          "Старый ключ можно отключить, не удаляя его из истории.",
        ],
        previewTitle: "Что видно на экране",
        previewLines: [
          "Пресеты scopes и поле произвольного набора прав",
          "Карточка созданного ключа с полным значением только один раз",
          "Список ключей со статусом, scopes и действиями включения или отключения",
        ],
        tags: ["api-ключи", "scopes", "processor", "preset", "сервисный ключ"],
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
            Раздел разбит по блокам интерфейса: можно открыть нужную вкладку или найти тему через неточный поиск.
          </div>
        </div>

        <div className="help-toolbar__side">
          <label className="field" style={{ minWidth: 280 }}>
            <span className="label">Неточный поиск по справке</span>
            <input
              className="input"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Live, архив, роли, процессор, ракурс..."
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
            Найдено тем: <strong>{visibleSections.length}</strong>. Поиск идёт по названиям вкладок, действиям, подсказкам и ключевым словам.
          </div>
        )}
      </section>

      {visibleSections.length === 0 ? (
        <section className="panel-card stack">
          <h3 className="panel-card__title">Совпадений не найдено</h3>
          <div className="muted">
            Попробуйте более короткий запрос, ключевое слово без окончания или название нужной вкладки.
          </div>
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
