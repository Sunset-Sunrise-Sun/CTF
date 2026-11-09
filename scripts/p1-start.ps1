param(
    [int]$BackendPort = 18110,
    [int]$FrontendPort = 15190,
    [string]$DataDir = "",
    [string]$RunDir = "",
    [switch]$AllowNonEmptyDataDir
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "p1-common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
if ([string]::IsNullOrWhiteSpace($RunDir)) {
    $runDir = Join-Path $root ".local-run"
} else {
    $runDir = $RunDir
}
$runDir = Assert-P1SafeRunDir -RunDir $runDir
$logs = Join-Path $runDir "logs"
$tmp = Join-Path $runDir "tmp"
$backendOut = Join-Path $logs "backend.stdout.log"
$backendErr = Join-Path $logs "backend.stderr.log"
$frontendOut = Join-Path $logs "frontend.stdout.log"
$frontendErr = Join-Path $logs "frontend.stderr.log"
if ([string]::IsNullOrWhiteSpace($DataDir)) {
    $DataDir = Join-Path $runDir "data"
}
if (-not [System.IO.Path]::IsPathRooted($DataDir)) {
    throw "DataDir must be an absolute path"
}
$DataDir = Assert-P1SafeDataDir -WorktreeRoot $root -DataDir $DataDir -AllowNonEmpty:$AllowNonEmptyDataDir
foreach ($port in @($BackendPort, $FrontendPort)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use; refusing to touch an existing service"
    }
}
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
# Re-inspect before creating logs, PID files or moving a previous record.
$runDir = Assert-P1SafeRunDir -RunDir $runDir
New-Item -ItemType Directory -Force -Path $DataDir, $logs, $tmp | Out-Null
$null = Assert-P1SafeRunDir -RunDir $logs
$null = Assert-P1SafeRunDir -RunDir $tmp
$DataDir = Assert-P1SafeDataDir -WorktreeRoot $root -DataDir $DataDir -AllowNonEmpty:$AllowNonEmptyDataDir

$criticalRunFiles = @(
    (Join-Path $runDir "backend.pid"),
    (Join-Path $runDir "frontend.pid"),
    (Join-Path $runDir "run-info.json"),
    (Join-Path $runDir "start-failure.json"),
    (Join-Path $runDir "stop-result.json"),
    $backendOut, $backendErr, $frontendOut, $frontendErr
)
foreach ($path in $criticalRunFiles) {
    $null = Assert-P1SafeRunFile -Path $path
}

# Archive a previous run record only after the final RunDir/file re-checks, so
# a failed safety check cannot write history, logs, PID or run-info.
$infoPath = Join-Path $runDir "run-info.json"
if (Test-Path -LiteralPath $infoPath) {
    $null = Assert-P1SafeRunFile -Path $infoPath
    $previous = Get-Content -LiteralPath $infoPath -Raw | ConvertFrom-Json
    foreach ($existingPid in @($previous.backend_pid, $previous.frontend_pid)) {
        if (-not $existingPid) { continue }
        $existing = Get-P1ProcessInfo -ProcessId ([int]$existingPid)
        if ($existing.state -ne "MISSING") {
            throw "A P1 run may still be alive or its identity is unknown; run scripts\p1-stop.ps1 first"
        }
    }
    $history = Join-Path $runDir "run-history"
    New-Item -ItemType Directory -Force -Path $history | Out-Null
    $null = Assert-P1SafeRunDir -RunDir $history
    $historyFile = Join-Path $history ("run-info-" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ") + ".json")
    $null = Assert-P1SafeRunFile -Path $historyFile
    Move-Item -LiteralPath $infoPath -Destination $historyFile
}

$python = (Get-Command python).Source
$node = (Get-Command node).Source
$vite = Join-Path $frontend "node_modules\vite\bin\vite.js"
if (-not (Test-Path $vite)) {
    throw "Frontend dependencies are missing; run npm install in $frontend first"
}

function Test-P1TestFault {
    param([string]$Name)
    if ($env:CTF_P1_TEST_MODE -ne "1") { return $false }
    return [Environment]::GetEnvironmentVariable("CTF_P1_TEST_$Name") -eq "1"
}

function New-P1LauncherRecord {
    param(
        [Parameter(Mandatory = $true)][string]$Kind,
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string[]]$Tokens,
        [switch]$AllowIdentityRecovery
    )
    $info = Get-P1ProcessInfo -ProcessId $ProcessId
    for ($i = 0; $i -lt 20 -and (-not $info.exists -or -not $info.executable); $i++) {
        Start-Sleep -Milliseconds 50
        $info = Get-P1ProcessInfo -ProcessId $ProcessId
    }
    $faultName = "FAIL_{0}_IDENTITY" -f $Kind.ToUpperInvariant()
    $injected = (-not $AllowIdentityRecovery) -and (Test-P1TestFault $faultName)
    if ($injected -or $info.state -ne "NORMAL") {
        $reason = if ($injected) { "injected $Kind identity read failure" } else { [string]$info.reason }
        $alive = $false
        try {
            $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
            if ($proc) {
                $alive = -not $proc.HasExited
                $proc.Dispose()
            }
        } catch { }
        $raw = [pscustomobject]@{
            kind = $Kind
            pid = $ProcessId
            port = $Port
            stage = if (Get-Variable -Name stage -ErrorAction SilentlyContinue) { $stage } else { "" }
            identity_state = if ($injected) { "UNKNOWN" } else { [string]$info.state }
            failure_reason = $reason
            alive_before_cleanup = $alive
            cleanup_status = "not_attempted_identity_unverified"
            manual_required = $true
            recovered = $false
        }
        $errorRecord = [System.InvalidOperationException]::new("$Kind identity record could not be generated: $reason")
        $errorRecord.Data["P1RawIdentity"] = $raw
        throw $errorRecord
    }
    $record = @{}
    $record["${Kind}_pid"] = $ProcessId
    $record["${Kind}_port"] = $Port
    $record["${Kind}_executable"] = $info.executable
    $record["${Kind}_command_line"] = $info.command_line
    $record["${Kind}_start_time"] = $info.start_time
    $record["${Kind}_identity_tokens"] = $Tokens
    $record["${Kind}_identity_state"] = $info.state
    return [pscustomobject]$record
}

