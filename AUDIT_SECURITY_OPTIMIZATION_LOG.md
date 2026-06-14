# Журнал аудита безопасности и оптимизации CCTV Комплекс

Дата ведения: 12.06.2026.

Правила журнала:
- не записывать пароли, токены, приватные ключи и реальные секреты;
- фиксировать только технические факты: поверхность, риск, исправление, проверка;
- `Диплом` и `Дизайн` не входят в аудит исходников.

## Исправлено

### F-001. Processor media мог остаться без авторизации

Поверхность: `processor/config.py`, `processor/media_server.py`.

Риск: при пустом `MEDIA_TOKEN` endpoints Processor media могли быть доступны без токена.

Исправление: пустой media token больше не считается валидной конфигурацией; при пустом значении генерируется runtime-token, защищённые endpoints требуют токен.

Проверка: Python compileall, processor unittest.

### F-002. `/embeddings/extract` не ограничивал размер тела

Поверхность: Processor media и backend photo embedding endpoints.

Риск: большой upload мог создавать лишнюю нагрузку на память/CPU.

Исправление: добавлены лимиты для embedding extraction и backend photo upload.

Проверка: Python compileall.

### F-003. Processor media URL собирался из недостаточно проверенных host/port

Поверхность: `app/processor_media.py`.

Риск: malformed host/port могли попасть в backend proxy target.

Исправление: добавлена базовая проверка host и диапазона port.

Проверка: Python compileall.

### F-004. Processor recording preview игнорировал caps

Поверхность: `processor/media_server.py`.

Риск: MJPEG/snapshot архива могли отдавать исходное разрешение/FPS/quality и грузить слабые клиенты.

Исправление: `fps`, `max_width`, `quality` теперь применяются на Processor стороне; добавлены resize и JPEG quality clamp.

Проверка: processor unittest.

### F-005. Processor Docker создавал non-root user, но не использовал его

Поверхность: `processor/Dockerfile`, `processor/Dockerfile.nvidia`.

Риск: контейнер Processor стартовал от root.

Исправление: добавлен `USER cctv`.

Проверка: `docker compose build processor`, `docker image inspect`.

### F-006. Отсутствовал `processor/docker-entrypoint.sh`

Поверхность: Processor Docker build.

Риск: Processor Docker image не собирался из исходников.

Исправление: добавлен entrypoint, создающий runtime/media директории и запускающий command через `exec`.

Проверка: `docker compose build processor`.

### F-007. Upload записей от Processor не имел backend-side лимита

Поверхность: `app/routers/processors.py`, `app/config.py`.

Риск: service key мог записать слишком большой файл и заполнить диск backend.

Исправление: добавлен `PROCESSOR_RECORDING_UPLOAD_MAX_BYTES`, default 2 GiB, hard minimum 8 MiB, превышение возвращает HTTP 413.

Проверка: Python compileall.

### F-008. Смена цвета темы в Console вызывала слишком частые глобальные rebuild

Поверхность: Native Console settings.

Риск: FPS проседал при drag color picker.

Исправление: `_ColorEditor` хранит draft color локально и отправляет глобальное изменение с debounce.

Проверка: `flutter test`, `dart analyze lib test`.

### F-009. Reports tab попадал в слепой автоrefresh

Поверхность: Native Console `AppShell`.

Риск: отчёты могли периодически грузить backend без действия пользователя.

Исправление: `/reports` убран из active-route auto-refresh; explicit refresh и `system/changes` сохранены.

Проверка: `flutter test`, `dart analyze lib test`.

### F-010. Reports dashboard слишком широко грузил записи и ревью

Поверхность: `app/routers/reports.py`.

Риск: `.all()` по архиву и ревью давал лишнюю нагрузку на backend/DB.

Исправление: записи и ревью фильтруются SQL-запросом по видимым камерам, датам, processor/person filters.

Проверка: `py -3.11 -m py_compile app\routers\reports.py`.

### F-011. Batch ffmpeg операции могли зависнуть без timeout

Поверхность: `app/routers/recordings.py`.

Риск: битый/тяжёлый файл мог занять backend worker.

Исправление: добавлен `FFMPEG_BATCH_TIMEOUT_SECONDS = 180`, stitch timeout отдаёт 503, cache transcode fallback не ломает playback.

