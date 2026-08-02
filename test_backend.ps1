Get-Process python,pycoder-backend,PyCoder -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$out = "C:\Users\Administrator\Desktop\pycode\dist\pycoder-backend.exe"
$p = Start-Process $out -PassThru -NoNewWindow -RedirectStandardError "be.err" -RedirectStandardOutput "be.out"
Write-Host "Started PID=$($p.Id)"

for ($i=0; $i -lt 25; $i++) {
    Start-Sleep -Seconds 1
    if (-not (Get-Process -Id $p.Id -ErrorAction SilentlyContinue)) {
        Write-Host "  died at $i s"
        break
    }
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8423/api/health" -TimeoutSec 1
        Write-Host "  [OK] status=$($r.StatusCode) at $i s"
        break
    } catch {
        Write-Host "  waiting $i s"
    }
}

if (Test-Path "be.out") {
    Write-Host "=== STDOUT ==="
    Get-Content be.out -Tail 20
}
if (Test-Path "be.err") {
    Write-Host "=== STDERR ==="
    Get-Content be.err -Tail 20
}

Get-Process pycoder-backend -ErrorAction SilentlyContinue | Stop-Process -Force
