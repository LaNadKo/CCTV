; Inno Setup script for CCTV Processor
; Requires: PyInstaller output in dist\CCTV-Processor\ and dist\CCTV-Processor-CLI.exe

#define MyAppName "CCTV Processor"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "CCTV System"
#define MyAppExeName "CCTV-Processor.exe"
#define MyCliExeName "CCTV-Processor-CLI.exe"

[Setup]
AppId={{E7B2C4F8-A91D-3E56-70F1-B8C4D2A963E5}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=CCTV-Processor-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\icon.ico
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startupheadless"; Description: "Запускать Processor в фоне при входе в Windows"; GroupDescription: "Автозапуск:"

[Files]
Source: "dist\CCTV-Processor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\{#MyCliExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} (Без GUI)"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--headless"
Name: "{group}\{#MyAppName} CLI"; Filename: "{app}\{#MyCliExeName}"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"" --headless"; Flags: uninsdeletevalue; Tasks: startupheadless

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\processor_config.json"
