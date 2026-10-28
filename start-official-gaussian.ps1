$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskContainer = 'gaussian-official-live'
$taskState = docker inspect --format '{{.State.Running}}' $taskContainer 2>$null
if ($LASTEXITCODE -eq 0) {
    if ($taskState -ne 'true') { docker start $taskContainer | Out-Null }
} else {
    docker image inspect empathic-avatar-gaussian-worker:latest | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Build the existing Gaussian worker image first.' }
    docker run -d --name $taskContainer --gpus all -p 127.0.0.1:8041:8041 -v "${taskRoot}:/workspace" -w /workspace/vendor/GaussianAvatars empathic-avatar-gaussian-worker:latest python /workspace/workers/gaussian/official_live.py | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not start official Gaussian renderer.' }
}
$taskDeadline = (Get-Date).AddSeconds(30)
do {
    try {
        $taskHealth = Invoke-RestMethod http://127.0.0.1:8041/health -TimeoutSec 2
        if ($taskHealth.ready) { Write-Output 'Official GaussianAvatars live renderer: ready (8041)'; return }
    } catch { Start-Sleep -Milliseconds 400 }
} while ((Get-Date) -lt $taskDeadline)
throw 'Official renderer startup timed out. Run: docker logs gaussian-official-live'
