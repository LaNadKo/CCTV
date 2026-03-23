# CCTV Console

Программный комплекс видеонаблюдения с распознаванием лиц, ревью событий и отдельным вычислительным модулем `Processor`.

Система состоит из 3 основных частей:
- `Console` — основной пользовательский интерфейс для администратора и оператора
- `Backend` — API, база данных, авторизация, отчёты и координация обработки
- `Processor` — модуль, который подключается к камерам, обрабатывает поток и передаёт результаты в систему

## Актуальное состояние

Актуально для текущей итерации проекта на `21 марта 2026`.

Приоритет разработки сейчас:
- `Desktop / Web Console`
- `Processor`
- backend и медиапайплайн между ними

Мобильный клиент сохранён в репозитории, но пока не является основным направлением развития и может отставать по возможностям от `Console`.

## Что уже умеет программа

### Console
- просмотр списка камер и live-потока
- работа с архивом записей и таймлайном по суткам
- ревью событий с подтверждением или отклонением обнаружений
- ведение базы персон и сбор эмбеддингов лица
- управление пользователями, ролями, группами камер и процессорами
- отчёты по появлениям с экспортом
- встроенная справка по основным разделам
- настройка интерфейса, панели быстрого доступа и цветовой темы

### Processor
- подключение к серверу по коду
- получение назначенных камер от backend
- обработка видеопотока и отправка heartbeat
- детекция лица и человека
- сопровождение треков даже в сценариях, где тело определяется не полностью
- настройка частоты сканирования и частоты обновления overlay
- быстрые пресеты производительности
- отдельный GUI в стиле `Console`
- настройка цветовой темы интерфейса

### Backend
- REST API на `FastAPI`
- хранение данных в `PostgreSQL`
- роли, авторизация и смена пароля
- работа с камерами, группами, пользователями, персонами и ревью
- выдача кодов подключения для `Processor`
- отчёты и экспорт
- медиасервер `MediaMTX` в серверном стеке

## Архитектура

```text
Console (Web / Electron)
        |
        v
   FastAPI Backend  <---->  PostgreSQL
        |
        +----> MediaMTX
        |
        +----> Processor
                    |
                    +----> RTSP / ONVIF / локальные источники
```

## Схемы работы

### 1. Схема развёртывания

```text
┌────────────────────┐
│   Console Web      │
│   Console Desktop  │
└─────────┬──────────┘
          │ HTTP / JWT
          v
┌────────────────────┐
│   Backend API      │
│   FastAPI          │
└───┬─────────┬──────┘
    │         │
    │         └─────────────────────┐
    v                               v
┌───────────────┐           ┌────────────────┐
│ PostgreSQL    │           │ MediaMTX       │
│ users/events  │           │ RTSP server    │
└───────────────┘           └────────────────┘
                                        ^
                                        │
                           publish / consume media
                                        │
                               ┌────────┴────────┐
                               │   Processor     │
                               │ detection/track │
                               └────────┬────────┘
                                        │
                                        v
                               ┌─────────────────┐
                               │ RTSP / ONVIF /  │
                               │ local sources   │
                               └─────────────────┘
```

### 2. Медиапоток live и архива

```text
Camera / RTSP source
        |
        v
   Processor
   - opens stream
   - detects face/person
   - draws overlay
   - writes snapshots / recordings
        |
        +----------------------> Backend metadata
        |                        - detections
        |                        - review queue
        |                        - recording index
        |
        +----------------------> Media endpoint / file storage
                                 |
                                 v
                           Console requests
                           - live stream
                           - recordings
                           - event snapshots
```

### 3. Подключение Processor

```text
Administrator in Console
        |
        | generate connection code
        v
     Backend
        |
        | one-time registration data
        v
    Processor GUI
        |
        | sends code + backend URL
        v
     Backend
        |
        | returns processor identity + API key
        v
    Processor runtime
        |
        +--> heartbeat
        +--> gallery sync
        +--> camera assignments
        +--> detections / media metadata
```

### 4. Цепочка ревью событий

```text
Camera frame
    |
    v
Processor detection
    |
    +--> known person  ---------> event in backend
    |
    +--> unknown / uncertain ---> review queue
                                   |
                                   v
                              Console / Review
                                   |
                    approve + assign person / reject
                                   |
                                   v
                              reports / timeline / archive
```

## Состав проекта

