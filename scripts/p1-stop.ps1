param(
    [string]$RunDir = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "p1-common.ps1")
$root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($RunDir)) {
    $RunDir = Join-Path $root ".local-run"
}
$RunDir = Assert-P1SafeRunDir -RunDir $RunDir
$infoPath = Join-Path $RunDir "run-info.json"
$null = Assert-P1SafeRunFile -Path $infoPath
if (-not (Test-Path -LiteralPath $infoPath)) {
    Write-Host "No P1 run record at $infoPath; nothing to stop."
    exit 0
}
$info = Get-Content -LiteralPath $infoPath -Raw | ConvertFrom-Json

# First identity pass: validate every recorded process before touching any of
# them.  A PID may have been recycled by another program; executable, exact
# command line, start time, identity tokens and listening port must all match.
$checks = [ordered]@{}
foreach ($kind in @("backend", "frontend")) {
    $checks[$kind] = Test-P1ProcessIdentity -Record $info -Kind $kind
}
$mismatches = @()
foreach ($kind in $checks.Keys) {
    if ($checks[$kind].status -in @("mismatch", "unknown")) {
        $mismatches += "${kind}: " + ($checks[$kind].reasons -join "; ")
    }
}
if ($mismatches.Count -gt 0) {
    $result = [ordered]@{
        stopped_at = (Get-Date).ToUniversalTime().ToString("o")
        status     = "refused"
        reason     = "process identity mismatch or unknown; no process was stopped"
        checks     = $checks
        mismatches = $mismatches
    }
    Write-P1SafeJsonFile -Path (Join-Path $RunDir "stop-result.json") -Value $result
    Write-Host "REFUSED to stop P1 run: process identity mismatch"
    $mismatches | ForEach-Object { Write-Host "  $_" }
    exit 2
}

# Second identity pass, then acquire the actual process handles.  Killing a
# verified Process object avoids a separate PID-only taskkill race.
$preflight = [ordered]@{}
$handles = @{}
foreach ($kind in @("backend", "frontend")) {
    if ($checks[$kind].status -eq "missing") { continue }
    $preflight[$kind] = Test-P1ProcessIdentity -Record $info -Kind $kind
    if ($preflight[$kind].status -ne "ok") {
        $preflightMismatch = @("${kind}: " + ($preflight[$kind].reasons -join "; "))
        $result = [ordered]@{
            stopped_at = (Get-Date).ToUniversalTime().ToString("o")
            status     = "refused"
            reason     = "identity changed between first and second check; no process was stopped"
            checks     = $checks
            preflight  = $preflight
            mismatches = $preflightMismatch
        }
        Write-P1SafeJsonFile -Path (Join-Path $RunDir "stop-result.json") -Value $result
        Write-Host "REFUSED to stop P1 run: identity changed before termination"
        $preflightMismatch | ForEach-Object { Write-Host "  $_" }
        exit 2
    }
    $processId = if ($kind -eq "backend") { [int]$info.backend_pid } else { [int]$info.frontend_pid }
    try {
        $process = Get-Process -Id $processId -ErrorAction Stop
    } catch {
        $recheck = Get-P1ProcessInfo -ProcessId $processId
        if ($recheck.state -ne "MISSING") {
            Write-Host "REFUSED to stop P1 run: process identity became unknown"
            exit 2
        }
        $process = $null
    }
    if ($null -eq $process) {
        $checks[$kind] = [pscustomobject]@{ status = "missing"; reasons = @("process exited before termination") }
        continue
    }
    $handles[$kind] = $process
}

$stopped = @()
$alreadyStopped = @()
$failures = @()
foreach ($kind in @("backend", "frontend")) {
    if ($checks[$kind].status -eq "missing") {
        $alreadyStopped += $kind
        continue
    }
    if (-not $handles.ContainsKey($kind)) {
        $alreadyStopped += $kind
        continue
    }
    $process = $handles[$kind]
    try {
        if ($process.HasExited) {
            $alreadyStopped += $kind
            continue
        }
        # Re-check the handle identity immediately before termination.  A
        # recycled PID cannot reach a live handle for the old process.
        $recordedStart = if ($kind -eq "backend") { $info.backend_start_time } else { $info.frontend_start_time }
        if (-not $recordedStart) { throw "no recorded start time for $kind" }
        $actualStart = $process.StartTime.ToUniversalTime()
        $expectedStart = [datetime]::Parse([string]$recordedStart).ToUniversalTime()
        if ([math]::Abs(($actualStart - $expectedStart).TotalSeconds) -gt 2) {
            throw "process handle start time changed for $kind"
        }
        $process.Kill()
        if (-not $process.WaitForExit(5000)) {
            throw "process $($process.Id) ($kind) did not exit within 5s"
        }
        $stopped += $kind
    } catch {
        $failures += "${kind}: $($_.Exception.Message)"
    } finally {
        try { $process.Dispose() } catch { }
    }
}

$stoppedAt = (Get-Date).ToUniversalTime().ToString("o")
$info | Add-Member -NotePropertyName stopped_at -NotePropertyValue $stoppedAt -Force
$info | Add-Member -NotePropertyName stop_mode -NotePropertyValue "identity-verified Process.Kill handles" -Force
$info | Add-Member -NotePropertyName stop_checks -NotePropertyValue $checks -Force
$info | Add-Member -NotePropertyName stop_preflight -NotePropertyValue $preflight -Force
Write-P1SafeJsonFile -Path (Join-Path $RunDir "run-info.json") -Value $info
$stopResult = [ordered]@{
    stopped_at      = $stoppedAt
    status          = if ($failures.Count -gt 0) { "partial_failure" } else { "stopped" }
    stopped         = $stopped
    already_stopped = $alreadyStopped
    failures        = $failures
    checks          = $checks
    preflight       = $preflight
}
Write-P1SafeJsonFile -Path (Join-Path $RunDir "stop-result.json") -Value $stopResult
if ($failures.Count -gt 0) {
    Write-Host "P1 stop had failures: $($failures -join '; ')"
    exit 1
}
Write-Host "Stopped P1 independent run at $stoppedAt"
if ($alreadyStopped.Count -gt 0) {
    Write-Host "Already stopped: $($alreadyStopped -join ', ')"
}
