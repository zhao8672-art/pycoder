# PyCoder post-commit 钩子 Windows 安装脚本
# 在 PowerShell 中运行: .\install-post-commit.ps1
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$gitDir = Join-Path $repoRoot ".git"
$hookSrc = Join-Path $repoRoot ".git-hooks\post-commit"
$hookDst = Join-Path $gitDir "hooks\post-commit"

if (-not (Test-Path $gitDir)) {
    Write-Host "[ERROR] $gitDir 不存在, 请在 Git 仓库根目录运行" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $hookSrc)) {
    Write-Host "[ERROR] $hookSrc 不存在" -ForegroundColor Red
    exit 1
}

# 备份现有钩子
if (Test-Path $hookDst) {
    $backup = "$hookDst.bak.$(Get-Date -Format 'yyyyMMddHHmmss')"
    Move-Item -Path $hookDst -Destination $backup -Force
    Write-Host "[INFO] 已备份旧钩子到 $backup" -ForegroundColor Yellow
}

# 复制新钩子
Copy-Item -Path $hookSrc -Destination $hookDst -Force
Write-Host "[OK] post-commit 钩子已安装到 $hookDst" -ForegroundColor Green

# Git for Windows 的 post-commit 钩子通常无需 chmod (Git Bash 内部处理)
Write-Host ""
Write-Host "安装完成. 下次 git commit 时将自动推送到 origin." -ForegroundColor Cyan
