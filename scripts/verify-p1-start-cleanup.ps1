param(
    [int]$BackendPort = 18112,
    [int]$FrontendPort = 15192
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "p1-common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $PSScriptRoot "p1-start.ps1"
$temp = Join-Path $env:TEMP ("p1-start-cleanup-" + [guid]::NewGuid().ToString("N"))
$runDir = Join-Path $temp "run"
$dataDir = Join-Path $temp "data"
New-Item -ItemType Directory -Force -Path $temp, $runDir, $dataDir | Out-Null
$failures = @()
$notes = @()
$child = $null
$dummy = $null
$dummy2 = $null
try {
    if (Get-NetTCPConnection -LocalPort $BackendPort, $FrontendPort -State Listen -ErrorAction SilentlyContinue) {
        throw "Test ports are already in use"
    }
    $arguments = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $startScript,
        "-BackendPort", "$BackendPort", "-FrontendPort", "$FrontendPort",
        "-DataDir", $dataDir, "-RunDir", $runDir
    )
    $child = Start-Process -FilePath (Get-Command powershell).Source `
        -ArgumentList $arguments -PassThru -WindowStyle Hidden
    $backendPidPath = Join-Path $runDir "backend.pid"
    for ($i = 0; $i -lt 200; $i++) {
        Start-Sleep -Milliseconds 50
        if (Test-Path $backendPidPath) { break }
        if ($child.HasExited) { break }
    }
    if (-not (Test-Path $backendPidPath)) {
        throw "Start script did not write backend.pid"
    }
    $backendPid = [int](Get-Content $backendPidPath -Raw)
    # Deliberately make the backend fail before it can become healthy.  The
    # start script's unified cleanup must then be used.
    Stop-Process -Id $backendPid -Force -ErrorAction SilentlyContinue
    if (-not $child.WaitForExit(30000)) {
        $failures += "start script did not exit after backend failure"
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "p1-stop.ps1") -RunDir $runDir 2>&1 | Out-Null
    }
    $failurePath = Join-Path $runDir "start-failure.json"
    if (-not (Test-Path $failurePath)) {
        $failures += "start-failure.json was not written"
    } else {
        $failure = Get-Content $failurePath -Raw | ConvertFrom-Json
        $notes += "PASS backend startup failure recorded component=$($failure.component)"
        $cleanup = $failure.cleanup.backend
        if (-not $cleanup) {
            $failures += "start-failure.json has no backend cleanup result"
        } elseif ($cleanup.status -notin @("stopped", "missing")) {
            $failures += "startup cleanup status was $($cleanup.status)"
        } else {
            $notes += "PASS unified startup cleanup status=$($cleanup.status)"
        }
    }
    Start-Sleep -Milliseconds 500
    if (Get-NetTCPConnection -LocalPort $BackendPort, $FrontendPort -State Listen -ErrorAction SilentlyContinue) {
        $failures += "startup failure left a listener on a test port"
    } else {
        $notes += "PASS startup failure left no listeners"
    }

    # Frontend cleanup uses the same verified-handle helper.  Exercise it with
    # a real dummy listener on a third port.
    $dummyPort = 18193
    if (Get-NetTCPConnection -LocalPort $dummyPort -State Listen -ErrorAction SilentlyContinue) {
        throw "Dummy cleanup port is already in use"
    }
    $dummy = Start-Process -FilePath (Get-Command python).Source `
        -ArgumentList @("-m", "http.server", "$dummyPort", "--bind", "127.0.0.1") `
        -PassThru -WindowStyle Hidden
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        if (Test-P1PortOwnedBy -Port $dummyPort -ProcessId $dummy.Id) { $ready = $true; break }
    }
    if (-not $ready) { throw "Dummy listener did not start" }
    $info = Get-P1ProcessInfo -ProcessId $dummy.Id
    $record = [pscustomobject]@{
        frontend_pid = $dummy.Id; frontend_port = $dummyPort
        frontend_executable = $info.executable; frontend_command_line = $info.command_line
        frontend_start_time = $info.start_time
        frontend_identity_tokens = @("http.server", "$dummyPort")
    }
    $cleanupDummy = Stop-P1ProcessByVerifiedHandle -Record $record -Kind "frontend"
    if ($cleanupDummy.status -ne "stopped") {
        $failures += "frontend verified-handle cleanup status=$($cleanupDummy.status)"
    } elseif (Test-P1PortOwnedBy -Port $dummyPort -ProcessId $dummy.Id) {
        $failures += "frontend dummy listener still owns the port"
    } else {
        $notes += "PASS frontend cleanup via verified handle"
    }

    # A cleanup identity mismatch must not kill the process and must retain its
    # process information in the returned, persisted failure record.
    $mismatchPort = 18194
    if (Get-NetTCPConnection -LocalPort $mismatchPort -State Listen -ErrorAction SilentlyContinue) {
        throw "Mismatch cleanup port is already in use"
    }
    $dummy2 = Start-Process -FilePath (Get-Command python).Source `
        -ArgumentList @("-m", "http.server", "$mismatchPort", "--bind", "127.0.0.1") `
        -PassThru -WindowStyle Hidden
    $ready2 = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        if (Test-P1PortOwnedBy -Port $mismatchPort -ProcessId $dummy2.Id) { $ready2 = $true; break }
    }
    if (-not $ready2) { throw "Mismatch dummy listener did not start" }
    $info2 = Get-P1ProcessInfo -ProcessId $dummy2.Id
    $record2 = [pscustomobject]@{
        frontend_pid = $dummy2.Id; frontend_port = $mismatchPort
        frontend_executable = $info2.executable; frontend_command_line = $info2.command_line
        frontend_start_time = $info2.start_time
        frontend_identity_tokens = @("http.server", "definitely-not-in-this-command")
    }
    $cleanupMismatch = Stop-P1ProcessByVerifiedHandle -Record $record2 -Kind "frontend"
    if ($cleanupMismatch.status -ne "mismatch") {
        $failures += "cleanup mismatch status=$($cleanupMismatch.status) (expected mismatch)"
    } elseif (-not (Get-Process -Id $dummy2.Id -ErrorAction SilentlyContinue)) {
        $failures += "cleanup mismatch killed the process"
    } elseif (-not $cleanupMismatch.process -or -not $cleanupMismatch.process.exists) {
        $failures += "cleanup mismatch did not retain process information"
    } else {
        $notes += "PASS cleanup mismatch refused kill and retained process info"
    }
} catch {
    $failures += "unexpected exception: $($_.Exception.Message)"
} finally {
    if ($dummy) {
        try { Stop-Process -Id $dummy.Id -Force -ErrorAction SilentlyContinue } catch { }
    }
    if ($dummy2) {
        try { Stop-Process -Id $dummy2.Id -Force -ErrorAction SilentlyContinue } catch { }
    }
    if ($child -and -not $child.HasExited) {
        try { & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "p1-stop.ps1") -RunDir $runDir 2>&1 | Out-Null } catch { }
        try { $child.Kill(); $child.WaitForExit(5000) } catch { }
    }
    $notes | ForEach-Object { Write-Host $_ }
    if ($failures.Count -gt 0) {
        $failures | ForEach-Object { Write-Host "FAIL $_" }
        Write-Host "START CLEANUP TESTS FAILED"
        exit 1
    }
    Write-Host "START CLEANUP TESTS PASSED"
    exit 0
}
