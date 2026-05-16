# CCTV Console

Комплекс видеонаблюдения с web/desktop-интерфейсом `Console`, серверной частью на `FastAPI` и отдельным модулем обработки видеопотока `Processor`.

## Текущее состояние

- `Backend` рабочий: авторизация, роли, TOTP, камеры, группы, персоны, события, ревью, отчёты, экспорт.
- `Console` рабочий: web и desktop-клиент на общей React-базе.
- `Processor` рабочий: подключение к backend, обработка камер, face/body detection, ONVIF/PTZ, трекинг.
- `Mobile` разделён на два независимых клиента:
  - `mobile/react-native` — сохранённый Expo/React Native клиент.
  - `mobile/react-capacitor` — отдельный React + Capacitor клиент для Android/iOS.
- Основной производственный контур сейчас: `backend + frontend/desktop + processor`.
- Мобильная адаптация идёт отдельно и не должна ломать основной `frontend`.

## Состав проекта

| Каталог | Назначение |
| --- | --- |
| `app/` | backend на FastAPI |
| `migrations/` | Alembic-миграции БД |
| `frontend/` | web-клиент `Console` на React/Vite |
| `desktop/` | Electron-обвязка для desktop-версии `Console` |
| `processor/` | модуль обработки видеопотока и Windows GUI |
| `mobile/react-native/` | старый мобильный клиент на Expo / React Native |
| `mobile/react-capacitor/` | новый отдельный мобильный клиент на React + Capacitor |
| `nginx/` | конфигурация reverse proxy |
| `scripts/` | shell-скрипты для запуска и обслуживания серверной части |
| `recordings/`, `snapshots/` | локальные runtime-данные архива и снимков, которые создаются при запуске |

## Технологии

- Python 3.11
- FastAPI
- SQLAlchemy
- Alembic
- PostgreSQL
- React 19
- TypeScript
- Vite
- Electron
- OpenCV
- ONNX Runtime
- MMDeploy Runtime
- MediaMTX
- Docker Compose
- Capacitor
- Expo / React Native

## Структура верхнего уровня

```text
.
├── app/
├── desktop/
├── frontend/
├── migrations/
├── mobile/
│   ├── react-capacitor/
│   └── react-native/
├── nginx/
├── processor/
├── scripts/
├── docker-compose.yml
├── Dockerfile
├── docker-entrypoint.sh
├── requirements.txt
└── README.md
```

## Что умеет система

- авторизация и роли пользователей;
- двухфакторная аутентификация по `TOTP`;
- управление камерами, группами камер и процессорами;
- live-просмотр камер и полноэкранный режим;
- архив записей и работа с временной шкалой;
- обработка событий и ревью;
- база персон и сбор face embeddings;
- ONVIF/RTSP-интеграция камер;
- отчёты и экспорт в `PDF / XLSX / DOCX`;
- desktop-упаковка `Console`;
- Windows-сборка `Processor`.

## Быстрый старт

### Вариант 1. Серверная часть в Docker

1. Создать `.env`:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

2. Поднять базовый стек:

```bash
docker compose up -d --build db backend mediamtx
```

3. Проверить backend:

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/docs
rtsp://127.0.0.1:8554
```

Контейнер `backend` сам ждёт PostgreSQL, применяет `alembic upgrade head` и затем запускает `uvicorn`.

### RuView / WiFi DensePose

RuView подключён как отдельный контур pose/skeleton, без возврата RF Room и координатной карты комнаты.

Запуск sidecar:

```powershell
.\scripts\start_ruview.ps1
```

Или через Docker Compose:

```bash
docker compose --profile ruview up -d ruview-sensing
```

Рабочие адреса:

- backend UDP для ESP32: `udp://<IP_ноутбука>:5005`;
- RuView sidecar UI: `http://127.0.0.1:3100/ui/index.html`;
- backend status: `GET /ruview/status`;
- upstream status: `GET /ruview/upstream`;
- pose для Live overlay: `GET /ruview/pose`.

По умолчанию `GET /ruview/pose` скрывает симуляцию RuView и отдаёт skeleton только при живом CSI/RF-link потоке от ESP32. Если платы присылают только health-пакеты, в Live будет статус `Нет live CSI от ESP32`.

Прошивка ESP32-S3 для live CSI находится в `firmware/esp32-rf-node`. Она использует ESP-NOW broadcast-sounding и отправляет в backend одновременно RuView ADR-018 CSI (`0xC5110001`) и диагностический RF-link (`0xC5110101`).

```powershell
.\scripts\flash_ruview_node.ps1 -Port COM3 -NodeId 1 -NoProvision
```

