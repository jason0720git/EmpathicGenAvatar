param([int]$Camera = 0, [switch]$Build)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    powershell -NoProfile -ExecutionPolicy Bypass -File workers/perception/start.ps1 -Camera $Camera
    if ($LASTEXITCODE -ne 0) { throw 'Face service startup failed.' }
    if ($Build) {
        docker compose -f docker-compose.yml -f docker-compose.gpu.yml build api web
        if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
    }
    docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
    if ($LASTEXITCODE -ne 0) { throw 'Docker services failed to start.' }
    docker cp data/perception/token empathic-avatar-api-1:/data/perception-token
    if ($LASTEXITCODE -ne 0) { throw 'Face service credential sync failed.' }
    Write-Output 'Ready: http://localhost:4173/ (camera remains off until explicitly enabled).'
} finally { Pop-Location }
