@echo off
cd /d C:\Users\Administrator\Desktop\pycode\pycoder\electron
echo Building Electron frontend...
call npm run build
echo BUILD_EXIT_CODE=%ERRORLEVEL%
pause
