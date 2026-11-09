param(
    [int]$DummyPortA = 18197,
    [int]$DummyPortB = 18198
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "p1-common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$stopScript = Join-Path $PSScriptRoot "p1-stop.ps1"
$temp = Join-Path $env:TEMP ("p1-guards-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $temp | Out-Null
$failures = @()
$notes = @()

function Assert-Throws {
    param([scriptblock]$Block, [string]$Name)
    try {
        & $Block
        $script:failures += "$Name did not throw"
    } catch {
        $script:notes += "PASS reject: $Name"
    }
}

function Write-RunInfo {
    param([string]$Dir, [System.Collections.IDictionary]$Data)
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    $Data | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $Dir "run-info.json") -Encoding utf8
}

function Start-Dummy {
    param([int]$Port)
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $Port is already in use"
    }
    $process = Start-Process -FilePath (Get-Command python).Source `
        -ArgumentList @("-m", "http.server", "$Port", "--bind", "127.0.0.1") `
        -PassThru -WindowStyle Hidden
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        if (Test-P1PortOwnedBy -Port $Port -ProcessId $process.Id) { return $process }
    }
    throw "Dummy server did not listen on $Port"
}

try {
    # 1. DataDir guards.
    Assert-Throws { Assert-P1SafeDataDir -WorktreeRoot $root -DataDir "D:\CTF\.local-data" } "original project data dir"
    Assert-Throws { Assert-P1SafeDataDir -WorktreeRoot $root -DataDir $root } "worktree source dir"
    $emptyCustom = Join-Path $temp "empty-custom"
    New-Item -ItemType Directory -Force -Path $emptyCustom | Out-Null
    $null = Assert-P1SafeDataDir -WorktreeRoot $root -DataDir $emptyCustom
    $nonEmpty = Join-Path $temp "nonempty-custom"
    New-Item -ItemType Directory -Force -Path $nonEmpty | Out-Null
    Set-Content -Path (Join-Path $nonEmpty "junk.txt") -Value "not a database"
    Assert-Throws { Assert-P1SafeDataDir -WorktreeRoot $root -DataDir $nonEmpty } "non-empty custom without flag"
    $null = Assert-P1SafeDataDir -WorktreeRoot $root -DataDir $nonEmpty -AllowNonEmpty
    $marked = Join-Path $temp "marked"
    New-Item -ItemType Directory -Force -Path $marked | Out-Null
    Set-Content -Path (Join-Path $marked "workbench.sqlite3") -Value "fake"
    Assert-Throws { Assert-P1SafeDataDir -WorktreeRoot $root -DataDir $marked -AllowNonEmpty } "directory with existing business database"
    $default = Join-Path $root ".local-run\data"
    $null = Assert-P1SafeDataDir -WorktreeRoot $root -DataDir $default
    $script:notes += "PASS accept: empty custom, default .local-run data"

    # 2. PID reuse / identity mismatch: a real process is recorded with a
    # command-line token that does not belong to it.  Stop must refuse and
    # leave the process untouched.
    $dummyA = Start-Dummy -Port $DummyPortA
    $infoA = Get-P1ProcessInfo -ProcessId $dummyA.Id
    $reusedDir = Join-Path $temp "reused"
    Write-RunInfo -Dir $reusedDir -Data ([ordered]@{
        backend_port = $DummyPortA; frontend_port = 0
        backend_pid = $dummyA.Id; frontend_pid = 0
        backend_executable = $infoA.executable; frontend_executable = $null
        backend_command_line = $infoA.command_line; frontend_command_line = $null
        backend_start_time = $infoA.start_time; frontend_start_time = $null
        backend_identity_tokens = @("http.server", "definitely-not-in-this-command")
        frontend_identity_tokens = @()
    })
    & powershell -NoProfile -ExecutionPolicy Bypass -File $stopScript -RunDir $reusedDir 2>&1 | Out-Null
    $refusedCode = $LASTEXITCODE
    if ($refusedCode -ne 2) { $script:failures += "PID reuse stop exit=$refusedCode (expected 2)" }
    if (-not (Get-Process -Id $dummyA.Id -ErrorAction SilentlyContinue)) {
        $script:failures += "PID reuse test killed the mismatched process"
    } else {
        $script:notes += "PASS refuse: PID reuse/identity mismatch left process alive"
    }
    Stop-Process -Id $dummyA.Id -Force -ErrorAction SilentlyContinue

    # 3. Process does not exist: stop is idempotent and does not kill a reused PID.
    $missingDir = Join-Path $temp "missing"
    Write-RunInfo -Dir $missingDir -Data ([ordered]@{
        backend_port = $DummyPortA; frontend_port = 0
        backend_pid = 999999; frontend_pid = 0
        backend_executable = "nonexistent.exe"; frontend_executable = $null
        backend_command_line = "nonexistent"; frontend_command_line = $null
        backend_start_time = $null; frontend_start_time = $null
        backend_identity_tokens = @("nonexistent"); frontend_identity_tokens = @()
    })
    & powershell -NoProfile -ExecutionPolicy Bypass -File $stopScript -RunDir $missingDir 2>&1 | Out-Null
    $missingCode = $LASTEXITCODE
    if ($missingCode -ne 0) { $script:failures += "missing process stop exit=$missingCode (expected 0)" }
    if (-not (Test-Path (Join-Path $missingDir "stop-result.json"))) {
        $script:failures += "missing process stop result not written"
    } else {
        $script:notes += "PASS missing: already stopped, no kill"
    }

    # 4. Normal stop: two real dummy listeners with matching identities are
    # stopped, and both ports become free.
    $dummyB = Start-Dummy -Port $DummyPortB
    $infoB = Get-P1ProcessInfo -ProcessId $dummyB.Id
    $normalDir = Join-Path $temp "normal"
    $dummyA2 = Start-Dummy -Port $DummyPortA
    $infoA2 = Get-P1ProcessInfo -ProcessId $dummyA2.Id
    Write-RunInfo -Dir $normalDir -Data ([ordered]@{
        backend_port = $DummyPortA; frontend_port = $DummyPortB
        backend_pid = $dummyA2.Id; frontend_pid = $dummyB.Id
        backend_executable = $infoA2.executable; frontend_executable = $infoB.executable
        backend_command_line = $infoA2.command_line; frontend_command_line = $infoB.command_line
        backend_start_time = $infoA2.start_time; frontend_start_time = $infoB.start_time
        backend_identity_tokens = @("http.server", "$DummyPortA")
        frontend_identity_tokens = @("http.server", "$DummyPortB")
    })
    & powershell -NoProfile -ExecutionPolicy Bypass -File $stopScript -RunDir $normalDir 2>&1 | Out-Null
    $normalCode = $LASTEXITCODE
    Start-Sleep -Milliseconds 500
    $aFree = -not (Test-P1PortOwnedBy -Port $DummyPortA -ProcessId $dummyA2.Id)
    $bFree = -not (Test-P1PortOwnedBy -Port $DummyPortB -ProcessId $dummyB.Id)
    if ($normalCode -ne 0) { $script:failures += "normal stop exit=$normalCode (expected 0)" }
    if (-not ($aFree -and $bFree)) { $script:failures += "normal stop left a listener running" }
    if ($normalCode -eq 0 -and $aFree -and $bFree) {
        $script:notes += "PASS normal stop: both listeners stopped"
    }
    Stop-Process -Id $dummyA2.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $dummyB.Id -Force -ErrorAction SilentlyContinue
} catch {
    $script:failures += "unexpected exception: $($_.Exception.Message)"
} finally {
    @($dummyA, $dummyB, $dummyA2) |
        Where-Object { $_ } |
        ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
    $notes | ForEach-Object { Write-Host $_ }
    if ($failures.Count -gt 0) {
        $failures | ForEach-Object { Write-Host "FAIL $_" }
        Write-Host "GUARD TESTS FAILED"
        exit 1
    }
    Write-Host "GUARD TESTS PASSED"
    exit 0
}