function Write-P1PidFile {
    param(
        [Parameter(Mandatory = $true)][string]$Kind,
        [Parameter(Mandatory = $true)][int]$ProcessId
    )
    $path = Join-Path $runDir "$Kind.pid"
    $null = Assert-P1SafeRunFile -Path $path
    if (Test-P1TestFault "FAIL_BACKEND_PID_WRITE" -and $Kind -eq "backend") {
        throw "injected backend PID write failure"
    }
    if (Test-P1TestFault "FAIL_FRONTEND_PID_WRITE" -and $Kind -eq "frontend") {
        throw "injected frontend PID write failure"
    }
    Write-P1SafeTextFile -Path $path -Content ([string]$ProcessId) -Encoding ascii
}

function Save-P1StartFailure {
    param(
        [string]$Component,
        $Records,
        $Cleanup,
        [bool]$ProcessAliveBeforeCleanup,
        [string]$ErrorMessage,
        [string]$Stage,
        [object[]]$StartedProcesses = @(),
        [object[]]$IdentityFailures = @()
    )
    $payload = [ordered]@{
        failed_at = (Get-Date).ToUniversalTime().ToString("o")
        component = $Component
        stage = $Stage
        error = $ErrorMessage
        records = $Records
        cleanup = $Cleanup
        started_processes = $StartedProcesses
        identity_failures = $IdentityFailures
        process_alive_before_cleanup = $ProcessAliveBeforeCleanup
        backend_stdout = $backendOut
        backend_stderr = $backendErr
        frontend_stdout = $frontendOut
        frontend_stderr = $frontendErr
    }
    Write-P1SafeJsonFile -Path (Join-Path $runDir "start-failure.json") -Value $payload
}

$env:CTF_DATA_DIR = $DataDir
$env:CTF_MODEL_NETWORK_ENABLED = "false"
$env:CTF_RUN_LIVE_MODEL = "0"
$env:PYTHONPATH = $backend
$env:TEMP = $tmp
$env:TMP = $tmp
$env:TMPDIR = $tmp

