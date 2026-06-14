# Аудит безопасности и оптимизации, 2026-06-13

## F-040. Rate-limit и доверенные proxy

Поверхность: `app/config.py`, `.env.example`, `app/rate_limit.py`.

Риск: при прямом доступе к backend через Docker bridge клиент мог подменять `X-Forwarded-For` и обходить лимит попыток входа.

Исправление: из дефолтных доверенных proxy-сетей убрана `172.16.0.0/12`; `X-Forwarded-For` разбирается справа налево до первого недоверенного hop.

## F-041. Повторное использование TOTP

Поверхность: `app/security.py`, `app/routers/auth.py`, `app/models.py`, `migrations/versions/0010_auth_token_totp_replay.py`.

Риск: перехваченный TOTP можно было повторно применить в пределах окна `valid_window`.

Исправление: добавлен `last_totp_counter`; TOTP теперь одноразовый по time-step счётчику.

## F-042. JWT после смены пароля

Поверхность: `app/security.py`, `app/dependencies.py`, `app/routers/auth.py`, `app/models.py`, `migrations/versions/0010_auth_token_totp_replay.py`.

Риск: старые access/media tokens оставались валидными после смены пароля.

Исправление: добавлен `users.token_version`; смена пароля инкрементирует версию, а проверка JWT сверяет claim с текущей версией пользователя. На смену пароля добавлен rate-limit.

## F-043. Авто-привязка Processor

Поверхность: `app/routers/processors.py`.

Риск: processor API key мог автоматически забрать существующий unpaired Processor и получить назначения/команды.

Исправление: авто-claim удалён; unpaired Processor должен подключаться через pairing code. `/register` не перепривязывает чужой или отвязанный `node_uid`.

## F-044. Gallery/storage-config для Processor без камер

Поверхность: `app/routers/processors.py`.

Риск: новый Processor без назначенных камер мог получить embeddings персон и конфигурацию хранилища.

Исправление: без назначенных камер gallery отдаёт пустой список, а storage-config отдаёт безопасный local fallback.

## F-045. Неверная привязка записи к событию

Поверхность: `app/routers/detections.py`.

Риск: detection мог сослаться на `recording_file_id` другой камеры.

Исправление: при создании detection проверяется соответствие `recording_file_id` и `camera_id` через `video_stream`.

## F-046. Неограниченное чтение snapshot/media в память

Поверхность: `app/routers/recordings.py`, `app/routers/detections.py`, `processor/media_server.py`.

Риск: большой upstream snapshot или сильно сжатое изображение могло раздувать память backend/processor.

Исправление: proxy snapshot читается потоково с лимитом 8 МБ; event snapshot fetch использует тот же лимит; Processor проверяет размер изображения после `cv2.imdecode`.

## F-047. Скачивание записей в Native Console через RAM

Поверхность: `native/cctv_console/lib/src/core/network/api_client.dart`.

Риск: большие записи полностью буферизовались в `bodyBytes`, что могло вызывать просадки UI или OutOfMemory.

Исправление: успешные file-download ответы пишутся из `StreamedResponse` во временный `.part` файл с последующим rename.

## F-048. Processor media DNS rebinding после проверки hostname

Поверхность: `app/processor_media.py`.

Риск: hostname проверялся через DNS один раз, но URL для `httpx` строился с исходным hostname, и последующий DNS resolve мог вернуть уже другой адрес.

Исправление: processor media URL теперь строится с pinned IP, полученным через сетевую policy; IPv6 форматируется в `[]`.

## F-049. Backend review candidates без decoded-pixel cap

Поверхность: `app/routers/detections.py`.

Риск: 8 МБ compressed snapshot мог развернуться в сильно больший массив OpenCV перед поиском кандидатов.

Исправление: после `cv2.imdecode` добавлен лимит `_MAX_EVENT_SNAPSHOT_PIXELS`.

## F-050. Partial ffmpeg output мог попасть в cache

