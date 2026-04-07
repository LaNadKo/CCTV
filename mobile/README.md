# Mobile

В каталоге `mobile` теперь живут два независимых клиента:

- `react-native` — прежний клиент на `Expo / React Native`
- `react-capacitor` — новый мобильный клиент на `React + Vite + Capacitor`

## React Native

Исходники старого клиента сохранены без удаления и без смешивания с новой версией.

Запуск:

```bash
cd mobile/react-native
npm install
npm run start
```

## React + Capacitor

Новый клиент собран как отдельная копия текущего `frontend` и предназначен для упаковки в Android/iOS-приложение.

Запуск web-версии:

```bash
cd mobile/react-capacitor
npm install
npm run dev
```

Подготовка Android:

```bash
cd mobile/react-capacitor
npm install
npm run build:android
npx cap open android
```

Подготовка iOS:

```bash
cd mobile/react-capacitor
npm install
npm run build:ios
npx cap open ios
```

Для полноценной iOS-сборки нужен `macOS + Xcode`.
