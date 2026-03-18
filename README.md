# CCTV Console — Система видеонаблюдения с распознаванием лиц

Комплексная система видеонаблюдения с поддержкой распознавания лиц, детекции движения, записи видео и многопользовательского управления. Включает серверную часть, веб-интерфейс, нативное мобильное приложение и десктопный клиент.

## Архитектура

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│   Mobile    │  │   Desktop   │  │   Frontend  │
│ React Native│  │  Electron   │  │  React+Vite │
│   (Expo)    │  │             │  │    (PWA)    │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │
       └────────────────┼────────────────┘
                        │ REST API
                ┌───────┴───────┐
                │    Backend    │
                │   FastAPI     │
                │  (asyncio)    │
                └───┬───────┬───┘
                    │       │
           ┌────────┘       └────────┐
           │                         │
    ┌──────┴──────┐          ┌───────┴──────┐
    │ PostgreSQL  │          │   MediaMTX   │
    │     16      │          │ RTSP Server  │
    └─────────────┘          └──────────────┘
                                    │
                            ┌───────┴──────┐
                            │  Processor   │
                            │  (Python)    │
                            │ OpenCV+MTCNN │
                            └──────────────┘
```

## Технологический стек

| Компонент | Технологии |
|-----------|-----------|
| **Backend** | Python 3.11, FastAPI 0.115, SQLAlchemy 2.0 (async), Alembic, Uvicorn |
| **База данных** | PostgreSQL 16 (asyncpg) |
| **Аутентификация** | JWT (python-jose), bcrypt, TOTP 2FA (pyotp) |
| **Компьютерное зрение** | OpenCV 4.10, MTCNN, FaceNet (facenet-pytorch), PyTorch |
| **Стриминг** | MediaMTX (RTSP/RTMP/HLS/WebRTC) |
| **Веб-интерфейс** | React 19, TypeScript 5.9, Vite 7, React Router 6, PWA |
| **Мобильное приложение** | React Native 0.83, Expo 55, expo-router, expo-av |
| **Десктоп** | Electron 33, Inno Setup (установщик Windows) |
| **Процессор** | Python, OpenCV, MTCNN, FaceNet, CustomTkinter (GUI) |
| **Деплой** | Docker Compose, Nginx (reverse proxy + SSL) |

## Основные возможности

### Видеонаблюдение
- Просмотр камер в реальном времени (RTSP / HTTP / MJPEG)
- Непрерывная и событийная запись видео
- Навигация по записям с таймлайном событий
- Поддержка ONVIF (PTZ-управление, пресеты)
- ROI-зоны (include/exclude полигоны)

### Распознавание лиц
- Детекция лиц в реальном времени (MTCNN)
- Идентификация по базе эмбеддингов (FaceNet, cosine similarity)
- Регистрация персон по фото (камера / галерея / стоп-кадр записи)
- Вход в систему по лицу (биометрия)
- Система ревью событий (pending → approved / rejected)
- Anti-spoofing проверка

### Детекция и аналитика
- Детекция движения (frame delta analysis)
- Детекция людей
- Трекинг объектов (track_id)
- Таймлайн событий с фильтрацией
- Статистика детекций и присутствия

### Отчётность
- Отчёт по появлениям персон (фильтры: дата, персона, камера)
- Экспорт в **PDF**, **XLSX**, **DOCX**
- JSON API для интеграций

### Управление доступом
- Ролевая модель: **Администратор** / **Пользователь** / **Наблюдатель**
- Группы камер с назначением
- Управление пользователями (создание, роли, принудительная смена пароля)
- API-ключи с областями видимости (scopes)
- Двухфакторная аутентификация (TOTP)
- Полный аудит действий

### Процессор (микросервис)
- Автономная регистрация через код подключения
- Heartbeat-мониторинг с системными метриками (CPU, RAM, GPU)
- Распределённая обработка камер
- GUI-интерфейс (CustomTkinter)
- Поддержка GPU (NVIDIA CUDA)

## Структура проекта

```
├── app/                       # FastAPI backend
│   ├── main.py               # Точка входа, startup, seed-функции
│   ├── models.py             # SQLAlchemy модели (30+ таблиц)
│   ├── config.py             # Настройки (переменные окружения)
│   ├── security.py           # JWT, хеширование паролей
│   ├── permissions.py        # Проверка прав доступа
│   ├── vision.py             # FaceNet, детекция лиц
│   ├── storage/              # Абстракция хранилищ (local/S3/FTP)
│   ├── routers/
│   │   ├── auth.py           # Аутентификация, 2FA, face login
│   │   ├── cameras.py        # Управление камерами, стримы
│   │   ├── groups.py         # Группы камер
│   │   ├── admin.py          # Администрирование пользователей
│   │   ├── detections.py     # События детекции, ревью
│   │   ├── recordings.py     # Видеозаписи
│   │   ├── persons.py        # База персон, эмбеддинги
│   │   ├── processors.py     # Управление процессорами
│   │   ├── reports.py        # Отчёты (PDF/XLSX/DOCX)
│   │   ├── face.py           # Биометрия (face login/enroll)
│   │   └── api_keys.py       # API-ключи
│   └── schemas/              # Pydantic-схемы
│
├── processor/                 # Микросервис обработки видео
│   ├── main.py               # ProcessorService (оркестрация)
│   ├── client.py             # BackendClient (HTTP API)
│   ├── detection.py          # CameraWorker (детекция/распознавание)
│   ├── tracker.py            # Трекинг объектов
│   ├── vision.py             # FaceNet эмбеддинги
│   ├── antispoof.py          # Anti-spoofing проверка
│   └── gui/                  # GUI на CustomTkinter
│
├── frontend/                  # React SPA (веб-клиент)
│   └── src/
│       ├── App.tsx           # Роутинг, навигация
│       ├── pages/            # Страницы (Live, Cameras, Groups, ...)
│       ├── lib/api.ts        # API-клиент
│       └── context/          # AuthContext
│
├── mobile/                    # React Native (Expo)
│   ├── app/                  # Expo Router (file-based routing)
│   │   ├── (auth)/           # Экран логина
│   │   └── (tabs)/           # Основные вкладки (11 экранов)
│   └── src/
│       ├── lib/api.ts        # API-клиент
│       └── theme/            # Стили, цветовая палитра
│
├── desktop/                   # Electron (десктоп-клиент)
│   ├── main.js              # Electron main process
│   └── installer.iss        # Inno Setup скрипт
│
├── migrations/                # Alembic миграции БД
├── nginx/                     # Конфигурация Nginx
├── docker-compose.yml         # Docker Compose стек
└── scripts/                   # Вспомогательные скрипты
```

## Установка и запуск

### Quick Start

Один скрипт — полная установка сервера (Docker, PostgreSQL, Backend, MediaMTX):

```bash
bash <(curl -Ls https://raw.githubusercontent.com/LaNadKo/CCTV/main/install.sh)
```

Скрипт автоматически:
- ✅ Проверит и установит Docker (если не установлен)
- ✅ Предложит выбрать директорию установки
- ✅ Склонирует репозиторий
- ✅ Сгенерирует безопасные ключи и пароли (.env)
- ✅ Поднимет PostgreSQL + Backend + MediaMTX
- ✅ Применит миграции БД и создаст администратора

> **Логин по умолчанию:** `admin` / `admin` (при первом входе потребуется сменить пароль)

### Ручная установка

```bash
# Клонировать
git clone https://github.com/LaNadKo/CCTV.git
cd CCTV

# Настроить окружение
cp .env.example .env
nano .env  # Задать пароли и секреты

# Запустить сервер (без GPU-процессора)
docker compose up -d --build db backend mediamtx
```

### Управление сервером

```bash
./scripts/start-server.sh     # Запуск
./scripts/stop-server.sh      # Остановка
./scripts/logs.sh             # Все логи
./scripts/logs.sh backend     # Логи бэкенда
./scripts/reset-db.sh         # Полный сброс БД
```

### Локальный запуск (без Docker)

```bash
# Backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend
cd frontend && npm install && npm run dev

# Processor (на машине с GPU)
cd processor && pip install -r requirements.txt && python main.py
```

### Сборка установщиков

**Desktop (Windows):**
```bash
cd desktop
npm install
node build.js                  # Frontend + Electron packaging
iscc installer.iss             # → installer_output/CCTV-Console-Setup-1.0.0.exe
```

**Processor (Windows):**
```bash
cd processor
python build_exe.py            # PyInstaller → dist/CCTV-Processor/
iscc installer.iss             # → installer_output/CCTV-Processor-Setup-1.0.0.exe
```

**Mobile (Android APK):**
```bash
cd mobile
npm install
npx expo prebuild --platform android
cd android && ./gradlew assembleDebug
# → android/app/build/outputs/apk/debug/app-debug.apk
```

## Аутентификация

При первом запуске автоматически создаётся учётная запись администратора:

| Параметр | Значение |
|----------|----------|
| **Логин** | `admin` |
| **Пароль** | `admin` |

> При первом входе система потребует сменить пароль.

### Роли

| Роль | ID | Возможности |
|------|:---:|------------|
| **Администратор** | 1 | Полный доступ: камеры, пользователи, группы, процессоры, персоны, API-ключи |
| **Пользователь** | 2 | Просмотр камер, ревью событий, отчёты |
| **Наблюдатель** | 3 | Только просмотр камер и записей |

## Status / В разработке

> Проект находится в активной разработке. Ниже указан фактический статус на текущем этапе, чтобы README не создавал ложного ощущения полной готовности всех модулей.

### Уже работает
- Backend на `FastAPI` с авторизацией, ролями, группами камер, пользователями и процессорами
- Desktop-клиент на `Electron`
- Processor c GUI, подключением по коду, heartbeat и обработкой камер
- Live, Review, Persons, Reports и Users в desktop/web-клиенте
- Отчёты по появлениям (`/reports/appearances`) и экспорт в `PDF` / `XLSX` / `DOCX`

### В разработке / стабилизации
- Pipeline записей через `Processor`: хранение и воспроизведение уже переведены на сторону `Processor`, но сценарии ещё доводятся
- Низколатентный live-stream и overlay: работают, но продолжается оптимизация задержек и отрисовки
- Review/media-flow: snapshots и медиапроксирование уже переведены на `Processor-first`, но часть UX ещё шлифуется
- Mobile-клиент: поддерживается, но может отставать от последних изменений desktop/backend
- Некоторые функции из старой архитектуры описаны в README как часть общего замысла системы и могут быть доступны частично или оставаться в статусе `В разработке`

## API

Документация доступна при запущенном сервере:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

### Основные эндпоинты

| Группа | Метод | Путь | Описание |
|--------|:-----:|------|----------|
| **Auth** | POST | `/auth/login` | Аутентификация (JWT) |
| | POST | `/auth/change-password` | Смена пароля |
| | POST | `/auth/face/enroll` | Регистрация лица для входа |
| **Камеры** | GET | `/cameras` | Список камер (фильтр по group_id) |
| | GET | `/cameras/{id}/stream` | Живой MJPEG-поток |
| **Группы** | GET | `/groups` | Список групп |
| | POST | `/groups/{id}/cameras/{cam_id}` | Привязка камеры к группе |
| **Детекции** | GET | `/detections/pending` | Ожидающие ревью события |
| | GET | `/detections/timeline` | Таймлайн событий |
| | POST | `/detections/events/{id}/review` | Одобрить / отклонить |
| **Записи** | GET | `/recordings` | Список записей |
| | GET | `/recordings/file/{id}` | Скачать запись |
| **Персоны** | GET | `/persons` | База персон |
| | POST | `/persons/{id}/embeddings/photo` | Загрузка фото лица |
| **Отчёты** | GET | `/reports/appearances` | Отчёт появлений (JSON) |
| | GET | `/reports/appearances/export` | Экспорт (PDF / XLSX / DOCX) |
| **Процессоры** | POST | `/processors/generate-code` | Генерация кода подключения |
| | GET | `/processors` | Список процессоров |
| **Админ** | GET | `/admin/users` | Список пользователей |
| | POST | `/admin/users` | Создание пользователя |
| **API Keys** | POST | `/api-keys` | Создание API-ключа |

## Подключение процессора

1. Администратор генерирует **код подключения** в интерфейсе
   *(Процессоры → Сгенерировать код)*
2. На компьютере с доступом к камерам запускается Processor
   *(установщик `.exe` или `python main.py`)*
3. При первом запуске вводится код подключения и URL сервера
4. Processor автоматически регистрируется, получает API-ключ и начинает обработку назначенных камер

### Мониторинг процессора

Processor отправляет heartbeat каждые 30 секунд с метриками:
- CPU / RAM использование
- GPU (NVIDIA): утилизация, память, температура
- Сетевая активность
- Количество активных камер

## Конфигурация

### Переменные окружения

| Переменная | Описание | По умолчанию |
|-----------|----------|:------------:|
| `DATABASE_URL` | PostgreSQL connection string | — |
| `JWT_SECRET` | Секрет для подписи JWT-токенов | — |
| `TOTP_ENCRYPTION_KEY` | Base64-ключ шифрования TOTP-секретов | — |
| `ENABLE_EMBEDDED_DETECTOR` | Встроенный детектор (без Processor) | `false` |

### Файлы конфигурации

- `.env` — локальная конфигурация (создать из `.env.example`)
- `alembic.ini` — настройки миграций БД
- `docker-compose.yml` — стек Docker-сервисов
- `nginx/default.conf.template` — конфигурация reverse proxy

## Клиентские приложения

### Веб-интерфейс
React SPA с поддержкой PWA. Работает в любом браузере, может быть установлен как приложение.

### Мобильное приложение (Android)
Нативное приложение на React Native (Expo). Экраны:
- **Live** — просмотр камер в реальном времени
- **Записи** — навигация по записям с плеером
- **Ревью** — модерация событий детекции
- **Камеры** — управление камерами (админ)
- **Группы** — организация камер по группам
- **Персоны** — база лиц с загрузкой фото
- **Отчёты** — отчёты с экспортом
- **Процессоры** — управление и подключение
- **Пользователи** — управление аккаунтами (админ)
- **Настройки** — смена пароля, URL сервера

### Десктоп (Windows)
Electron-приложение с системным треем и автозапуском. Использует тот же React SPA что и веб-версия, но запускается локально без браузера.

## Лицензия

Проект разработан в рамках дипломной работы.