Поверхность: `app/routers/recordings.py`.

Риск: stitch/AVI cache писали ffmpeg output прямо в финальный путь; при timeout/fail мог остаться partial файл, который позже считался валидным.

Исправление: ffmpeg пишет только во временный `.tmp.mp4`; финальный cache заменяется атомарно после успешного результата, partial удаляется.

## F-051. Локальный MJPEG playback без ограничения параллельных декодеров

Поверхность: `app/routers/recordings.py`.

Риск: каждый клиент открывал отдельный `cv2.VideoCapture`; на слабом устройстве это могло быстро забить CPU/IO.

Исправление: добавлен `_MJPEG_SEMAPHORE`, слот удерживается от открытия `VideoCapture` до закрытия streaming generator.

## F-052. Ошибочные download responses в Native Console и сохранность старого файла

Поверхность: `native/cctv_console/lib/src/core/network/api_client.dart`.

Риск: не-2xx ответ скачивания мог буферизоваться без лимита; старый файл удалялся до успешного rename нового `.part`.

Исправление: error-body читается максимум до 64 КиБ; старый файл временно переносится в backup и восстанавливается при ошибке rename.

## F-053. Включение TOTP без повторной проверки пароля

Поверхность: `app/routers/auth.py`, `app/schemas/auth.py`, `native/cctv_console/lib/src/core/network/api_client.dart`, `native/cctv_console/lib/src/features/settings/profile_security_panel.dart`.

Риск: украденный JWT позволял сгенерировать TOTP secret и активировать 2FA без знания пароля.

Исправление: `/auth/totp/setup` и `/auth/totp/activate` требуют `current_password`; UI запрашивает текущий пароль перед показом секрета. TOTP-проверки используют `SELECT ... FOR UPDATE`, чтобы один код не проходил в параллельных запросах.

## Проверки

- `py -3.11 -m unittest processor.tests.test_security_helpers processor.tests.test_realtime_pipeline` — OK, 38 tests.
- `docker compose run --rm --no-deps backend python -m unittest discover -s app/tests -p 'test_*.py'` — OK, 20 tests на новом backend image.
- `py -3.11 -m compileall -q app processor cctv_ai migrations` — OK.
- `flutter pub get` в ASCII-копии Native Console — OK.
- `dart analyze lib test` в ASCII-копии Native Console — OK, 11 секунд.
- `flutter test test\widget_test.dart --reporter expanded --timeout 30s` в ASCII-копии Native Console — OK, 2 tests.
- `git diff --check` — OK, только CRLF-предупреждения рабочей копии.
- `docker compose build backend` с `DOCKER_BUILDKIT=0` — OK.
- `docker compose run --rm --no-deps backend alembic upgrade head` — OK, применён переход `0009 -> 0010`.
- `docker compose up -d --no-deps backend` — OK, backend пересоздан без БД/volumes.
- `curl.exe http://127.0.0.1:8001/health` — HTTP 200, `{"status":"ok"}`.
- `docker compose ps` — `backend` и `db` healthy, `mediamtx` running.
- `docker compose run --rm --no-deps backend alembic current` — `0010 (head)`.

## Дополнительная проверка 2026-06-13 14:45

