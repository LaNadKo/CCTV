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

### Console Installer / Portable

```bash
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
python build_exe.py
iscc installer.iss
```

Результат:
- сборка `PyInstaller`: `processor/dist/`
- установщик: `processor/installer_output/`

## Структура репозитория

```text
app/            backend и API
desktop/        Electron-оболочка Console
frontend/       React-интерфейс Console
mobile/         мобильный клиент
processor/      обработчик видеопотока и GUI
migrations/     миграции базы данных
scripts/        серверные bash-скрипты
docker-compose.yml
install.sh
README.md
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
