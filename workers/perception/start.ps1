param([int]$Camera = 0)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runtime = Join-Path $projectRoot '.venv-perception/Scripts/python.exe'
if (!(Test-Path -LiteralPath $runtime)) { throw 'Create .venv-perception and install workers/perception/requirements.txt first.' }
if (!(Test-Path -LiteralPath (Join-Path $projectRoot 'data/perception/token'))) { throw 'Run workers/perception/provision.py first.' }
# Docker API needs the host endpoint; every route is token-authenticated.
if (Get-NetTCPConnection -LocalPort 8020 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 8020 is already in use. Do not start a second camera service.' }
Start-Process -FilePath $runtime -ArgumentList @('workers/perception/service.py','--host','0.0.0.0','--camera',"$Camera") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot 'data/perception/service.log') -RedirectStandardError (Join-Path $projectRoot 'data/perception/service-error.log')
