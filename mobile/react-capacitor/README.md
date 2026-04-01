# CCTV Console Mobile

Отдельный мобильный клиент на `React + Vite + Capacitor`.

## Что уже готово

- отдельная копия web `Console`, не связанная напрямую с основным `frontend/`;
- собственный `vite.config.ts`;
- собственный `package.json`;
- `Capacitor`-конфиг;
- сгенерированный Android-проект в `android/`.

## Запуск

```bash
npm install
npm run dev
```

## Сборка web-части

```bash
npm run build
```

## Подготовка Android

```bash
npm run build:android
npx cap open android
```

## Подготовка iOS

```bash
npm run build:ios
npx cap open ios
```

Для реальной iOS-сборки нужен `macOS + Xcode`.