Проверка: Python compileall.

### F-012. Service API-key cache не учитывал expiry на cache-hit

Поверхность: `app/dependencies.py`.

Риск: ключ мог приниматься до 5 минут после истечения срока в рамках процесса.

Исправление: TTL уменьшен до 30 секунд, cache deadline ограничен `expires_at`.

Проверка: Python compileall.

### F-013. Camera/ONVIF sources не блокировали localhost/link-local

Поверхность: admin camera CRUD/probe, backend direct-stream, ONVIF/PTZ, Processor source resolver.

Риск: camera source мог направить backend/Processor на localhost, loopback, link-local или invalid local URL.

Исправление: добавлены `app/network_policy.py` и `processor/network_policy.py`; private LAN камеры разрешены, localhost/loopback/link-local/multicast/unspecified блокируются.

Проверка: processor unittest, inline checks для `192.168.88.242`, `C200`, `localhost`, `127.0.0.1`, `::1`, `169.254.169.254`, `file:///...`.

### F-014. Reports dashboard грузил события целиком для счётчиков

Поверхность: `app/routers/reports.py`.

Риск: рост таблицы `events` увеличивал память/CPU backend при открытии отчётов.

Исправление: event counts, events by type, last event per camera и processor event counts считаются SQL-агрегацией вместо загрузки всех rows.

Проверка: `py -3.11 -m py_compile app\routers\reports.py`.

### F-015. Reports dashboard грузил auth/audit rows целиком для счётчиков

Поверхность: `app/routers/reports.py`.

Риск: рост `auth_events` и `audit_log` увеличивал память/CPU backend.

Исправление: total/top counters считаются SQL-агрегацией; для UI загружаются только последние auth/audit rows и последние ошибки входа.

Проверка: `py -3.11 -m py_compile app\routers\reports.py`, Python compileall, backend Docker build, backend health через `curl.exe`.

### F-016. Docker Compose имел слабый fallback пароля PostgreSQL

Поверхность: `docker-compose.yml`, `.env.example`.

Риск: при прямом запуске compose или копировании примера конфигурации можно было получить рабочий PostgreSQL с паролем `cctv`.

Исправление: compose теперь требует явный `POSTGRES_PASSWORD`; `.env.example` оставляет пароль пустым, чтобы его генерировал `scripts/cctv-up.ps1` или задавал администратор.

Проверка: `docker compose --profile server-cpu config --quiet`.

### F-017. Processor CLI выводил локальные секреты открытым текстом

Поверхность: `processor/cli.py`, команда `config show`.

Риск: `api_key` и `media_token` могли попасть в терминал, скриншоты или лог диагностики.

Исправление: `config show` и `config show --json` маскируют `api_key`/`media_token` по умолчанию; для локальной диагностики оставлен явный флаг `--show-secrets`.

Проверка: `py -3.11 -m py_compile processor\cli.py`, `py -3.11 -m processor.cli config show`, `py -3.11 -m processor.cli config show --json`.

### F-018. Python Runtime сохранял `processor_config.json` без ограничения прав

Поверхность: `processor/runtime.py`.

Риск: локальный файл с `api_key` и `media_token` мог остаться доступным шире, чем нужно, если конфиг создавался CLI/headless runtime, а не Native Processor GUI.

Исправление: `save_config()` после записи best-effort ограничивает права: `0600` на POSIX, `icacls` для текущего пользователя/System/Admins на Windows.

Проверка: `py -3.11 -m py_compile processor\runtime.py processor\cli.py`, сохранение конфига во временный `PROCESSOR_RUNTIME_DIR`.

### F-019. Default admin создавался без обязательной смены пароля

Поверхность: `app/main.py`, первичная инициализация пустой БД.

Риск: при `ALLOW_DEFAULT_ADMIN=true` и пустом `BOOTSTRAP_ADMIN_PASSWORD` создавался известный `admin/admin` без флага смены пароля.

Исправление: default admin по-прежнему возможен только если это явно разрешено, но теперь получает `must_change_password=True`.

Проверка: `py -3.11 -m py_compile app\main.py`.

### F-020. `Cache-Control: no-store` не покрывал `/face` и `/groups`

Поверхность: `app/main.py`, security headers middleware.

