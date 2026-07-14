@echo off
title PyCoder IDE 离线打包
cd /d "%~dp0pycoder\electron"

echo ========================================
echo  PyCoder IDE 离线安装包生成
echo ========================================
echo.

:: 1. 检查构建
if not exist dist\main\index.js (
    echo [1/4] 构建前端...
    call npm run build
    if %errorlevel% neq 0 ( echo 构建失败 & pause & exit /b 1 )
) else ( echo [1/4] 构建文件已存在 )

:: 2. 创建打包目录
set PKG_DIR=out\PyCoder
echo [2/4] 创建打包目录: %PKG_DIR%
if exist %PKG_DIR% rmdir /s /q %PKG_DIR%
mkdir %PKG_DIR% 2>nul
mkdir %PKG_DIR%\resources 2>nul

:: 3. 复制核心文件
echo [3/4] 复制文件...
xcopy /E /I /Q dist\main %PKG_DIR%\dist\main >nul
xcopy /E /I /Q dist\preload %PKG_DIR%\dist\preload >nul
xcopy /E /I /Q dist\renderer %PKG_DIR%\dist\renderer >nul
if exist resources\icon.png copy resources\icon.png %PKG_DIR%\resources\ >nul
if exist resources\tray-icon.png copy resources\tray-icon.png %PKG_DIR%\resources\ >nul

:: 复制 package.json（修改 main 字段为相对路径）
copy package.json %PKG_DIR%\ >nul

:: 4. 创建启动脚本
echo [4/4] 创建启动脚本...
(
echo @echo off
echo title PyCoder IDE
echo echo 正在启动 PyCoder IDE...
echo.
echo :: 启动 Python 后端
echo start /B python -m pycoder --server --server-port 8423
echo.
echo :: 等待后端就绪
echo timeout /t 3 /nobreak ^>nul
echo.
echo :: 启动 Electron
echo start /B npx electron "%%~dp0."
echo.
echo echo PyCoder IDE 已启动
echo echo 关闭此窗口不会关闭 IDE
) > %PKG_DIR%\start.bat

:: 显示结果
echo.
echo ========================================
echo  打包完成！
echo ========================================
echo  输出目录: %PKG_DIR%
echo.
dir /B %PKG_DIR%\dist\main\ 2>nul
echo.
echo  运行方式:
echo  1. 复制 out\PyCoder 到目标机器
echo  2. 确保安装了 Python 3.12+ 和 Node.js
echo  3. 双击 start.bat
echo.
pause
