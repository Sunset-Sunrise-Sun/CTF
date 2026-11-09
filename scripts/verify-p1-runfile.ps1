param(
    [int]$BackendPort = 18189,
    [int]$FrontendPort = 15189
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "p1-common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$temp = Join-Path $env:TEMP ("p1-runfile-" + [guid]::NewGuid().ToString("N"))
$run = Join-Path $temp "run"
$logs = Join-Path $run "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$failures = @()
$notes = @()
$links = @()
$critical = @(
    "backend.pid", "frontend.pid", "run-info.json", "start-failure.json",
    "stop-result.json", "backend.stdout.log", "backend.stderr.log",
    "frontend.stdout.log", "frontend.stderr.log"
)
function Assert-Throws {
    param([scriptblock]$Block, [string]$Name)
    try {
        & $Block
        $script:failures += "$Name did not throw"
    } catch {
        $script:notes += "PASS reject: $Name"
    }
}
function New-FileJunction {
    param([string]$Path, [string]$Target)
    New-Item -ItemType Junction -Path $Path -Target $Target | Out-Null
    $script:links += $Path
}
try {
    foreach ($name in $critical) {
        $path = if ($name -like "*.log") { Join-Path $logs $name } else { Join-Path $run $name }
        $result = Assert-P1SafeRunFile -Path $path
        if ($result.exists) { throw "missing file was reported as existing: $path" }
        Set-Content -LiteralPath $path -Value "ordinary"
        $result = Assert-P1SafeRunFile -Path $path
        if (-not $result.exists) { throw "ordinary file was not accepted: $path" }
    }
    $notes += "PASS accept: missing files and ordinary files for all 9 RunDir files"

    $directoryAsFile = Join-Path $run "backend.pid"
    Remove-Item -LiteralPath $directoryAsFile -Force
    New-Item -ItemType Directory -Path $directoryAsFile | Out-Null
    Assert-Throws { Assert-P1SafeRunFile -Path $directoryAsFile } "ordinary directory at file path"
    Remove-Item -LiteralPath $directoryAsFile -Force
    Set-Content -LiteralPath $directoryAsFile -Value "ordinary"
    $notes += "PASS reject: unexpected directory type at critical file path"

    $target = Join-Path $temp "target"
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    foreach ($name in $critical) {
        $path = if ($name -like "*.log") { Join-Path $logs $name } else { Join-Path $run $name }
        Remove-Item -LiteralPath $path -Force
        New-FileJunction -Path $path -Target $target
        Assert-Throws { Assert-P1SafeRunFile -Path $path } "$name leaf Junction/reparse"
        & cmd /c rmdir "$path" 2>$null | Out-Null
        $links = @($links | Where-Object { $_ -ne $path })
    }
    $notes += "PASS reject: pre-existing Junction at every critical file path"

    # A pre-existing reparse at backend.pid must stop start before spawning.
    $badRun = Join-Path $temp "bad-run"
    New-Item -ItemType Directory -Force -Path (Join-Path $badRun "logs") | Out-Null
    New-FileJunction -Path (Join-Path $badRun "backend.pid") -Target $target
    $start = Join-Path $PSScriptRoot "p1-start.ps1"
    $out = Join-Path $temp "bad-start.stdout.log"
    $err = Join-Path $temp "bad-start.stderr.log"
    $child = Start-Process -FilePath (Get-Command powershell).Source `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $start,
            "-RunDir", $badRun, "-DataDir", (Join-Path $temp "bad-data"),
            "-BackendPort", "$BackendPort", "-FrontendPort", "$FrontendPort") `
        -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -Wait -WindowStyle Hidden
    if ($child.ExitCode -eq 0) { $failures += "start accepted a RunDir file reparse point" }
    if (Get-NetTCPConnection -LocalPort $BackendPort, $FrontendPort -State Listen -ErrorAction SilentlyContinue) {
        $failures += "start with reparse PID left a listener"
    }
    if (@(Get-ChildItem -LiteralPath $target -Force).Count -ne 0) {
        $failures += "start wrote through a RunDir file reparse point"
    }
    if ($child.ExitCode -ne 0) { $notes += "PASS start refuses pre-existing file reparse before spawning" }
} catch {
    $failures += "unexpected exception: $($_.Exception.Message)"
} finally {
    foreach ($link in $links) {
        if (Test-Path -LiteralPath $link) {
            & cmd /c rmdir "$link" 2>$null | Out-Null
        }
    }
    if (Test-Path -LiteralPath $temp) {
        Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
    $notes | ForEach-Object { Write-Host $_ }
    if ($failures.Count -gt 0) {
        $failures | ForEach-Object { Write-Host "FAIL $_" }
        Write-Host "RUNFILE TESTS FAILED"
        exit 1
    }
    Write-Host "RUNFILE TESTS PASSED"
    exit 0
}
