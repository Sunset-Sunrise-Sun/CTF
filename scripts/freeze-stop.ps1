$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot "p1-stop.ps1"
$runDir = Join-Path $root ".local-run\run"
& powershell -NoProfile -ExecutionPolicy Bypass -File $runner -RunDir $runDir
exit $LASTEXITCODE