| Компонент | Назначение | Технологии |
|-----------|------------|------------|
| `frontend/` | веб-интерфейс `Console` | React, TypeScript, Vite |
| `desktop/` | десктопная упаковка `Console` | Electron, electron-builder, Inno Setup |
| `app/` | серверная часть | FastAPI, SQLAlchemy, Alembic |
| `processor/` | обработчик видеопотока и GUI | Python, OpenCV, PyTorch, CustomTkinter |
| `mobile/` | мобильный клиент | React Native, Expo |
| `scripts/` | управление серверным стеком | Bash |

## Основные сценарии использования

### 1. Работа через IP-камеру

Система может использовать:
- прямой `RTSP` URL
- `ONVIF`-камеру с получением потока и параметров
- локальный источник, если это необходимо для тестов

Пример `RTSP`-источника:

```text
rtsp://192.168.50.3:554/stream1
```

### 2. Работа через локальный RTSP-источник

Если под рукой нет отдельной IP-камеры, можно опубликовать поток с веб-камеры ноутбука или USB-камеры в `MediaMTX` через `ffmpeg`, а затем использовать его как обычный `RTSP`-источник.

Пример для Windows:

```powershell
ffmpeg -f dshow -i video="USB2.0 HD UVC WebCam" -an -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/webcam
```

После этого поток будет доступен по адресу:

```text
rtsp://127.0.0.1:8554/webcam
```

Это удобно для демонстрации системы без отдельного сетевого оборудования.

## Что важно для текущей версии

### Console
- интерфейс ориентирован на desktop и web
- настройки применяются сразу, без отдельного сохранения
- порядок вкладок быстрого доступа можно менять
- в `Recordings` есть ограничение на переход в будущие даты
- в `Review` работа с персонами переведена на выбор из всплывающего окна
- в `Persons` live-сбор эмбеддингов упрощён и не зависит от жёсткого сценария поз

### Processor
- поддерживает head-only кейсы лучше, чем в ранних итерациях
- частота сканирования и частота overlay настраиваются независимо
- есть быстрые пресеты нагрузки
- GUI приведён к единому стилю с `Console`
- добавлена кастомизация цветовой темы

## Статус модулей

| Модуль | Статус |
|--------|--------|
| `Backend` | рабочий |
| `Console Web` | рабочий |
| `Console Desktop` | рабочий |
| `Processor` | рабочий, в активной доработке |
| `MediaMTX` | рабочий |
| `Mobile` | не в приоритете |

## Быстрый запуск серверной части

Полный серверный стек поднимает:
- `PostgreSQL`
- `Backend`
- `MediaMTX`

### Вариант 1. Скрипт установки

```bash
bash <(curl -Ls https://raw.githubusercontent.com/LaNadKo/CCTV/main/install.sh)
```

Скрипт:
- проверяет Docker
- клонирует проект
- создаёт `.env`
- поднимает `db`, `backend`, `mediamtx`
- применяет миграции
- создаёт администратора

### Вариант 2. Запуск из репозитория

```bash
./scripts/start-server.sh
```

Полезные команды:

```bash
./scripts/start-server.sh
./scripts/stop-server.sh
./scripts/logs.sh
./scripts/logs.sh backend
./scripts/reset-db.sh
```

После запуска обычно доступны:
- API: `http://127.0.0.1:8000`
- Swagger: `http://127.0.0.1:8000/docs`
- RTSP сервер `MediaMTX`: `rtsp://127.0.0.1:8554`

## Учётная запись по умолчанию

После первичной инициализации создаётся администратор:

- логин: `admin`
- пароль: `admin`

При первом входе пароль нужно сменить.

## Подключение Processor

Стандартный сценарий:
1. В `Console` администратор генерирует код подключения.
2. На машине с доступом к камерам запускается `Processor`.
3. Вводится адрес backend и код подключения.
4. `Processor` регистрируется и начинает получать назначения камер.

`Processor` отправляет heartbeat и системные метрики, поэтому в `Console` видно его состояние.

## Локальная разработка

### Backend