Риск: ответы с персональными/административными данными могли кэшироваться клиентом/прокси слабее, чем остальные API-разделы.

Исправление: `/face` и `/groups` добавлены в список API-префиксов, для которых backend выставляет `Cache-Control: no-store`.

Проверка: `py -3.11 -m py_compile app\main.py`.

### F-021. Git ignore не закрывал Flutter build/.dart_tool и zip-артефакты

Поверхность: `.gitignore`.

Риск: после сборок Native Console/Processor GUI в git могли попасть `.dart_tool`, `build/` или zip-архивы артефактов.

Исправление: добавлены `native/**/build/`, `native/**/.dart_tool/`, Flutter plugin metadata и `*.zip`.

Проверка: `git status --short`, `git ls-files` sweep по build/dist/env/zip шаблонам.

### F-022. Processor event `snapshot_b64` принимался без лимита

Поверхность: `app/routers/processors.py`, `app/tests/test_processor_payloads.py`.

Риск: сервисный endpoint `/processors/{processor_id}/events` мог получить слишком большой base64 snapshot и нагрузить память backend.

Исправление: добавлен лимит 8 MiB на decoded snapshot и предварительный лимит на base64 длину; слишком большой payload возвращает HTTP 413. Дополнительно 413-константы переведены на актуальную `HTTP_413_CONTENT_TOO_LARGE`.

Проверка: `docker compose build backend`, `docker compose run --rm --no-deps backend python -m unittest app.tests.test_processor_payloads`.

### F-023. Reports dashboard грузил все `event_reviews` для метрик

Поверхность: `app/routers/reports.py`.

Риск: рост очереди ревью увеличивал память/CPU backend при открытии отчётов.

Исправление: статусы ревью, top reviewers, pending by camera и среднее время ревью считаются SQL-агрегацией; для UI последних действий загружаются только 10 последних ревью. Во время smoke найдено и исправлено неверное имя PK в агрегате: `review_id` -> `event_review_id`.

Проверка: `py -3.11 -m py_compile app\routers\reports.py`, smoke `/reports/dashboard` после обновления backend — HTTP 200, `dur_ms=118.4` в backend audit log.

### F-024. Hostname камеры проходил без проверки DNS-результата

Поверхность: `app/network_policy.py`, `processor/network_policy.py`.

Риск: literal IP уже блокировались для loopback/link-local, но hostname мог резолвиться в `127.0.0.1`, `169.254.0.0/16` или другой запрещённый адрес уже после валидации. Это оставляло SSRF-сценарий через DNS-имя камеры.

Исправление: для hostname добавлена best-effort DNS-проверка через `socket.getaddrinfo`; если хотя бы один resolved address попадает в loopback, unspecified, multicast или link-local, источник камеры отклоняется. Нерезолвящиеся локальные имена вроде `C200` не ломаются: они всё равно не дадут успешного сетевого подключения до появления валидного DNS/NetBIOS-резолва.

Проверка: `py -3.11 -m unittest processor.tests.test_realtime_pipeline` — 30 tests OK; `docker compose run --rm --no-deps backend python -m unittest app.tests.test_processor_payloads app.tests.test_network_policy` — 6 tests OK после пересборки backend image; свежий backend-контейнер поднят, `/health` — OK.

### F-025. Backend config содержал hardcoded fallback-пароль PostgreSQL

Поверхность: `app/config.py`, `app/db.py`.

Риск: в исходниках оставался fallback `DATABASE_URL` с паролем. Даже если Docker уже требовал `POSTGRES_PASSWORD`, локальный запуск без `.env` мог незаметно использовать credential из кода.

Исправление: default `DATABASE_URL` очищен; перед созданием SQLAlchemy engine добавлена явная ошибка `DATABASE_URL is required...`. Штатный Docker-путь не ломается, потому что Compose формирует `DATABASE_URL` из `.env`.

Проверка: `py -3.11 -m py_compile app\config.py app\db.py`; `docker compose build backend` при `DOCKER_BUILDKIT=0`; `docker compose run --rm --no-deps backend python -m unittest app.tests.test_processor_payloads app.tests.test_network_policy` — 6 tests OK; свежий backend-контейнер поднят, `/health` — OK.

### F-026. Processor media proxy доверял `advertised_ip` без сетевой политики

