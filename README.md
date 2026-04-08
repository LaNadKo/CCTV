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
| `recordings/`, `snapshots/` | локальные данные архива и снимков |

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
- PyTorch
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

### Вариант 2. Готовый shell-скрипт

Linux-сценарий для серверной части:

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

Для первой Windows-сборки может потребоваться `Developer Mode` или запуск терминала от администратора из-за `electron-builder` и `winCodeSign`.

### Processor

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

- Файл [CCTV-Processor.spec](CCTV-Processor.spec) остаётся в корне как legacy-артефакт сборки.
- Модель [yolov8n-pose.pt](yolov8n-pose.pt) используется `Processor` для body/pose detection.
- Файл [yolov8n.pt](yolov8n.pt) остаётся в репозитории, но не является основным runtime-артефактом текущего пайплайна.
