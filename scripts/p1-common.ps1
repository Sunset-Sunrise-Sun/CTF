# Shared P1 launcher/stop helpers.  Dot-source from p1-start.ps1 / p1-stop.ps1.

function Get-P1FullPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "Path must not be empty"
    }
    if (-not [System.IO.Path]::IsPathRooted($Path)) {
        throw "Path must be absolute: $Path"
    }
    $full = [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $driveRoot = [System.IO.Path]::GetPathRoot($full).TrimEnd('\', '/')
    if ($full -eq $driveRoot) {
        throw "Refusing a drive root as a P1 data directory: $full"
    }
    return $full
}

function Test-P1PathWithin {
    param([string]$Child, [string]$Parent)
    $c = $Child.TrimEnd('\', '/')
    $p = $Parent.TrimEnd('\', '/')
    if ($c.Equals($p, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    return $c.StartsWith($p + '\', [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-P1NoReparseComponents {
    param([Parameter(Mandatory = $true)][string]$Path)
    # Inspect the original path components; do not Resolve-Path first, because
    # resolving a junction would lose the identity of the link itself.
    $full = Get-P1FullPath $Path
    $drive = [System.IO.Path]::GetPathRoot($full)
    if ([string]::IsNullOrWhiteSpace($drive)) {
        throw "Cannot determine the drive root for path: $full"
    }
    $components = @($drive.TrimEnd('\', '/'))
    $relative = $full.Substring($drive.Length).Trim('\', '/')
    if ($relative) {
        foreach ($part in ($relative -split '[\\/]+')) {
            if ($part) { $components += $part }
        }
    }
    $current = ""
    foreach ($part in $components) {
        if ($current -eq "") {
            $current = if ($part -match '^[A-Za-z]:$') { $part + '\' } else { $part }
        } else {
            $current = [System.IO.Path]::Combine($current, $part)
        }
        try {
            $attributes = [System.IO.File]::GetAttributes($current)
        } catch [System.IO.FileNotFoundException] {
            break
        } catch [System.IO.DirectoryNotFoundException] {
            break
        } catch {
            throw "Cannot inspect path component (fail closed): $current"
        }
        if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing reparse point (junction/symlink) in data path: $current"
        }
        if (($attributes -band [System.IO.FileAttributes]::Directory) -eq 0) {
            throw "Path component is not a directory: $current"
        }
    }
    return $full
}

function Assert-P1SafeRunDir {
    param([Parameter(Mandatory = $true)][string]$RunDir)
    if (-not [System.IO.Path]::IsPathRooted($RunDir) -or
        ($RunDir -split '[\\/]+' -contains '..')) {
        throw "RunDir must be an absolute path without parent traversal"
    }
    return Assert-P1NoReparseComponents -Path $RunDir
}

function Assert-P1SafeRunFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    $full = Get-P1FullPath $Path
    try {
        $attributes = [System.IO.File]::GetAttributes($full)
    } catch [System.IO.FileNotFoundException] {
        return [pscustomobject]@{ exists = $false; path = $full }
    } catch [System.IO.DirectoryNotFoundException] {
        return [pscustomobject]@{ exists = $false; path = $full }
    } catch {
        throw "Cannot inspect RunDir file (fail closed): $full"
    }
    if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing reparse point (junction/symlink) at RunDir file: $full"
    }
    if (($attributes -band [System.IO.FileAttributes]::Directory) -ne 0) {
        throw "RunDir file path is a directory, not a file: $full"
    }
    return [pscustomobject]@{ exists = $true; path = $full; attributes = $attributes }
}

function Write-P1SafeTextFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Content,
        [string]$Encoding = "utf8"
    )
    $null = Assert-P1SafeRunFile -Path $Path
    Set-Content -LiteralPath $Path -Value $Content -Encoding $Encoding
    $null = Assert-P1SafeRunFile -Path $Path
}

function Write-P1SafeJsonFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
    Write-P1SafeTextFile -Path $Path -Content ($Value | ConvertTo-Json -Depth 8) -Encoding utf8
}

function Assert-P1SafeDataDir {
    param(
        [Parameter(Mandatory = $true)][string]$WorktreeRoot,
        [Parameter(Mandatory = $true)][string]$DataDir,
        [switch]$AllowNonEmpty
    )
    $path = Get-P1FullPath $DataDir
    $root = Get-P1FullPath $WorktreeRoot
    $defaultData = Get-P1FullPath (Join-Path $root ".local-run\data")
    $null = Assert-P1NoReparseComponents -Path $path
    if (($path -split '[\\/]+') -contains ".local-data") {
        throw "Refusing a directory under .local-data: $path"
    }
    $protected = @(
        "D:\CTF\.local-data",
        (Join-Path $root ".local-data"),
        (Join-Path $root "backend\data"),
        (Join-Path $root "data")
    )
    foreach ($item in $protected) {
        try { $protectedPath = Get-P1FullPath $item } catch { continue }
        if (Test-P1PathWithin $path $protectedPath) {
            throw "Refusing original/project data directory: $path"
        }
    }
    foreach ($blocked in @($root, (Join-Path $root "backend"), (Join-Path $root "frontend"), (Join-Path $root "scripts"), (Join-Path $root "docs"))) {
        try { $blockedPath = Get-P1FullPath $blocked } catch { continue }
        if ($path.Equals($blockedPath, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing project source directory as a P1 data directory: $path"
        }
    }
    if (Test-Path -LiteralPath $path) {
        if (-not (Test-Path -LiteralPath $path -PathType Container)) {
            throw "P1 data path is not a directory: $path"
        }
        $isDefault = $path.Equals($defaultData, [System.StringComparison]::OrdinalIgnoreCase)
        if (-not $isDefault) {
            $markers = @(
                "workbench.sqlite3", "model-audit.sqlite3", "project.json",
                "challenges", "artifacts", "writeups", "model-service.json",
                "model-service.secret", ".local-data"
            )
            foreach ($marker in $markers) {
                if (Test-Path -LiteralPath (Join-Path $path $marker)) {
                    throw "Refusing data directory containing existing workbench data ($marker): $path"
                }
            }
            try {
                $nestedDb = @(Get-ChildItem -LiteralPath $path -Recurse -File -Force -ErrorAction Stop |
                    Where-Object { $_.Name -in @("workbench.sqlite3", "model-audit.sqlite3") })
            } catch {
                throw "Cannot enumerate data directory (fail closed): $path"
            }
            if ($nestedDb.Count -gt 0) {
                throw "Refusing data directory containing an existing business database: $path"
            }
        }
        try {
            $entries = @(Get-ChildItem -LiteralPath $path -Force -ErrorAction Stop)
        } catch {
            throw "Cannot enumerate data directory (fail closed): $path"
        }
        if ($entries.Count -gt 0 -and -not $isDefault -and -not $AllowNonEmpty) {
            throw "Refusing non-empty custom data directory without -AllowNonEmptyDataDir: $path"
        }
    }
    return $path
}

function Get-P1ProcessInfo {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    try {
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
    } catch {
        return [pscustomobject]@{ state = "UNKNOWN"; exists = $null; reason = "CIM query failed" }
    }
    if ($null -eq $cim) {
        try {
            $process = Get-Process -Id $ProcessId -ErrorAction Stop
            if ($process) {
                return [pscustomobject]@{ state = "UNKNOWN"; exists = $null; reason = "CIM returned no identity for a live process" }
            }
        } catch [Microsoft.PowerShell.Commands.ProcessCommandException] {
            if ($_.CategoryInfo.Category -eq [System.Management.Automation.ErrorCategory]::ObjectNotFound -and
                $_.FullyQualifiedErrorId -like "NoProcessFoundForGivenId*") {
                return [pscustomobject]@{ state = "MISSING"; exists = $false; reason = "process not found" }
            }
            return [pscustomobject]@{ state = "UNKNOWN"; exists = $null; reason = "process lookup failed" }
        } catch {
            return [pscustomobject]@{ state = "UNKNOWN"; exists = $null; reason = "process lookup failed" }
        }
    }
    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        $startTime = $process.StartTime.ToUniversalTime().ToString("o")
        if ([string]::IsNullOrWhiteSpace([string]$cim.Name) -or
            [string]::IsNullOrWhiteSpace([string]$cim.ExecutablePath) -or
            [string]::IsNullOrWhiteSpace([string]$cim.CommandLine) -or
            [string]::IsNullOrWhiteSpace($startTime)) {
            throw "incomplete process identity"
        }
        return [pscustomobject]@{
            state = "NORMAL"; exists = $true; pid = $ProcessId
            name = $cim.Name; executable = $cim.ExecutablePath
            command_line = $cim.CommandLine; start_time = $startTime
        }
    } catch {
        return [pscustomobject]@{ state = "UNKNOWN"; exists = $null; reason = "process identity unavailable" }
    } finally {
        if ($process) { try { $process.Dispose() } catch { } }
    }
}

function Test-P1PortOwnedBy {
    param([int]$Port, [int]$ProcessId)
    $connections = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($connections.Count -eq 0) { return $false }
    return [bool]($connections | Where-Object { [int]$_.OwningProcess -eq $ProcessId })
}

function Stop-P1ProcessByVerifiedHandle {
    param(
        [Parameter(Mandatory = $true)]$Record,
        [Parameter(Mandatory = $true)][string]$Kind,
        [switch]$RequirePort
    )
    $processId = if ($Kind -eq "backend") { $Record.backend_pid } else { $Record.frontend_pid }
    $portValue = if ($Kind -eq "backend") { $Record.backend_port } else { $Record.frontend_port }
    $executable = if ($Kind -eq "backend") { $Record.backend_executable } else { $Record.frontend_executable }
    $commandLine = if ($Kind -eq "backend") { $Record.backend_command_line } else { $Record.frontend_command_line }
    $startTime = if ($Kind -eq "backend") { $Record.backend_start_time } else { $Record.frontend_start_time }
    $tokens = if ($Kind -eq "backend") { $Record.backend_identity_tokens } else { $Record.frontend_identity_tokens }
    if (-not $processId) {
        return [pscustomobject]@{ status = "missing"; reasons = @("no pid recorded") }
    }
    $info = Get-P1ProcessInfo -ProcessId ([int]$processId)
    if ($info.state -eq "MISSING") {
        return [pscustomobject]@{ status = "missing"; reasons = @("pid not running"); process = $info }
    }
    if ($info.state -ne "NORMAL") {
        return [pscustomobject]@{ status = "unknown"; reasons = @($info.reason); process = $info }
    }
    $reasons = @()
    if (-not $executable -or -not $info.executable -or
        -not $info.executable.Equals([string]$executable, [System.StringComparison]::OrdinalIgnoreCase)) {
        $reasons += "executable does not match recorded executable"
    }
    if (-not $commandLine -or -not $info.command_line -or
        -not $info.command_line.Equals([string]$commandLine, [System.StringComparison]::OrdinalIgnoreCase)) {
        $reasons += "command line does not match recorded command line"
    }
    if (-not $startTime) {
        $reasons += "no process start time recorded"
    } else {
        try {
            $expectedStart = [datetime]::Parse([string]$startTime).ToUniversalTime()
            $actualStart = [datetime]::Parse([string]$info.start_time).ToUniversalTime()
            if ([math]::Abs(($actualStart - $expectedStart).TotalSeconds) -gt 2) {
                $reasons += "process start time does not match (possible PID reuse)"
            }
        } catch {
            $reasons += "cannot compare process start time"
        }
    }
    if ($tokens) {
        foreach ($token in @($tokens)) {
            if ([string]$info.command_line -notmatch [regex]::Escape([string]$token)) {
                $reasons += "missing identity token: $token"
            }
        }
    } else {
        $reasons += "no identity tokens recorded"
    }
    if ($RequirePort -and -not (Test-P1PortOwnedBy -Port ([int]$portValue) -ProcessId ([int]$processId))) {
        $reasons += "recorded port is not owned by this PID"
    }
    if ($reasons.Count -gt 0) {
        return [pscustomobject]@{ status = "mismatch"; reasons = $reasons; process = $info }
    }
    try {
        $process = Get-Process -Id ([int]$processId) -ErrorAction Stop
    } catch {
        $recheck = Get-P1ProcessInfo -ProcessId ([int]$processId)
        if ($recheck.state -eq "MISSING") {
            return [pscustomobject]@{ status = "missing"; reasons = @("process exited before cleanup"); process = $recheck }
        }
        return [pscustomobject]@{ status = "unknown"; reasons = @("process handle unavailable"); process = $recheck }
    }
    try {
        if ($process.HasExited) {
            return [pscustomobject]@{ status = "missing"; reasons = @("process already exited"); process = $info }
        }
        $expectedStart = [datetime]::Parse([string]$startTime).ToUniversalTime()
        if ([math]::Abs(($process.StartTime.ToUniversalTime() - $expectedStart).TotalSeconds) -gt 2) {
            return [pscustomobject]@{ status = "mismatch"; reasons = @("handle start time changed"); process = $info }
        }
        $process.Kill()
        if (-not $process.WaitForExit(5000)) {
            return [pscustomobject]@{ status = "failed"; reasons = @("process did not exit within 5s"); process = $info }
        }
        return [pscustomobject]@{ status = "stopped"; reasons = @(); process = $info }
    } catch {
        return [pscustomobject]@{ status = "failed"; reasons = @($_.Exception.Message); process = $info }
    } finally {
        try { $process.Dispose() } catch { }
    }
}

function Test-P1ProcessIdentity {
    param(
        [Parameter(Mandatory = $true)]$Record,
        [Parameter(Mandatory = $true)][string]$Kind
    )
    $pidValue = if ($Kind -eq "backend") { $Record.backend_pid } else { $Record.frontend_pid }
    $portValue = if ($Kind -eq "backend") { $Record.backend_port } else { $Record.frontend_port }
    $executable = if ($Kind -eq "backend") { $Record.backend_executable } else { $Record.frontend_executable }
    $commandLine = if ($Kind -eq "backend") { $Record.backend_command_line } else { $Record.frontend_command_line }
    $startTime = if ($Kind -eq "backend") { $Record.backend_start_time } else { $Record.frontend_start_time }
    $tokens = if ($Kind -eq "backend") { $Record.backend_identity_tokens } else { $Record.frontend_identity_tokens }

    if (-not $pidValue) { return [pscustomobject]@{ status = "missing"; reasons = @("no pid recorded") } }
    $info = Get-P1ProcessInfo -ProcessId ([int]$pidValue)
    if ($info.state -eq "MISSING") {
        return [pscustomobject]@{ status = "missing"; reasons = @("pid not running") }
    }
    if ($info.state -ne "NORMAL") {
        return [pscustomobject]@{ status = "unknown"; reasons = @($info.reason); process = $info }
    }
    $reasons = @()
    if (-not $executable -or -not $info.executable -or
        -not $info.executable.Equals([string]$executable, [System.StringComparison]::OrdinalIgnoreCase)) {
        $reasons += "executable does not match recorded executable"
    }
    if ($startTime) {
        try {
            $recordedStart = [datetime]::Parse([string]$startTime).ToUniversalTime()
            $actualStart = [datetime]::Parse([string]$info.start_time).ToUniversalTime()
            if ([math]::Abs(($actualStart - $recordedStart).TotalSeconds) -gt 2) {
                $reasons += "process start time does not match (possible PID reuse)"
            }
        } catch {
            $reasons += "cannot compare process start time"
        }
    } else {
        $reasons += "no process start time recorded"
    }
    if (-not $commandLine -or -not $info.command_line -or
        -not $info.command_line.Equals([string]$commandLine, [System.StringComparison]::OrdinalIgnoreCase)) {
        $reasons += "command line does not match recorded command line"
    }
    if ($tokens) {
        $actualCommand = [string]$info.command_line
        foreach ($token in @($tokens)) {
            if ($actualCommand.IndexOf([string]$token, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
                $reasons += "missing identity token: $token"
            }
        }
    } else {
        $reasons += "no identity tokens recorded"
    }
    if (-not (Test-P1PortOwnedBy -Port ([int]$portValue) -ProcessId ([int]$pidValue))) {
        $reasons += "recorded port is not owned by this PID"
    }
    if ($reasons.Count -gt 0) {
        return [pscustomobject]@{ status = "mismatch"; reasons = $reasons; process = $info }
    }
    return [pscustomobject]@{ status = "ok"; reasons = @(); process = $info }
}
