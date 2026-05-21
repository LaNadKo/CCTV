# Processor GUI parity checklist

Сравнение нового Flutter GUI с прежним `processor/gui/app.py`.

| Функция старого GUI | Статус в Flutter GUI | Реализация |
| --- | --- | --- |
| Подключение к backend по коду | Есть | Вкладка `Подключение`, команда `connect --json` существующего Processor CLI |
| Проверка `/health` backend | Есть | Кнопка `Проверить` |
| Локальная сводка config/backend/id/ip/gpu | Есть | Вкладки `Подключение`, `Монитор`, `Диагностика` |
| Запуск Processor | Есть | Запуск того же Python/PyInstaller runtime в headless-режиме |
| Остановка Processor | Есть | Остановка запущенного headless-процесса |
| CPU/RAM/GPU/disk/network мониторинг | Есть | Локальные Windows-метрики + данные `system-info`/`acceleration` CLI |
| Список назначенных камер | Есть | `status --json`, поле `assignments` |
| Быстрые действия: записи/снимки/лог/конфиг | Есть | Вкладка `Монитор` |
| Настройки max_workers, motion_threshold, segment_seconds | Есть | Вкладка `Настройки` |
| Лимит сегмента записи до 60 секунд | Есть | GUI и runtime-нормализация ограничивают значение сверху |
| Настройки face_scan_divisor и overlay_frame_divisor | Есть | Отдельные выпадающие списки и пресеты |
| Пресеты производительности | Есть | `Экономия`, `Баланс`, `Максимум` |
| Папки recordings/snapshots с выбором каталога | Есть | Windows folder picker + ручной ввод |
| Media port/token | Есть | Вкладка `Настройки` |
| Настройки цветов темы | Есть | Пишутся в тот же `processor_config.json` |
| Справка | Есть | Вкладка `Справка` |
| Live-журнал stdout/stderr и processor.log | Есть | Вкладка `Журнал` |
| Очистка окна журнала без удаления файла | Есть | Кнопка `Очистить окно` |
| Диагностика ускорения и прогрев моделей | Расширено | `acceleration --json --prewarm` |
| Галерея персон | Расширено | `gallery --json` |

Логика обнаружения, записи, media server, ONNX/MMDeploy, CUDA/DirectML/CPU выбор, heartbeat, назначения камер и отправка событий не перенесены в Dart. Новый GUI управляет существующим Processor runtime через конфиг, CLI и headless-запуск.
