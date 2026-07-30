@echo off
chcp 65001 >nul
title PyCoder v1.0.0 便携版

echo.
echo   启动 PyCoder v1.0.0 (便携版)
echo.

set "ROOT=%~dp0"
set "EXE=%ROOT%PyCoder.exe"

if not exist "%EXE%" (
    echo [X] 找不到 PyCoder.exe
    pause
    exit /b 1
)

start "" "%EXE%"
exit /b 0
