; Oracle 数据库备份工具 - Inno Setup 安装脚本
; 编译方式：安装 Inno Setup 6 后运行 build_installer.bat，
; 或用 Inno Setup IDE 打开本文件点击 Compile。
; 编译前需先运行 build.bat 生成 dist\OracleBackup\ 目录。

#define MyAppName "Oracle数据库备份工具"
#define MyAppNameEn "OracleBackup"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "School IT"
#define MyAppURL "https://www.example.com/"
#define MyAppExeName "OracleBackup.exe"

[Setup]
; 注意：以下 GUID 为本应用的固定标识，请勿随意更改
AppId={{A6F2C4D8-3B7E-4F1A-9C5D-2E8B6A1F7C3D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppNameEn}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; 安装到 Program Files 需要管理员权限
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist_installer
OutputBaseFilename=OracleBackup_Setup_v{#MyAppVersion}
SetupIconFile=assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
; 默认简体中文（使用项目自带的语言文件，任何机器均可编译），同时提供英文
Name: "chinesesimp"; MessagesFile: "assets\languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 打包后的整个目录（含 Python 运行时依赖）
Source: "dist\OracleBackup\*"; DestDir: "{app}"; \
    Flags: recursesubdirs createallsubdirs ignoreversion; \
    Excludes: "*.pyc,__pycache__"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Comment: "Oracle 数据库自动备份工具"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Run]
; 安装完成后可选立即运行
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent
