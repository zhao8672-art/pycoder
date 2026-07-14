#requires -Version 5.1

<#
.SYNOPSIS
    PyCoder unified manager - single entry for all start/stop/status operations
#>

param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet("Start-All","Stop-All","Start-Backend","Stop-Backend","Start-Desktop","Stop-Desktop","Start-TUI","Status","Doctor","Cleanup","Install-Deps","Restart")]
    [string]$Action
)

$BASE    = "C:\Users\Administrator\Desktop\pycode"
$ELEC    = Join-Path $BASE "pycoder\electron"
$LOG_DIR = Join-Path $BASE "scripts\logs"
$LOG     = Join-Path $LOG_DIR "pycoder-manager.log"
$BACKEND_PORT = 8423
$HEALTH_URL   = "http://127.0.0.1:${BACKEND_PORT}/api/health"

if (-not (Test-Path $LOG_DIR)) { New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null }

function Write-Log {
    param([string]$Level, [string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    $line = "[${timestamp}] [${Level}] ${Message}"
    $line | Out-File -FilePath $LOG -Append -Encoding UTF8
    Write-Host $line
}

function Get-PyCoderBackendProcess {
    # Try direct CommandLine first (works when process is owned by PowerShell/CMD)
    $direct = Get-Process "python" -ErrorAction SilentlyContinue | Where-Object {
        try { $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match 'pycoder.server.app' } catch { $false }
    }
    if ($direct) { return $direct }

    # Fallback: use WMI/CIM for processes started via CreateProcess (no CommandLine available)
    try {
        $cim = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
        $matched = $cim | Where-Object { $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match 'pycoder.server.app' }
        if ($matched) {
            return Get-Process -Id $matched.ProcessId -ErrorAction SilentlyContinue
        }
    } catch { }
    return $null
}

function Get-PyCoderDesktopProcess {
    function Test-ElectronCommandLine {
        param($proc)
        try { return $proc.CommandLine -match "pycoder" } catch { return $false }
    }
    $direct = Get-Process "electron" -ErrorAction SilentlyContinue | Where-Object {
        $_.MainWindowTitle -match "PyCoder" -or
        ($_.MainWindowTitle -eq "" -and (Test-ElectronCommandLine $_))
    }
    if ($direct) { return $direct }

    # Fallback: CIM for orphaned processes
    try {
        $cim = Get-CimInstance Win32_Process -Filter "Name='electron.exe' AND CommandLine LIKE '%pycoder%'" -ErrorAction SilentlyContinue
        if ($cim) {
            $p = Get-Process -Id $cim.ProcessId -ErrorAction SilentlyContinue
            if ($p) { return $p }
        }
    } catch { }
    return $null
}

function Test-BackendHealth {
    try {
        $r = Invoke-WebRequest -Uri $HEALTH_URL -TimeoutSec 3 -UseBasicParsing
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Wait-BackendReady {
    param([int]$TimeoutSeconds = 30)
    $elapsed = 0
    while ($elapsed -lt $TimeoutSeconds) {
        if (Test-BackendHealth) {
            Write-Log "INFO" "Backend health check passed"
            return $true
        }
        Start-Sleep -Seconds 1
        $elapsed++
        if ($elapsed % 5 -eq 0) {
            Write-Log "INFO" "Waiting for backend... (${elapsed}s/${TimeoutSeconds}s)"
        }
    }
    Write-Log "WARN" "Backend did not respond within ${TimeoutSeconds}s"
    return $false
}

function Start-Backend {
    Write-Log "INFO" "Starting backend (port ${BACKEND_PORT})..."
    $existing = Get-PyCoderBackendProcess
    if ($existing) {
        Write-Log "WARN" "Backend already running (PID: $($existing.Id)). Use Restart."
        return $true
    }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "python"
    $psi.Arguments = "-m uvicorn pycoder.server.app:app --host 127.0.0.1 --port ${BACKEND_PORT} --reload"
    $psi.WorkingDirectory = $BASE
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $psi.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
    $psi.EnvironmentVariables["PYTHONUTF8"] = "1"
    $psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8"
    $p = [System.Diagnostics.Process]::Start($psi)
    Write-Log "INFO" "Backend started (PID: $($p.Id))"
    return Wait-BackendReady
}

function Stop-Backend {
    Write-Log "INFO" "Stopping backend..."
    $procs = Get-PyCoderBackendProcess
    if (-not $procs) {
        Write-Log "INFO" "No backend process found"
        return $true
    }
    foreach ($p in $procs) {
        Write-Log "INFO" "Closing backend PID $($p.Id) gracefully..."
        if ($p.CloseMainWindow()) {
            Write-Log "INFO" "CloseMainWindow sent, waiting 5s..."
            if (-not $p.WaitForExit(5000)) {
                Write-Log "WARN" "Backend PID $($p.Id) did not exit gracefully, killing..."
                $p.Kill(); $p.WaitForExit(2000)
            }
        } else {
            Write-Log "WARN" "Backend PID $($p.Id) has no window, killing..."
            $p.Kill(); $p.WaitForExit(2000)
        }
    }
    Write-Log "INFO" "Backend stopped"
}

function Start-Desktop {
    Write-Log "INFO" "Starting Electron desktop..."
    $existing = Get-PyCoderDesktopProcess
    if ($existing) {
        Write-Log "WARN" "Electron already running (PID: $($existing.Id))."
        try {
            Add-Type -AssemblyName System.Windows.Forms
            [System.Windows.Forms.SendKeys]::SendWait("%{tab}")
        } catch {}
        return $true
    }
    if (-not (Test-BackendHealth)) {
        Write-Log "WARN" "Backend not ready, starting backend first..."
        $ok = Start-Backend
        if (-not $ok) { Write-Log "ERROR" "Backend failed"; return $false }
    }
    # Electron must be started with a visible window (UseShellExecute=$true)
    $p = Start-Process -FilePath "npm.cmd" -ArgumentList "run dev" -WorkingDirectory $ELEC -WindowStyle Normal -PassThru
    Write-Log "INFO" "Electron started (PID: $($p.Id))"
    $found = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        # Try direct MainWindowTitle first
        $w = Get-Process "electron" -ErrorAction SilentlyContinue |
             Where-Object { $_.MainWindowTitle -match "PyCoder" -and $_.Responding }
        if ($w) {
            Write-Log "INFO" "Electron window appeared (PID: $($w.Id), Title: '$($w.MainWindowTitle)')"
            $found = $true; break
        }
        # Try CIM as fallback for processes with blank MainWindowTitle
        try {
            $cim = Get-CimInstance Win32_Process -Filter "Name='electron.exe' AND CommandLine LIKE '%pycoder%' AND CommandLine LIKE '%index.js%'" -ErrorAction SilentlyContinue
            if ($cim) {
                $wp = Get-Process -Id $cim.ProcessId -ErrorAction SilentlyContinue
                if ($wp -and $wp.Responding -and $wp.MainWindowTitle -match "PyCoder") {
                    Write-Log "INFO" "Electron window appeared via CIM (PID: $($wp.Id), Title: '$($wp.MainWindowTitle)')"
                    $found = $true; break
                }
            }
        } catch { }
        if ($i -eq 5) { Write-Log "INFO" "Waiting for Electron window... (5s/20s)" }
        if ($i -eq 10) { Write-Log "INFO" "Waiting for Electron window... (10s/20s)" }
        if ($i -eq 15) { Write-Log "INFO" "Waiting for Electron window... (15s/20s)" }
    }
    if (-not $found) { Write-Log "WARN" "Electron window did not appear within 20s (it may still be loading)" }
    return $true
}

function Stop-Desktop {
    Write-Log "INFO" "Stopping Electron desktop..."
    $procs = Get-PyCoderDesktopProcess
    if (-not $procs) {
        $allElec = Get-Process "electron" -ErrorAction SilentlyContinue |
                   Where-Object { $_.CommandLine -match "pycoder" }
        if ($allElec) { $procs = $allElec } else { Write-Log "INFO" "No Electron process found"; return $true }
    }
    foreach ($p in $procs) {
        Write-Log "INFO" "Closing Electron PID $($p.Id) gracefully..."
        if ($p.CloseMainWindow()) {
            Write-Log "INFO" "CloseMainWindow sent, waiting 5s..."
            if (-not $p.WaitForExit(5000)) {
                Write-Log "WARN" "Electron PID $($p.Id) did not exit, killing..."
                $p.Kill(); $p.WaitForExit(2000)
            }
        } else {
            Write-Log "WARN" "Electron PID $($p.Id) has no window, killing..."
            $p.Kill(); $p.WaitForExit(2000)
        }
    }
    Write-Log "INFO" "Electron stopped"
}

function Start-TUI {
    Write-Log "INFO" "Starting TUI terminal..."
    Write-Host ""; Write-Host "Starting PyCoder TUI..." -ForegroundColor Cyan
    Write-Host "(TUI runs in this console. Press Ctrl+C to exit.)" -ForegroundColor Yellow
    Write-Host ""
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    Set-Location $BASE
    python -m pycoder --tui
    Write-Log "INFO" "TUI exited"
}

function Show-Status {
    $s = @{}
    $be = Get-PyCoderBackendProcess
    $s.backendRunning = ($be -ne $null)
    $s.backendPid = if ($be) { $be.Id } else { $null }
    $s.healthOk = if ($be) { Test-BackendHealth } else { $false }
    $de = Get-PyCoderDesktopProcess
    $s.desktopRunning = ($de -ne $null)
    $s.desktopPid = if ($de) { $de.Id } else { $null }
    $s.desktopTitle = if ($de) { $de.MainWindowTitle } else { $null }
    $portInfo = netstat -ano 2>$null | Select-String "127.0.0.1:${BACKEND_PORT}" | Select-Object -First 1
    $s.portInUse = ($portInfo -ne $null)

    Write-Host ""; Write-Host "=== PyCoder Status ===" -ForegroundColor Cyan; Write-Host ""
    if ($s.backendRunning) {
        Write-Host "  [GREEN]Backend  : RUNNING (PID: $($s.backendPid))" -ForegroundColor Green
        Write-Host "  Health  : $(if($s.healthOk){'OK [CHECK_MARK]'}else{'FAIL [CROSS_MARK]'})" -ForegroundColor $(if($s.healthOk){'Green'}else{'Red'})
    } else {
        Write-Host "  [RED]Backend  : STOPPED" -ForegroundColor Red
    }
    if ($s.desktopRunning) {
        Write-Host "  [GREEN]Desktop : RUNNING (PID: $($s.desktopPid))" -ForegroundColor Green
        if ($s.desktopTitle) { Write-Host "  Window  : '$($s.desktopTitle)'" }
    } else {
        Write-Host "  Desktop : STOPPED" -ForegroundColor DarkGray
    }
    Write-Host "  Port ${BACKEND_PORT}: $(if($s.portInUse){'IN USE'}else{'FREE'})" -ForegroundColor $(if($s.portInUse){'Cyan'}else{'DarkGray'})
    Write-Host "  Log     : $LOG" -ForegroundColor DarkGray; Write-Host ""
}

function Show-Doctor {
    Write-Host ""; Write-Host "=== PyCoder Doctor ===" -ForegroundColor Yellow; Write-Host ""
    $pyVer = python --version 2>&1; Write-Host "Python: $pyVer"
    $nodeVer = node --version 2>&1; $npmVer = npm --version 2>&1
    Write-Host "Node  : $nodeVer"; Write-Host "npm   : $npmVer"
    $elecBin = "$ELEC\node_modules\electron\dist\electron.exe"
    if (Test-Path $elecBin) { Write-Host "Electron: INSTALLED" -ForegroundColor Green }
    else { Write-Host "Electron: NOT INSTALLED" -ForegroundColor Red }
    $be = Get-PyCoderBackendProcess
    if ($be) { Write-Host "Backend: RUNNING PID $($be.Id) $(if(Test-BackendHealth){'HEALTHY'}else{'UNRESPONSIVE'})" }
    else { Write-Host "Backend: NOT RUNNING" }
    $de = Get-PyCoderDesktopProcess
    if ($de) { Write-Host "Desktop: RUNNING PID $($de.Id) '$($de.MainWindowTitle)'" }
    else { Write-Host "Desktop: NOT RUNNING" }
    $portInfo = netstat -ano 2>$null | Select-String "127.0.0.1:${BACKEND_PORT}" | Select-Object -First 1
    if ($portInfo) { Write-Host "Port ${BACKEND_PORT}: $($portInfo.ToString().Trim())" }
    else { Write-Host "Port ${BACKEND_PORT}: FREE" }
    Write-Host ""; Write-Host "All python/node/electron processes:" -ForegroundColor Yellow
    Get-Process "python","node","electron" -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, @{N='MemMB';E={[math]::Round($_.WorkingSet/1MB,1)}} | Format-Table -AutoSize
    Write-Host ""
}

function Invoke-Cleanup {
    Write-Log "INFO" "Starting cleanup..."
    Stop-Desktop; Stop-Backend
    $logFiles = Get-ChildItem -Path $LOG_DIR -Filter "*.log" -ErrorAction SilentlyContinue
    $oldLogs = $logFiles | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) }
    foreach ($f in $oldLogs) { Remove-Item $f.FullName -Force -ErrorAction SilentlyContinue }
    Write-Log "INFO" "Cleanup: removed $($oldLogs.Count) old log files"
    Write-Host "Cleanup complete" -ForegroundColor Green
}

function Install-Deps {
    Write-Log "INFO" "Checking dependencies..."
    Write-Host "Installing Python deps..." -ForegroundColor Cyan
    $r = python -m pip install -r "$BASE\requirements.txt" 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Host "  Python deps OK" -ForegroundColor Green }
    Write-Host "Installing Electron deps..." -ForegroundColor Cyan
    Push-Location $ELEC
    $r2 = npm install 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Host "  Electron deps OK" -ForegroundColor Green }
    Pop-Location
    Write-Log "INFO" "Dependencies checked"
}

