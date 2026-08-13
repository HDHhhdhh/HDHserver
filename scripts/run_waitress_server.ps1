param(
    [string]$Listen = "0.0.0.0:8003",
    [int]$Threads = 16,
    [int]$ConnectionLimit = 400,
    [int]$ChannelTimeout = 60
)

$ErrorActionPreference = "Stop"

$adminMachineEnv = @(
    "ACADEMY_ADMIN_USERNAME",
    "ACADEMY_ADMIN_PASSWORD_HASH"
)
foreach ($name in $adminMachineEnv) {
    $value = [Environment]::GetEnvironmentVariable($name, "Machine")
    if ($null -ne $value) {
        Set-Item -LiteralPath "Env:$name" -Value $value
    } else {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }
}

$serverRoot = Split-Path -Parent $PSScriptRoot
$waitressPath = Join-Path $serverRoot "venv\Scripts\waitress-serve.exe"
if (-not (Test-Path -LiteralPath $waitressPath)) {
    throw "Waitress is not installed in the server virtual environment: $waitressPath"
}

$listenPort = [int](($Listen -split ":")[-1])
$existingListener = Get-NetTCPConnection -LocalPort $listenPort -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($existingListener) {
    throw "Port $listenPort is already in use by PID $($existingListener.OwningProcess)."
}

$env:DATA_MIRROR_MAX_SNAPS_PER_FILE = "24"
$env:DATA_MIRROR_SNAPSHOT_MIN_SEC = "3600"

Set-Location -LiteralPath $serverRoot
& $waitressPath `
    "--listen=$Listen" `
    "--threads=$Threads" `
    "--connection-limit=$ConnectionLimit" `
    "--channel-timeout=$ChannelTimeout" `
    "--cleanup-interval=15" `
    "--channel-request-lookahead=1" `
    "app:app"
exit $LASTEXITCODE