$started = [ordered]@{}
$records = [ordered]@{}
$stage = "backend_start"
try {
    $backendProcess = Start-Process -FilePath $python `
        -ArgumentList @("-B", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
        -WorkingDirectory $backend -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr `
        -PassThru -WindowStyle Hidden
    $started["backend"] = $backendProcess
    $backendRecord = New-P1LauncherRecord -Kind "backend" -ProcessId $backendProcess.Id `
        -Port $BackendPort -Tokens @("uvicorn", "app.main:app", "--port", "$BackendPort")
    $records["backend"] = $backendRecord
    Write-P1PidFile -Kind "backend" -ProcessId $backendProcess.Id
    if ($backendRecord.backend_identity_state -eq "UNKNOWN") {
        throw "backend identity could not be verified"
    }

    $health = "http://127.0.0.1:$BackendPort/api/health"
    $backendReady = $false
    $pollAttempts = if ($env:CTF_P1_TEST_MODE -eq "1") { 12 } else { 120 }
    for ($i = 0; $i -lt $pollAttempts; $i++) {
        Start-Sleep -Milliseconds 500
        if ($env:CTF_P1_TEST_MODE -ne "1" -or $env:CTF_P1_TEST_BACKEND_HEALTH_FAIL -ne "1") {
            try {
                $response = Invoke-RestMethod -Uri $health -TimeoutSec 2
                if ($response.status -eq "ok") { $backendReady = $true; break }
            } catch { }
        }
        if ($backendProcess.HasExited) { break }
    }
    if (-not $backendReady) {
        throw "backend did not become healthy at $health"
    }

    $stage = "frontend_start"
    $viteConfig = if ($env:CTF_P1_TEST_MODE -eq "1" -and $env:CTF_P1_TEST_FRONTEND_START_FAIL -eq "1") {
        "vite.p1-intentionally-missing.config.ts"
    } else { "vite.p1.config.ts" }
    $frontendProcess = Start-Process -FilePath $node `
        -ArgumentList @($vite, "--config", $viteConfig, "--host", "127.0.0.1", "--port", "$FrontendPort", "--strictPort") `
        -WorkingDirectory $frontend -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr `
        -PassThru -WindowStyle Hidden
    $started["frontend"] = $frontendProcess
    $frontendRecord = New-P1LauncherRecord -Kind "frontend" -ProcessId $frontendProcess.Id `
        -Port $FrontendPort -Tokens @($viteConfig, "--port", "$FrontendPort")
    $records["frontend"] = $frontendRecord
    Write-P1PidFile -Kind "frontend" -ProcessId $frontendProcess.Id
    if ($frontendRecord.frontend_identity_state -eq "UNKNOWN") {
        throw "frontend identity could not be verified"
    }

    $url = "http://127.0.0.1:$FrontendPort/"
    $frontendReady = $false
    for ($i = 0; $i -lt $pollAttempts; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $page = Invoke-WebRequest -Uri $url -TimeoutSec 2 -UseBasicParsing
            if ($page.StatusCode -eq 200) { $frontendReady = $true; break }
        } catch { }
        if ($frontendProcess.HasExited) { break }
    }
    if (-not $frontendReady) {
        throw "frontend did not become ready at $url"
    }

    $stage = "run_info"
    $info = [ordered]@{
        started_at     = (Get-Date).ToUniversalTime().ToString("o")
        worktree       = $root
        branch         = (git -C $root branch --show-current)
        head           = (git -C $root rev-parse HEAD)
        backend_port   = $BackendPort
        frontend_port  = $FrontendPort
        backend_pid    = $backendProcess.Id
        frontend_pid   = $frontendProcess.Id
        backend_executable = $backendRecord.backend_executable
        frontend_executable = $frontendRecord.frontend_executable
        backend_command_line = $backendRecord.backend_command_line
        frontend_command_line = $frontendRecord.frontend_command_line
        backend_start_time = $backendRecord.backend_start_time
        frontend_start_time = $frontendRecord.frontend_start_time
        backend_identity_tokens = $backendRecord.backend_identity_tokens
        frontend_identity_tokens = $frontendRecord.frontend_identity_tokens
        data_dir       = $DataDir
        backend_url    = "http://127.0.0.1:$BackendPort"
        frontend_url   = $url
        model_network  = "disabled"
        run_mode       = "synthetic/Mock only; no real DeepSeek request"
        backend_stdout = $backendOut
        backend_stderr = $backendErr
        frontend_stdout = $frontendOut
        frontend_stderr = $frontendErr
    }
    $info["lifecycle_stage"] = "complete"
    if (Test-P1TestFault "FAIL_RUN_INFO_WRITE") {
        throw "injected run-info write failure"
    }
    Write-P1SafeJsonFile -Path $infoPath -Value $info
} catch {
    $failure = $_
    $cleanup = [ordered]@{}
    $startedProcesses = @()
    $identityFailures = @()
    $aliveBefore = $false

    # Preserve the raw identity-failure details from the exception before any
    # recovery attempt.  This is the evidence that must survive even when no
    # verified identity record can be produced.
    $rawFailure = $null
    try {
        if ($failure.Exception.Data -and $failure.Exception.Data.Contains("P1RawIdentity")) {
            $rawFailure = $failure.Exception.Data["P1RawIdentity"]
            $identityFailures += $rawFailure
        }
    } catch { }

    foreach ($kind in @("backend", "frontend")) {
        $process = if ($started.Contains($kind)) { $started[$kind] } else { $null }
        $alive = $false
        if ($process) {
            try { $alive = -not $process.HasExited } catch { }
            if ($alive) { $aliveBefore = $true }
        }
        $rawForKind = @($identityFailures | Where-Object { $_.kind -eq $kind }) | Select-Object -First 1
        if ($process -and -not $records.Contains($kind)) {
            $recoveryAllowed = $true
            if ($rawForKind -and ([string]$rawForKind.failure_reason) -like "injected *") {
                $recoveryAllowed = Test-P1TestFault "IDENTITY_RECOVER"
            }
            if ($recoveryAllowed) {
                try {
                    $tokens = if ($kind -eq "backend") {
                        @("uvicorn", "app.main:app", "--port", "$BackendPort")
                    } elseif (Get-Variable -Name viteConfig -ErrorAction SilentlyContinue) {
                        @($viteConfig, "--port", "$FrontendPort")
                    } else {
                        @("vite.p1.config.ts", "--port", "$FrontendPort")
                    }
                    $kindPort = if ($kind -eq "backend") { $BackendPort } else { $FrontendPort }
                    $recovered = New-P1LauncherRecord -Kind $kind -ProcessId $process.Id `
                        -Port $kindPort -Tokens $tokens -AllowIdentityRecovery
                    if ($recovered."${kind}_identity_state" -eq "NORMAL") {
                        $records[$kind] = $recovered
                        if ($rawForKind) {
                            $rawForKind.recovered = $true
                            $rawForKind.identity_state = "NORMAL"
                            $rawForKind.manual_required = $false
                        }
                    }
                } catch {
                    if (-not $rawForKind) {
                        $rawForKind = [pscustomobject]@{
                            kind = $kind
                            pid = if ($process) { $process.Id } else { $null }
                            stage = $stage
                            identity_state = "UNKNOWN"
                            failure_reason = "identity record unavailable during cleanup"
                            alive_before_cleanup = $alive
                            cleanup_status = "not_attempted_identity_unverified"
                            manual_required = $true
                            recovered = $false
                        }
                        $identityFailures += $rawForKind
                    }
                }
            }
        }
        if ($records.Contains($kind)) {
            $record = $records[$kind]
            if (Test-P1TestFault "CLEANUP_IDENTITY_CHANGE" -and $kind -eq "backend") {
                $changed = $record.PSObject.Copy()
                $changed.backend_executable = [string]$record.backend_executable + ".changed"
                $record = $changed
            }
            $cleanup[$kind] = Stop-P1ProcessByVerifiedHandle -Record $record -Kind $kind
            if ($rawForKind) {
                $rawForKind.cleanup_status = $cleanup[$kind].status
                $rawForKind.manual_required = ($cleanup[$kind].status -notin @("stopped", "missing"))
            }
        }
        $startedProcesses += [pscustomobject]@{
            kind = $kind
            pid = if ($process) { $process.Id } else { $null }
            stage = $stage
            identity_state = if ($records.Contains($kind)) { $records[$kind]."${kind}_identity_state" } elseif ($rawForKind) { $rawForKind.identity_state } else { "UNKNOWN" }
            failure_reason = if ($rawForKind) { $rawForKind.failure_reason } elseif ($process) { "no started process identity failure recorded" } else { "process not started" }
            alive_before_cleanup = $alive
            cleanup_status = if ($cleanup.Contains($kind)) { $cleanup[$kind].status } elseif ($rawForKind) { $rawForKind.cleanup_status } else { "not_attempted" }
            manual_required = if ($cleanup.Contains($kind)) { $cleanup[$kind].status -notin @("stopped", "missing") } else { [bool]$alive }
        }
    }

    $component = if ($stage -like "backend*") { "backend" } elseif ($stage -like "frontend*") { "frontend" } else { "run_info" }
    try {
        Save-P1StartFailure -Component $component -Records $records -Cleanup $cleanup `
            -ProcessAliveBeforeCleanup $aliveBefore -ErrorMessage $failure.Exception.Message -Stage $stage `
            -StartedProcesses $startedProcesses -IdentityFailures $identityFailures
    } catch {
        Write-Host "WARNING: startup failure record could not be written: $($_.Exception.Message)"
    }
    throw $failure
}

Write-Host "P1 independent run started"
Write-Host "  Worktree: $root"
Write-Host "  Frontend: http://127.0.0.1:$FrontendPort/"
Write-Host "  Backend:  http://127.0.0.1:$BackendPort"
Write-Host "  Data dir: $DataDir"
Write-Host "  PIDs: backend=$($started['backend'].Id) frontend=$($started['frontend'].Id)"
Write-Host "  Stop with: powershell -File scripts\\p1-stop.ps1"
