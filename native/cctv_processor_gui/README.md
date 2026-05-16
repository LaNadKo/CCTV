# CCTV Processor GUI

Нативная Flutter-оболочка для локального `Processor`.

Приложение не переписывает Python-обработчик. Оно управляет существующим runtime через:

- `processor_config.json`;
- `CCTV-Processor.exe --headless`;
- `CCTV-Processor.exe --cli ...`;
- `processor.log`.

## Runtime lookup

При запуске GUI ищет Processor в таком порядке:

1. `processor/CCTV-Processor.exe` рядом с `cctv_processor_gui.exe`;
2. `CCTV-Processor.exe` рядом с `cctv_processor_gui.exe`;
3. `processor/dist/CCTV-Processor/CCTV-Processor.exe` в репозитории;
4. `processor/run_gui.py` в репозитории как dev fallback.

Для portable-сборки рядом с Flutter GUI кладётся папка `processor` из PyInstaller-сборки.
