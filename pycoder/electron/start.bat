@echo off
setlocal EnableExtensions

title PyCoder IDE - Python AI Programming Assistant

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"

cd /d "%SCRIPT_DIR%" || exit /b 1

echo ========================================
echo   PyCoder IDE - Starting...
echo ========================================
echo.

echo [1/3] Checking build tools...
where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm was not found. Please install Node.js first.
    pause
    exit /b 1
)

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] python was not found. Please install Python first.
    pause
    exit /b 1
)

if not exist "%SCRIPT_DIR%node_modules" (
    echo [INFO] Installing Node dependencies...
    call npm install
    if errorlevel 1 (
        echo [ERROR] Failed to install Node dependencies.
        pause
        exit /b 1
    )
)

echo [2/3] Building frontend...

echo [INFO] Cleaning old dist...
if exist "%SCRIPT_DIR%dist" rmdir /s /q "%SCRIPT_DIR%dist"

call npm run build
if errorlevel 1 (
    echo [ERROR] Frontend build failed.
    pause
    exit /b 1
)

set "BACKEND_URL=http://127.0.0.1:8423/api/health"
set "BACKEND_LOG=%SCRIPT_DIR%backend.log"

echo [3/3] Starting backend...
cd /d "%PROJECT_ROOT%" || exit /b 1
powershell.exe -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; try { Invoke-WebRequest -UseBasicParsing -Uri '%BACKEND_URL%' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    start "PyCoder Backend" /B python -m pycoder --server --server-port 8423 > "%BACKEND_LOG%" 2>&1
)

cd /d "%SCRIPT_DIR%" || exit /b 1

echo [4/4] Waiting for backend...
set WAIT_COUNT=0
:WAIT_LOOP
timeout /t 1 /nobreak > nul
set /a WAIT_COUNT+=1
if %WAIT_COUNT% geq 30 goto LAUNCH

powershell.exe -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; try { Invoke-WebRequest -UseBasicParsing -Uri '%BACKEND_URL%' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 goto WAIT_LOOP

:LAUNCH
echo.
echo ========================================
echo   Launching Electron desktop app...
echo ========================================
call npm run start:prod
if errorlevel 1 (
    echo.
    echo [ERROR] Electron exited unexpectedly.
    echo Please check the backend log: %BACKEND_LOG%
    pause
    exit /b 1
)

echo.
echo PyCoder IDE closed.
echo Backend is still running in background.
echo Press any key to close this window.
pause

endlocal