```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Processor

```bash
cd processor
pip install -r requirements.txt
python run_gui.py
```

Для headless-режима:

```bash
python run_gui.py --headless
```

## Сборка приложений

Перед сборкой на чистом Windows-ПК должны быть установлены:
- `Node.js` и `npm`
- `Python 3.11`
- `Inno Setup 6` (`ISCC.exe`)

Для первой Windows-сборки `Console` рекомендуется либо включить `Windows Developer Mode`, либо запускать терминал от имени администратора. Иначе `electron-builder` может завершиться ошибкой при распаковке `winCodeSign` с сообщением о невозможности создать symbolic link. Также при первой сборке требуется доступ в интернет для загрузки служебных бинарников `electron-builder`.

### Console Installer / Portable

```bash
cd frontend
npm install
cd desktop
npm install
npm run build:win
```

Результат:
- установщик: `desktop/release/`
- portable: `desktop/release/win-unpacked/`

### Processor Installer

```bash
cd processor
pip install -r requirements.txt
python build_exe.py
iscc installer.iss
```

Результат:
- сборка `PyInstaller`: `processor/dist/`
- установщик: `processor/installer_output/`

## Структура репозитория

```text
.
├── .dockerignore                    # исключения для Docker build
├── .env.example                     # шаблон переменных окружения
├── .gitignore                       # исключения git
├── alembic.ini                      # конфигурация Alembic
├── CCTV-Processor.spec              # PyInstaller-спецификация для Processor
├── docker-compose.yml               # основной compose-стек проекта
├── Dockerfile                       # Dockerfile backend-контейнера
├── docker-entrypoint.sh             # entrypoint контейнера backend
├── init-ssl.sh                      # вспомогательная инициализация SSL для nginx
├── install.sh                       # автоматическая установка серверной части
├── README.md                        # основная документация проекта
├── requirements.txt                 # Python-зависимости backend
├── start-all-docker.bat             # запуск docker-стека под Windows
├── start-all.bat                    # локальный запуск основных компонентов
├── start-backend.bat                # запуск backend под Windows
├── start-db.bat                     # запуск БД под Windows
├── start-frontend.bat               # запуск frontend под Windows
├── start-local.bat                  # локальный запуск без общего сценария
├── stop-all.bat                     # остановка Windows-сценария
├── stop-local.bat                   # остановка локального запуска
├── nginx/
│   └── default.conf.template        # шаблон reverse proxy для nginx
├── migrations/
│   ├── README                       # служебное описание Alembic
│   ├── env.py                       # окружение миграций
│   ├── script.py.mako               # шаблон генерации миграций
│   └── versions/
│       ├── 0001_full_schema.py      # базовая схема БД
│       ├── 0002_groups_processors.py# расширение по группам и processor
│       └── 0003_soft_delete.py      # soft delete и связанные правки
├── scripts/
│   ├── logs.sh                      # просмотр логов compose-стека
│   ├── reset-db.sh                  # полный сброс БД и повторный запуск
│   ├── seed_data.py                 # начальные данные и тестовые сущности
│   ├── smoke_api.py                 # smoke-тест основных API-сценариев
│   ├── start-server.sh              # запуск db + backend + mediamtx
│   └── stop-server.sh               # остановка серверного стека
├── yolov8n-pose.pt                  # модель pose detection для Processor
├── yolov8n.pt                       # дополнительная YOLO-модель
├── app/
│   ├── __init__.py                  # пакет backend
│   ├── camera_utils.py              # выбор и нормализация источника камеры
│   ├── config.py                    # настройки backend из env
│   ├── db.py                        # async session / engine
│   ├── dependencies.py              # зависимости FastAPI и auth helper-ы
│   ├── detector.py                  # серверная координация событий/детекций
│   ├── main.py                      # точка входа FastAPI, startup и routers
│   ├── models.py                    # SQLAlchemy-модели БД
│   ├── permissions.py               # проверка ролей и прав доступа
│   ├── processor_media.py           # проксирование media-ресурсов processor
│   ├── security.py                  # JWT, хеширование паролей, токены
│   ├── vision.py                    # backend-часть face vision helper-ов
│   ├── routers/
│   │   ├── __init__.py              # пакет routers
│   │   ├── admin.py                 # админ-операции, камеры, стримы, пользователи
│   │   ├── api_keys.py              # API-ключи
│   │   ├── auth.py                  # логин, токены, смена пароля
│   │   ├── cameras.py               # список камер и live stream proxy
│   │   ├── detections.py            # события, pending review, snapshots
│   │   ├── face.py                  # биометрия, face-login, enroll
│   │   ├── groups.py                # группы камер
│   │   ├── homes.py                 # заготовка маршрутов домов/объектов
│   │   ├── persons.py               # база персон и эмбеддинги
│   │   ├── processors.py            # регистрация и управление processor
│   │   ├── recordings.py            # архив, файлы записей, proxy playback
│   │   ├── reports.py               # отчёты и экспорт
│   │   └── users.py                 # профиль пользователя и связанное API
│   ├── schemas/
│   │   ├── __init__.py              # пакет Pydantic-схем
│   │   ├── api_keys.py              # схемы API-ключей
│   │   ├── auth.py                  # схемы авторизации
│   │   ├── camera_admin.py          # admin-схемы камер и stream-конфигов
│   │   ├── cameras.py               # схемы камер
│   │   ├── detections.py            # схемы событий/ревью
│   │   ├── face.py                  # схемы face API
│   │   ├── groups.py                # схемы групп
│   │   ├── homes.py                 # схемы homes-модуля
│   │   ├── persons.py               # схемы персон и эмбеддингов
│   │   ├── processors.py            # схемы processor API
│   │   ├── recordings.py            # схемы записей
│   │   ├── reports.py               # схемы отчётов
│   │   └── users.py                 # схемы пользователей
│   └── storage/
│       ├── __init__.py              # пакет storage backends
│       ├── base.py                  # базовый интерфейс хранилища
│       ├── factory.py               # фабрика storage backend
│       ├── ftp.py                   # FTP-хранилище
│       ├── local.py                 # локальное файловое хранилище
│       └── s3.py                    # S3-совместимое хранилище
├── frontend/
│   ├── eslint.config.js             # ESLint-конфигурация
│   ├── index.html                   # HTML-точка входа Vite
│   ├── package-lock.json            # lockfile npm
│   ├── package.json                 # зависимости и скрипты frontend
│   ├── tsconfig.app.json            # TS-конфиг приложения
│   ├── tsconfig.json                # базовый TS-конфиг
│   ├── tsconfig.node.json           # TS-конфиг node-инструментов
│   ├── vite.config.ts               # конфиг Vite / PWA-сборки
│   ├── public/
│   │   ├── apple-touch-icon.png     # PWA-иконка Apple
│   │   ├── favicon.png              # favicon
│   │   ├── icon.svg                 # базовая иконка приложения
│   │   ├── vite.svg                 # иконка шаблона Vite
│   │   └── icons/
│   │       ├── icon-72x72.png       # PWA icon 72
│   │       ├── icon-96x96.png       # PWA icon 96
│   │       ├── icon-128x128.png     # PWA icon 128
│   │       ├── icon-144x144.png     # PWA icon 144
│   │       ├── icon-152x152.png     # PWA icon 152
│   │       ├── icon-192x192.png     # PWA icon 192
│   │       ├── icon-384x384.png     # PWA icon 384
│   │       └── icon-512x512.png     # PWA icon 512
│   └── src/
│       ├── App.tsx                  # роутинг, shell и навигация Console
│       ├── app.css                  # основная стилизация интерфейса
│       ├── index.css                # глобальные стили и CSS-переменные
│       ├── main.tsx                 # точка входа React
│       ├── assets/
│       │   └── react.svg            # служебный svg-asset
│       ├── context/
│       │   └── AuthContext.tsx      # контекст авторизации
│       ├── hooks/
│       │   └── usePWA.ts            # PWA helper-логика
│       ├── lib/
│       │   ├── api.ts               # HTTP API-клиент
│       │   ├── fuzzy.ts             # неточный поиск
│       │   ├── personNames.ts       # нормализация ФИО
│       │   └── uiSettings.ts        # настройки интерфейса и темы
│       └── pages/
│           ├── ApiKeys.tsx          # экран API-ключей
│           ├── Cameras.tsx          # экран камер
│           ├── Groups.tsx           # экран групп
│           ├── Help.tsx             # встроенная справка
│           ├── Live.tsx             # live-мониторинг
│           ├── Login.tsx            # авторизация
│           ├── Persons.tsx          # база персон и сбор эмбеддингов
│           ├── Processors.tsx       # управление processor
│           ├── Recordings.tsx       # архив записей
│           ├── Reports.tsx          # отчёты
│           ├── Reviews.tsx          # ревью событий
│           ├── Settings.tsx         # настройки Console
│           └── Users.tsx            # пользователи и роли
├── desktop/
│   ├── build_installer.bat          # вспомогательная сборка installer
│   ├── installer.iss                # Inno Setup-скрипт Console
│   ├── main.js                      # main process Electron
│   ├── package-lock.json            # lockfile npm
│   ├── package.json                 # зависимости и скрипты desktop
│   └── preload.js                   # preload bridge Electron
├── mobile/
│   ├── .gitignore                   # исключения mobile-модуля
│   ├── App.tsx                      # legacy Expo entry
│   ├── app.json                     # конфиг Expo
│   ├── index.ts                     # точка входа Expo
│   ├── package-lock.json            # lockfile npm
│   ├── package.json                 # зависимости mobile
│   ├── tsconfig.json                # TS-конфиг mobile
│   ├── assets/
│   │   ├── android-icon-background.png   # фон adaptive icon
│   │   ├── android-icon-foreground.png   # foreground adaptive icon
│   │   ├── android-icon-monochrome.png   # monochrome adaptive icon
│   │   ├── favicon.png                   # favicon mobile
│   │   ├── icon.png                      # основная иконка
│   │   └── splash-icon.png               # splash-иконка
│   ├── app/
│   │   ├── _layout.tsx              # корневой layout Expo Router
│   │   ├── index.tsx                # стартовый экран / redirect
│   │   ├── (auth)/
│   │   │   ├── _layout.tsx          # layout auth-группы
│   │   │   └── login.tsx            # экран логина
│   │   └── (tabs)/
│   │       ├── _layout.tsx          # layout tab-навигации
│   │       ├── apikeys.tsx          # экран API-ключей
│   │       ├── cameras.tsx          # экран камер
│   │       ├── groups.tsx           # экран групп
│   │       ├── live.tsx             # live
│   │       ├── persons.tsx          # персоны
│   │       ├── processors.tsx       # processor
│   │       ├── recordings.tsx       # записи
│   │       ├── reports.tsx          # отчёты
│   │       ├── reviews.tsx          # ревью
│   │       ├── settings.tsx         # настройки
│   │       └── users.tsx            # пользователи
│   └── src/
│       ├── context/
│       │   └── AuthContext.tsx      # auth context mobile-клиента
│       ├── lib/
│       │   ├── api.ts               # API-клиент mobile
│       │   └── storage.ts           # локальное хранение токенов/настроек
│       └── theme/
│           ├── colors.ts            # палитра
│           └── styles.ts            # общие стили
└── processor/
    ├── .dockerignore                # исключения для Docker build processor
    ├── .env.example                 # шаблон env processor
    ├── Dockerfile                   # Dockerfile processor
    ├── __init__.py                  # пакет processor
    ├── antispoof.py                 # anti-spoofing helper
    ├── body_detector.py             # детекция тела / опорных точек
    ├── build_exe.py                 # сборка PyInstaller
    ├── build_installer.bat          # полная сборка installer под Windows
    ├── build_installer_fast.bat     # ускоренная сборка installer
    ├── camera_utils.py              # выбор RTSP/ONVIF/local источников
    ├── cli.py                       # CLI-инструменты processor
    ├── client.py                    # HTTP-клиент backend
    ├── config.py                    # конфигурация processor
    ├── detection.py                 # основной worker детекции и overlay
    ├── docker-compose.yml           # compose-файл processor-модуля
    ├── install.bat                  # установка processor под Windows
    ├── install.sh                   # установка processor под Linux
    ├── installer.iss                # Inno Setup-скрипт Processor
    ├── launcher.py                  # запуск process/runtime
    ├── main.py                      # сервис orchestration
    ├── media_server.py              # локальный media HTTP-сервер processor
    ├── monitor.py                   # сбор системных метрик
    ├── networking.py                # сетевые helper-ы и адреса
    ├── paths.py                     # вычисление рабочих путей
    ├── requirements.txt             # Python-зависимости processor
    ├── run_gui.py                   # вход в GUI и headless-режим
    ├── runtime.py                   # runtime, heartbeat, config-apply
    ├── tracker.py                   # логика трекера
    ├── tracking.py                  # дополнительные tracking helper-ы
    ├── vision.py                    # face embeddings / recognition
    ├── assets/
    │   ├── icon.ico                 # иконка Windows
    │   └── icon.png                 # PNG-иконка
    └── gui/
        ├── __init__.py              # пакет GUI
        └── app.py                   # интерфейс Processor на CustomTkinter
```

## Технологии

- `Python 3.11`
- `FastAPI`
- `SQLAlchemy`
- `PostgreSQL`
- `React`
- `TypeScript`
- `Electron`
- `OpenCV`
- `PyTorch`
- `MediaMTX`
- `Docker Compose`

## Примечание

Проект разработан в рамках дипломной работы и продолжает доводиться по части `Processor`, обнаружения и медиапайплайна.
