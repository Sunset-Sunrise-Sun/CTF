param([int]$BackendPort = 18185, [int]$FrontendPort = 15185)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "p1-common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$start = Join-Path $PSScriptRoot "p1-start.ps1"
$temp = Join-Path $env:TEMP ("p1-r3-startup-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temp | Out-Null
$prior = @{
    CTF_P1_TEST_MODE = $env:CTF_P1_TEST_MODE
    CTF_P1_TEST_BACKEND_HEALTH_FAIL = $env:CTF_P1_TEST_BACKEND_HEALTH_FAIL
    CTF_P1_TEST_FRONTEND_START_FAIL = $env:CTF_P1_TEST_FRONTEND_START_FAIL
}
function Invoke-FailedStart {
    param([string]$Case, [string]$Flag)
    if (Get-NetTCPConnection -LocalPort $BackendPort, $FrontendPort -State Listen -ErrorAction SilentlyContinue) {
        throw "test ports already occupied"
    }
    $caseRoot = Join-Path $temp $Case
    $run = Join-Path $caseRoot "run"
    $data = Join-Path $caseRoot "data"
    New-Item -ItemType Directory -Path $caseRoot | Out-Null
    $env:CTF_P1_TEST_MODE = "1"
    $env:CTF_P1_TEST_BACKEND_HEALTH_FAIL = if ($Flag -eq "backend") { "1" } else { "0" }
    $env:CTF_P1_TEST_FRONTEND_START_FAIL = if ($Flag -eq "frontend") { "1" } else { "0" }
    $stdout = Join-Path $caseRoot "launcher.stdout.log"
    $stderr = Join-Path $caseRoot "launcher.stderr.log"
    $child = Start-Process -FilePath (Get-Command powershell).Source `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $start,
            "-BackendPort", "$BackendPort", "-FrontendPort", "$FrontendPort",
            "-DataDir", $data, "-RunDir", $run) `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
        -PassThru -Wait -WindowStyle Hidden
    try {
        $launcherExit = $child.ExitCode
        if ($null -eq $launcherExit -or $launcherExit -eq 0) {
            throw "$Case launcher exit code was not a verified failure: $launcherExit"
        }
        $failurePath = Join-Path $run "start-failure.json"
        if (-not (Test-Path -LiteralPath $failurePath)) { throw "$Case missing start-failure.json" }
        $failure = Get-Content -LiteralPath $failurePath -Raw | ConvertFrom-Json
        if ($failure.component -ne $Flag) { throw "$Case failure component=$($failure.component)" }
        if (-not $failure.records -or -not $failure.cleanup.backend) {
            throw "$Case missing process records or backend cleanup"
        }
        if ($failure.cleanup.backend.status -notin @("stopped", "missing")) {
            throw "$Case backend cleanup=$($failure.cleanup.backend.status)"
        }
        if ($Case -eq "backend-alive-health-failure") {
            if (-not $failure.process_alive_before_cleanup) { throw "backend was not alive before cleanup" }
            if ($failure.cleanup.backend.status -ne "stopped") { throw "live backend was not stopped" }
        } else {
            if (-not $failure.cleanup.frontend -or
                $failure.cleanup.frontend.status -notin @("stopped", "missing")) {
                throw "frontend failure cleanup was not recorded"
            }
        }
        Start-Sleep -Milliseconds 300
        if (Get-NetTCPConnection -LocalPort $BackendPort, $FrontendPort -State Listen -ErrorAction SilentlyContinue) {
            throw "$Case left a listener on a test port"
        }
        Write-Host "PASS $Case exit=$launcherExit backend=$($failure.cleanup.backend.status) frontend=$($failure.cleanup.frontend.status)"
        Write-Host "EVIDENCE $failurePath"
    } finally {
        if (-not $child.HasExited) { $child.Kill(); $null = $child.WaitForExit(5000) }
        $child.Dispose()
        $runInfo = Join-Path $run "run-info.json"
        if (Test-Path -LiteralPath $runInfo) {
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "p1-stop.ps1") -RunDir $run | Out-Null
        }
    }
}
try {
    Invoke-FailedStart -Case "backend-alive-health-failure" -Flag "backend"
    Invoke-FailedStart -Case "frontend-start-failure" -Flag "frontend"

    # Identity mismatch must be rejected without touching the real test process.
    $info = Get-P1ProcessInfo -ProcessId $PID
    if ($info.state -ne "NORMAL") { throw "cannot inspect test process" }
    $bad = [pscustomobject]@{
        backend_pid = $PID; backend_port = 0
        backend_executable = $info.executable; backend_command_line = $info.command_line
        backend_start_time = $info.start_time
        backend_identity_tokens = @("definitely-not-in-this-process-command")
    }
    $refused = Stop-P1ProcessByVerifiedHandle -Record $bad -Kind "backend"
    if ($refused.status -ne "mismatch" -or -not (Get-Process -Id $PID -ErrorAction SilentlyContinue)) {
        throw "identity mismatch did not refuse termination"
    }
    Write-Host "PASS identity mismatch refused termination"
    Write-Host "R3 STARTUP TESTS PASSED"
    exit 0
} finally {
    foreach ($name in $prior.Keys) {
        if ($null -eq $prior[$name]) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
        else { Set-Item "Env:$name" $prior[$name] }
    }
    # Keep isolated launcher logs and JSON records for independent inspection.
    Write-Host "EVIDENCE_ROOT $temp"
}
