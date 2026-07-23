@echo off
REM ============================================================================
REM PyCoder 一键启动 (Windows CMD)
REM
REM 用法:
REM   start.bat              启动后端 + 桌面 IDE (推荐)
REM   start.bat server       仅启动后端 (端口 8423)
REM   start.bat web          仅启动后端 (同 server)
REM   start.bat electron     仅启动 Electron
REM   start.bat install      首次安装 (pip install -r requirements-all.txt)
REM   start.bat clean        清理缓存
REM   start.bat help         显示帮助
REM
REM 环境要求:
REM   - Python 3.12+
REM   - Node.js 18+ (Electron 用)
REM   - Windows 10+
REM
REM 等价命令 (PowerShell): .\start.ps1
REM ============================================================================
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

REM 1. 寻找 Python
set "PY="
for %%P in (python.exe) do (
    if exist ".venv\Scripts\%%P" set "PY=.venv\Scripts\%%P"
    if exist "venv\Scripts\%%P" set "PY=venv\Scripts\%%P"
)
if "%PY%"=="" (
    where python.exe >nul 2>&1 && set "PY=python.exe"
)
if "%PY%"=="" (
    echo [ERROR] Python 未找到. 请先安装 Python 3.12+ 或激活 venv.
    exit /b 1
)

REM 2. 强制 UTF-8
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM 3. 分发命令
if /I "%1"=="" goto :start_all
if /I "%1"=="server" goto :start_server
if /I "%1"=="web" goto :start_server
if /I "%1"=="electron" goto :start_electron
if /I "%1"=="install" goto :do_install
if /I "%1"=="clean" goto :do_clean
if /I "%1"=="help" goto :show_help
if /I "%1"=="-h" goto :show_help
if /I "%1"=="--help" goto :show_help

echo [ERROR] 未知命令: %1
echo 运行 start.bat help 查看帮助
exit /b 1

:start_all
echo [INFO] 启动后端 + Electron (后台模式)
start "PyCoder Backend" cmd /c "%PY% -m pycoder --server"
timeout /t 3 /nobreak >nul
if exist "pycoder\electron" (
    start "PyCoder IDE" cmd /c "cd /d pycoder\electron && npx electron ."
    echo [OK] 后端 + Electron 已启动
) else (
    echo [WARN] pycoder\electron 目录不存在, 仅启动后端
)
exit /b 0

:start_server
echo [INFO] 启动后端 (http://127.0.0.1:8423)
"%PY%" -m pycoder --server
exit /b %errorlevel%

:start_electron
echo [INFO] 启动 Electron 桌面 IDE
cd /d pycoder\electron
npx electron .
exit /b %errorlevel%

:do_install
echo [INFO] 安装全量依赖 (main + dev + help + browser + playwright)
"%PY%" -m pip install -r requirements-all.txt
"%PY%" -m pip install -e .
echo [OK] 安装完成
exit /b 0

:do_clean
echo [INFO] 清理缓存
if exist ".pycoder\Cache" rmdir /s /q ".pycoder\Cache" 2>nul
if exist "%APPDATA%\pycoder\Cache" rmdir /s /q "%APPDATA%\pycoder\Cache" 2>nul
if exist "%APPDATA%\pycoder\GPUCache" rmdir /s /q "%APPDATA%\pycoder\GPUCache" 2>nul
if exist "%APPDATA%\pycoder\Code Cache" rmdir /s /q "%APPDATA%\pycoder\Code Cache" 2>nul
echo [OK] 缓存清理完成
exit /b 0

:show_help
echo PyCoder 一键启动 (Windows)
echo.
echo 用法: start.bat [command]
echo.
echo 命令:
echo   (无参数)    启动后端 + Electron
echo   server      仅启动后端
echo   electron    仅启动 Electron
echo   install     安装全量依赖
echo   clean       清理缓存
echo   help        显示此帮助
echo.
echo 环境变量:
echo   PYCODER_API_KEY    API 鉴权 key (默认: REDACTED-PYCODER-API-KEY)
echo   DEEPSEEK_API_KEY   DeepSeek 模型 key
exit /b 0
