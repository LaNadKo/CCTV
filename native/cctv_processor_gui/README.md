# CCTV Processor GUI

Нативная Flutter-оболочка для локального управления `Processor` на Windows и Linux.

GUI не переписывает Python-детекцию. Он управляет существующим runtime через:

- `processor_config.json`;
- `CCTV-Processor --headless`;
- `CCTV-Processor --cli ...`;
- `processor.log`.

## Runtime Lookup

При запуске GUI ищет Processor в таком порядке:

1. `processor/CCTV-Processor.exe` или `processor/CCTV-Processor` рядом с GUI;
2. `CCTV-Processor.exe` или `CCTV-Processor` рядом с GUI;
3. `processor/dist/CCTV-Processor/CCTV-Processor.exe` или `processor/dist/CCTV-Processor/CCTV-Processor` в репозитории;
4. `processor/run_gui.py` в репозитории как dev fallback (`python` на Windows, `python3` на Linux).

Для portable-сборки рядом с Flutter GUI кладётся папка `processor` из PyInstaller-сборки.

## Linux Server

На серверной Linux-ОС GUI не обязателен. Processor запускается headless:

```bash
cd /opt/cctv-complex
python -m processor.runtime
```

Для постоянного запуска используйте шаблоны:

- `processor/systemd/cctv-processor.service`;
- `processor/systemd/cctv-processor.env.example`.

Docker-вариант лежит в `processor/docker-compose.yml` и поддерживает профили `cpu` и `nvidia`.
