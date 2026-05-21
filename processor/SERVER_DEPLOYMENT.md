# CCTV Processor Deployment

Processor поддерживает три режима запуска:

- Windows/Linux GUI: `native/cctv_processor_gui` управляет локальным Python runtime.
- Linux headless: `python -m processor.runtime` с переменными окружения или `processor_config.json`.
- Docker: `processor/docker-compose.yml` с профилями `cpu` и `nvidia`.

## Подключение к Backend

Рекомендуемый сценарий:

1. В Console откройте `Processor` и создайте код подключения.
2. На узле Processor задайте `BACKEND_URL` и `PROCESSOR_CONNECT_CODE`.
3. Первый запуск обменяет код на `API_KEY` и `PROCESSOR_ID`, затем сохранит `processor_config.json`.

Один физический узел не должен регистрироваться дважды. Для этого Processor хранит стабильный `PROCESSOR_NODE_UID`, а backend переиспользует существующую запись с тем же UID.

Дополнительно runtime держит локальный lock-файл на машине. Если второй Processor запускается параллельно из другой portable-папки или другого runtime-каталога, запуск будет остановлен до завершения уже работающего экземпляра.

## Docker CPU

```bash
cd processor
cp .env.example .env
docker compose --profile cpu up -d
```

## Docker NVIDIA

Нужны драйвер NVIDIA и NVIDIA Container Toolkit.

```bash
cd processor
cp .env.example .env
docker compose --profile nvidia up -d processor-nvidia
```

## Linux Systemd

```bash
sudo useradd --system --home /var/lib/cctv-processor --shell /usr/sbin/nologin cctv
sudo mkdir -p /opt/cctv-complex /var/lib/cctv-processor
sudo chown -R cctv:cctv /var/lib/cctv-processor
sudo cp processor/systemd/cctv-processor.env.example /etc/cctv-processor.env
sudo cp processor/systemd/cctv-processor.service /etc/systemd/system/cctv-processor.service
sudo systemctl daemon-reload
sudo systemctl enable --now cctv-processor
```

Перед запуском заполните `/etc/cctv-processor.env`: `BACKEND_URL`, `PROCESSOR_CONNECT_CODE`, имя узла и при необходимости `PROCESSOR_ACCEL`.

## Удалённое Управление

Backend поддерживает команды:

- `reload_assignments`: перечитать назначения камер.
- `restart_workers`: перезапустить воркеры камер.
- `stop_all_cameras`: поставить обработку камер на паузу.
- `resume_cameras`: снять паузу и запустить назначенные камеры.
- `refresh_gallery`: обновить локальную галерею лиц.
- `shutdown`: остановить Processor.
