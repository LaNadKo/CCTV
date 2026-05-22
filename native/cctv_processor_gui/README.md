# CCTV Processor GUI

Нативная Flutter-оболочка для локального управления `Processor` на Windows и Linux.

GUI не переписывает Python-детекцию. Он управляет существующим runtime через:

- `processor_config.json`;
- `CCTV-Processor-Runtime --headless`;
- `CCTV-Processor-CLI ...`;
- `processor.log`.

## Runtime Lookup

При запуске GUI ищет Processor в таком порядке:

1. `processor/CCTV-Processor-Runtime.exe` или `processor/CCTV-Processor-Runtime` рядом с GUI;
2. `CCTV-Processor-Runtime.exe` или `CCTV-Processor-Runtime` рядом с GUI;
3. `processor/dist/CCTV-Processor-Runtime/CCTV-Processor-Runtime.exe` или `processor/dist/CCTV-Processor-Runtime/CCTV-Processor-Runtime` в репозитории;
4. `processor/run_runtime.py` и `processor/cli.py` в репозитории как dev fallback (`python` на Windows, `python3` на Linux).

Для portable-сборки рядом с Flutter GUI кладётся папка `processor` из headless PyInstaller runtime. Старый Python GUI в portable больше не нужен.

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
