# CCTV Комплекс

Система видеонаблюдения с центральным backend, web-консолью, нативной консолью оператора и отдельным локальным Processor. Проект собирает камеры, live-просмотр, архив, события, ревью, отчеты, персоны для распознавания, ONVIF/PTZ и обработку видеопотока в один рабочий стенд.

Сейчас основной путь разработки такой: backend и web живут на сервере, операторская консоль постепенно переезжает в Flutter, а Processor остается Python-модулем с отдельной Flutter-оболочкой для локального управления.

## Что входит в проект

| Часть | Назначение |
| --- | --- |
| `app/` | FastAPI backend, авторизация, роли, камеры, события, архив, отчеты, Processor API |
| `cctv_ai/` | общая AI-логика, ONNX Runtime, face runtime |
| `processor/` | локальная обработка потоков, face/body detection, трекинг, overlay, media server, CLI |
| `frontend/` | серверная web-консоль на React/Vite, встраивается в Docker-образ backend |
| `native/cctv_console/` | Flutter Console для Windows и Android |
| `native/cctv_processor_gui/` | Flutter GUI для локального управления Processor |
| `migrations/` | Alembic-миграции PostgreSQL |
| `nginx/` | шаблон reverse proxy для публичного контура |
| `scripts/` | вспомогательные shell-скрипты для сервера, логов и сброса БД |
| `data/`, `recordings/`, `snapshots/` | runtime-данные, в Git не входят |

Старые ветки с RF/RuView/ESP32-позиционированием, face-login пользователей и отдельными legacy mobile/desktop-клиентами больше не являются рабочим направлением. Персоны нужны для распознавания людей в видеопотоке, а не для входа в систему.

## Архитектура

```text
Камеры RTSP/ONVIF
        |
        v
   Processor
   - читает назначенные камеры
   - распознает лица и body
   - рисует overlay
   - пишет события и архив
   - отдает локальные media endpoints
        |
        v
Backend FastAPI  <---->  PostgreSQL
        |
        +---- Web Console React/Vite
        +---- Flutter Console
        +---- Flutter Processor GUI через Processor CLI
```

Backend хранит пользователей, роли, камеры, группы, персоны, события, ревью, записи, настройки Processor и API-ключи. Processor регистрируется в backend, получает назначения камер и отправляет heartbeat. GUI Processor не переписывает Python-обработку, а запускает и диагностирует готовый runtime через `CCTV-Processor-CLI.exe`.

## Стек

- Python 3.11, FastAPI, SQLAlchemy async, Alembic.
- PostgreSQL 16.
- React 19, TypeScript, Vite.
- Flutter для `native/cctv_console` и `native/cctv_processor_gui`.
- OpenCV, ONNX Runtime, MMDeploy runtime.
- MediaMTX для RTSP/HTTP/MJPEG.
- Docker Compose.
- NVIDIA GPU через `onnxruntime-gpu` и `CUDAExecutionProvider`; CPU fallback допустим только если CUDA недоступна.

## Быстрый запуск через Docker

Скопируйте `.env.example` в `.env` и проверьте секреты:

```powershell
Copy-Item .env.example .env
```

Минимальный серверный контур:

```powershell
docker compose --profile core up -d --build backend mediamtx
```

Полный серверный профиль с web-консолью:

```powershell
docker compose --profile server up -d --build
```

Сервер с CPU/auto Processor:

```powershell
docker compose --profile server-cpu up -d --build
```

Сервер с NVIDIA Processor:

```powershell
docker compose --profile server-gpu up -d --build
```

Проверка:

```powershell
docker compose ps
Invoke-WebRequest http://127.0.0.1:8000/health
```

Если в `.env` задан `BACKEND_PORT=8001`, backend будет снаружи на `http://127.0.0.1:8001`.

## Полезные адреса

| Сервис | Адрес по умолчанию |
| --- | --- |
| Backend health | `http://127.0.0.1:8000/health` |
| Swagger/OpenAPI | `http://127.0.0.1:8000/docs` |
| OpenAPI JSON | `http://127.0.0.1:8000/openapi.json` |
| MediaMTX RTSP | `rtsp://127.0.0.1:8554` |
| MediaMTX HTTP | `http://127.0.0.1:8888` |
| Processor media server | `http://127.0.0.1:8777` |

## Конфигурация

Главный файл настроек: `.env`.

Важные переменные:

