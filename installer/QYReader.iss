#define MyAppName "启远阅读"
#define MyAppVersion "2.1.4"
#define MyAppPublisher "QYReader"
#define MyAppExeName "QYReader.exe"

[Setup]
AppId={{F89DBA15-6137-422E-A264-391F8BBCCC1D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\QYReader
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
PrivilegesRequired=admin
OutputDir=..\dist\installer
OutputBaseFilename=QYReader-Setup-{#MyAppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
DisableWelcomePage=no

[Languages]
Name: "chinesesimp"; MessagesFile: "{#SourcePath}\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面图标"; GroupDescription: "附加快捷方式："

[Files]
Source: "..\dist\QYReader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{app}\多多朗读.exe"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\卸载{#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动{#MyAppName}"; Flags: nowait postinstall skipifsilent

; The application creates {app}\data at first launch. It is intentionally not
; registered as an installed file or an uninstall target, so upgrades and
; uninstall preserve it.