- `flutter --no-version-check pub get --offline` в свежей ASCII-копии Native Console — OK, 12 секунд. Предыдущий зависший `flutter pub get` не оставил активных `flutter/dart` процессов.
- `dart analyze lib/src/core/network/api_client.dart lib/src/features/settings/profile_security_panel.dart test/widget_test.dart` — OK.
- `dart analyze lib test` — OK после повторного запуска analyzer, 5 секунд.
- `flutter --no-version-check test test\widget_test.dart --reporter expanded --timeout 30s` — OK, 2 tests.
- `flutter --no-version-check build windows --release` — OK; первый запуск упал на stale Flutter plugin symlink во временной копии, после очистки `windows/flutter/ephemeral` и `build` во временной копии сборка прошла.
- Windows portable Console обновлён: `C:\Users\dsok8\Desktop\CCTV Console Flutter portable\cctv_console.exe`, SHA256 `6F6992127A443B0507457635E398AAFA4F3D7D8EE4D866B7E842DFFFB663DC1B`.
- `flutter --no-version-check build apk --release --target-platform android-arm64 --split-per-abi` — OK; APK обновлён: `C:\Users\dsok8\Desktop\CCTV Console Android\CCTV-Console-arm64-v8a-release.apk`, SHA256 `6EC06C28F6F4EF66BAB5E4BD4A9DA698B0F4140B8DF1ACFCE83E643523DBF535`.
- `py -3.11 -m compileall -q app processor cctv_ai migrations` — OK после последних правок.
- `py -3.11 -m unittest processor.tests.test_security_helpers processor.tests.test_realtime_pipeline` — OK, 38 tests.
- `docker compose build backend` — OK на актуальных исходниках.
- `docker compose run --rm --no-deps backend python -m unittest discover -s app/tests -p 'test_*.py'` — OK, 22 tests.
- `docker compose run --rm --no-deps backend alembic current` — `0010 (head)`.
- `docker compose up -d --no-deps backend` — OK; `http://127.0.0.1:8001/health` вернул `{"status":"ok"}`.
- Processor Runtime/Supervisor пересобраны через `$env:SKIP_PROCESSOR_CLI='1'; py -3.11 processor\build_exe.py`.
- Processor portable обновлён: Runtime SHA256 `1F3AE8FE4869BA7FAA55B74CF7AD7F3B495DF5514990C08E6500D59FB2731066`, Supervisor SHA256 `EECA3D595DC41F3C3AE84B5D9C29DCB8CE78106D1034A22D6280E488EA86A83A`.
- CUDA CLI через `--cli-capture-file` — OK: `selected_device=cuda`, `selected_provider=CUDAExecutionProvider`.
- Обновлённый Processor Runtime запущен обратно; `http://127.0.0.1:8777/health` вернул `{"ok": true}`.
- Реальный MJPEG raw/overlay сейчас не измерен: камера `192.168.88.242` недоступна в LAN, `Test-NetConnection` по портам 554/2020/443 не проходит, ARP не показывает MAC камеры. Это внешний блокер стенда, не ошибка сборки.
- `git diff --check` — OK, только CRLF warnings рабочей копии.
- Cleanup исходников: после копирования release-артефактов удалены только generated-директории `processor/build`, `processor/dist`, `native/cctv_processor_gui/build`, `native/cctv_console/build`. Portable-папки на рабочем столе и `CCTV Processor Flutter portable.zip` не трогались.
- Повторный scan вне `Диплом/Дизайн`: файлов больше 50 МБ и архивов/бинарников `.zip/.7z/.rar/.exe/.dll/.pdb` в исходниках не найдено.
- `native/cctv_console/android/gradlew.bat` оставлен намеренно: это Gradle wrapper Android-проекта, не пользовательская bat-запускалка.

## Дополнительный проход 2026-06-13 15:05

Ограничение: subagent/deep-security-scan не смог стартовать из-за лимита среды выполнения. Дальнейший аудит выполнен локально основным агентом с теми же направлениями проверки: Docker hardening, опасные subprocess/SQL sinks, лимиты входных данных backend/processor и Native Console storage/network.

## F-054. MediaMTX был привязан к `latest`

Поверхность: `docker-compose.yml`.

Риск: при повторном развёртывании `latest` мог подтянуть другой образ MediaMTX без явного контроля версии.

Исправление: образ MediaMTX закреплён digest-ом `bluenviron/mediamtx@sha256:35f9e8aefaca5352b5f4667c8cd529360a53a493c51fa639e8f5898c03bc0d06`. Контейнер `mediamtx` пересоздан, `docker compose ps` показывает digest, а не `latest`.

