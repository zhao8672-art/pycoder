@echo off
REM ─────────────────────────────────────────────────────────
REM   PyCoder v1.0.0  一键打包脚本
REM
REM   用法: build_installer.bat
REM
REM   输出:
REM     - dist\PyCoder-1.0.0-win32-x64-portable.zip   (便携版)
REM     - dist\pycoder-1.0.0-py3-none-any.zip         (Python Wheel)
REM     - dist\PyCoder-win32-x64\                     (完整安装目录)
REM     - dist\pycoder-backend.exe                    (独立后端, 调试用)
REM ─────────────────────────────────────────────────────────

setlocal EnableDelayedExpansion
chcp 65001 >nul

echo.
echo   PyCoder v1.0.0  打包脚本
echo   ==========================
echo.

REM ── 1. 清理旧的 dist ──
echo [1/7] 清理旧构建...
if exist dist rmdir /S /Q dist
if exist pycoder\electron\dist rmdir /S /Q pycoder\electron\dist
if exist pycoder\electron\out rmdir /S /Q pycoder\electron\out
if exist build rmdir /S /Q build
mkdir dist\wheels
echo   [OK]

REM ── 2. 构建 Electron 前端 ──
echo [2/7] 构建 Electron 应用...
pushd pycoder\electron
call npm run build
if !errorlevel! neq 0 (
    echo   [X] Electron 构建失败
    popd
    exit /b 1
)
popd
echo   [OK]

REM ── 3. 构建 Python wheel ──
echo [3/7] 构建 Python wheel...
python -m pip wheel . --no-deps --no-build-isolation -w dist\wheels\ >nul
if !errorlevel! neq 0 (
    echo   [X] Wheel 构建失败
    exit /b 1
)
echo   [OK]

REM ── 4. PyInstaller 打包后端 ──
echo [4/7] PyInstaller 打包后端 (pycoder-backend.exe)...
pyinstaller --noconfirm --clean packaging\pycoder_backend.spec >nul 2>&1
if !errorlevel! neq 0 (
    echo   [X] PyInstaller 打包失败
    echo   正在显示详细错误...
    pyinstaller --noconfirm --clean packaging\pycoder_backend.spec
    exit /b 1
)
if not exist dist\pycoder-backend.exe (
    echo   [X] pycoder-backend.exe 未生成
    exit /b 1
)
echo   [OK] pycoder-backend.exe ! (Get-Item dist\pycoder-backend.exe).Length! bytes
powershell -NoProfile -Command "$s=(Get-Item 'dist\pycoder-backend.exe').Length; Write-Host \"   [OK] pycoder-backend.exe ($([math]::Round($s/1MB,1)) MB)\""

REM ── 5. 组装安装目录 ──
echo [5/7] 组装安装目录...
mkdir dist\PyCoder-win32-x64
xcopy /E /I /Y /Q pycoder\electron\node_modules\electron\dist\* dist\PyCoder-win32-x64\ >nul
mkdir dist\PyCoder-win32-x64\resources
REM ★ 复制 dist 到 app\dist\ 并创建根 package.json 包装
xcopy /E /I /Y /Q pycoder\electron\dist dist\PyCoder-win32-x64\resources\app\dist\ >nul
REM ★ 创建包装 package.json: Electron 从 asar 根读取 main，指向 dist/main/index.js
echo {"name":"pycoder","version":"1.0.0","main":"dist/main/index.js"} > dist\PyCoder-win32-x64\resources\app\package.json
pushd dist\PyCoder-win32-x64\resources
call npx --prefix "%~dp0..\..\pycoder\electron" asar pack app app.asar
if !errorlevel! neq 0 (
    echo   [X] asar 打包失败
    popd
    exit /b 1
)
popd
del /F /Q dist\PyCoder-win32-x64\resources\default_app.asar >nul 2>&1
rmdir /S /Q dist\PyCoder-win32-x64\resources\app
ren dist\PyCoder-win32-x64\electron.exe PyCoder.exe

REM 复制后端 (★关键步骤)
mkdir dist\PyCoder-win32-x64\backend
copy /Y dist\pycoder-backend.exe dist\PyCoder-win32-x64\backend\ >nul
echo   [OK] 已复制 pycoder-backend.exe

REM 复制安装脚本
copy /Y packaging\install.bat dist\PyCoder-win32-x64\ >nul
copy /Y packaging\install.ps1 dist\PyCoder-win32-x64\ >nul
copy /Y packaging\uninstall.ps1 dist\PyCoder-win32-x64\ >nul
copy /Y packaging\PyCoder.bat dist\PyCoder-win32-x64\ >nul
copy /Y dist\wheels\pycoder-*.whl dist\PyCoder-win32-x64\ >nul

if exist LICENSE copy /Y LICENSE dist\PyCoder-win32-x64\LICENSE >nul
copy /Y packaging\README.md dist\PyCoder-win32-x64\README.md >nul
echo   [OK]

REM ── 6. 打包 ZIP ──
echo [6/7] 打包 ZIP...
powershell -NoProfile -Command "Compress-Archive -Path 'dist\PyCoder-win32-x64' -DestinationPath 'dist\PyCoder-1.0.0-win32-x64-portable.zip' -CompressionLevel Optimal -Force" >nul
if !errorlevel! neq 0 (
    echo   [X] 便携版 ZIP 失败
    exit /b 1
)
powershell -NoProfile -Command "Compress-Archive -Path 'dist\wheels\pycoder-1.0.0-py3-none-any.whl' -DestinationPath 'dist\pycoder-1.0.0-py3-none-any.zip' -Force" >nul
if !errorlevel! neq 0 (
    echo   [X] Wheel ZIP 失败
    exit /b 1
)
echo   [OK]

REM ── 7. 显示结果 ──
echo.
echo [7/7] 打包完成！
echo.
echo   输出文件:
for %%F in (dist\PyCoder-1.0.0-win32-x64-portable.zip, dist\pycoder-1.0.0-py3-none-any.zip, dist\PyCoder-win32-x64\PyCoder.exe, dist\PyCoder-win32-x64\backend\pycoder-backend.exe, dist\wheels\pycoder-1.0.0-py3-none-any.whl) do (
    if exist %%F (
        powershell -NoProfile -Command "$s=(Get-Item '%%F').Length; Write-Host (\"     {0,-55} {1,10:N1} MB\" -f (Split-Path '%%F' -Leaf), ($s/1MB))"
    )
)
echo.
echo   安装方式:
echo     1. 解压 PyCoder-1.0.0-win32-x64-portable.zip
echo     2. 双击 PyCoder.exe 启动 (或运行 install.bat 一键安装)
echo.
endlocal
exit /b 0
