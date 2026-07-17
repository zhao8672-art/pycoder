@echo off
cd /d C:\Users\Administrator\Desktop\pycode

echo Stopping old backends...
netstat -ano | findstr ":8423" > %temp%\port.txt
for /f "tokens=5" %%a in (%temp%\port.txt) do taskkill /F /PID %%a >nul 2>&1
timeout /t 3 /nobreak >nul

echo Starting backend...
set PYCODER_CLOUD_JWT_SECRET=test-123
set PYCODER_API_KEY=REDACTED-PYCODER-API-KEY
set DEEPSEEK_API_KEY=sk-REDACTED-DEEPSEEK
set AGNES_API_KEY=sk-REDACTED-AGNES

start "PyCoder" /B .venv\Scripts\python.exe -m uvicorn pycoder.server.app:app --host 127.0.0.1 --port 8423 > backend.log 2>&1

echo Waiting for backend...
timeout /t 10 /nobreak >nul
netstat -ano | findstr ":8423.*LISTENING"
echo Done.