Поверхность: `app/processor_media.py`, proxy URL для записей/снимков Processor.

Риск: Processor сообщает backend свой `advertised_ip` и `ip_address`; до исправления backend фильтровал их только regex-ом. Скомпрометированный или ошибочно настроенный Processor мог заставить backend ходить в `127.0.0.1`, link-local/metadata address или другой служебный host.

Исправление: `_safe_processor_media_host()` теперь применяет общий `validate_camera_host()`, поэтому loopback/link-local/unspecified/multicast и hostname с запрещённым DNS-резолвом не используются для proxy URL. Добавлены тесты на блокировку `127.0.0.1` и `169.254.0.0/16`.

Проверка: `py -3.11 -m py_compile app\processor_media.py app\tests\test_processor_media.py`; `docker compose run --rm --no-deps backend python -m unittest app.tests.test_processor_payloads app.tests.test_network_policy app.tests.test_processor_media` — 8 tests OK; свежий backend-контейнер поднят, `/health` — OK. Локальный host Python не запускает этот unittest из-за отсутствующего SQLAlchemy, контейнерная проверка используется как основная.

### F-027. Docker profile `public` был невалиден и nginx/certbot были слабее укреплены

Поверхность: `docker-compose.yml`.

Риск: `docker compose --profile public config` падал, потому что `nginx` зависел от `backend`, но `backend/db/mediamtx` не входили в profile `public`. Дополнительно `nginx` и `certbot` не имели `security_opt: no-new-privileges:true`, в отличие от core-сервисов.

Исправление: `public` добавлен в профили `db`, `backend`, `mediamtx`; для `nginx` и `certbot` включён `no-new-privileges`. Более жёсткие `cap_drop/read_only` для nginx/certbot не добавлялись без runtime-проверки, чтобы не сломать bind 80/443 и renew state.

Проверка: `docker compose --profile public config --quiet`, `docker compose --profile server-cpu config --quiet`, `docker compose --profile core config --quiet` — OK.

### F-028. Media-токен передавался в URL Native Console

Поверхность: `app/dependencies.py`, Native Console API client, live/recordings/admin media widgets.

Риск: query-параметр мог попасть в историю, диагностические логи и скриншоты.

Исправление: Native Console передаёт media-токен через `Authorization: Bearer`; query-вариант оставлен только как управляемый legacy fallback backend.

Проверка: `flutter test`, `dart analyze lib test`, Windows/Android release build.

### F-029. Backend media-задачи не имели общих ограничений размера и параллелизма

Поверхность: `app/routers/recordings.py`.

Риск: большой pull/upload или несколько одновременных ffmpeg могли исчерпать диск, RAM и CPU.

Исправление: добавлены лимиты upload/pull-cache, проверка `Content-Length` и фактического числа принятых байт, общий semaphore для ffmpeg.

Проверка: Python compileall, backend health, Docker status.

### F-030. Reports загружал лишние строки и мог формировать неограниченный экспорт

Поверхность: `app/routers/reports.py`, `app/config.py`.

Риск: рост записей и appearance rows увеличивал память, время ответа и размер экспорта.

Исправление: статистика записей переведена на SQL-агрегации; экспорт ограничен `REPORT_EXPORT_MAX_ROWS` с явным HTTP 413 при превышении.

Проверка: Python compileall, backend `/health` — HTTP 200.

### F-031. Processor не ограничивал очередь загрузок и локальный архив

Поверхность: `processor/config.py`, `processor/detection.py`, `processor/runtime.py`.

Риск: при недоступном backend фоновые upload-задачи и записи могли неограниченно занимать память и диск.

Исправление: добавлены bounded upload queue/concurrency и отключённые по умолчанию retention-лимиты по возрасту/объёму. Очистка разрешена только внутри `RECORDINGS_DIR`.

Проверка: processor unittest, Runtime build.

### F-032. Processor игнорировал отдельный bind-адрес media server

Поверхность: `processor/config.py`, `processor/runtime.py`, `processor/main.py`.

Риск: media server мог слушать более широкую сеть, чем указано оператором.

Исправление: добавлен `MEDIA_BIND`/`media_bind`, фактический bind берётся из конфигурации.

Проверка: Python compileall, portable Runtime `/health` — HTTP 200.

### F-033. Ошибка GPU body backend могла повторно инициализировать тяжёлый fallback

