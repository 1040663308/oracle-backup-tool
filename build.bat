@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d %~dp0

echo ============================================================
echo   Oracle 数据库备份工具 - EXE 打包脚本
echo ============================================================

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10 及以上版本
    echo        （安装时勾选 "Add python.exe to PATH"，
    echo         并确保安装内容包含 tkinter/tcl，即使用完整安装包）
    pause
    exit /b 1
)

python -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo [错误] 当前 Python 缺少 tkinter 模块。
    echo        请使用完整的 Python 安装包（而非 embeddable 版），
    echo        或重新安装并勾选 tcl/tk 组件。
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [1/3] 创建虚拟环境...
    python -m venv .venv
)
echo [2/3] 安装/更新依赖...
.venv\Scripts\python.exe -m pip install -r requirements.txt

echo [3/3] 正在打包 EXE（约需 1-3 分钟）...
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean orabackup.spec

if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请检查上方错误信息。
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   打包完成！
echo   程序目录：dist\OracleBackup\
echo   可执行文件：dist\OracleBackup\OracleBackup.exe
echo.
echo   制作安装包：安装 Inno Setup 6 后运行 build_installer.bat
echo ============================================================
pause
