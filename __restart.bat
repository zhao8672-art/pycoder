@echo off
cd /d C:\Users\Administrator\Desktop\pycode

echo Stopping old processes...
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM electron.exe >nul 2>&1
timeout /t 3 /nobreak >nul

echo Cleaning cache...
for /r . %%i in (__pycache__) do if exist "%%i" rmdir /s /q "%%i" 2>nul
del /s /q *.pyc >nul 2>&1

echo Starting backend...
start "PyCoder Backend" /B .venv\Scripts\python.exe -m uvicorn pycoder.server.app:app --host 127.0.0.1 --port 8423 > backend.log 2>&1

echo Waiting for backend...
timeout /t 10 /nobreak >nul

echo Building frontend...
cd pycoder\electron
call npm run build >nul 2>&1

echo Starting Electron...
start "PyCoder Desktop" /B npx electron .

cd ..\..
echo.
echo Done! Backend: http://127.0.0.1:8423
echo Start-Backend.bat PID:
netstat -ano | findstr ":8423.*LISTENING"