Поверхность: `processor/body_detector.py`.

Риск: повторные ошибки MMDeploy/CUDA создавали скачки latency и нагрузки.

Исправление: после ошибки non-CPU backend используется sticky CPU fallback на ограниченный период перед повторной попыткой GPU.

Проверка: processor unittest, Runtime CUDA diagnostics.

### F-034. DNS-проверка не закрепляла проверенный IP

Поверхность: `app/network_policy.py`, `processor/network_policy.py`.

Риск: между валидацией hostname и сетевым запросом DNS-ответ мог измениться.

Исправление: URL hostname преобразуется в URL с проверенным IP до сетевого обращения; исходный hostname сохраняется только там, где он нужен протоколу.

Проверка: backend/processor network-policy tests.

### F-035. До выпуска сертификата public profile мог проксировать API по HTTP

Поверхность: nginx templates/entrypoint, `scripts/setup_public_https.py`.

Риск: первичная настройка public profile могла временно открыть API без TLS.

Исправление: добавлен ACME-only HTTP template: доступны только challenge и `/health`, остальные запросы получают 426. Полный HTTP proxy включается отдельным флагом.

Проверка: compose config; runtime nginx-проверка остаётся обязательной перед production-публикацией.

### F-036. `.env` при public setup создавался без явного ограничения прав

Поверхность: `scripts/setup_public_https.py`.

Риск: секреты могли наследовать слишком широкие права файловой системы.

Исправление: запись `.env` централизована и после записи применяется `chmod 0600` на поддерживаемых системах.

Проверка: Python compileall.

### F-037. Android release использовал debug signing

Поверхность: `native/cctv_console/android/app/build.gradle.kts`.

Риск: release APK нельзя считать пригодным для распространения и безопасного обновления.

Исправление: release требует отдельный keystore из игнорируемого `key.properties` или переменных окружения; debug signing удалён. Добавлен безопасный пример конфигурации.

Проверка: APK собран и подтверждён `apksigner`: v2 signature valid, RSA 4096.

### F-038. Gradle был настроен на память, несоразмерную тестовому ПК

Поверхность: `native/cctv_console/android/gradle.properties`.

Риск: `-Xmx8G`, metaspace до 4 ГБ и отдельный Kotlin daemon на ПК с 16 ГБ вызывали paging; команда выглядела зависшей более часа.

Исправление: Gradle ограничен 4 ГБ heap, 1 ГБ metaspace, четырьмя workers; Kotlin daemon ограничен 2 ГБ.

Проверка: Flutter tests — 2/2 за 20 секунд; Android release assemble — 32 секунды.

### F-039. MJPEG-клиент мог бесконечно ждать зависший поток

Поверхность: Native Console `mjpeg_stream_view.dart`.

Риск: потерянное соединение оставляло фоновые ресурсы и зависшее состояние UI.

Исправление: добавлены timeout подключения и idle timeout потока.

Проверка: `dart analyze lib test`, Windows/Android release build.

## Проверки текущего прохода