## F-055. Избыточные Linux capabilities у публичных контейнеров

Поверхность: `docker-compose.yml`.

Риск: nginx/certbot запускались с capabilities по умолчанию, хотя для штатной работы они не нужны полностью.

Исправление: для `nginx` добавлен `cap_drop: [ALL]` и точечно возвращён только `NET_BIND_SERVICE`; для `certbot` добавлен `cap_drop: [ALL]`.

## F-056. Processor Docker images писали `.pyc` и буферизовали логи

Поверхность: `processor/Dockerfile`, `processor/Dockerfile.nvidia`.

Риск: лишний writable-мусор в контейнере и задержки диагностических логов при падениях.

Исправление: добавлены `PYTHONDONTWRITEBYTECODE=1` и `PYTHONUNBUFFERED=1`.

## F-057. Face upload защищал размер файла, но не размер decoded image

Поверхность: `app/routers/face.py`, `app/routers/persons.py`.

Риск: маленький сжатый image мог разворачиваться в большой OpenCV-массив перед извлечением embedding.

Исправление: добавлен общий `_decode_face_image` с лимитом `_MAX_FACE_IMAGE_PIXELS`; загрузка фото персоны и enrolment используют один проверенный decoder. Добавлен unit-тест decoded-pixel cap.

## F-058. Processor command result мог обойти Content-Length лимит chunked body

Поверхность: `app/routers/processors.py`.

Риск: middleware проверял `Content-Length`, но chunked request без заголовка мог начать читать тело до Pydantic-валидации.

Исправление: endpoint результата команды теперь читает `request.stream()` вручную и обрывает body после 256 KiB до JSON/Pydantic-валидации. Добавлен unit-тест для stream без `Content-Length`.

## F-059. `start-server.sh` вводил в заблуждение по bootstrap-паролю

Поверхность: `scripts/start-server.sh`.

Риск: скрипт печатал `admin/admin`, хотя фактический пароль либо генерируется, либо берётся из `.env`.

Исправление: скрипт явно выводит сгенерированный пароль только при генерации; если пароль уже задан, пишет, что смотреть нужно `BOOTSTRAP_ADMIN_PASSWORD` в `.env`.

## Дополнительные результаты ручного аудита

- Опасных Python-вызовов `shell=True` и `os.system` в `app`, `processor`, `cctv_ai`, `scripts` не найдено. Найденные `subprocess.run/Popen/create_subprocess_exec` используют argv-list; места с ffmpeg/ffprobe и supervisor проверены отдельно.
- SQL scan по `text(`/`exec_driver_sql` не выявил пользовательской строковой SQL-инъекции: найденные SQL-фрагменты статические либо ложные совпадения в PDF/text helpers.
- Android Console: `usesCleartextTraffic=false`; cleartext разрешён только через `network_security_config.xml` для `localhost`, `127.0.0.1`, emulator `10.0.2.2` и стендового backend `192.168.88.10`.
- Токены Native Console хранятся через `FlutterSecureStorage`; `SharedPreferences` используются для профилей подключения, темы и несекретных настроек.
- `flutter pub get` не оставил зависших `flutter/dart` процессов; активен только Java-процесс Android Studio, не относящийся к зависшему тесту.

## Проверки после дополнительного прохода

- `py -3.11 -m compileall -q app processor cctv_ai migrations` — OK.
- `docker compose config --quiet` — OK.
- `git diff --check` — OK, только CRLF warnings рабочей копии.
- `py -3.11 -m unittest processor.tests.test_security_helpers processor.tests.test_realtime_pipeline` — OK, 38 tests.
- `docker compose build backend` — OK.
- `docker compose run --rm --no-deps backend python -m unittest discover -s app/tests -p 'test_*.py'` — OK, 24 tests.
- `docker compose up -d --no-deps backend` — OK, backend healthy.
- `docker compose up -d --no-deps mediamtx` — OK, MediaMTX поднят с pinned digest.
- `Invoke-WebRequest http://127.0.0.1:8001/health` — OK, `{"status":"ok"}`.
- `docker logs --tail 80 cctv-backend-1` — критических ошибок после перезапуска не обнаружено.
- Точечный scan известных стендовых секретов/идентификаторов в исходниках без `Диплом/Дизайн`, `build`, `dist`, `.dart_tool` — OK, совпадений нет.
- Pattern scan на private keys, AWS/GitHub/Slack token formats — OK, совпадений нет.
- `gitleaks`, `trufflehog`, `detect-secrets` в PATH не найдены; external secret scanner не запускался.

