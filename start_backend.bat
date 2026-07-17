@echo off
cd /d C:\Users\Administrator\Desktop\pycode
taskkill /f /im python.exe >nul 2>&1
taskkill /f /im electron.exe >nul 2>&1
timeout /t 3 /nobreak >nul

set PYCODER_CLOUD_JWT_SECRET=local-dev-jwt-2026
set PYCODER_API_KEY=REDACTED-PYCODER-API-KEY
set DEEPSEEK_API_KEY=sk-REDACTED-DEEPSEEK
set AGNES_API_KEY=sk-REDACTED-AGNES

start /B .venv\Scripts\python.exe -m uvicorn pycoder.server.app:app --host 127.0.0.1 --port 8423 --log-level warning > backend.log 2>&1
timeout /t 12 /nobreak >nul

.venv\Scripts\python.exe -c "import urllib.request,json; d=json.loads(urllib.request.urlopen('http://127.0.0.1:8423/api/config/status',timeout=5).read().decode()); print('Model:',d['recommended_model']); print('Keys:',[p['id'] for p in d['providers'] if p['has_key']])"
echo BACKEND_READY
