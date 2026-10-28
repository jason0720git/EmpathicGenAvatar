param([switch]$SkipGenerator)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
if (Test-Path -LiteralPath (Join-Path $taskRoot 'vendor/GaussianAvatars/media/306/point_cloud.ply')) {
    & (Join-Path $taskRoot 'start-official-gaussian.ps1')
}
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
$logDir = Join-Path $taskRoot 'data/gaussian/service-logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
if (!(Test-Path -LiteralPath $taskPython)) { throw 'Create .venv and install apps/api/requirements-gaussian.txt first.' }
if (!(Test-Path -LiteralPath (Join-Path $taskRoot 'apps/web/node_modules/vite/bin/vite.js'))) { throw 'Run pnpm install from the repository root first.' }
if (!(Get-NetTCPConnection -LocalPort 8030 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $taskPython -ArgumentList @('workers/gaussian_lab/run_api.py') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'api.log') -RedirectStandardError (Join-Path $logDir 'api-error.log')
}
if (!(Get-NetTCPConnection -LocalPort 5174 -State Listen -ErrorAction SilentlyContinue)) {
    $taskNode = (Get-Command node).Source
    $viteEntry = Join-Path $taskRoot 'apps/web/node_modules/vite/bin/vite.js'
    Start-Process -FilePath $taskNode -ArgumentList @($viteEntry,'--host','127.0.0.1','--port','5174','--strictPort') -WorkingDirectory (Join-Path $taskRoot 'apps/web') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'web.log') -RedirectStandardError (Join-Path $logDir 'web-error.log')
}
if (!$SkipGenerator -and (Test-Path -LiteralPath (Join-Path $taskRoot 'workers/gaussian/compose.yml'))) {
    Push-Location $taskRoot
    try { docker compose -f workers/gaussian/compose.yml up -d; if ($LASTEXITCODE -ne 0) { throw 'Generation worker startup failed.' } } finally { Pop-Location }
}
$a2fRunning = docker inspect --format '{{.State.Running}}' audio2face-3d 2>$null
if ($LASTEXITCODE -eq 0 -and $a2fRunning -eq 'false') {
    docker start audio2face-3d | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Warning 'The existing Audio2Face container could not be started.' }
}
$taskDeadline = (Get-Date).AddSeconds(30)
$taskHealth = $null
do {
    try {
        $taskHealth = Invoke-RestMethod 'http://127.0.0.1:8030/gaussian-api/health' -TimeoutSec 8
        $null = Invoke-WebRequest 'http://127.0.0.1:5174/gaussian' -UseBasicParsing -TimeoutSec 4
        break
    } catch { Start-Sleep -Milliseconds 500 }
} while ((Get-Date) -lt $taskDeadline)
if (!$taskHealth) { throw "Gaussian services did not become available. Inspect $logDir" }
if (!$taskHealth.openai.ready) { Write-Warning 'Set OPENAI_API_KEY in .env and restart the Gaussian API.' }
if (!$taskHealth.a2f.ready) { Write-Warning 'Audio2Face is not ready yet. Check its container and refresh services in the studio.' }
if (!$taskHealth.generator.ready) { Write-Warning 'Photo generation is not ready yet. Check the Gaussian worker health and assets.' }
Write-Output 'Gaussian studio: http://127.0.0.1:5174/gaussian'
Write-Output 'Diagnostic logs: data/gaussian/sessions/'