## Дополнительный проход 2026-06-13 18:40

После повторного dependency/container-аудита обновлены Python-зависимости runtime-ветки и пересобраны контейнеры/portable Runtime. Скачивание зависимостей выполнялось обычным `py -3.11 -m pip install -r processor\requirements.txt`, без отдельного wheel-cache и без proxy-overrides.

## F-060. Устаревшие OpenCV/NumPy/ONNXRuntime в runtime-ветке

Поверхность: `requirements.txt`, `processor/requirements.txt`, `processor/Dockerfile`.

Риск: старые wheels тянули устаревшие нативные библиотеки FFmpeg/OpenCV и увеличивали поверхность известных CVE в backend/processor контейнерах.

Исправление: runtime-ветка обновлена до `opencv-python-headless>=4.13,<4.14`, `numpy>=2,<2.3`, `onnxruntime>=1.23.2,<1.24`; Windows Processor использует `onnxruntime-gpu>=1.23.2,<1.24`. В контейнерах подтверждены `cv2=4.13.0`, `numpy=2.2.6`, `onnxruntime=1.23.2`; старых `libavcodec 59` в образах нет.

## F-061. NVIDIA Dockerfile был несовместим с обновлением до ONNXRuntime 1.23

Поверхность: `processor/Dockerfile.nvidia`, `processor/requirements-nvidia.txt`.

Риск: образ NVIDIA основан на Python 3.10/CUDA 11.8. Прямое обновление `onnxruntime-gpu` до 1.23 для него ломает сборку и может создать ложное ощущение, что GPU-контейнер актуализирован.

Исправление: NVIDIA requirements зафиксированы в совместимой ветке `onnxruntime-gpu>=1.16.3,<1.17` с прежним диапазоном OpenCV/NumPy. Полный переход NVIDIA-образа на CUDA 12/Python 3.11 вынесен как отдельная миграция, чтобы не сломать текущий runtime.

## F-062. MediaMTX digest с High CVE

Поверхность: `docker-compose.yml`.

Риск: ранее закреплённый digest MediaMTX уже имел известные High CVE по контейнерным сканерам.

Исправление: digest MediaMTX обновлён на текущий проверенный образ; `trivy` и `grype` для MediaMTX после обновления показывают `Critical=0`, `High=0`.

## F-063. Linux-зависимость `imageio-ffmpeg` в backend/processor образах

Поверхность: `requirements.txt`.

Риск: wheel `imageio-ffmpeg` приносил дополнительный FFmpeg-бинарник в Linux-контейнеры, хотя текущий backend/processor используют системный ffmpeg/OpenCV.

Исправление: зависимость ограничена Windows-средой через marker `platform_system == "Windows"`. В Linux Docker образах лишний FFmpeg wheel больше не устанавливается.

## F-064. PyInstaller runtime-зависимость попадала в Linux контейнеры

Поверхность: `processor/requirements.txt`, `processor/Dockerfile`.

Риск: PyInstaller нужен для Windows portable сборки, но в Linux контейнере добавляет лишнюю поверхность зависимостей.

Исправление: PyInstaller оставлен Windows-only. Docker processor больше не тянет PyInstaller в runtime image.

## F-065. MJPEG overlay мог ждать новый overlay-кадр до 0.5 секунды

