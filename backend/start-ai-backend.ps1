param(
    [Parameter(Mandatory = $true)]
    [string]$DataDir,

    [int]$Port = 8002,

    [string]$Model = "deepseek-flash",

    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$originalLocation = Get-Location
$plainKey = $null

if (-not [System.IO.Path]::IsPathRooted($DataDir)) {
    throw "DataDir must be an absolute path. Refusing an ambiguous data location."
}

$resolvedData = [System.IO.Path]::GetFullPath($DataDir)
if (-not (Test-Path -LiteralPath $resolvedData -PathType Container)) {
    throw "The isolated data directory does not exist: $resolvedData"
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    throw "Port $Port is already in use. Nothing was stopped; choose an unused isolated port."
}

$pythonCommand = Get-Command $Python -ErrorAction Stop
$tempDir = Join-Path $resolvedData "tmp"
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

$variableNames = @(
    "CTF_DATA_DIR",
    "TEMP",
    "TMP",
    "TMPDIR",
    "CTF_MODEL_NETWORK_ENABLED",
    "CTF_MODEL_ID",
    "CTF_MODEL_API_KEY_ENV",
    "CTF_MODEL_BASE_URL",
    "CTF_MODEL_TIMEOUT_SECONDS",
    "DEEPSEEK_API_KEY"
)
$previousValues = @{}
foreach ($name in $variableNames) {
    $previousValues[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

$secureKey = Read-Host "Enter DeepSeek API Key (input hidden)" -AsSecureString
if ($secureKey.Length -eq 0) {
    throw "An API Key is required. No service was started."
}

$bstr = [IntPtr]::Zero
try {
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)

    $env:CTF_DATA_DIR = $resolvedData
    $env:TEMP = $tempDir
    $env:TMP = $tempDir
    $env:TMPDIR = $tempDir
    $env:CTF_MODEL_NETWORK_ENABLED = "true"
    $env:CTF_MODEL_ID = $Model
    $env:CTF_MODEL_API_KEY_ENV = "DEEPSEEK_API_KEY"
    $env:CTF_MODEL_BASE_URL = "https://api.deepseek.com"
    $env:CTF_MODEL_TIMEOUT_SECONDS = "120"
    $env:DEEPSEEK_API_KEY = $plainKey

    Set-Location -LiteralPath $PSScriptRoot
    Write-Host "Starting isolated CTF backend on 127.0.0.1:$Port"
    Write-Host "Data directory: $resolvedData"
    Write-Host "Provider: DeepSeek; model: $Model"
    Write-Host "The API Key is process-scoped and will not be written to disk."
    & $pythonCommand.Source -B -m uvicorn app.main:app --app-dir $PSScriptRoot --host 127.0.0.1 --port $Port --workers 1
    if ($LASTEXITCODE -ne 0) {
        throw "Backend exited with code $LASTEXITCODE"
    }
}
finally {
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    $plainKey = $null
    if ($null -ne $secureKey) {
        $secureKey.Dispose()
    }
    Set-Location -LiteralPath $originalLocation
    foreach ($name in $variableNames) {
        $oldValue = $previousValues[$name]
        if ($null -eq $oldValue) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
        else {
            [Environment]::SetEnvironmentVariable($name, $oldValue, "Process")
        }
    }
}
