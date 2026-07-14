Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Administrator\Desktop\pycode"
WshShell.Environment("PROCESS")("PYCODER_CLOUD_JWT_SECRET") = "local-dev-jwt-secret-2026"
WshShell.Environment("PROCESS")("PYCODER_API_KEY") = "REDACTED-PYCODER-API-KEY"
WshShell.Run "python -m uvicorn pycoder.server.app:app --host 127.0.0.1 --port 8423 --log-level error", 0, False
