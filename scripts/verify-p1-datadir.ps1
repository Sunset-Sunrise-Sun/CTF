param()

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "p1-common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$temp = Join-Path $env:TEMP ("p1-datadir-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $temp | Out-Null
$failures = @()
$notes = @()
$links = @()

function Assert-Throws {
    param([scriptblock]$Block, [string]$Name)
    try {
        & $Block
        $script:failures += "$Name did not throw"
    } catch {
        $script:notes += "PASS reject: $Name"
    }
}

function New-Junction {
    param([string]$Link, [string]$Target)
    New-Item -ItemType Junction -Path $Link -Target $Target | Out-Null
    $script:links += $Link
    return $Link
}

try {
    # Normal independent directory remains accepted.
    $normal = Join-Path $temp "normal"
    New-Item -ItemType Directory -Force -Path $normal | Out-Null
    $null = Assert-P1SafeDataDir -WorktreeRoot $root -DataDir $normal
    $notes += "PASS accept: normal independent directory"

    # Default .local-run\data remains accepted (including non-empty rerun data).
    $default = Join-Path $root ".local-run\data"
    $null = Assert-P1SafeDataDir -WorktreeRoot $root -DataDir $default
    $notes += "PASS accept: default .local-run\data"

    # DataDir itself is a junction.
    $targetA = Join-Path $temp "target-a"
    New-Item -ItemType Directory -Force -Path $targetA | Out-Null
    $linkA = New-Junction -Link (Join-Path $temp "link-a") -Target $targetA
    Assert-Throws { Assert-P1SafeDataDir -WorktreeRoot $root -DataDir $linkA } "DataDir itself is a junction"

    # Parent component is a junction.
    $targetB = Join-Path $temp "target-b"
    New-Item -ItemType Directory -Force -Path $targetB | Out-Null
    $linkB = New-Junction -Link (Join-Path $temp "link-b") -Target $targetB
    Assert-Throws {
        Assert-P1SafeDataDir -WorktreeRoot $root -DataDir (Join-Path $linkB "data")
    } "parent component is a junction"

    # Junction points at the original project data directory.
    $linkOld = New-Junction -Link (Join-Path $temp "link-old") -Target "D:\CTF\.local-data"
    Assert-Throws {
        Assert-P1SafeDataDir -WorktreeRoot $root -DataDir $linkOld
    } "junction points to original project data"

    # Permission failure during enumeration must fail closed.
    $denied = Join-Path $temp "denied"
    New-Item -ItemType Directory -Force -Path $denied | Out-Null
    Set-Content -Path (Join-Path $denied "x.txt") -Value "x"
    $user = $env:USERNAME
    & icacls $denied /deny "${user}:(OI)(CI)(RX,W)" | Out-Null
    try {
        Assert-Throws {
            Assert-P1SafeDataDir -WorktreeRoot $root -DataDir $denied
        } "permission denied while inspecting directory"
    } finally {
        & icacls $denied /remove:d $user | Out-Null
    }
} catch {
    $failures += "unexpected exception: $($_.Exception.Message)"
} finally {
    foreach ($link in $links) {
        if (Test-Path -LiteralPath $link) {
            # Remove only the junction link; never recurse through it.
            & cmd /c rmdir "$link" 2>$null | Out-Null
        }
    }
    $denied = Join-Path $temp "denied"
    if (Test-Path -LiteralPath $denied) {
        & icacls $denied /remove:d $env:USERNAME 2>$null | Out-Null
    }
    if (Test-Path -LiteralPath $temp) {
        Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
    $notes | ForEach-Object { Write-Host $_ }
    if ($failures.Count -gt 0) {
        $failures | ForEach-Object { Write-Host "FAIL $_" }
        Write-Host "DATADIR GUARD TESTS FAILED"
        exit 1
    }
    Write-Host "DATADIR GUARD TESTS PASSED"
    exit 0
}