try {
    $startTime = Get-Date
    switch ($Action) {
        "Start-All"   { Write-Log "INFO" "=== Start-All ==="; Start-Backend; Start-Desktop; Start-Sleep 2; Show-Status }
        "Stop-All"    { Write-Log "INFO" "=== Stop-All ==="; Stop-Desktop; Stop-Backend; Show-Status }
        "Restart"     { Write-Log "INFO" "=== Restart ==="; Stop-Desktop; Stop-Backend; Start-Sleep 2; Start-Backend; Start-Desktop; Show-Status }
        "Start-Backend" { Start-Backend }
        "Stop-Backend"  { Stop-Backend }
        "Start-Desktop" { Start-Desktop }
        "Stop-Desktop"  { Stop-Desktop }
        "Start-TUI"     { Start-TUI }
        "Status"        { Show-Status }
        "Doctor"        { Show-Doctor }
        "Cleanup"       { Invoke-Cleanup }
        "Install-Deps"  { Install-Deps }
    }
    $dur = [math]::Round(((Get-Date) - $startTime).TotalSeconds, 1)
    Write-Log "INFO" "${Action} completed in ${dur}s"
} catch {
    Write-Log "ERROR" "Unhandled: $_"
    Write-Log "ERROR" "$($_.ScriptStackTrace)"
    Write-Host "Error: $_" -ForegroundColor Red
    exit 1
}




