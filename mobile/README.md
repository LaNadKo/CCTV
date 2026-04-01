# Mobile

В каталоге `mobile` находятся два независимых клиента.

## `react-native`

Сохранённый мобильный клиент на `Expo / React Native`.

Запуск:

```bash
cd mobile/react-native
npm install
npm run start
```

## `react-capacitor`

Новый отдельный мобильный клиент на `React + Vite + Capacitor`.

Запуск web-режима:

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
