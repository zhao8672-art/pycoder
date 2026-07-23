@echo off
REM ============================================================================
REM PyCoder Windows 启动包装器 (CMD)
REM 用法:
REM   pycoder.bat --server
REM   pycoder.bat --setup
REM   pycoder.bat --scan pycoder/
REM
REM 自动检测:
REM   1) 优先使用 pip 安装的 pycoder.exe (在 PATH 或 venv\Scripts)
REM   2) 回退到 python -m pycoder
REM ============================================================================
setlocal

REM 切换到脚本所在目录的父目录 (项目根)
pushd "%~dp0\.." >nul

REM 1. 寻找 pycoder.exe (Windows 可执行入口)
set "PYCODER_EXE="
for %%P in (pycoder.exe) do (
    if exist "venv\Scripts\%%P" set "PYCODER_EXE=venv\Scripts\%%P"
    if exist ".venv\Scripts\%%P" set "PYCODER_EXE=.venv\Scripts\%%P"
)
if not defined PYCODER_EXE (
    where pycoder.exe >nul 2>&1 && set "PYCODER_EXE=pycoder.exe"
)

REM 2. 寻找 python.exe
set "PYTHON_EXE="
for %%P in (python.exe) do (
    if exist "venv\Scripts\%%P" set "PYTHON_EXE=venv\Scripts\%%P"
    if exist ".venv\Scripts\%%P" set "PYTHON_EXE=.venv\Scripts\%%P"
)
if not defined PYTHON_EXE (
    where python.exe >nul 2>&1 && set "PYTHON_EXE=python.exe"
)
if not defined PYTHON_EXE (
    echo [ERROR] python.exe 未找到. 请先安装 Python 3.12+ 或激活 venv.
    popd
    exit /b 1
)

REM 3. 强制 UTF-8 (避免 Windows GBK 编码问题)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM 4. 调用 pycoder (优先 .exe, 回退到 -m)
if defined PYCODER_EXE (
    "%PYCODER_EXE%" %*
) else (
    "%PYTHON_EXE%" -m pycoder %*
)

popd
endlocal