`-NoProvision` сохраняет текущий `node_id`, WiFi и target из NVS. Если плату нужно настроить заново, задайте `RUVIEW_WIFI_PASSWORD` и запустите без `-NoProvision`.

### Вариант 2. Готовый shell-скрипт

Shell-скрипт для серверной части. Поднимает тот же стек, что и Вариант 1: `db + backend + mediamtx`.

```bash
./scripts/start-server.sh
```

Требования:

- Linux;
- или Windows с `Git Bash` / `WSL`.

На чистом Windows без POSIX shell используйте прямой запуск `docker compose` из Варианта 1.

Полезные команды:

```bash
./scripts/start-server.sh
./scripts/stop-server.sh
./scripts/logs.sh
./scripts/logs.sh backend
./scripts/reset-db.sh
```

### Вариант 3. Локальная разработка на Windows

```bat
start-local.bat
```

Сценарий поднимает:

- `db` и `mediamtx` через Docker;
- backend на `http://localhost:8000`;
- frontend dev server на `http://localhost:5173`.

## Локальная разработка

### Backend

```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Desktop Console

```bash
cd desktop
npm install
npm run dev
```

### Processor

GUI:

```bash
python processor/run_gui.py
```

CLI:

```bash
python -m processor.cli run
```

## Камеры и потоки

Поддерживаются:

- `RTSP`;
- `ONVIF`;
- локальные источники и тестовые потоки через `MediaMTX`.

Пример локального тестового RTSP-потока с веб-камеры:

```powershell
ffmpeg -f dshow -i video="USB2.0 HD UVC WebCam" -an -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/webcam
```

После этого поток доступен по адресу:

```text
rtsp://127.0.0.1:8554/webcam
```

## Сборка desktop и processor

### Console Desktop

```bash
cd desktop
npm install
npm run build
```

На Windows команда `npm run build` может упираться в `electron-builder` / `winCodeSign`, если не включён `Developer Mode` или нет прав на создание symlink в кеше `electron-builder`.

Рабочий обход для portable-сборки на Windows:

```bat
cd desktop
npx electron-builder --win portable --config.win.signAndEditExecutable=false
```

Артефакты:

- `desktop/release/CCTV Console 1.0.0.exe` — portable `.exe`;
- `desktop/release/win-unpacked/` — folder-based portable.

### Processor

Portable GUI + CLI:

```bat
py -3.11 -m venv .venv-processor311
.\.venv-processor311\Scripts\python.exe -m pip install -r processor\requirements.txt pyinstaller
.\.venv-processor311\Scripts\python.exe processor\build_exe.py
```

Артефакты:

- `processor/dist/CCTV-Processor/` — folder-based portable GUI;
- `processor/dist/CCTV-Processor-CLI.exe` — CLI executable.

Полная Windows-сборка:

```bat
cd processor
build_installer.bat
```

Быстрый вариант:

```bat
cd processor
build_installer_fast.bat
```

Для сборки нужен установленный `Inno Setup 6`.

## Мобильные клиенты

### React Native

Старый клиент сохранён отдельно:

```bash
cd mobile/react-native
npm install
npm run start
```

### React + Capacitor

Новый отдельный клиент:

```bash
cd mobile/react-capacitor
npm install
npm run dev
```

Подготовка Android:

```bash
cd mobile/react-capacitor
npm run build:android
npx cap open android
```

Подготовка iOS:

```bash
cd mobile/react-capacitor
npm run build:ios
npx cap open ios
```

Для реальной iOS-сборки нужен `macOS + Xcode`.

Дополнительно:

- [mobile/README.md](mobile/README.md)
- [mobile/react-capacitor/README.md](mobile/react-capacitor/README.md)

## Установочный скрипт

Автоматическая установка под Linux:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/LaNadKo/CCTV/main/install.sh)
```

Скрипт:

- проверяет Docker и Git;
- клонирует проект;
- создаёт `.env`;
- поднимает `db`, `backend`, `mediamtx`;
- применяет миграции;
- подготавливает сервер к первому входу.

## Учётная запись по умолчанию

После первичного старта создаётся администратор:

- логин: `admin`
- пароль: `admin`

Пароль нужно сменить при первом входе.

## Примечания

- Runtime-конфиги и медиа-папки (`.env`, `recordings/`, `recordings_cache/`, `snapshots/`, `processor_config.json`) не хранятся в Git и создаются локально.
- Текущий face/body runtime использует `ONNX Runtime + MMDeploy Runtime`; legacy-артефакты PyInstaller/YOLO в корне проекта не требуются.
