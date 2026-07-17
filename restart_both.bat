@echo off
cd /d C:\Users\Administrator\Desktop\pycode
taskkill /f /im python.exe >nul 2>&1
taskkill /f /im electron.exe >nul 2>&1
timeout /t 2 /nobreak >nul

for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul
del /s /q *.pyc >nul 2>&1

set PYCODER_CLOUD_JWT_SECRET=local-dev-jwt-2026
set PYCODER_API_KEY=REDACTED-PYCODER-API-KEY
set DEEPSEEK_API_KEY=sk-REDACTED-DEEPSEEK
set AGNES_API_KEY=sk-REDACTED-AGNES

start "PyCoderBackend" /B .venv\Scripts\python.exe -m uvicorn pycoder.server.app:app --host 127.0.0.1 --port 8423 --log-level error > backend.log 2>&1

echo Waiting for backend...
timeout /t 12 /nobreak >nul

.venv\Scripts\python.exe -c "import urllib.request,json; print('HEALTH:',json.loads(urllib.request.urlopen('http://127.0.0.1:8423/api/health',timeout=5).read().decode())['status']); r=json.loads(urllib.request.urlopen('http://127.0.0.1:8423/api/models',timeout=5).read().decode()); print('Model:',r['recommended_model']); print('Avail:',[m['id'] for m in r['models'] if m['available']])"
echo.
echo BACKEND READY