| Переменная | Что задает |
| --- | --- |
| `BACKEND_PORT` | внешний порт backend |
| `ENVIRONMENT` | режим `development` или `production` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | доступ к PostgreSQL |
| `JWT_SECRET` | подпись JWT |
| `PROCESSOR_API_KEY` | общий ключ для регистрации Processor |
| `BOOTSTRAP_ADMIN_LOGIN`, `BOOTSTRAP_ADMIN_PASSWORD` | первичный администратор |
| `CORS_ORIGINS`, `ALLOWED_HOSTS` | допустимые клиенты и host headers |
| `PROCESSOR_POLL_INTERVAL` | частота обновления назначений Processor |
| `PROCESSOR_HEARTBEAT_INTERVAL` | частота heartbeat Processor |
| `PROCESSOR_ACCEL` | `auto`, `cpu`, `nvidia`, `intel`, `amd`, `directml` |
| `FACE_SCAN_DIVISOR` | частота face scan относительно кадров |
| `OVERLAY_FRAME_DIVISOR` | частота генерации overlay |

Для production нельзя оставлять стандартные секреты из `.env.example`. При `ENVIRONMENT=production` backend проверяет опасные настройки на старте.

## Учетная запись по умолчанию

В development backend может создать администратора:

```text
login: admin
password: admin
```

После первого входа пароль нужно сменить. В production лучше задать `BOOTSTRAP_ADMIN_PASSWORD` заранее и отключить `ALLOW_DEFAULT_ADMIN`.

## Локальная разработка

Backend:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\uvicorn.exe app.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Flutter Console:

```powershell
cd native\cctv_console
flutter pub get
flutter test
dart analyze lib test
flutter run -d windows
```

Flutter Processor GUI:

```powershell
cd native\cctv_processor_gui
flutter pub get
flutter test
dart analyze lib test
flutter run -d windows
```

Processor CLI в dev-режиме:

```powershell
py -3.11 -m processor.cli acceleration --json
py -3.11 -m processor.cli run
```

## Processor и GPU

На Windows рабочий portable Processor должен использовать `onnxruntime-gpu` и видеть `CUDAExecutionProvider`.

Проверка Python-окружения:

```powershell
py -3.11 -m pip show onnxruntime-gpu
py -3.11 -c "import onnxruntime as ort; print(ort.get_available_providers())"
```

Если установлен CPU-only пакет:

```powershell
py -3.11 -m pip uninstall -y onnxruntime
py -3.11 -m pip install "onnxruntime-gpu>=1.18.1,<1.24"
```

Проверка portable Processor:

```powershell
& "$env:USERPROFILE\Desktop\CCTV Processor Flutter portable\processor\CCTV-Processor-CLI.exe" acceleration --json
```

Ожидаемый результат для GPU-стенда: `selected_device` равен `cuda`, а среди providers есть `CUDAExecutionProvider`.

## Сборка Processor runtime

GUI/headless runtime:

```powershell
$env:SKIP_PROCESSOR_CLI='1'
py -3.11 processor\build_exe.py
```

CLI:

```powershell
py -3.11 -c "from processor.build_exe import _run, _cli_cmd; _run(_cli_cmd())"
```

Артефакты:

```text
processor/dist/CCTV-Processor-Runtime/
processor/dist/CCTV-Processor-CLI/CCTV-Processor-CLI.exe
```

В portable-сборке рядом с Flutter GUI должна лежать папка `processor` с Python runtime и CLI:

```text
%USERPROFILE%\Desktop\CCTV Processor Flutter portable\processor
%USERPROFILE%\Desktop\CCTV Processor Flutter portable\processor\processor_config.json
%USERPROFILE%\Desktop\CCTV Processor Flutter portable\processor\CCTV-Processor-CLI.exe
```

`processor_config.json` должен создаваться и обновляться через подключение к backend. Не нужно вручную дублировать назначения камер, если backend уже выдает их Processor.

## Сборка Flutter Console

Из-за кириллицы в пути Flutter/MSBuild иногда ломается. Для release-сборок удобнее копировать проект во временную ASCII-папку.

Пример для Windows:

```powershell
$src = "$env:USERPROFILE\Desktop\CCTV Комплекс\native\cctv_console"
$tmp = "$env:TEMP\cctv_console_build"
$out = "$env:USERPROFILE\Desktop\CCTV Console Flutter portable"

Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
robocopy $src $tmp /E /XD build .dart_tool
cd $tmp
flutter pub get
flutter test
dart analyze lib test
flutter build windows --release
robocopy "$tmp\build\windows\x64\runner\Release" $out /E
```

Android:

```powershell
cd native\cctv_console
flutter pub get
flutter test
dart analyze lib test
flutter build apk --release
```

## Сборка Flutter Processor GUI

Windows release:

