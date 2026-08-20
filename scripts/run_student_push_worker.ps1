param(
    [switch]$DryRun,
    [string]$PublicHostOverride = "",
    [ValidateSet("0", "1")][string]$PublicEnabledOverride = "",
    [ValidateSet("0", "1")][string]$RemindersEnabledOverride = "",
    [string]$CanarySidsOverride = "",
    [string]$VapidSubjectOverride = "",
    [string]$VapidPrivateKeyPathOverride = "",
    [string]$RuntimeRootOverride = "",
    [string]$ContractFixtureId = "",
    [switch]$DevelopmentIsolation
)

$ErrorActionPreference = "Stop"
$serverRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $serverRoot "venv\Scripts\python.exe"
$legacyWorkerPath = Join-Path $PSScriptRoot "deliver_student_push_outbox.py"
$reminderScannerPath = Join-Path $PSScriptRoot "enqueue_student_reminders.py"
$notificationWorkerPath = Join-Path $PSScriptRoot "deliver_student_notification_outbox.py"
$mutex = $null
$ownsMutex = $false
$isContractFixture = $PSBoundParameters.ContainsKey("ContractFixtureId")

if ($isContractFixture) {
    if (-not $DryRun -or $ContractFixtureId -notmatch '^[A-Za-z0-9_-]{8,64}$') {
        throw "ContractFixtureId requires DryRun and an opaque 8-64 character identifier."
    }
}

$workerMachineEnv = @(
    "STUDENT_APP_PUBLIC_ENABLED",
    "STUDENT_APP_PUBLIC_HOST",
    "STUDENT_APP_LEGACY_HOST",
    "STUDENT_APP_LEGACY_REDIRECT_ENABLED",
    "STUDENT_APP_TRUSTED_PROXIES",
    "STUDENT_APP_CANARY_SIDS",
    "STUDENT_APP_REMINDERS_ENABLED",
    "STUDENT_APP_FOCUS_ENABLED",
    "STUDENT_APP_VAPID_SUBJECT",
    "STUDENT_APP_VAPID_PRIVATE_KEY_PATH",
    "STUDENT_APP_PUSH_ENDPOINT_ALLOWLIST",
    "STUDENT_APP_RUNTIME_ROOT",
    "STUDENT_APP_ACCOUNTS_PATH",
    "STUDENT_APP_STUDENTS_PATH",
    "STUDENT_APP_DB_PATH",
    "STUDENT_APP_LOGS_PATH",
    "STUDENT_APP_ABSENT_PATH",
    "STUDENT_APP_EXTRA_PATH",
    "STUDENT_APP_WEEKEND_PATH",
    "STUDENT_APP_MAKEUP_PATH"
)

if ($DevelopmentIsolation -or $isContractFixture) {
    foreach ($name in $workerMachineEnv) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }
    $env:STUDENT_APP_PUBLIC_ENABLED = "0"
    $env:STUDENT_APP_LEGACY_REDIRECT_ENABLED = "0"
    $env:STUDENT_APP_TRUSTED_PROXIES = "127.0.0.1/32"
    $env:STUDENT_APP_REMINDERS_ENABLED = "0"
    $env:STUDENT_APP_FOCUS_ENABLED = "0"
} else {
    foreach ($name in $workerMachineEnv) {
        $value = [Environment]::GetEnvironmentVariable($name, "Machine")
        if ($null -ne $value) {
            Set-Item -LiteralPath "Env:$name" -Value $value
        } else {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        }
    }
}

