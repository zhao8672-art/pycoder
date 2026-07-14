$key = (Get-Content "$env:USERPROFILE\.pycoder\.api_key" -Raw).Trim()
$base = "http://127.0.0.1:8423"
$h = @{"X-API-Key" = $key }

# 1. 搜索
Write-Host "=== 1. Search extensions (ruff) ==="
$r = Invoke-WebRequest -Uri "$base/api/extensions/search?q=ruff&limit=5" -Headers $h -UseBasicParsing
$d = $r.Content | ConvertFrom-Json
Write-Host "Extensions: $($d.extensions.Count)"
if ($d.extensions.Count -gt 0) {
    Write-Host "  First: $($d.extensions[0].name) ($($d.extensions[0].id))"
}

# 2. 安装种子扩展
Write-Host "`n=== 2. Install seed (astral.sh.ruff) ==="
$r2 = Invoke-WebRequest -Uri "$base/api/extensions/install" -Method Post -Headers $h -Body '{"id":"astral.sh.ruff"}' -ContentType "application/json" -UseBasicParsing
$d2 = $r2.Content | ConvertFrom-Json
Write-Host "Success: $($d2.success)"
if (-not $d2.success) { Write-Host "  Error: $($d2.error)" }

# 3. 安装另一个种子
Write-Host "`n=== 3. Install seed (psf.black) ==="
$r3 = Invoke-WebRequest -Uri "$base/api/extensions/install" -Method Post -Headers $h -Body '{"id":"psf.black"}' -ContentType "application/json" -UseBasicParsing
$d3 = $r3.Content | ConvertFrom-Json
Write-Host "Success: $($d3.success)"

# 4. 已安装列表
Write-Host "`n=== 4. Installed extensions ==="
$r4 = Invoke-WebRequest -Uri "$base/api/extensions/installed" -Headers $h -UseBasicParsing
$d4 = $r4.Content | ConvertFrom-Json
Write-Host "Installed: $($d4.extensions.Count)"
$d4.extensions | ForEach-Object { Write-Host "  $($_.id) - $($_.name)" }
