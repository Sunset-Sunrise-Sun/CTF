$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "p1-common.ps1")
$temp = Join-Path $env:TEMP ("p1-rundir-r3-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temp | Out-Null
$results = @()
$links = @()
try {
    $normal = Join-Path $temp "normal"
    if ((Assert-P1SafeRunDir -RunDir $normal) -ne $normal) { throw "normal RunDir changed" }
    $results += "PASS normal new RunDir"

    foreach ($kind in @("self", "parent")) {
        $target = Join-Path $temp ("target-" + $kind)
        New-Item -ItemType Directory -Path $target | Out-Null
        $link = Join-Path $temp ("junction-" + $kind)
        New-Item -ItemType Junction -Path $link -Target $target | Out-Null
        $links += $link
        $run = if ($kind -eq "self") { $link } else { Join-Path $link "run" }
        try {
            $null = Assert-P1SafeRunDir -RunDir $run
            throw "$kind Junction accepted by RunDir guard"
        } catch {
            if ($_.Exception.Message -notlike "*reparse point*") { throw }
        }
        $results += "PASS reject $kind Junction"

        $data = Join-Path $temp ("data-" + $kind)
        $start = Join-Path $PSScriptRoot "p1-start.ps1"
        $startOutput = Join-Path $temp ("start-" + $kind + ".stdout.log")
        $startError = Join-Path $temp ("start-" + $kind + ".stderr.log")
        $child = Start-Process -FilePath (Get-Command powershell).Source `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $start,
                "-RunDir", $run, "-DataDir", $data, "-BackendPort", "18184", "-FrontendPort", "15184") `
            -RedirectStandardOutput $startOutput -RedirectStandardError $startError `
            -PassThru -WindowStyle Hidden -Wait
        if ($child.ExitCode -eq 0) { throw "$kind Junction start unexpectedly succeeded" }
        if (@(Get-ChildItem -LiteralPath $target -Force).Count -ne 0) {
            throw "$kind Junction target received PID, log or run-info files"
        }
        $results += "PASS no writes through $kind Junction"
    }

    $swapped = Join-Path $temp "swapped"
    New-Item -ItemType Directory -Path $swapped | Out-Null
    $null = Assert-P1SafeRunDir -RunDir $swapped
    Remove-Item -LiteralPath $swapped
    $outside = Join-Path $temp "outside"
    New-Item -ItemType Directory -Path $outside | Out-Null
    New-Item -ItemType Junction -Path $swapped -Target $outside | Out-Null
    $links += $swapped
    try {
        $null = Assert-P1SafeRunDir -RunDir $swapped
        throw "post-create RunDir recheck accepted a Junction"
    } catch {
        if ($_.Exception.Message -notlike "*reparse point*") { throw }
    }
    $results += "PASS post-create recheck"
    $results | ForEach-Object { Write-Host $_ }
    Write-Host "RUNDIR TESTS PASSED"
    exit 0
} finally {
    foreach ($link in $links) {
        if (Test-Path -LiteralPath $link) { Remove-Item -LiteralPath $link -Force }
    }
    $expected = [System.IO.Path]::GetFullPath((Join-Path $env:TEMP (Split-Path -Leaf $temp)))
    if ($expected -ne [System.IO.Path]::GetFullPath($temp)) { throw "unsafe test cleanup path" }
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
