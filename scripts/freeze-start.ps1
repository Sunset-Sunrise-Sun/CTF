param(
    [int]$BackendPort = 18110,
    [int]$FrontendPort = 15190
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot "p1-start.ps1"
$runDir = Join-Path $root ".local-run\run"
$dataDir = Join-Path $root ".local-run\data"
& powershell -NoProfile -ExecutionPolicy Bypass -File $runner `
    -BackendPort $BackendPort -FrontendPort $FrontendPort `
    -RunDir $runDir -DataDir $dataDir
exit $LASTEXITCODE