- `py -3.11 -m unittest processor.tests.test_realtime_pipeline processor.tests.test_security_helpers` — OK, 36 tests.
- `py -3.11 -m compileall -q app processor cctv_ai` — OK.
- `py -3.11 -m py_compile app\main.py app\network_policy.py app\camera_utils.py app\routers\reports.py app\routers\processors.py app\routers\face.py app\routers\persons.py processor\cli.py processor\runtime.py processor\network_policy.py processor\media_server.py` — OK.
- `docker compose build backend processor` — OK при `DOCKER_BUILDKIT=0`; обычный BuildKit на этом хосте упал до сборки из-за Docker gRPC header `x-docker-expose-session-sharedkey` с непечатаемым символом, это проблема окружения Docker/BuildKit, а не Dockerfile.
- `docker compose --profile server-cpu config --quiet` — OK.
- `docker compose --profile public config --quiet` — OK после F-027.
- `docker compose --profile core config --quiet` — OK после F-027.
- `docker compose run --rm --no-deps backend python -m unittest app.tests.test_processor_payloads` — OK, 3 tests.
- `docker compose run --rm --no-deps backend python -m unittest app.tests.test_processor_payloads app.tests.test_network_policy` — OK, 6 tests после пересборки backend image.
- `docker compose run --rm --no-deps backend python -m unittest app.tests.test_processor_payloads app.tests.test_network_policy app.tests.test_processor_media` — OK, 8 tests после пересборки backend image.
- `docker compose run --rm --no-deps backend python -m unittest discover -s app/tests -p 'test_*.py'` на свежем image — OK, 16 tests.
- `docker compose build processor` — OK после F-024.
- `docker compose up -d --no-deps backend` — OK после F-024/F-025/F-026, свежий backend image запущен без пересоздания БД/volumes.
- `docker logs --tail 40 cctv-backend-1` — startup OK, stack trace нет.
- `curl.exe http://127.0.0.1:8001/health` — HTTP 200, `{"status":"ok"}`.
- `/reports/dashboard` smoke на обновлённом backend — HTTP 200.
- `Invoke-WebRequest http://127.0.0.1:8001/health` на хосте вернул внутренний `NullReferenceException` PowerShell cmdlet; backend подтверждён через `curl.exe` и логи контейнера.
- `docker logs --tail 80 cctv-backend-1` — только успешные `/health`, stack trace нет.
- `py -3.11 -m processor.cli config show` — OK, секретные поля замаскированы.
- `py -3.11 -m processor.cli config show --json` — OK, секретные поля замаскированы.
- `processor.runtime.save_config()` во временный `PROCESSOR_RUNTIME_DIR` — OK, temp удалён.
- `flutter test test\widget_test.dart --reporter expanded --timeout 30s` в чистой ASCII-копии Native Console — OK, 2 tests, 20 секунд.
- `dart analyze lib test` в чистой ASCII-копии Native Console — OK.
- `flutter build windows --release` — OK; Windows portable обновлён, SHA-256 исходной и portable копии совпадает.
- `flutter build apk --release --target-platform android-arm64 --split-per-abi` — OK; APK обновлён на рабочем столе и подписан release-ключом.
- Native Processor GUI: `flutter test --timeout 30s` — OK, 3 tests; `dart analyze lib test` — OK; `flutter build windows --release` — OK после `flutter clean`.
- Native Processor GUI portable обновлён; SHA-256 совпадает, вложенная папка `processor` сохранена.
- `py -3.11 processor\build_exe.py` с `SKIP_PROCESSOR_CLI=1` — OK; Runtime и Supervisor обновлены в portable, SHA-256 совпадают с `processor\dist`.
- Portable `CCTV-Processor-Runtime.exe --cli acceleration --json` — OK, `selected_device=cuda`, `selected_provider=CUDAExecutionProvider`.
- Portable Runtime `/health` — HTTP 200.
- Backend `/health` — HTTP 200; `db`, `backend`, `mediamtx` запущены.
- `git diff --check` — OK, только CRLF-предупреждения рабочей копии.
- `pip-audit` по backend/processor CPU/processor NVIDIA requirements отдельно — известных CVE не найдено.

## Остаточные риски / следующий этап

- DNS pinning реализован; остаётся расширить интеграционные тесты на повторный DNS-resolve и протоколы, которым требуется исходный hostname.
- Права доступа к камерам сейчас по сути глобальные по роли (`admin/user/viewer`), без проверки принадлежности конкретной камеры/группы. Это требует отдельной модели ACL или group-camera binding в permission checks.
- Processor command paths и API-key revocation требуют негативных API-тестов.
- Нужны отдельные тесты на timeout ffmpeg для битых/долгих media-файлов.
- Trivy/Grype не запускались: утилиты не установлены.
- Полный nmap не запускался: `nmap` не установлен, есть только TCP snapshot.
- Нужна дальнейшая оптимизация dashboard/report export там, где остаются полные выборки справочников.
- Реальный raw/overlay MJPEG замер не выполнен: камера `192.168.88.242` не отвечает в LAN, ARP-записи нет, TCP 554 недоступен.
- Flutter test coverage пока минимальный: два unit/widget-level теста не покрывают навигацию, lifecycle и media playback.
- Flutter предупреждает, что `package_info_plus` и `wakelock_plus` ещё применяют legacy Kotlin Gradle Plugin; перед следующим major Flutter их нужно обновить.
- Android E2E на физическом телефоне не выполнен: `adb devices -l` не показывает подключённых устройств.
