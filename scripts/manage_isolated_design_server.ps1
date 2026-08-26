[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("Start", "Stop", "Status", "Refresh")]
    [string]$Action = "Status",
    [ValidateRange(1024, 65535)]
    [int]$Port = 8004,
    [string]$IsolatedRoot = "",
    [switch]$Restart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$sourceRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd("\")
$instanceParent = [IO.Path]::GetFullPath((Join-Path $sourceRoot "instance")).TrimEnd("\")
if ([string]::IsNullOrWhiteSpace($IsolatedRoot)) {
    $IsolatedRoot = Join-Path $instanceParent "isolated-design-server"
}
$isolatedBase = [IO.Path]::GetFullPath($IsolatedRoot).TrimEnd("\")
$allowedPrefix = $instanceParent + "\"
if (-not $isolatedBase.StartsWith($allowedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "IsolatedRoot must stay below $instanceParent"
}

$codeRoot = Join-Path $isolatedBase "app"
$receiptPath = Join-Path $isolatedBase "server.json"
$markerPath = Join-Path $codeRoot ".academy-isolated-server.json"
$stdoutPath = Join-Path $isolatedBase "waitress.stdout.log"
$stderrPath = Join-Path $isolatedBase "waitress.stderr.log"
$waitressPath = Join-Path $sourceRoot "venv\Scripts\waitress-serve.exe"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-JsonFile {
    param([string]$Path, [object]$Value)
    $parent = Split-Path -Parent $Path
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $json = $Value | ConvertTo-Json -Depth 10
    [IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, $utf8NoBom)
}

function Read-Receipt {
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) { return $null }
    try {
        Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "Isolated server receipt is unreadable: $receiptPath"
    }
}

function Get-Listeners {
    @(
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Sort-Object LocalAddress, OwningProcess
    )
}

function Get-HttpStatus {
    try {
        $result = & curl.exe -sS -o NUL --connect-timeout 1 --max-time 4 `
            -w "%{http_code}" "http://127.0.0.1:$Port/api/ping" 2>$null
        if ($LASTEXITCODE -eq 0 -and $result -match '^\d{3}$') { return [int]$result }
    } catch { }
    return 0
}

function Get-ProcessStartUtc {
    param([int]$ProcessId)
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) { return "" }
    try { return $process.StartTime.ToUniversalTime().ToString("o") } catch { return "" }
}

function Test-SameStartTime {
    param([int]$ProcessId, [string]$ExpectedUtc)
    if ([string]::IsNullOrWhiteSpace($ExpectedUtc)) { return $false }
    $actual = Get-ProcessStartUtc -ProcessId $ProcessId
    if (-not $actual) { return $false }
    [DateTime]::Parse($actual).ToUniversalTime().Ticks -eq [DateTime]::Parse($ExpectedUtc).ToUniversalTime().Ticks
}

function Get-ManagedStatus {
    $receipt = Read-Receipt
    $listeners = @(Get-Listeners)
    $loopback = @($listeners | Where-Object { $_.LocalAddress -eq "127.0.0.1" })
    $managed = $false
    if ($receipt -and $loopback.Count -eq 1) {
        $managed = (
            [int]$receipt.port -eq $Port -and
            [string]$receipt.codeRoot -eq $codeRoot -and
            [int]$receipt.listenerProcessId -eq [int]$loopback[0].OwningProcess -and
            (Test-SameStartTime -ProcessId ([int]$receipt.listenerProcessId) -ExpectedUtc ([string]$receipt.listenerStartTimeUtc))
        )
    }
    [ordered]@{
        format = "academy-isolated-design-server-status/v1"
        action = $Action
        running = ($loopback.Count -gt 0)
        managed = $managed
        port = $Port
        listenerProcessId = if ($loopback.Count -eq 1) { [int]$loopback[0].OwningProcess } else { 0 }
        httpStatus = if ($loopback.Count -eq 1) { Get-HttpStatus } else { 0 }
        sourceRoot = $sourceRoot
        isolatedRoot = $isolatedBase
        codeRoot = $codeRoot
        runtimePersistent = $true
        liveRuntimeCopied = $false
    }
}

function Sync-CodeSnapshot {
    [IO.Directory]::CreateDirectory($isolatedBase) | Out-Null
    [IO.Directory]::CreateDirectory($codeRoot) | Out-Null

    foreach ($directoryName in @("core", "routes", "static")) {
        $source = Join-Path $sourceRoot $directoryName
        $destination = Join-Path $codeRoot $directoryName
        [IO.Directory]::CreateDirectory($destination) | Out-Null
        & robocopy.exe $source $destination /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NP `
            /XD "__pycache__" ".pytest_cache" /XF "*.pyc" "*.pyo" | Out-Null
        $copyExit = $LASTEXITCODE
        if ($copyExit -gt 7) {
            throw "Failed to mirror $directoryName into the isolated server (robocopy exit $copyExit)."
        }
    }

    foreach ($fileName in @("app.py", "models.py")) {
        $source = Join-Path $sourceRoot $fileName
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $codeRoot $fileName) -Force
        }
    }

    $marker = [ordered]@{
        format = "academy-isolated-server/v1"
        isolatedRoot = $codeRoot
        sourceRoot = $sourceRoot
        refreshedAtUtc = [DateTime]::UtcNow.ToString("o")
        liveRuntimeCopied = $false
    }
    Write-JsonFile -Path $markerPath -Value $marker
}

function Stop-ManagedServer {
    $receipt = Read-Receipt
    $listeners = @(Get-Listeners)
    if ($listeners.Count -eq 0) {
        if (Test-Path -LiteralPath $receiptPath -PathType Leaf) {
            Remove-Item -LiteralPath $receiptPath -Force
        }
        return
    }
    if (-not $receipt) {
        throw "Port $Port is occupied but no isolated-server receipt exists; refusing to stop it."
    }
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne "127.0.0.1") {
        throw "Port $Port has an unexpected listener set; refusing to stop it."
    }
    $listenerPid = [int]$listeners[0].OwningProcess
    if ($listenerPid -ne [int]$receipt.listenerProcessId -or
        -not (Test-SameStartTime -ProcessId $listenerPid -ExpectedUtc ([string]$receipt.listenerStartTimeUtc))) {
        throw "Port $Port is no longer owned by the recorded isolated server."
    }
    $listenerProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$listenerPid" -ErrorAction SilentlyContinue
    if (-not $listenerProcess -or
        $listenerProcess.CommandLine -notmatch ("--listen=127\.0\.0\.1:" + [regex]::Escape([string]$Port)) -or
        $listenerProcess.CommandLine -notmatch "\sapp:app(?:\s|$)") {
        throw "Recorded listener does not match the isolated Waitress command."
    }

    Stop-Process -Id $listenerPid -Force
    $wrapperPid = [int]$receipt.wrapperProcessId
    if ($wrapperPid -gt 0 -and
        (Test-SameStartTime -ProcessId $wrapperPid -ExpectedUtc ([string]$receipt.wrapperStartTimeUtc))) {
        Stop-Process -Id $wrapperPid -Force -ErrorAction SilentlyContinue
    }

    $deadline = (Get-Date).AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 250
        $remaining = @(Get-Listeners)
    } while ($remaining.Count -gt 0 -and (Get-Date) -lt $deadline)
    if ($remaining.Count -gt 0) {
        throw "Isolated server did not release port $Port."
    }
    Remove-Item -LiteralPath $receiptPath -Force -ErrorAction SilentlyContinue
}

