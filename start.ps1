# ============================================================================
# PyCoder 一键启动 (Windows PowerShell 5.x / 7+)
#
# 用法:
#   .\start.ps1                启动后端 + 桌面 IDE
#   .\start.ps1 server         仅启动后端
#   .\start.ps1 electron       仅启动 Electron
#   .\start.ps1 install        安装依赖
#   .\start.ps1 clean          清理缓存
#   .\start.ps1 help           显示帮助
#
# 等价命令 (CMD): start.bat
# ============================================================================
[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [ValidateSet("server", "web", "electron", "install", "clean", "help", "")]
    [string]$Command = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSCommandPath
Set-Location $root

# P2-2: 强制 UTF-8 编码，解决中文输出乱码
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# 1. 寻找 Python
$python = $null
foreach ($p in @(".venv\Scripts\python.exe", "venv\Scripts\python.exe")) {
    if (Test-Path (Join-Path $root $p)) { $python = (Join-Path $root $p); break }
}
if (-not $python) {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { $python = $cmd.Source }
}
if (-not $python) {
    Write-Host "[ERROR] Python 未找到. 请先安装 Python 3.12+ 或激活 venv." -ForegroundColor Red
    exit 1
}

# 2. 强制 UTF-8 (避免 Windows GBK 编码问题)
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# 3. 分发
switch ($Command) {
    "" {
        Write-Host "[INFO] 启动后端 + Electron" -ForegroundColor Cyan
        Start-Process -FilePath $python -ArgumentList @("-m", "pycoder", "--server") -WindowStyle Normal
        Start-Sleep -Seconds 3
        if (Test-Path (Join-Path $root "pycoder\electron")) {
            $electronDir = Join-Path $root "pycoder\electron"
            Start-Process -FilePath "cmd" -ArgumentList @("/c", "cd /d `"$electronDir`" && npx electron .") -WindowStyle Normal
            Write-Host "[OK] 后端 + Electron 已启动" -ForegroundColor Green
        } else {
            Write-Host "[WARN] pycoder\electron 目录不存在, 仅启动后端" -ForegroundColor Yellow
        }
        exit 0
    }
    { $_ -in @("server", "web") } {
        Write-Host "[INFO] 启动后端 (http://127.0.0.1:8423)" -ForegroundColor Cyan
        & $python -m pycoder --server
        exit $LASTEXITCODE
    }
    "electron" {
        Write-Host "[INFO] 启动 Electron" -ForegroundColor Cyan
        Set-Location (Join-Path $root "pycoder\electron")
        npx electron .
        exit $LASTEXITCODE
    }
    "install" {
        Write-Host "[INFO] 安装全量依赖" -ForegroundColor Cyan
        & $python -m pip install -r requirements-all.txt
        & $python -m pip install -e .
        Write-Host "[OK] 安装完成" -ForegroundColor Green
        exit 0
    }
    "clean" {
        Write-Host "[INFO] 清理缓存" -ForegroundColor Cyan
        $caches = @(
            (Join-Path $root ".pycoder\Cache"),
            (Join-Path $env:APPDATA "pycoder\Cache"),
            (Join-Path $env:APPDATA "pycoder\GPUCache"),
            (Join-Path $env:APPDATA "pycoder\Code Cache")
        )
        foreach ($c in $caches) {
            if (Test-Path $c) { Remove-Item $c -Recurse -Force -ErrorAction SilentlyContinue }
        }
        Write-Host "[OK] 缓存清理完成" -ForegroundColor Green
        exit 0
    }
    "help" {
        Write-Host "PyCoder 一键启动 (Windows PowerShell)" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "用法: .\start.ps1 [command]"
        Write-Host ""
        Write-Host "命令:"
        Write-Host "  (无参数)    启动后端 + Electron"
        Write-Host "  server      仅启动后端"
        Write-Host "  electron    仅启动 Electron"
        Write-Host "  install     安装全量依赖"
        Write-Host "  clean       清理缓存"
        Write-Host "  help        显示此帮助"
        Write-Host ""
        Write-Host "环境变量:"
        Write-Host "  PYCODER_API_KEY    API 鉴权 key"
        Write-Host "  DEEPSEEK_API_KEY   DeepSeek 模型 key"
        exit 0
    }
}
