param(
    [int]$BackendPort = 18188,
    [int]$FrontendPort = 15188
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "p1-common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$start = Join-Path $PSScriptRoot "p1-start.ps1"
$stop = Join-Path $PSScriptRoot "p1-stop.ps1"
$temp = Join-Path $env:TEMP ("p1-r4-startup-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temp | Out-Null
$failures = @()
$notes = @()
$savedEnv = @{}
$sentinel = $null

function Set-TestFlags {
    param([hashtable]$Flags)
    $names = @("CTF_P1_TEST_MODE", "CTF_P1_TEST_BACKEND_HEALTH_FAIL",
        "CTF_P1_TEST_FRONTEND_START_FAIL", "CTF_P1_TEST_FAIL_BACKEND_PID_WRITE",
        "CTF_P1_TEST_FAIL_BACKEND_RECORD", "CTF_P1_TEST_FAIL_FRONTEND_RECORD",
        "CTF_P1_TEST_FAIL_BACKEND_IDENTITY", "CTF_P1_TEST_FAIL_FRONTEND_IDENTITY",
        "CTF_P1_TEST_IDENTITY_RECOVER",
        "CTF_P1_TEST_FAIL_RUN_INFO_WRITE", "CTF_P1_TEST_CLEANUP_IDENTITY_CHANGE")
    foreach ($name in $names) {
        if (-not $savedEnv.ContainsKey($name)) { $savedEnv[$name] = [Environment]::GetEnvironmentVariable($name) }
        [Environment]::SetEnvironmentVariable($name, $null)
    }
    foreach ($name in $Flags.Keys) {
        [Environment]::SetEnvironmentVariable($name, [string]$Flags[$name])
    }
}

function Restore-TestFlags {
    foreach ($name in $savedEnv.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnv[$name])
    }
}

function Invoke-FailedStart {
    param([string]$Case, [hashtable]$Flags, [string]$ExpectedComponent, [bool]$ExpectAlive = $false)
    if (Get-NetTCPConnection -LocalPort $BackendPort, $FrontendPort -State Listen -ErrorAction SilentlyContinue) {
        throw "test ports already occupied before $Case"
    }
    $caseRoot = Join-Path $temp $Case
    $run = Join-Path $caseRoot "run"
    $data = Join-Path $caseRoot "data"
    New-Item -ItemType Directory -Force -Path $caseRoot | Out-Null
    Set-TestFlags $Flags
    $stdout = Join-Path $caseRoot "launcher.stdout.log"
    $stderr = Join-Path $caseRoot "launcher.stderr.log"
    $child = Start-Process -FilePath (Get-Command powershell).Source `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $start,
            "-BackendPort", "$BackendPort", "-FrontendPort", "$FrontendPort",
            "-DataDir", $data, "-RunDir", $run) `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
        -PassThru -WindowStyle Hidden
    if (-not $child.WaitForExit(30000)) {
        try { $child.Kill(); $child.WaitForExit(5000) } catch { }
        throw "$Case launcher did not exit"
    }
    if ($child.ExitCode -eq 0) { throw "$Case unexpectedly succeeded" }
    $failurePath = Join-Path $run "start-failure.json"
    if (-not (Test-Path -LiteralPath $failurePath)) { throw "$Case missing start-failure.json" }
    $failure = Get-Content -LiteralPath $failurePath -Raw | ConvertFrom-Json
    if ($failure.component -ne $ExpectedComponent) {
        throw "$Case component=$($failure.component), expected $ExpectedComponent"
    }
    if (-not $failure.records) { throw "$Case missing records" }
    if ($ExpectAlive) {
        $record = if ($failure.records.backend) { $failure.records.backend } elseif ($failure.records.frontend) { $failure.records.frontend } else { $null }
        $pidValue = if ($record -and $record.backend_pid) { $record.backend_pid } elseif ($record) { $record.frontend_pid } else { $null }
        if (-not $pidValue -or -not (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
            throw "$Case expected the process to remain alive after refused cleanup"
        }
        if (-not $failure.cleanup.backend -or $failure.cleanup.backend.status -ne "mismatch") {
            throw "$Case expected backend cleanup mismatch"
        }
        try { Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue } catch { }
    } else {
        foreach ($kind in @("backend", "frontend")) {
            if ($failure.cleanup.$kind -and $failure.cleanup.$kind.status -notin @("stopped", "missing")) {
                throw "$Case $kind cleanup=$($failure.cleanup.$kind.status)"
            }
        }
    }
    Start-Sleep -Milliseconds 500
    if (Get-NetTCPConnection -LocalPort $BackendPort, $FrontendPort -State Listen -ErrorAction SilentlyContinue) {
        throw "$Case left a listener on a test port"
    }
    $notes += "PASS $Case component=$($failure.component) exit=$($child.ExitCode)"
    Write-Host "PASS $Case"
}

try {
    $sentinelPort = 18192
    if (Get-NetTCPConnection -LocalPort $sentinelPort -State Listen -ErrorAction SilentlyContinue) {
        throw "sentinel port occupied"
    }
    $sentinel = Start-Process -FilePath (Get-Command python).Source `
        -ArgumentList @("-m", "http.server", "$sentinelPort", "--bind", "127.0.0.1") `
        -PassThru -WindowStyle Hidden
    Start-Sleep -Milliseconds 800
    if (-not (Get-Process -Id $sentinel.Id -ErrorAction SilentlyContinue)) { throw "sentinel failed" }

    Invoke-FailedStart -Case "backend-pid-write-failure" -ExpectedComponent "backend" -Flags @{
        CTF_P1_TEST_MODE = "1"; CTF_P1_TEST_FAIL_BACKEND_PID_WRITE = "1"
    }
    Invoke-FailedStart -Case "backend-record-failure" -ExpectedComponent "backend" -Flags @{
        CTF_P1_TEST_MODE = "1"; CTF_P1_TEST_FAIL_BACKEND_IDENTITY = "1"; CTF_P1_TEST_IDENTITY_RECOVER = "1"
    }
    Invoke-FailedStart -Case "frontend-record-failure" -ExpectedComponent "frontend" -Flags @{
        CTF_P1_TEST_MODE = "1"; CTF_P1_TEST_FAIL_FRONTEND_IDENTITY = "1"; CTF_P1_TEST_IDENTITY_RECOVER = "1"
    }
    Invoke-FailedStart -Case "run-info-write-failure" -ExpectedComponent "run_info" -Flags @{
        CTF_P1_TEST_MODE = "1"; CTF_P1_TEST_FAIL_RUN_INFO_WRITE = "1"
    }
    Invoke-FailedStart -Case "cleanup-identity-change" -ExpectedComponent "backend" -ExpectAlive $true -Flags @{
        CTF_P1_TEST_MODE = "1"; CTF_P1_TEST_BACKEND_HEALTH_FAIL = "1"; CTF_P1_TEST_CLEANUP_IDENTITY_CHANGE = "1"
    }
    if (-not (Get-Process -Id $sentinel.Id -ErrorAction SilentlyContinue)) {
        throw "cleanup failure killed the unrelated sentinel process"
    }
    $notes += "PASS cleanup failure did not kill unrelated sentinel"

    # Normal lifecycle with the final start/stop code.
    Restore-TestFlags
    $normalRoot = Join-Path $temp "normal"
    $normalRun = Join-Path $normalRoot "run"
    $normalData = Join-Path $normalRoot "data"
    New-Item -ItemType Directory -Force -Path $normalRoot | Out-Null
    $normalOut = Join-Path $normalRoot "launcher.stdout.log"
    $normalErr = Join-Path $normalRoot "launcher.stderr.log"
    $normalChild = Start-Process -FilePath (Get-Command powershell).Source `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $start,
            "-BackendPort", "$BackendPort", "-FrontendPort", "$FrontendPort",
            "-DataDir", $normalData, "-RunDir", $normalRun) `
        -RedirectStandardOutput $normalOut -RedirectStandardError $normalErr `
        -PassThru -WindowStyle Hidden
    $normalReady = $false
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-Path (Join-Path $normalRun "run-info.json")) { $normalReady = $true; break }
        if ($normalChild.HasExited) { break }
    }
    if (-not $normalReady) { throw "normal start did not write run-info" }
    $normalStop = Start-Process -FilePath (Get-Command powershell).Source `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $stop, "-RunDir", $normalRun) `
        -PassThru -WindowStyle Hidden
    if (-not $normalStop.WaitForExit(30000)) { throw "normal stop did not exit" }
    if ($normalStop.ExitCode -ne 0) { throw "normal stop failed" }
    if (Get-NetTCPConnection -LocalPort $BackendPort, $FrontendPort -State Listen -ErrorAction SilentlyContinue) {
        throw "normal stop left a listener"
    }
    $notes += "PASS normal start/stop after lifecycle refactor"
} catch {
    $failures += "unexpected exception: $($_.Exception.Message)"
} finally {
    Restore-TestFlags
    if ($sentinel) { try { Stop-Process -Id $sentinel.Id -Force -ErrorAction SilentlyContinue } catch { } }
    $notes | ForEach-Object { Write-Host $_ }
    if ($failures.Count -gt 0) {
        $failures | ForEach-Object { Write-Host "FAIL $_" }
        Write-Host "R4 STARTUP TESTS FAILED"
        exit 1
    }
    Write-Host "R4 STARTUP TESTS PASSED"
    Write-Host "EVIDENCE_ROOT $temp"
    exit 0
}
