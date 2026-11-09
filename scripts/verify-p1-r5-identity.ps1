param(
    [int]$BackendPort = 18190,
    [int]$FrontendPort = 15190
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "p1-common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$start = Join-Path $PSScriptRoot "p1-start.ps1"
$stop = Join-Path $PSScriptRoot "p1-stop.ps1"
$temp = Join-Path $env:TEMP ("p1-r5-identity-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temp | Out-Null
$failures = @()
$notes = @()
$savedEnv = @{}
$sentinel = $null

function Set-Flags {
    param([hashtable]$Flags)
    $names = @("CTF_P1_TEST_MODE", "CTF_P1_TEST_FAIL_BACKEND_IDENTITY",
        "CTF_P1_TEST_FAIL_FRONTEND_IDENTITY", "CTF_P1_TEST_IDENTITY_RECOVER")
    foreach ($name in $names) {
        if (-not $savedEnv.ContainsKey($name)) { $savedEnv[$name] = [Environment]::GetEnvironmentVariable($name) }
        [Environment]::SetEnvironmentVariable($name, $null)
    }
    foreach ($name in $Flags.Keys) { [Environment]::SetEnvironmentVariable($name, [string]$Flags[$name]) }
}
function Restore-Flags {
    foreach ($name in $savedEnv.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnv[$name]) }
}

function Invoke-Case {
    param([string]$Name, [hashtable]$Flags)
    if (Get-NetTCPConnection -LocalPort $BackendPort, $FrontendPort -State Listen -ErrorAction SilentlyContinue) {
        throw "test ports occupied before $Name"
    }
    $caseRoot = Join-Path $temp $Name
    $run = Join-Path $caseRoot "run"
    $data = Join-Path $caseRoot "data"
    New-Item -ItemType Directory -Force -Path $caseRoot | Out-Null
    Set-Flags $Flags
    $child = Start-Process -FilePath (Get-Command powershell).Source `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $start,
            "-BackendPort", "$BackendPort", "-FrontendPort", "$FrontendPort",
            "-DataDir", $data, "-RunDir", $run) `
        -PassThru -WindowStyle Hidden
    if (-not $child.WaitForExit(30000)) { throw "$Name launcher did not exit" }
    if ($child.ExitCode -eq 0) { throw "$Name unexpectedly succeeded" }
    $failurePath = Join-Path $run "start-failure.json"
    if (-not (Test-Path -LiteralPath $failurePath)) { throw "$Name missing start-failure.json" }
    $failure = Get-Content -LiteralPath $failurePath -Raw | ConvertFrom-Json
    return [pscustomobject]@{ run = $run; failure = $failure; exit = $child.ExitCode }
}

try {
    $sentinelPort = 18193
    if (Get-NetTCPConnection -LocalPort $sentinelPort -State Listen -ErrorAction SilentlyContinue) {
        throw "sentinel port occupied"
    }
    $sentinel = Start-Process -FilePath (Get-Command python).Source `
        -ArgumentList @("-m", "http.server", "$sentinelPort", "--bind", "127.0.0.1") `
        -PassThru -WindowStyle Hidden
    Start-Sleep -Milliseconds 800
    if (-not (Get-Process -Id $sentinel.Id -ErrorAction SilentlyContinue)) { throw "sentinel failed" }

    # 1. Backend identity generation failed and cannot be recovered: no kill,
    # raw PID and failure reasons must survive.
    $case = Invoke-Case -Name "backend-identity-unrecoverable" -Flags @{
        CTF_P1_TEST_MODE = "1"; CTF_P1_TEST_FAIL_BACKEND_IDENTITY = "1"
    }
    $raw = @($case.failure.identity_failures | Where-Object { $_.kind -eq "backend" }) | Select-Object -First 1
    $started = @($case.failure.started_processes | Where-Object { $_.kind -eq "backend" }) | Select-Object -First 1
    if (-not $raw -or -not $started) { throw "backend identity failure not recorded" }
    if ($raw.pid -notmatch '^\d+$') { throw "backend identity failure has no raw PID" }
    if ($started.pid -notmatch '^\d+$') { throw "backend started_processes has no PID" }
    if ([int]$raw.pid -ne [int]$started.pid) {
        throw "backend started_processes.pid=$($started.pid) != identity_failures.pid=$($raw.pid)"
    }
    if ($raw.cleanup_status -ne "not_attempted_identity_unverified") {
        throw "backend identity_failures cleanup_status=$($raw.cleanup_status)"
    }
    if ($started.cleanup_status -ne "not_attempted_identity_unverified") {
        throw "backend started_processes cleanup_status=$($started.cleanup_status)"
    }
    if ([string]::IsNullOrWhiteSpace([string]$raw.stage) -or
        [string]::IsNullOrWhiteSpace([string]$started.stage)) {
        throw "backend stage is empty"
    }
    if ([string]::IsNullOrWhiteSpace([string]$raw.failure_reason) -or
        [string]::IsNullOrWhiteSpace([string]$started.failure_reason)) {
        throw "backend failure_reason is empty"
    }
    if ($raw.identity_state -ne "UNKNOWN" -or $started.identity_state -ne "UNKNOWN") {
        throw "backend identity_state raw=$($raw.identity_state) started=$($started.identity_state)"
    }
    if ($raw.manual_required -ne $true -or $started.manual_required -ne $true) {
        throw "backend manual_required not true"
    }
    if (-not $raw.alive_before_cleanup -or -not $started.alive_before_cleanup) {
        throw "backend was not alive before cleanup"
    }
    if ($case.failure.records.backend) { throw "a fake backend record was produced" }
    if (-not (Get-Process -Id ([int]$raw.pid) -ErrorAction SilentlyContinue)) {
        throw "unverified backend process was killed"
    }
    if (-not (Get-Process -Id $sentinel.Id -ErrorAction SilentlyContinue)) {
        throw "unverified backend cleanup killed sentinel"
    }
    try { Stop-Process -Id ([int]$raw.pid) -Force -ErrorAction SilentlyContinue } catch { }
    Start-Sleep -Milliseconds 300
    $notes += "PASS backend identity generation failure retained PID/manual/no kill"
    $notes += "PASS start-failure.json kept raw PID $($raw.pid)"

    # 2. Frontend identity generation failed: backend record is cleaned; the
    # frontend must remain alive and be marked manual.
    $case = Invoke-Case -Name "frontend-identity-unrecoverable" -Flags @{
        CTF_P1_TEST_MODE = "1"; CTF_P1_TEST_FAIL_FRONTEND_IDENTITY = "1"
    }
    $frontRaw = @($case.failure.identity_failures | Where-Object { $_.kind -eq "frontend" }) | Select-Object -First 1
    $frontStarted = @($case.failure.started_processes | Where-Object { $_.kind -eq "frontend" }) | Select-Object -First 1
    if (-not $frontRaw -or -not $frontStarted) { throw "frontend identity failure not recorded" }
    if ($frontRaw.pid -notmatch '^\d+$' -or $frontStarted.pid -notmatch '^\d+$') {
        throw "frontend PID missing"
    }
    if ([int]$frontRaw.pid -ne [int]$frontStarted.pid) {
        throw "frontend started_processes.pid=$($frontStarted.pid) != identity_failures.pid=$($frontRaw.pid)"
    }
    if ($frontRaw.cleanup_status -ne "not_attempted_identity_unverified") {
        throw "frontend identity_failures cleanup_status=$($frontRaw.cleanup_status)"
    }
    if ($frontStarted.cleanup_status -ne "not_attempted_identity_unverified") {
        throw "frontend started_processes cleanup_status=$($frontStarted.cleanup_status)"
    }
    if ([string]::IsNullOrWhiteSpace([string]$frontRaw.stage) -or
        [string]::IsNullOrWhiteSpace([string]$frontStarted.stage)) {
        throw "frontend stage is empty"
    }
    if ([string]::IsNullOrWhiteSpace([string]$frontRaw.failure_reason) -or
        [string]::IsNullOrWhiteSpace([string]$frontStarted.failure_reason)) {
        throw "frontend failure_reason is empty"
    }
    if ($frontRaw.identity_state -ne "UNKNOWN" -or $frontStarted.identity_state -ne "UNKNOWN") {
        throw "frontend identity_state raw=$($frontRaw.identity_state) started=$($frontStarted.identity_state)"
    }
    if ($frontRaw.manual_required -ne $true -or $frontStarted.manual_required -ne $true) {
        throw "frontend manual_required not true"
    }
    if (-not $frontRaw.alive_before_cleanup -or -not $frontStarted.alive_before_cleanup) {
        throw "frontend was not alive before cleanup"
    }
    # Do not rely only on the historical alive_before_cleanup field: obtain the
    # actual current process from the PID recorded by the failed start.
    $frontProcess = Get-Process -Id ([int]$frontRaw.pid) -ErrorAction SilentlyContinue
    if ($null -eq $frontProcess) {
        throw "frontend raw PID $($frontRaw.pid) has no current process"
    }
    try {
        if ($frontProcess.HasExited) {
            throw "frontend raw PID $($frontRaw.pid) process has exited"
        }
    } finally {
        $frontProcess.Dispose()
    }
    $notes += "PASS frontend raw PID $($frontRaw.pid) references a live process"
    if ($case.failure.records.frontend) { throw "a fake frontend record was produced" }
    if ($case.failure.cleanup.backend.status -notin @("stopped", "missing")) {
        throw "verified backend was not cleaned after frontend identity failure"
    }
    if (-not (Get-Process -Id ([int]$frontRaw.pid) -ErrorAction SilentlyContinue)) {
        throw "unverified frontend process was killed"
    }
    try { Stop-Process -Id ([int]$frontRaw.pid) -Force -ErrorAction SilentlyContinue } catch { }
    Start-Sleep -Milliseconds 300
    if (-not (Get-Process -Id $sentinel.Id -ErrorAction SilentlyContinue)) {
        throw "frontend failure cleanup killed sentinel"
    }
    $notes += "PASS frontend failure did not kill sentinel"
    $notes += "PASS frontend identity generation failure retained live PID/manual/no kill"

    # 3. Identity becomes readable on retry: safe verified cleanup is allowed.
    $case = Invoke-Case -Name "identity-recovered" -Flags @{
        CTF_P1_TEST_MODE = "1"; CTF_P1_TEST_FAIL_BACKEND_IDENTITY = "1"; CTF_P1_TEST_IDENTITY_RECOVER = "1"
    }
    $raw = @($case.failure.identity_failures | Where-Object { $_.kind -eq "backend" }) | Select-Object -First 1
    if (-not $raw) { throw "recovered identity failure not recorded" }
    if ($raw.recovered -ne $true) { throw "identity recovered flag is not true" }
    if ($raw.cleanup_status -notin @("stopped", "missing")) {
        throw "recovered identity cleanup=$($raw.cleanup_status)"
    }
    if ($raw.manual_required -ne $false) { throw "recovered identity manual_required is not false" }
    if ($case.failure.cleanup.backend.status -notin @("stopped", "missing")) {
        throw "recovered backend cleanup not safe"
    }
    Start-Sleep -Milliseconds 300
    if (Get-NetTCPConnection -LocalPort $BackendPort, $FrontendPort -State Listen -ErrorAction SilentlyContinue) {
        throw "recovered identity case left a listener"
    }
    $notes += "PASS recovered identity allowed verified cleanup and released ports"

    # 4. Normal start/stop still works.
    Restore-Flags
    $normalRoot = Join-Path $temp "normal"
    $normalRun = Join-Path $normalRoot "run"
    $normalData = Join-Path $normalRoot "data"
    New-Item -ItemType Directory -Force -Path $normalRoot | Out-Null
    $normal = Start-Process -FilePath (Get-Command powershell).Source `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $start,
            "-BackendPort", "$BackendPort", "-FrontendPort", "$FrontendPort",
            "-DataDir", $normalData, "-RunDir", $normalRun) `
        -PassThru -WindowStyle Hidden
    $ready = $false
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-Path (Join-Path $normalRun "run-info.json")) { $ready = $true; break }
        if ($normal.HasExited) { break }
    }
    if (-not $ready) { throw "normal start did not write run-info" }
    $stopped = Start-Process -FilePath (Get-Command powershell).Source `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $stop, "-RunDir", $normalRun) `
        -PassThru -WindowStyle Hidden
    if (-not $stopped.WaitForExit(30000)) { throw "normal stop did not exit" }
    if ($stopped.ExitCode -ne 0) { throw "normal stop failed" }
    if (Get-NetTCPConnection -LocalPort $BackendPort, $FrontendPort -State Listen -ErrorAction SilentlyContinue) {
        throw "normal stop left a listener"
    }
    $notes += "PASS normal start/stop unaffected"
} catch {
    $failures += "unexpected exception: $($_.Exception.Message)"
} finally {
    Restore-Flags
    if ($sentinel) { try { Stop-Process -Id $sentinel.Id -Force -ErrorAction SilentlyContinue } catch { } }
    $notes | ForEach-Object { Write-Host $_ }
    if ($failures.Count -gt 0) {
        $failures | ForEach-Object { Write-Host "FAIL $_" }
        Write-Host "R5 IDENTITY TESTS FAILED"
        exit 1
    }
    Write-Host "R5 IDENTITY TESTS PASSED"
    Write-Host "EVIDENCE_ROOT $temp"
    exit 0
}
