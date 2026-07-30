@echo off
chcp 65001 >nul
title PyCoder v1.0.0 安装器

echo.
echo   ============================================
echo      PyCoder v1.0.0  Windows 安装器
echo      Python AI Programming IDE
echo   ============================================
echo.

REM 默认安装到用户目录
set "INSTALL_DIR=%LOCALAPPDATA%\PyCoder"
set "PYTHON_WHEEL=pycoder-1.0.0-py3-none-any.whl"

REM 解析参数
:parse_args
if "%~1"=="" goto :main
if /i "%~1"=="/portable" (
    set "PORTABLE=1"
    set "INSTALL_DIR=%CD%\PyCoder"
    shift
    goto :parse_args
)
if /i "%~1"=="/addpath" (
    set "ADD_PATH=1"
    shift
    goto :parse_args
)
if /i "%~1"=="/installpython" (
    set "INSTALL_PY=1"
    shift
    goto :parse_args
)
if /i "%~1"=="/dir" (
    set "INSTALL_DIR=%~2"
    shift
    shift
    goto :parse_args
)
if /i "%~1"=="/?" goto :help
shift
goto :parse_args

:help
echo 用法: install.bat [/portable] [/addpath] [/installpython] [/dir PATH]
echo.
echo   /portable       便携模式，安装到当前目录
echo   /addpath        添加到系统 PATH
echo   /installpython  同时安装 Python wheel 包
echo   /dir PATH       指定安装目录（默认: %%LOCALAPPDATA%%\PyCoder）
echo.
pause
exit /b 0

:main
echo 安装目录: %INSTALL_DIR%
echo.

REM 检查管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] 建议以管理员身份运行以获得完整功能
    echo.
)

REM 创建目录
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

REM 复制文件
echo [1/3] 复制文件...
xcopy /E /I /Y /Q "%~dp0*" "%INSTALL_DIR%\" >nul
if %errorlevel% neq 0 (
    echo [X] 复制失败
    pause
    exit /b 1
)
echo   [OK] 复制完成

REM 创建快捷方式（需要 PowerShell）
echo [2/3] 创建快捷方式...
powershell -ExecutionPolicy Bypass -NoProfile -Command ^
    "$shell = New-Object -ComObject WScript.Shell; ^
     $target = '%INSTALL_DIR%\PyCoder.exe'; ^
     $icon = $target; ^
     $desktop = [Environment]::GetFolderPath('Desktop'); ^
     $s = $shell.CreateShortcut((Join-Path $desktop 'PyCoder.lnk')); ^
     $s.TargetPath = $target; $s.WorkingDirectory = '%INSTALL_DIR%'; ^
     $s.IconLocation = $icon; $s.Description = 'PyCoder - Python AI Programming IDE'; ^
     $s.Save(); ^
     Write-Host '   [OK] 桌面快捷方式已创建'" 2>nul
if %errorlevel% neq 0 (
    echo   [!] 快捷方式创建失败（可手动创建）
)

REM 添加到 PATH
if defined ADD_PATH (
    echo [3/3] 添加到 PATH...
    powershell -ExecutionPolicy Bypass -NoProfile -Command ^
        "$p = [Environment]::GetEnvironmentVariable('Path', 'User'); ^
         if ($p -notlike '*%INSTALL_DIR%*') { ^
             [Environment]::SetEnvironmentVariable('Path', $p + ';%INSTALL_DIR%', 'User'); ^
             Write-Host '   [OK] PATH 已更新' ^
         } else { ^
             Write-Host '   [OK] PATH 已包含' ^
         }"
)

REM 安装 Python 包
if defined INSTALL_PY (
    if exist "%~dp0%PYTHON_WHEEL%" (
        echo [附加] 安装 Python 包...
        python -m pip install --upgrade "%~dp0%PYTHON_WHEEL%"
    ) else (
        echo [!] wheel 不存在: %PYTHON_WHEEL%
    )
)

echo.
echo   ============================================
echo      安装成功！
echo   ============================================
echo.
echo   启动: %INSTALL_DIR%\PyCoder.exe
echo.

choice /C YN /N /M "立即启动 PyCoder? (Y/N)"
if %errorlevel% equ 1 (
    start "" "%INSTALL_DIR%\PyCoder.exe"
)
exit /b 0