function Start-ManagedServer {
    if (-not (Test-Path -LiteralPath $waitressPath -PathType Leaf)) {
        throw "Waitress is missing from the source virtual environment: $waitressPath"
    }
    $listeners = @(Get-Listeners)
    if ($listeners.Count -gt 0) {
        $status = Get-ManagedStatus
        if ($status.managed -and -not $Restart) { return $status }
        if (-not $status.managed) {
            throw "Port $Port is occupied by a process not owned by the isolated design server."
        }
        Stop-ManagedServer
    }

    Sync-CodeSnapshot
    [IO.Directory]::CreateDirectory((Join-Path $codeRoot "instance")) | Out-Null
    [IO.Directory]::CreateDirectory((Join-Path $codeRoot "data")) | Out-Null

    $environment = [ordered]@{
        ACADEMY_ISOLATED_SERVER_ROOT = $codeRoot
        DATA_DIR = (Join-Path $codeRoot "data")
        DATA_MIRROR_DIR = (Join-Path $codeRoot "_data_mirror")
        DATA_MIRROR_SNAPSHOTS = "0"
        DB_PATH = (Join-Path $codeRoot "app.sqlite")
        STUDENT_APP_DB_PATH = (Join-Path $codeRoot "app.sqlite")
        STUDENT_APP_ACCOUNTS_PATH = (Join-Path $codeRoot "auth_accounts.json")
        STUDENT_APP_STUDENTS_PATH = (Join-Path $codeRoot "students.json")
        STUDENT_APP_LOGS_PATH = (Join-Path $codeRoot "logs.json")
        STUDENT_APP_RUNTIME_ROOT = $codeRoot
        STUDENT_APP_ABSENT_PATH = (Join-Path $codeRoot "absent.json")
        STUDENT_APP_EXTRA_PATH = (Join-Path $codeRoot "extra_attend.json")
        STUDENT_APP_WEEKEND_PATH = (Join-Path $codeRoot "weekend_slots.json")
        STUDENT_APP_MAKEUP_PATH = (Join-Path $codeRoot "makeup_carryover.json")
        STUDENT_APP_PUBLIC_ENABLED = "0"
        STUDENT_APP_PUBLIC_HOST = "dev-app.5a-math.com"
        STUDENT_APP_LEGACY_HOST = "5a-math.com"
        STUDENT_APP_LEGACY_REDIRECT_ENABLED = "0"
        STUDENT_APP_DASHBOARD_ENABLED = "0"
        STUDENT_APP_HOMEWORK_ENABLED = "0"
        STUDENT_APP_REMINDERS_ENABLED = "0"
        STUDENT_APP_FOCUS_ENABLED = "0"
        TRUST_PROXY_HEADERS = "0"
    }
    $clearEnvironment = @(
        "ANNOUNCEMENT_IMAGE_SOURCE_DIR",
        "KOLLUS_CALLBACK_SECRET",
        "STUDENT_APP_VAPID_PRIVATE_KEY",
        "STUDENT_APP_VAPID_PRIVATE_KEY_PATH"
    )
    $previous = @{}
    foreach ($name in @($environment.Keys) + $clearEnvironment) {
        $item = Get-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        $previous[$name] = [ordered]@{
            exists = ($null -ne $item)
            value = if ($item) { [string]$item.Value } else { "" }
        }
    }

    $wrapper = $null
    try {
        foreach ($name in $environment.Keys) {
            Set-Item -LiteralPath "Env:$name" -Value ([string]$environment[$name])
        }
        foreach ($name in $clearEnvironment) {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        }
        $arguments = @(
            "--listen=127.0.0.1:$Port",
            "--threads=8",
            "--connection-limit=100",
            "--channel-timeout=60",
            "--cleanup-interval=15",
            "app:app"
        )
        $wrapper = Start-Process -FilePath $waitressPath -ArgumentList $arguments `
            -WorkingDirectory $codeRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    } finally {
        foreach ($name in $previous.Keys) {
            if ($previous[$name].exists) {
                Set-Item -LiteralPath "Env:$name" -Value ([string]$previous[$name].value)
            } else {
                Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
            }
        }
    }

    $deadline = (Get-Date).AddSeconds(20)
    $listener = $null
    do {
        Start-Sleep -Milliseconds 250
        $wrapper.Refresh()
        if ($wrapper.HasExited) { break }
        $listener = Get-Listeners | Where-Object { $_.LocalAddress -eq "127.0.0.1" } | Select-Object -First 1
    } while (-not $listener -and (Get-Date) -lt $deadline)

    if (-not $listener) {
        if ($wrapper -and -not $wrapper.HasExited) {
            Stop-Process -Id $wrapper.Id -Force -ErrorAction SilentlyContinue
        }
        $tail = if (Test-Path -LiteralPath $stderrPath -PathType Leaf) {
            (Get-Content -LiteralPath $stderrPath -Tail 20 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
        } else { "" }
        throw "Isolated Waitress did not start on port $Port. $tail"
    }

    $listenerPid = [int]$listener.OwningProcess
    $receipt = [ordered]@{
        format = "academy-isolated-design-server/v1"
        startedAtUtc = [DateTime]::UtcNow.ToString("o")
        sourceRoot = $sourceRoot
        codeRoot = $codeRoot
        port = $Port
        wrapperProcessId = [int]$wrapper.Id
        wrapperStartTimeUtc = Get-ProcessStartUtc -ProcessId ([int]$wrapper.Id)
        listenerProcessId = $listenerPid
        listenerStartTimeUtc = Get-ProcessStartUtc -ProcessId $listenerPid
        liveRuntimeCopied = $false
    }
    Write-JsonFile -Path $receiptPath -Value $receipt

    $status = Get-ManagedStatus
    if ($status.httpStatus -ne 200) {
        Stop-ManagedServer
        throw "Isolated server started but /api/ping returned $($status.httpStatus)."
    }
    return $status
}

switch ($Action) {
    "Start" {
        $result = Start-ManagedServer
        $result | ConvertTo-Json -Depth 8
    }
    "Stop" {
        Stop-ManagedServer
        (Get-ManagedStatus) | ConvertTo-Json -Depth 8
    }
    "Status" {
        (Get-ManagedStatus) | ConvertTo-Json -Depth 8
    }
    "Refresh" {
        Sync-CodeSnapshot
        $status = Get-ManagedStatus
        $status["restartRequiredForPythonChanges"] = [bool]$status.running
        $status | ConvertTo-Json -Depth 8
    }
}