Поверхность: `processor/media_server.py`.

Риск: при тяжёлом `face_pipeline` overlay stream мог отдавать редкие кадры и создавать видимые паузы/мигание, хотя raw stream продолжал идти.

Исправление: overlay generator теперь ждёт кадр не дольше `frame_interval`, а при короткой задержке overlay-рендера повторяет последний валидный overlay-кадр до 0.75 с. Это не блокирует raw и убирает клиентские паузы без изменения inference-пайплайна.

## F-066. MJPEG latency script не показывал реальные длинные паузы

Поверхность: `scripts/measure_mjpeg_latency.py`.

Риск: по одному среднему FPS было трудно увидеть редкие провалы stream-а.

Исправление: добавлены `interval_ms_max`, `gaps_over_250ms`, `gaps_over_300ms`; текущие raw/overlay замеры теперь явно показывают отсутствие длинных пауз.

## Остаточные риски после контейнерных сканов

- `trivy` после обновлений: backend `Critical=8`, `High=18`, processor `Critical=2`, `High=8`, `FixableHighCritical=0`; Postgres и MediaMTX `0/0`.
- `grype` после обновлений: backend `Critical=14`, `High=45`, `FixableHighCritical=4`; processor `Critical=7`, `High=21`, `FixableHighCritical=4`; Postgres и MediaMTX `0/0`.
- Оставшиеся fixable High/Critical по `grype` относятся к FFmpeg 8.0.1 внутри wheel `opencv-python-headless 4.13.0.92` (`CVE-2026-40962`, fix FFmpeg 8.1) и к Python 3.11.15 CVE, где fixes заявлены только в ветках Python 3.13/3.14/3.15 beta. На текущую дату нет безопасного patch-обновления OpenCV wheel/ветки Python 3.11, поэтому это зафиксировано как upstream/major-version residual risk.

## Проверки после dependency/runtime прохода

- `py -3.11 -m pip install -r processor\requirements.txt` — OK; локально подтверждены `cv2 4.13.0`, `numpy 2.2.6`, `onnxruntime 1.23.2`, providers `TensorrtExecutionProvider`, `CUDAExecutionProvider`, `CPUExecutionProvider`.
- `py -3.11 -m unittest processor.tests.test_realtime_pipeline processor.tests.test_security_helpers` — OK, 44 tests.
- `py -3.11 -m compileall -q app processor cctv_ai migrations` — OK.
- Docker backend tests в актуальном образе — OK, `39 passed`.
- Docker processor tests в актуальном образе — OK, `44 passed`.
- `docker compose --profile core up -d --no-build backend mediamtx` — OK после локальной сборки образов; backend/db healthy, MediaMTX running.
- `Invoke-WebRequest http://127.0.0.1:8001/health` — OK, `{"status":"ok"}`.
- Processor portable обновлён: `C:\Users\dsok8\Desktop\CCTV Processor Flutter portable\processor\CCTV-Processor-Runtime.exe`, SHA256 `A96FF8DE00256FE56E4B34E2F3E453A01FBE48DE513EB541212C1122F4AFAFC7`; Supervisor SHA256 `CAAD7626F32ACFC4FD727906AA03926F636E8543CFF9C6AB961185764BE3277E`.
- CUDA portable CLI — OK: `selected_device=cuda`, `selected_provider=CUDAExecutionProvider`.
- Processor health — OK: `http://127.0.0.1:8777/health` вернул `{"ok": true}`.
- Реальный MJPEG Tapo после overlay-stall fix, 30 секунд: raw `14.35 FPS`, max gap `173.1 мс`, gaps `>250/>300 = 0/0`; overlay `17.95 FPS`, max gap `80.0 мс`, gaps `>250/>300 = 0/0`.
- Processor metrics всё ещё показывают узкое место `face_pipeline: p95 546 мс, max 644 мс`; это уже не блокирует live MJPEG, но остаётся целью отдельной оптимизации inference.
