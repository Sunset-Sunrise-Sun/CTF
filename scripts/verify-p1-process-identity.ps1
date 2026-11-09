$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "p1-common.ps1")
$normal = Get-P1ProcessInfo -ProcessId $PID
if ($normal.state -ne "NORMAL") { throw "live process was not NORMAL" }
Write-Host "PASS live process NORMAL"

$missing = Get-P1ProcessInfo -ProcessId 999999
if ($missing.state -ne "MISSING" -or $missing.exists -ne $false) {
    throw "nonexistent process was not MISSING"
}
Write-Host "PASS nonexistent process MISSING"

$record = [pscustomobject]@{
    backend_pid = $PID; backend_port = 0
    backend_executable = $normal.executable
    backend_command_line = $normal.command_line
    backend_start_time = $normal.start_time
    backend_identity_tokens = @("verify-p1-process-identity")
}
function Get-CimInstance { throw [System.UnauthorizedAccessException]::new("synthetic access denied") }
try {
    $unknown = Get-P1ProcessInfo -ProcessId $PID
    if ($unknown.state -ne "UNKNOWN") { throw "CIM permission error was not UNKNOWN" }
    $identity = Test-P1ProcessIdentity -Record $record -Kind "backend"
    if ($identity.status -ne "unknown") { throw "identity check accepted unknown process" }
    $cleanup = Stop-P1ProcessByVerifiedHandle -Record $record -Kind "backend"
    if ($cleanup.status -ne "unknown") { throw "cleanup accepted unknown process" }
    Write-Host "PASS CIM permission failure UNKNOWN and stop refused"
} finally {
    Remove-Item Function:\Get-CimInstance
}
if (-not (Get-Process -Id $PID -ErrorAction SilentlyContinue)) { throw "test process was stopped" }
$originalInfoFunction = (Get-Command Get-P1ProcessInfo).ScriptBlock
function Get-P1ProcessInfo { return $script:normal }
function Get-Process { throw [System.UnauthorizedAccessException]::new("synthetic handle access denied") }
try {
    $handleDenied = Stop-P1ProcessByVerifiedHandle -Record $record -Kind "backend"
    if ($handleDenied.status -ne "unknown") { throw "handle access denial was not UNKNOWN" }
    Write-Host "PASS handle access denied UNKNOWN and stop refused"
} finally {
    Remove-Item Function:\Get-Process
    Set-Item Function:\Get-P1ProcessInfo $originalInfoFunction
}
function Get-Process { throw [System.UnauthorizedAccessException]::new("synthetic process access denied") }
try {
    $denied = Get-P1ProcessInfo -ProcessId $PID
    if ($denied.state -ne "UNKNOWN") { throw "process access denial was not UNKNOWN" }
    Write-Host "PASS process access denied UNKNOWN"
} finally {
    Remove-Item Function:\Get-Process
}
function Get-CimInstance { return $null }
try {
    $cimMissing = Get-P1ProcessInfo -ProcessId $PID
    if ($cimMissing.state -ne "UNKNOWN") { throw "live process with no CIM identity was not UNKNOWN" }
    Write-Host "PASS live process without CIM identity UNKNOWN"
} finally {
    Remove-Item Function:\Get-CimInstance
}
function Get-CimInstance { return [pscustomobject]@{ Name = "synthetic"; ExecutablePath = $null; CommandLine = $null } }
try {
    $incomplete = Get-P1ProcessInfo -ProcessId $PID
    if ($incomplete.state -ne "UNKNOWN") { throw "incomplete identity was not UNKNOWN" }
    Write-Host "PASS incomplete identity UNKNOWN"
} finally {
    Remove-Item Function:\Get-CimInstance
}
Write-Host "PROCESS IDENTITY TESTS PASSED"
