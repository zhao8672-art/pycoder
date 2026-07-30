<#
.SYNOPSIS
    PyCoder 卸载脚本
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\PyCoder",
    [switch]$RemoveShortcuts = $true,
    [switch]$RemoveFromPath = $false
)

$ErrorActionPreference = "Stop"
$ProductName = "PyCoder"

function Write-Step($msg) { Write-Host "==> " -NoNewline -ForegroundColor Cyan; Write-Host $msg }
function Write-OK($msg)   { Write-Host "  [OK] " -NoNewline -ForegroundColor Green; Write-Host $msg }

Write-Host ""
Write-Host "  PyCoder 卸载程序" -ForegroundColor Cyan
Write-Host ""

# 结束进程
Write-Step "结束 PyCoder 进程"
Get-Process PyCoder,pycoder -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Write-OK "进程已停止"

# 等待文件锁释放
Start-Sleep -Seconds 2

# 删除安装目录
if (Test-Path $InstallDir) {
    Write-Step "删除安装目录: $InstallDir"
    try {
        Remove-Item -Recurse -Force $InstallDir -ErrorAction Stop
        Write-OK "已删除"
    } catch {
        Write-Warn "部分文件无法删除，请手动清理"
    }
}

# 删除快捷方式
if ($RemoveShortcuts) {
    Write-Step "删除快捷方式"
    $paths = @(
        (Join-Path ([Environment]::GetFolderPath("Desktop")) "$ProductName.lnk"),
        (Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\$ProductName.lnk")
    )
    foreach ($p in $paths) {
        if (Test-Path $p) {
            Remove-Item $p -Force
            Write-OK "已删除: $p"
        }
    }
}

# 清理注册表
Write-Step "清理注册表"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$ProductName"
if (Test-Path $uninstallKey) {
    Remove-Item -Path $uninstallKey -Recurse -Force
    Write-OK "已清理"
}

# 清理 PATH
if ($RemoveFromPath) {
    Write-Step "从 PATH 移除"
    $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($currentPath -like "*$InstallDir*") {
        $newPath = ($currentPath -split ";" | Where-Object { $_ -ne $InstallDir }) -join ";"
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-OK "PATH 已更新"
    }
}

Write-Host ""
Write-Host "  卸载完成" -ForegroundColor Green
Write-Host ""
