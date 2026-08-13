param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Development", "Production")]
    [string]$Role,
    [ValidateSet("app.5a-math.com", "dev-app.5a-math.com")]
    [string]$PublicHost = "",
    [ValidateRange(1, 65535)]
    [int]$OriginPort = 0,
    [string]$ServerRoot = "",
    [string]$OutFile = ""
)

$ErrorActionPreference = "Stop"

if (-not $PublicHost) {
    $PublicHost = if ($Role -eq "Development") { "dev-app.5a-math.com" } else { "app.5a-math.com" }
}
if ($OriginPort -eq 0) {
    $OriginPort = if ($Role -eq "Development") { 8004 } else { 8003 }
}
if (-not $ServerRoot) {
    $ServerRoot = Split-Path -Parent $PSScriptRoot
}
$ServerRoot = [IO.Path]::GetFullPath($ServerRoot)

function Get-SafeHash([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $item = Get-Item -LiteralPath $Path
    [ordered]@{
        exists = $true
        size = [long]$item.Length
        modifiedUtc = $item.LastWriteTimeUtc.ToString("o")
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    }
}

function Get-GitValue([string[]]$Arguments) {
    try {
        $value = & git -C $ServerRoot @Arguments 2>$null
        if ($LASTEXITCODE -eq 0) { return (($value | Out-String).Trim()) }
    } catch { }
    return ""
}

function Get-HttpStatus([int]$Port, [string]$HostName) {
    try {
        $headers = & curl.exe --path-as-is -sS -o NUL -D - --max-time 5 `
            "http://127.0.0.1:$Port/app" `
            -H "Host: $HostName" `
            -H "X-Forwarded-Proto: https" `
            -H "CF-Connecting-IP: 203.0.113.10"
        if ($LASTEXITCODE -ne 0) { return 0 }
        $statusLine = ($headers | Select-String '^HTTP/').Line | Select-Object -Last 1
        if ($statusLine -match '^HTTP/\S+\s+(\d{3})') { return [int]$matches[1] }
        return 0
    } catch {
        return 0
    }
}

function Get-CloudflaredIngress {
    $path = "C:\ProgramData\cloudflared\config.yml"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return @() }
    $lines = Get-Content -LiteralPath $path -Encoding UTF8
    $rows = @()
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*-?\s*hostname:\s*(.+?)\s*$') {
            $hostName = $matches[1].Trim('"', "'")
            $service = ""
            for ($j = $i + 1; $j -lt [Math]::Min($i + 5, $lines.Count); $j++) {
                if ($lines[$j] -match '^\s*service:\s*(.+?)\s*$') { $service = $matches[1].Trim(); break }
                if ($lines[$j] -match '^\s*-?\s*hostname:') { break }
            }
            $rows += [ordered]@{ hostname = $hostName; service = $service }
        }
    }
    return $rows
}

$listenerRows = @()
$listeners = Get-NetTCPConnection -LocalPort $OriginPort -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    $listenerRows += [ordered]@{
        address = $listener.LocalAddress
        port = [int]$listener.LocalPort
        processId = [int]$listener.OwningProcess
        executableName = if ($process.ExecutablePath) { Split-Path -Leaf $process.ExecutablePath } else { "" }
    }
}

$taskRows = @()
Get-ScheduledTask -ErrorAction SilentlyContinue |
    Where-Object { $_.TaskName -match 'Academy.*(Waitress|Push)' } |
    ForEach-Object {
        $taskRows += [ordered]@{ name = $_.TaskName; state = $_.State.ToString() }
    }

$service = Get-Service cloudflared -ErrorAction SilentlyContinue
$dirty = Get-GitValue @("status", "--porcelain")
$critical = [ordered]@{}
foreach ($name in @("students.json", "auth_accounts.json", "app.sqlite", "updates.json")) {
    $critical[$name] = Get-SafeHash (Join-Path $ServerRoot $name)
}
$expectedHost = [Environment]::GetEnvironmentVariable("STUDENT_APP_PUBLIC_HOST", "Machine")
$expectedEnabled = [Environment]::GetEnvironmentVariable("STUDENT_APP_PUBLIC_ENABLED", "Machine")
$otherHost = if ($PublicHost -eq "app.5a-math.com") { "dev-app.5a-math.com" } else { "app.5a-math.com" }

$status = [ordered]@{
    format = "student-app-node-status/v1"
    capturedAtUtc = [DateTime]::UtcNow.ToString("o")
    role = $Role
    computer = $env:COMPUTERNAME
    serverRoot = $ServerRoot
    network = [ordered]@{
        ipv4 = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" } |
            ForEach-Object { [ordered]@{ interface = $_.InterfaceAlias; address = $_.IPAddress; prefixLength = $_.PrefixLength } })
    }
    public = [ordered]@{
        expectedHost = $PublicHost
        originPort = $OriginPort
        localStatus = Get-HttpStatus $OriginPort $PublicHost
        crossHostStatus = Get-HttpStatus $OriginPort $otherHost
        machinePublicHostMatches = ($expectedHost -eq $PublicHost)
        machinePublicEnabled = $expectedEnabled
    }
    listener = $listenerRows
    tasks = $taskRows
    cloudflared = [ordered]@{
        status = if ($service) { $service.Status.ToString() } else { "Missing" }
        startType = if ($service) { $service.StartType.ToString() } else { "" }
        ingress = @(Get-CloudflaredIngress)
    }
    source = [ordered]@{
        branch = Get-GitValue @("branch", "--show-current")
        commit = Get-GitValue @("rev-parse", "HEAD")
        dirty = [bool]$dirty
        dirtyPathCount = if ($dirty) { @($dirty -split "`r?`n").Count } else { 0 }
    }
    runtimeFingerprints = $critical
    privacy = [ordered]@{
        containsRuntimeContents = $false
        containsCanarySids = $false
        containsCredentials = $false
        containsVapidKey = $false
    }
}

$json = $status | ConvertTo-Json -Depth 8
if ($OutFile) {
    $resolvedOut = [IO.Path]::GetFullPath($OutFile)
    $parent = Split-Path -Parent $resolvedOut
    if ($parent) { $null = New-Item -ItemType Directory -Path $parent -Force }
    [IO.File]::WriteAllText($resolvedOut, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    [ordered]@{ ok = $true; statusFile = $resolvedOut; sha256 = (Get-FileHash -LiteralPath $resolvedOut -Algorithm SHA256).Hash } |
        ConvertTo-Json
} else {
    $json
}
