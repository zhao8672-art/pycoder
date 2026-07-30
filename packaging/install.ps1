<#
.SYNOPSIS
    PyCoder v1.0.0 Windows 安装器 (PowerShell)
.DESCRIPTION
    将 PyCoder 解压到指定目录，创建桌面/开始菜单快捷方式，注册 PATH，
    可选安装 Python wheel 包。
.NOTES
    用法（管理员 PowerShell）:
        .\install.ps1 -InstallDir "C:\Program Files\PyCoder" -CreateShortcuts -AddToPath
        .\install.ps1 -InstallDir "$env:LOCALAPPDATA\PyCoder" -Portable
#>

[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\PyCoder",
    [switch]$CreateShortcuts = $true,
    [switch]$AddToPath = $false,
    [switch]$Portable = $false,
    [switch]$InstallPython = $false,
    [string]$SourceDir = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ProductName = "PyCoder"
$Version = "1.0.0"
$ExeName = "PyCoder.exe"

# ── 颜色输出 ──
function Write-Step($msg) { Write-Host "==> " -NoNewline -ForegroundColor Cyan; Write-Host $msg }
function Write-OK($msg)   { Write-Host "  [OK] " -NoNewline -ForegroundColor Green; Write-Host $msg }
function Write-Warn($msg) { Write-Host "  [!]  " -NoNewline -ForegroundColor Yellow; Write-Host $msg }
function Write-Err($msg)  { Write-Host "  [X]  " -NoNewline -ForegroundColor Red; Write-Host $msg }

# ── 横幅 ──
Write-Host ""
Write-Host "  ╔════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║   PyCoder v$Version  Windows 安装器     ║" -ForegroundColor Cyan
Write-Host "  ║   Python AI Programming IDE               ║" -ForegroundColor Cyan
Write-Host "  ╚════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── 1. 校验源文件 ──
Write-Step "校验安装包"
$expectedFiles = @($ExeName, "resources\app.asar", "LICENSE")
foreach ($f in $expectedFiles) {
    $path = Join-Path $SourceDir $f
    if (-not (Test-Path $path)) {
        Write-Err "缺少必要文件: $path"
        exit 1
    }
}
Write-OK "源文件完整"

# ── 2. 确认安装目录 ──
Write-Step "安装目录: $InstallDir"
if (Test-Path $InstallDir) {
    Write-Warn "目录已存在，将被覆盖"
    if (-not $Portable) {
        try {
            Get-ChildItem $InstallDir -Recurse -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        } catch {
            Write-Warn "部分文件无法删除（可能正在运行）"
        }
    }
} else {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}
Write-OK "已准备"

# ── 3. 复制文件 ──
Write-Step "复制文件到 $InstallDir"
Copy-Item -Path (Join-Path $SourceDir "*") -Destination $InstallDir -Recurse -Force
Write-OK "复制完成"

# ── 4. 创建快捷方式 ──
if ($CreateShortcuts) {
    Write-Step "创建快捷方式"
    $shell = New-Object -ComObject WScript.Shell
    $targetPath = Join-Path $InstallDir $ExeName
    $iconPath = $targetPath

    # 桌面
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $shortcut = $shell.CreateShortcut((Join-Path $desktop "$ProductName.lnk"))
        $shortcut.TargetPath = $targetPath
        $shortcut.WorkingDirectory = $InstallDir
        $shortcut.IconLocation = $iconPath
        $shortcut.Description = "PyCoder - Python AI Programming IDE"
        $shortcut.Save()
        Write-OK "桌面快捷方式已创建"
    } catch {
        Write-Warn "桌面快捷方式创建失败: $_"
    }

    # 开始菜单
    try {
        $startMenu = [Environment]::GetFolderPath("StartMenu")
        $programsDir = Join-Path $startMenu "Programs"
        if (-not (Test-Path $programsDir)) { New-Item -ItemType Directory -Path $programsDir -Force | Out-Null }
        $shortcut = $shell.CreateShortcut((Join-Path $programsDir "$ProductName.lnk"))
        $shortcut.TargetPath = $targetPath
        $shortcut.WorkingDirectory = $InstallDir
        $shortcut.IconLocation = $iconPath
        $shortcut.Description = "PyCoder - Python AI Programming IDE"
        $shortcut.Save()
        Write-OK "开始菜单快捷方式已创建"
    } catch {
        Write-Warn "开始菜单快捷方式创建失败: $_"
    }
}

# ── 5. 添加到 PATH ──
if ($AddToPath) {
    Write-Step "添加 $InstallDir 到用户 PATH"
    $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($currentPath -notlike "*$InstallDir*") {
        $newPath = "$currentPath;$InstallDir"
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        $env:Path = "$env:Path;$InstallDir"
        Write-OK "PATH 已更新（重新打开终端生效）"
    } else {
        Write-OK "PATH 已包含 $InstallDir"
    }
}

# ── 6. 注册卸载程序（写入注册表） ──
if (-not $Portable) {
    Write-Step "注册卸载信息"
    try {
        $uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$ProductName"
        New-Item -Path $uninstallKey -Force | Out-Null
        Set-ItemProperty -Path $uninstallKey -Name "DisplayName" -Value "$ProductName $Version"
        Set-ItemProperty -Path $uninstallKey -Name "DisplayVersion" -Value $Version
        Set-ItemProperty -Path $uninstallKey -Name "Publisher" -Value "PyCoder Team"
        Set-ItemProperty -Path $uninstallKey -Name "InstallLocation" -Value $InstallDir
        Set-ItemProperty -Path $uninstallKey -Name "UninstallString" -Value "powershell -ExecutionPolicy Bypass -File `"$InstallDir\uninstall.ps1`""
        Set-ItemProperty -Path $uninstallKey -Name "DisplayIcon" -Value (Join-Path $InstallDir $ExeName)
        Set-ItemProperty -Path $uninstallKey -Name "NoModify" -Value 1
        Set-ItemProperty -Path $uninstallKey -Name "NoRepair" -Value 1
        Write-OK "已注册到「应用和功能」"
    } catch {
        Write-Warn "注册卸载信息失败: $_"
    }
}

# ── 7. 可选：安装 Python wheel ──
if ($InstallPython) {
    Write-Step "安装 PyCoder Python 包 (pip)"
    $wheelPath = Join-Path $SourceDir "pycoder-$Version-py3-none-any.whl"
    if (Test-Path $wheelPath) {
        try {
            python -m pip install --upgrade $wheelPath 2>&1 | Select-Object -Last 5
            Write-OK "Python 包已安装"
        } catch {
            Write-Warn "Python 包安装失败: $_"
        }
    } else {
        Write-Warn "wheel 文件不存在: $wheelPath（跳过）"
    }
}

# ── 完成 ──
Write-Host ""
Write-Host "  ╔════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║         安装成功！                          ║" -ForegroundColor Green
Write-Host "  ╚════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  安装目录: $InstallDir" -ForegroundColor White
Write-Host "  启动:     $InstallDir\$ExeName" -ForegroundColor White
if ($CreateShortcuts) {
    Write-Host "  快捷方式: 桌面 / 开始菜单" -ForegroundColor White
}
Write-Host ""
Write-Host "  按任意键启动 PyCoder..." -ForegroundColor Cyan
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
Start-Process (Join-Path $InstallDir $ExeName)
