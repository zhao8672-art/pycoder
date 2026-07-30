@echo off
REM ─────────────────────────────────────────────────────────
REM   PyCoder v1.0.0  一键打包脚本
REM
REM   用法: build_installer.bat
REM
REM   输出:
REM     - dist\PyCoder-1.0.0-win32-x64-portable.zip   (便携版)
REM     - dist\pycoder-1.0.0-py3-none-any.whl         (Python 包)
REM     - dist\PyCoder-win32-x64\                     (完整安装目录)
REM ─────────────────────────────────────────────────────────

setlocal EnableDelayedExpansion
chcp 65001 >nul

echo.
echo   PyCoder v1.0.0  打包脚本
echo   ==========================
echo.

REM ── 1. 清理旧的 dist ──
echo [1/6] 清理旧构建...
if exist dist rmdir /S /Q dist
if exist pycoder\electron\dist rmdir /S /Q pycoder\electron\dist
if exist pycoder\electron\out rmdir /S /Q pycoder\electron\out
mkdir dist\wheels
echo   [OK]

REM ── 2. 构建 Electron 前端 ──
echo [2/6] 构建 Electron 应用...
pushd pycoder\electron
call npm run build
if %errorlevel% neq 0 (
    echo   [X] Electron 构建失败
    popd
    exit /b 1
)
popd
echo   [OK]

REM ── 3. 构建 Python wheel ──
echo [3/6] 构建 Python wheel...
python -m pip wheel . --no-deps --no-build-isolation -w dist\wheels\ >nul
if %errorlevel% neq 0 (
    echo   [X] Wheel 构建失败
    exit /b 1
)
echo   [OK]

REM ── 4. 组装安装目录 ──
echo [4/6] 组装安装目录...
mkdir dist\PyCoder-win32-x64
xcopy /E /I /Y /Q pycoder\electron\node_modules\electron\dist\* dist\PyCoder-win32-x64\ >nul
mkdir dist\PyCoder-win32-x64\resources
xcopy /E /I /Y /Q pycoder\electron\dist dist\PyCoder-win32-x64\resources\app\ >nul
pushd dist\PyCoder-win32-x64\resources
call npx --prefix "%~dp0..\..\pycoder\electron" asar pack app app.asar
if %errorlevel% neq 0 (
    echo   [X] asar 打包失败
    popd
    exit /b 1
)
popd
del /F /Q dist\PyCoder-win32-x64\resources\default_app.asar >nul 2>&1
rmdir /S /Q dist\PyCoder-win32-x64\resources\app
ren dist\PyCoder-win32-x64\electron.exe PyCoder.exe

REM 复制安装脚本
copy /Y packaging\install.bat dist\PyCoder-win32-x64\ >nul
copy /Y packaging\install.ps1 dist\PyCoder-win32-x64\ >nul
copy /Y packaging\uninstall.ps1 dist\PyCoder-win32-x64\ >nul
copy /Y packaging\PyCoder.bat dist\PyCoder-win32-x64\ >nul
copy /Y dist\wheels\pycoder-*.whl dist\PyCoder-win32-x64\ >nul

if exist LICENSE copy /Y LICENSE dist\PyCoder-win32-x64\LICENSE >nul
copy /Y packaging\README.md dist\PyCoder-win32-x64\README.md >nul
echo   [OK]

REM ── 5. 打包 ZIP ──
echo [5/6] 打包 ZIP...
powershell -NoProfile -Command "Compress-Archive -Path 'dist\PyCoder-win32-x64' -DestinationPath 'dist\PyCoder-1.0.0-win32-x64-portable.zip' -CompressionLevel Optimal -Force" >nul
if %errorlevel% neq 0 (
    echo   [X] 便携版 ZIP 失败
    exit /b 1
)
powershell -NoProfile -Command "Compress-Archive -Path 'dist\wheels\pycoder-1.0.0-py3-none-any.whl' -DestinationPath 'dist\pycoder-1.0.0-py3-none-any.zip' -Force" >nul
if %errorlevel% neq 0 (
    echo   [X] Wheel ZIP 失败
    exit /b 1
)
echo   [OK]

REM ── 6. 显示结果 ──
echo.
echo [6/6] 打包完成！
echo.
echo   输出文件:
for %%F in (dist\PyCoder-1.0.0-win32-x64-portable.zip, dist\pycoder-1.0.0-py3-none-any.zip, dist\PyCoder-win32-x64\PyCoder.exe, dist\wheels\pycoder-1.0.0-py3-none-any.whl) do (
    if exist %%F (
        for %%A in ("%%F") do (
            echo     %%~nxF - !%%~nxF!  2>nul
        )
    )
)
echo.
echo   发布建议:
echo     1. dist\PyCoder-1.0.0-win32-x64-portable.zip  - GitHub Release 资产
echo     2. dist\pycoder-1.0.0-py3-none-any.whl         - pip install (可上传 PyPI)
echo.
endlocal
exit /b 0
