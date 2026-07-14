@echo off
cd /d C:\Users\Administrator\Desktop\pycode
set PYCODER_CLOUD_JWT_SECRET=local-dev-jwt-secret-2026
set PYCODER_API_KEY=REDACTED-PYCODER-API-KEY
python -m uvicorn pycoder.server.app:app --host 127.0.0.1 --port 8423 --log-level error