if ($PublicHostOverride) {
    $normalizedPublicHost = $PublicHostOverride.Trim().ToLowerInvariant()
    if ($normalizedPublicHost -notmatch '^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$') {
        throw "PublicHostOverride must be an exact DNS hostname."
    }
    $env:STUDENT_APP_PUBLIC_HOST = $normalizedPublicHost
}
if ($PSBoundParameters.ContainsKey("PublicEnabledOverride")) {
    $env:STUDENT_APP_PUBLIC_ENABLED = $PublicEnabledOverride
}
if ($PSBoundParameters.ContainsKey("RemindersEnabledOverride")) {
    $env:STUDENT_APP_REMINDERS_ENABLED = $RemindersEnabledOverride
}
if ($PSBoundParameters.ContainsKey("CanarySidsOverride")) {
    $env:STUDENT_APP_CANARY_SIDS = $CanarySidsOverride
}
if ($PSBoundParameters.ContainsKey("VapidSubjectOverride") -xor $PSBoundParameters.ContainsKey("VapidPrivateKeyPathOverride")) {
    throw "VAPID overrides must be provided together."
}
if ($PSBoundParameters.ContainsKey("VapidSubjectOverride")) {
    $vapidSubject = $VapidSubjectOverride.Trim()
    $vapidSubjectUri = $null
    $isHttpsSubject = [Uri]::TryCreate($vapidSubject, [UriKind]::Absolute, [ref]$vapidSubjectUri) -and
        $vapidSubjectUri.Scheme -eq "https" -and -not [string]::IsNullOrWhiteSpace($vapidSubjectUri.Host)
    $isMailtoSubject = $vapidSubject -match '^mailto:[^@\s]+@[^@\s]+$'
    if (-not ($isHttpsSubject -or $isMailtoSubject)) {
        throw "VapidSubjectOverride must be an HTTPS URL or mailto address."
    }
    $vapidPrivateKeyPath = [IO.Path]::GetFullPath($VapidPrivateKeyPathOverride)
    if (-not (Test-Path -LiteralPath $vapidPrivateKeyPath -PathType Leaf)) {
        throw "VapidPrivateKeyPathOverride must be an existing file."
    }
    if ($DevelopmentIsolation) {
        $developmentInstancePrefix = [IO.Path]::GetFullPath((Join-Path $serverRoot "instance")).TrimEnd("\") + "\"
        if (-not $vapidPrivateKeyPath.StartsWith($developmentInstancePrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Development VAPID keys must stay inside the repository instance directory."
        }
    }
    $env:STUDENT_APP_VAPID_SUBJECT = $vapidSubject
    $env:STUDENT_APP_VAPID_PRIVATE_KEY_PATH = $vapidPrivateKeyPath
}

if ($RuntimeRootOverride) {
    $runtimeRoot = [IO.Path]::GetFullPath($RuntimeRootOverride)
    if (-not (Test-Path -LiteralPath $runtimeRoot -PathType Container)) {
        throw "RuntimeRootOverride must be an existing directory."
    }
    $runtimeFiles = @{
        "STUDENT_APP_RUNTIME_ROOT" = $runtimeRoot
        "STUDENT_APP_ACCOUNTS_PATH" = Join-Path $runtimeRoot "auth_accounts.json"
        "STUDENT_APP_STUDENTS_PATH" = Join-Path $runtimeRoot "students.json"
        "STUDENT_APP_DB_PATH" = Join-Path $runtimeRoot "app.sqlite"
        "STUDENT_APP_LOGS_PATH" = Join-Path $runtimeRoot "logs.json"
        "STUDENT_APP_ABSENT_PATH" = Join-Path $runtimeRoot "absent.json"
        "STUDENT_APP_EXTRA_PATH" = Join-Path $runtimeRoot "extra_attend.json"
        "STUDENT_APP_WEEKEND_PATH" = Join-Path $runtimeRoot "weekend_slots.json"
        "STUDENT_APP_MAKEUP_PATH" = Join-Path $runtimeRoot "makeup_carryover.json"
    }
    foreach ($entry in $runtimeFiles.GetEnumerator()) {
        Set-Item -LiteralPath "Env:$($entry.Key)" -Value $entry.Value
    }
}

if ($DevelopmentIsolation) {
    if ($env:STUDENT_APP_PUBLIC_HOST -ne "dev-app.5a-math.com" -or
        $env:STUDENT_APP_PUBLIC_ENABLED -ne "1" -or
        [string]::IsNullOrWhiteSpace($env:STUDENT_APP_CANARY_SIDS) -or
        [string]::IsNullOrWhiteSpace($env:STUDENT_APP_VAPID_SUBJECT) -or
        [string]::IsNullOrWhiteSpace($env:STUDENT_APP_VAPID_PRIVATE_KEY_PATH) -or
        [IO.Path]::GetFullPath($env:STUDENT_APP_RUNTIME_ROOT) -ne [IO.Path]::GetFullPath($serverRoot)) {
        throw "Development worker isolation requires the dev host, public canary, repository runtime, and dev VAPID pair."
    }
}

try {
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "The server virtual-environment Python is unavailable."
    }
    foreach ($workerPath in @($legacyWorkerPath, $reminderScannerPath, $notificationWorkerPath)) {
        if (-not (Test-Path -LiteralPath $workerPath -PathType Leaf)) {
            throw "A student notification worker is unavailable."
        }
    }

    $mutexName = if ($isContractFixture) {
        "Local\AcademyStudentPushDelivery-ContractFixture-$ContractFixtureId"
    } else {
        "Global\AcademyStudentPushDelivery-v1"
    }
    $mutex = [Threading.Mutex]::new($false, $mutexName)
    try {
        $ownsMutex = $mutex.WaitOne(0)
    } catch [Threading.AbandonedMutexException] {
        $ownsMutex = $true
    }
    if (-not $ownsMutex) {
        Write-Output '{"ok":false,"code":"worker_overlap"}'
        exit 3
    }

    if ($DryRun) {
        $summary = [ordered]@{
            ok = $true
            mode = "dry-run"
            contractFixture = [bool]$isContractFixture
            developmentIsolation = [bool]$DevelopmentIsolation
            publicEnabled = [string]$env:STUDENT_APP_PUBLIC_ENABLED
            remindersEnabled = [string]$env:STUDENT_APP_REMINDERS_ENABLED
            canaryConfigured = -not [string]::IsNullOrWhiteSpace($env:STUDENT_APP_CANARY_SIDS)
            vapidConfigured = -not [string]::IsNullOrWhiteSpace($env:STUDENT_APP_VAPID_PRIVATE_KEY_PATH)
            commands = @(
                "venv-python deliver_student_push_outbox.py --once",
                "venv-python enqueue_student_reminders.py --once",
                "venv-python deliver_student_notification_outbox.py --once"
            )
        }
        Write-Output ($summary | ConvertTo-Json -Compress)
        exit 0
    }

    Set-Location -LiteralPath $serverRoot
    $exitCode = 0
    foreach ($workerPath in @($legacyWorkerPath, $reminderScannerPath, $notificationWorkerPath)) {
        & $pythonPath $workerPath --once
        if ($LASTEXITCODE -ne 0) {
            $exitCode = 1
        }
    }
    exit $exitCode
} finally {
    if ($ownsMutex -and $null -ne $mutex) {
        $mutex.ReleaseMutex()
    }
    if ($null -ne $mutex) {
        $mutex.Dispose()
    }
}
