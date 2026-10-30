@echo off
chcp 65001 >nul
setlocal
cd /d %~dp0

set ISCC=
where iscc >nul 2>nul && set ISCC=iscc
if "%ISCC%"=="" if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if "%ISCC%"=="" if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
if "%ISCC%"=="" if exist "C:\Program Files\Inno Setup 7\ISCC.exe" set ISCC="C:\Program Files\Inno Setup 7\ISCC.exe"
if "%ISCC%"=="" if exist "C:\Program Files (x86)\Inno Setup 7\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 7\ISCC.exe"

if "%ISCC%"=="" (
    echo [错误] 未找到 Inno Setup 编译器 ISCC.exe
    echo        请从 https://jrsoftware.org/isinfo.php 下载安装 Inno Setup 6，
    echo        或使用 Inno Setup IDE 打开 installer.iss 后点击 Compile。
    pause
    exit /b 1
)

if not exist "dist\OracleBackup\OracleBackup.exe" (
    echo [提示] 未找到已打包的 EXE，先执行 build.bat 完成打包。
    pause
    exit /b 1
)

echo 正在编译安装包...
%ISCC% installer.iss

if errorlevel 1 (
    echo [错误] 安装包编译失败。
    pause
    exit /b 1
)

echo.
echo 安装包已生成：dist_installer\OracleBackup_Setup_v1.0.0.exe
pause
