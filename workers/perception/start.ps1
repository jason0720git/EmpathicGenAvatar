param([int]$Camera = 0)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runtime = Join-Path $projectRoot '.venv-perception/Scripts/python.exe'
if (!(Test-Path -LiteralPath $runtime)) { throw 'Create .venv-perception and install workers/perception/requirements.txt first.' }
if (!(Test-Path -LiteralPath (Join-Path $projectRoot 'data/perception/token'))) { throw 'Run workers/perception/provision.py first.' }
# Docker API needs the host endpoint; every route is token-authenticated.
$token = (Get-Content -LiteralPath (Join-Path $projectRoot 'data/perception/token') -Raw).Trim()
if (Get-NetTCPConnection -LocalPort 8020 -State Listen -ErrorAction SilentlyContinue) {
    $health = Invoke-RestMethod 'http://127.0.0.1:8020/health' -Headers @{'X-Perception-Token'=$token} -TimeoutSec 2
    if ($health.status -eq 'ok') { Write-Output 'Face analysis service already ready (camera remains user-controlled).'; return }
    throw 'Port 8020 is occupied by an unhealthy or differently configured service.'
}
Start-Process -FilePath $runtime -ArgumentList @('workers/perception/service.py','--host','0.0.0.0','--camera',"$Camera") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot 'data/perception/service.log') -RedirectStandardError (Join-Path $projectRoot 'data/perception/service-error.log')
for ($attempt=0; $attempt -lt 30; $attempt++) {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8020/health' -Headers @{'X-Perception-Token'=$token} -TimeoutSec 1
        if ($health.status -eq 'ok') { Write-Output 'Face analysis service ready. Camera stays off until enabled in the site.'; return }
    } catch { }
    Start-Sleep -Milliseconds 300
}
throw 'Face service startup failed. Check data/perception/service-error.log.'
