[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("Start", "Stop", "Status", "Refresh")]
    [string]$Action = "Status",
    [ValidateRange(1024, 65535)]
    [int]$Port = 8004,
    [string]$IsolatedRoot = "",
    [switch]$Restart,
    [switch]$KollusVideoQa
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($KollusVideoQa -and $Port -ne 8004) { throw "Kollus video QA is restricted to port 8004." }
if ($KollusVideoQa -and $Action -ne "Start") { throw "Kollus video QA requires Start (with -Restart for a running server)." }

$sourceRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd("\")
$instanceParent = [IO.Path]::GetFullPath((Join-Path $sourceRoot "instance")).TrimEnd("\")
if ([string]::IsNullOrWhiteSpace($IsolatedRoot)) {
    $IsolatedRoot = Join-Path $instanceParent "isolated-design-server"
}
$isolatedBase = [IO.Path]::GetFullPath($IsolatedRoot).TrimEnd("\")
if ($KollusVideoQa -and $isolatedBase -ne (Join-Path $instanceParent "isolated-design-server")) {
    throw "Kollus video QA requires the canonical isolated-design-server root."
}
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
        # A failed ownership query must never be interpreted as an unused port.
        Get-NetTCPConnection -State Listen -ErrorAction Stop |
            Where-Object { $_.LocalPort -eq $Port } |
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
    param([int]$ProcessId, [object]$ExpectedUtc)
    if ($null -eq $ExpectedUtc) { return $false }
    $actual = Get-ProcessStartUtc -ProcessId $ProcessId
    if (-not $actual) { return $false }
    try {
        $expectedDate = if ($ExpectedUtc -is [DateTime]) {
            ([DateTime]$ExpectedUtc).ToUniversalTime()
        } else {
            $expectedText = [string]$ExpectedUtc
            if ([string]::IsNullOrWhiteSpace($expectedText)) { return $false }
            [DateTime]::Parse(
                $expectedText,
                [Globalization.CultureInfo]::InvariantCulture,
                [Globalization.DateTimeStyles]::RoundtripKind
            ).ToUniversalTime()
        }
        [DateTime]::Parse(
            $actual,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        ).ToUniversalTime().Ticks -eq $expectedDate.Ticks
    } catch {
        $false
    }
}

function Get-ManagerMutexName {
    # Different snapshot roots must still serialize management of the same port.
    return "Global\AcademyIsolatedDesignServerManager-$Port"
}

function Invoke-WithManagerLock {
    param([scriptblock]$Operation, [int]$TimeoutMilliseconds = 60000)
    $mutex = New-Object Threading.Mutex($false, (Get-ManagerMutexName))
    $acquired = $false
    try {
        try { $acquired = $mutex.WaitOne($TimeoutMilliseconds) }
        catch [Threading.AbandonedMutexException] { $acquired = $true }
        if (-not $acquired) {
            throw "Timed out waiting for isolated-server management on port $Port."
        }
        & $Operation
    } finally {
        if ($acquired) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}

function Test-LaunchedProcess {
    param([int]$ProcessId, [int]$WrapperProcessId, [string]$WrapperStartTimeUtc)
    if (-not (Test-SameStartTime -ProcessId $WrapperProcessId -ExpectedUtc $WrapperStartTimeUtc)) {
        return $false
    }
    $wrapperStart = [DateTime]::Parse(
        $WrapperStartTimeUtc, [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind
    ).ToUniversalTime()
    $currentPid = $ProcessId
    $childStart = $null
    for ($depth = 0; $depth -lt 16 -and $currentPid -gt 0; $depth++) {
        if ($currentPid -eq $WrapperProcessId) {
            return (Test-SameStartTime -ProcessId $WrapperProcessId -ExpectedUtc $WrapperStartTimeUtc)
        }
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$currentPid" -ErrorAction Stop
        if (-not $process -or $null -eq $process.CreationDate) { return $false }
        $created = ([DateTime]$process.CreationDate).ToUniversalTime()
        # Parent PIDs can be reused; their chronology must fit this launch.
        if ($created -lt $wrapperStart -or ($null -ne $childStart -and $created -gt $childStart)) {
            return $false
        }
        $childStart = $created
        $currentPid = [int]$process.ParentProcessId
    }
    return $false
}

function Stop-LaunchedServer {
    param([object]$Wrapper, [string]$WrapperStartTimeUtc,
          [int]$ListenerProcessId, [string]$ListenerStartTimeUtc)
    if (-not $Wrapper -or -not $WrapperStartTimeUtc) { return }
    if ($ListenerProcessId -gt 0 -and $ListenerProcessId -ne [int]$Wrapper.Id -and
        (Test-SameStartTime -ProcessId $ListenerProcessId -ExpectedUtc $ListenerStartTimeUtc)) {
        try {
            if (Test-LaunchedProcess -ProcessId $ListenerProcessId -WrapperProcessId ([int]$Wrapper.Id) `
                -WrapperStartTimeUtc $WrapperStartTimeUtc) {
                Stop-Process -Id $ListenerProcessId -Force -ErrorAction Stop
            }
        } catch {
            Write-Warning "Could not verify or stop the launch-owned listener: $($_.Exception.Message)"
        }
    }
    if (Test-SameStartTime -ProcessId ([int]$Wrapper.Id) -ExpectedUtc $WrapperStartTimeUtc) {
        Stop-Process -Id ([int]$Wrapper.Id) -Force -ErrorAction Stop
    }
}

function Get-ManagedStatus {
    $receipt = Read-Receipt
    $listeners = @(Get-Listeners)
    $loopback = @($listeners | Where-Object { $_.LocalAddress -eq "127.0.0.1" })
    $managed = $false
    if ($receipt -and $listeners.Count -eq 1 -and $loopback.Count -eq 1) {
        $managed = (
            [int]$receipt.port -eq $Port -and
            [string]$receipt.codeRoot -eq $codeRoot -and
            [string]$receipt.sourceRoot -eq $sourceRoot -and
            [int]$receipt.listenerProcessId -eq [int]$loopback[0].OwningProcess -and
            (Test-SameStartTime -ProcessId ([int]$receipt.listenerProcessId) -ExpectedUtc $receipt.listenerStartTimeUtc)
        )
    }
    [ordered]@{
        format = "academy-isolated-design-server-status/v1"
        action = $Action
        running = ($listeners.Count -gt 0)
        managed = $managed
        port = $Port
        listenerProcessId = if ($loopback.Count -eq 1) { [int]$loopback[0].OwningProcess } else { 0 }
        httpStatus = if ($loopback.Count -eq 1) { Get-HttpStatus } else { 0 }
        sourceRoot = $sourceRoot
        isolatedRoot = $isolatedBase
        codeRoot = $codeRoot
        runtimePersistent = $true
        liveRuntimeCopied = $false
        kollusVideoQaEnabled = ($receipt -and $receipt.PSObject.Properties.Name -contains "kollusVideoQaEnabled" -and $receipt.kollusVideoQaEnabled -eq $true)
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

    $workerDestination = Join-Path $codeRoot "scripts"
    [IO.Directory]::CreateDirectory($workerDestination) | Out-Null
    foreach ($fileName in @(
        "student_test_choice_worker.py",
        "student_test_formula_worker.py",
        "student_test_paddle_worker.py",
        "student_test_unimernet_worker.py",
        "student_test_formula_inference.py",
        "student_test_ocr_worker_server.py",
        "student_test_sheet_crop_worker.py"
    )) {
        $source = Join-Path (Join-Path $sourceRoot "scripts") $fileName
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Required isolated OCR worker is missing: $source"
        }
        Copy-Item -LiteralPath $source -Destination (Join-Path $workerDestination $fileName) -Force
    }

    $marker = [ordered]@{
        format = "academy-isolated-server/v1"
        isolatedRoot = $codeRoot
        sourceRoot = $sourceRoot
        refreshedAtUtc = [DateTime]::UtcNow.ToString("o")
        liveRuntimeCopied = $false
        copiedWorkerScripts = 7
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
    if ([int]$receipt.port -ne $Port -or [string]$receipt.codeRoot -ne $codeRoot -or
        [string]$receipt.sourceRoot -ne $sourceRoot) {
        throw "Isolated-server receipt belongs to another port or snapshot root; refusing to stop it."
    }
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne "127.0.0.1") {
        throw "Port $Port has an unexpected listener set; refusing to stop it."
    }
    $listenerPid = [int]$listeners[0].OwningProcess
    if ($listenerPid -ne [int]$receipt.listenerProcessId -or
        -not (Test-SameStartTime -ProcessId $listenerPid -ExpectedUtc $receipt.listenerStartTimeUtc)) {
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
        (Test-SameStartTime -ProcessId $wrapperPid -ExpectedUtc $receipt.wrapperStartTimeUtc)) {
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
    if (@(Get-Listeners).Count -gt 0) {
        throw "Port $Port became occupied before launch; refusing to start another server."
    }

    $ocrEnabled = if ([string]$env:STUDENT_TEST_OCR_ENABLED -match '^(?i:1|true|yes|on)$') { "1" } else { "0" }
    $ocrAllowUnready = if ([string]$env:STUDENT_TEST_OCR_ALLOW_UNREADY_MODELS -match '^(?i:1|true|yes|on)$') { "1" } else { "0" }
    $ocrRuntimeRoot = if ([string]::IsNullOrWhiteSpace([string]$env:STUDENT_TEST_OCR_RUNTIME_ROOT)) {
        "C:\server-ocr"
    } else {
        [IO.Path]::GetFullPath([string]$env:STUDENT_TEST_OCR_RUNTIME_ROOT)
    }

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
        STUDENT_TEST_OCR_ENABLED = $ocrEnabled
        STUDENT_TEST_OCR_ALLOW_UNREADY_MODELS = $ocrAllowUnready
        STUDENT_TEST_OCR_RUNTIME_ROOT = $ocrRuntimeRoot
        STUDENT_TEST_OCR_ASSET_ROOT = (Join-Path $codeRoot "instance\student-test-ocr")
        STUDENT_TEST_OCR_SOLUTION_PDF_ROOT = (Join-Path $codeRoot ".codex_drive_download\unit_answer_pdfs")
        TRUST_PROXY_HEADERS = "0"
        ACADEMY_ISOLATED_KOLLUS_QA = if ($KollusVideoQa) { "1" } else { "0" }
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

    $wrapperStartTimeUtc = ""
    $listenerPid = 0
    $listenerStartTimeUtc = ""
    $receiptWritten = $false
    try {
        $wrapperStartTimeUtc = $wrapper.StartTime.ToUniversalTime().ToString("o")
        $deadline = (Get-Date).AddSeconds(20)
        $listener = $null
        do {
            Start-Sleep -Milliseconds 250
            $wrapper.Refresh()
            if ($wrapper.HasExited) { break }
            $startedListeners = @(Get-Listeners)
            if ($startedListeners.Count -gt 0) {
                $ownedListener = $null
                foreach ($candidate in $startedListeners) {
                    if ($candidate.LocalAddress -eq "127.0.0.1" -and
                        (Test-LaunchedProcess -ProcessId ([int]$candidate.OwningProcess) `
                            -WrapperProcessId ([int]$wrapper.Id) -WrapperStartTimeUtc $wrapperStartTimeUtc)) {
                        $ownedListener = $candidate
                        $listenerPid = [int]$candidate.OwningProcess
                        $listenerStartTimeUtc = Get-ProcessStartUtc -ProcessId $listenerPid
                        break
                    }
                }
                if ($startedListeners.Count -ne 1 -or -not $ownedListener) {
                    throw "Port $Port is not exclusively owned by the server launched by this invocation."
                }
                $listener = $ownedListener
            }
        } while (-not $listener -and (Get-Date) -lt $deadline)

        if (-not $listener) {
            $tail = if (Test-Path -LiteralPath $stderrPath -PathType Leaf) {
                (Get-Content -LiteralPath $stderrPath -Tail 20 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
            } else { "" }
            throw "Isolated Waitress did not start on port $Port. $tail"
        }

        if (-not $listenerStartTimeUtc) { throw "Cannot verify the launched listener's start time." }
        $httpStatus = Get-HttpStatus
        if ($httpStatus -ne 200) {
            throw "Isolated server started but /api/ping returned $httpStatus."
        }
        $confirmedListeners = @(Get-Listeners)
        if ($confirmedListeners.Count -ne 1 -or $confirmedListeners[0].LocalAddress -ne "127.0.0.1" -or
            [int]$confirmedListeners[0].OwningProcess -ne $listenerPid -or
            -not (Test-SameStartTime -ProcessId $listenerPid -ExpectedUtc $listenerStartTimeUtc) -or
            -not (Test-LaunchedProcess -ProcessId $listenerPid -WrapperProcessId ([int]$wrapper.Id) `
                -WrapperStartTimeUtc $wrapperStartTimeUtc)) {
            throw "Port $Port ownership changed before the isolated-server receipt could be recorded."
        }
        $receipt = [ordered]@{
            format = "academy-isolated-design-server/v1"
            startedAtUtc = [DateTime]::UtcNow.ToString("o")
            sourceRoot = $sourceRoot
            codeRoot = $codeRoot
            port = $Port
            wrapperProcessId = [int]$wrapper.Id
            wrapperStartTimeUtc = $wrapperStartTimeUtc
            listenerProcessId = $listenerPid
            listenerStartTimeUtc = $listenerStartTimeUtc
            liveRuntimeCopied = $false
            kollusVideoQaEnabled = [bool]$KollusVideoQa
            studentTestOcrEnabled = ($ocrEnabled -eq "1")
            studentTestOcrAllowUnreadyModels = ($ocrAllowUnready -eq "1")
        }
        Write-JsonFile -Path $receiptPath -Value $receipt
        $receiptWritten = $true

        $status = Get-ManagedStatus
        if (-not $status.managed -or $status.httpStatus -ne 200) {
            throw "Isolated server ownership or health changed after startup."
        }
        return $status
    } catch {
        $startupError = $_
        # Never use the current port owner as the target of startup cleanup.
        try {
            Stop-LaunchedServer -Wrapper $wrapper -WrapperStartTimeUtc $wrapperStartTimeUtc `
                -ListenerProcessId $listenerPid -ListenerStartTimeUtc $listenerStartTimeUtc
        } catch {
            Write-Warning "Could not clean up the launch-owned wrapper: $($_.Exception.Message)"
        }
        if ($receiptWritten) {
            try {
                $writtenReceipt = Read-Receipt
                $writtenWrapperStart = if (-not $writtenReceipt) { "" } elseif ($writtenReceipt.wrapperStartTimeUtc -is [DateTime]) {
                    ([DateTime]$writtenReceipt.wrapperStartTimeUtc).ToUniversalTime().ToString("o")
                } else { [string]$writtenReceipt.wrapperStartTimeUtc }
                $writtenListenerStart = if (-not $writtenReceipt) { "" } elseif ($writtenReceipt.listenerStartTimeUtc -is [DateTime]) {
                    ([DateTime]$writtenReceipt.listenerStartTimeUtc).ToUniversalTime().ToString("o")
                } else { [string]$writtenReceipt.listenerStartTimeUtc }
                if ($writtenReceipt -and [int]$writtenReceipt.port -eq $Port -and
                    [string]$writtenReceipt.codeRoot -eq $codeRoot -and
                    [int]$writtenReceipt.wrapperProcessId -eq [int]$wrapper.Id -and
                    $writtenWrapperStart -eq $wrapperStartTimeUtc -and
                    [int]$writtenReceipt.listenerProcessId -eq $listenerPid -and
                    $writtenListenerStart -eq $listenerStartTimeUtc) {
                    Remove-Item -LiteralPath $receiptPath -Force -ErrorAction Stop
                }
            } catch {
                Write-Warning "Could not remove the failed launch's receipt: $($_.Exception.Message)"
            }
        }
        throw $startupError
    }
}

Invoke-WithManagerLock {
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
}
