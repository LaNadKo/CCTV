# CCTV Console Native

Flutter client for the CCTV backend. The current target set is Windows desktop and Android.

## What is implemented

- Login through `/auth/login` with optional TOTP code.
- Secure token storage through platform storage.
- Backend URL setting, persisted per device.
- Theme mode, primary accent, secondary accent, and Live density settings.
- Responsive shell close to the existing web console visual language.
- Live camera grid with authenticated stream URLs.
- Basic ONVIF PTZ commands from Live cards.
- First status cards for cameras, processors, and pending reviews.

## Local commands

Run from this directory:

```powershell
flutter pub get
flutter analyze
flutter test
flutter build apk --debug
```

The repository path contains Cyrillic characters. Flutter analysis currently crashes on that path, so use the ASCII junction created for local tooling:

```powershell
cd C:\dev\cctv_console_repo
flutter analyze
flutter test
flutter build apk --debug
```

For Windows builds with Flutter plugins, enable Windows Developer Mode:

```powershell
start ms-settings:developers
```

Then run:

```powershell
flutter build windows --debug
```
