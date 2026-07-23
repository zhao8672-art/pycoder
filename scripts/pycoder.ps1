# ============================================================================
# PyCoder Windows 启动包装器 (PowerShell 5.x / 7+)
# 用法:
#   .\scripts\pycoder.ps1 --server
#   .\scripts\pycoder.ps1 --setup
#   .\scripts\pycoder.ps1 --scan pycoder/
#
# 自动检测:
#   1) 优先使用 pip 安装的 pycoder.exe
#   2) 回退到 python -m pycoder
# ============================================================================
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PyCoderArgs
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $PSCommandPath
$repoRoot = Split-Path -Parent $scriptRoot
Push-Location $repoRoot

try {
    # 1. 寻找 pycoder.exe
    $pycoderExe = $null
    $candidates = @(
        (Join-Path $repoRoot "venv\Scripts\pycoder.exe"),
        (Join-Path $repoRoot ".venv\Scripts\pycoder.exe")
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { $pycoderExe = $p; break }
    }
    if (-not $pycoderExe) {
        $cmd = Get-Command pycoder.exe -ErrorAction SilentlyContinue
        if ($cmd) { $pycoderExe = $cmd.Source }
    }

    # 2. 寻找 python.exe
    $pythonExe = $null
    $pyCandidates = @(
        (Join-Path $repoRoot "venv\Scripts\python.exe"),
        (Join-Path $repoRoot ".venv\Scripts\python.exe")
    )
    foreach ($p in $pyCandidates) {
        if (Test-Path $p) { $pythonExe = $p; break }
    }
    if (-not $pythonExe) {
        $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($cmd) { $pythonExe = $cmd.Source }
    }
    if (-not $pythonExe) {
        Write-Host "[ERROR] python.exe 未找到. 请先安装 Python 3.12+ 或激活 venv." -ForegroundColor Red
        exit 1
    }

    # 3. 强制 UTF-8 (避免 Windows GBK 编码问题)
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

    # 4. 调用 pycoder
    $argList = @()
    if ($PyCoderArgs) { $argList += $PyCoderArgs }

    if ($pycoderExe) {
        & $pycoderExe @argList
    } else {
        & $pythonExe -m pycoder @argList
    }
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