```powershell
$src = "$env:USERPROFILE\Desktop\CCTV Комплекс\native\cctv_processor_gui"
$tmp = "$env:TEMP\cctv_processor_gui_build"
$out = "$env:USERPROFILE\Desktop\CCTV Processor Flutter portable"

Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
robocopy $src $tmp /E /XD build .dart_tool
cd $tmp
flutter pub get
flutter test
dart analyze lib test
flutter build windows --release
robocopy "$tmp\build\windows\x64\runner\Release" $out /E /XD processor
```

Папку `processor` внутри portable-директории удалять нельзя: там лежит runtime.

## Проверки перед коммитом

Python:

```powershell
py -3.11 -m compileall app processor cctv_ai
```

Backend Docker:

```powershell
docker compose --profile core up -d --build backend
docker compose ps
docker logs --tail 100 cctv-backend-1
Invoke-WebRequest http://127.0.0.1:8000/health
```

Flutter:

```powershell
flutter test
dart analyze lib test
```

Frontend:

```powershell
cd frontend
npm install
npm run build
```

## Работа с камерами

Система рассчитана на RTSP и ONVIF-камеры. ONVIF используется для обнаружения возможностей камеры и PTZ-команд, RTSP - для видеопотока.

Пример тестового RTSP-потока с веб-камеры через FFmpeg:

```powershell
ffmpeg -f dshow -i video="USB2.0 HD UVC WebCam" -an -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/webcam
```

После этого поток можно добавить как:

```text
rtsp://127.0.0.1:8554/webcam
```

## Типовые проблемы

Processor не видит назначенные камеры:

- проверьте, что Processor зарегистрирован в backend;
- проверьте `PROCESSOR_API_KEY`, `PROCESSOR_CONNECT_CODE` и `PROCESSOR_ID`;
- откройте вкладку Processor в консоли и убедитесь, что камеры назначены именно этому Processor;
- посмотрите `processor_config.json` рядом с portable runtime;
- уменьшите `PROCESSOR_POLL_INTERVAL`, если обновления приходят слишком редко.

Processor ушел на CPU:

- проверьте `onnxruntime-gpu`;
- проверьте наличие `CUDAExecutionProvider`;
- запустите `CCTV-Processor-CLI.exe acceleration --json`;
- не считайте CPU fallback нормой для Windows GPU-стенда, если CUDA доступна.

Live-видео идет с большой задержкой:

- проверьте RTSP transport и доступность MediaMTX;
- не включайте лишний overlay на слабом железе;
- проверьте `FACE_SCAN_DIVISOR`, `OVERLAY_FRAME_DIVISOR`, `MAX_WORKERS`;
- смотрите нагрузку CPU/GPU и логи Processor.

Flutter зависает или странно масштабируется:

- собирайте release, debug-сборка заметно тяжелее;
- проверяйте Android на реальном размере телефона;
- для Windows-сборки используйте ASCII-путь.

## Безопасность

Для локального дипломного стенда допустимы упрощения, но для сети и тем более интернета нужны нормальные настройки:

- замените `JWT_SECRET`, `PROCESSOR_API_KEY`, `POSTGRES_PASSWORD`, `TOTP_ENCRYPTION_KEY`;
- включайте `ENVIRONMENT=production`;
- задавайте конкретные `CORS_ORIGINS` и `ALLOWED_HOSTS`;
- не публикуйте PostgreSQL наружу;
- не оставляйте Swagger публичным без необходимости;
- закрывайте MediaMTX и Processor media server от внешней сети или ставьте их за reverse proxy с доступом только для backend/клиентов;
- не передавайте основной JWT в query-string, используйте короткоживущие media access tokens.

## Сброс БД

Сброс БД удаляет пользователей, камеры, события, персоны и настройки. Делайте это только когда точно нужен чистый стенд.

```powershell
docker compose down
docker volume ls
docker volume rm <compose_project>_pgdata
docker compose --profile core up -d --build backend mediamtx
```

Имя volume зависит от имени Compose-проекта. В обычном случае его видно через `docker volume ls`.

## Быстрая памятка по рабочему стенду

Частые локальные пути:

```text
%USERPROFILE%\Desktop\CCTV Комплекс
%USERPROFILE%\Desktop\CCTV Console Flutter portable
%USERPROFILE%\Desktop\CCTV Processor Flutter portable
```

Частые проверки:

```powershell
git status --short
docker compose ps
Invoke-WebRequest http://127.0.0.1:8001/health
& "$env:USERPROFILE\Desktop\CCTV Processor Flutter portable\processor\CCTV-Processor-CLI.exe" acceleration --json
```

Если backend поднят на стандартном порту, замените `8001` на `8000`.
