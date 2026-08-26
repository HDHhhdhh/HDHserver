param(
    [string]$Listen = "0.0.0.0:8003",
    [int]$Threads = 16,
    [int]$ConnectionLimit = 400,
    [int]$ChannelTimeout = 60,
    [string]$PublicHostOverride = "",
    [ValidateSet("0", "1")][string]$PublicEnabledOverride = "",
    [ValidateSet("0", "1")][string]$DashboardEnabledOverride = "",
    [ValidateSet("0", "1")][string]$HomeworkEnabledOverride = "",
    [ValidateSet("0", "1")][string]$RemindersEnabledOverride = "",
    [ValidateSet("0", "1")][string]$FocusEnabledOverride = "",
    [string]$CanarySidsOverride = "",
    [string]$VapidSubjectOverride = "",
    [string]$VapidPrivateKeyPathOverride = "",
    [string]$RuntimeRootOverride = "",
    [switch]$DevelopmentIsolation
)

$ErrorActionPreference = "Stop"
$serverRoot = Split-Path -Parent $PSScriptRoot

$studentAppMachineEnv = @(
    "STUDENT_APP_PUBLIC_ENABLED", "STUDENT_APP_PUBLIC_HOST",
    "STUDENT_APP_LEGACY_HOST", "STUDENT_APP_LEGACY_REDIRECT_ENABLED",
    "STUDENT_APP_TRUSTED_PROXIES", "STUDENT_APP_CANARY_SIDS",
    "STUDENT_APP_SESSION_COOKIE_SECURE", "STUDENT_APP_SESSION_SAMESITE",
    "STUDENT_APP_DASHBOARD_ENABLED", "STUDENT_APP_HOMEWORK_ENABLED",
    "STUDENT_APP_REMINDERS_ENABLED", "STUDENT_APP_FOCUS_ENABLED",
    "STUDENT_APP_VAPID_SUBJECT", "STUDENT_APP_VAPID_PRIVATE_KEY_PATH",
    "ACADEMY_ADMIN_USERNAME", "ACADEMY_ADMIN_PASSWORD_HASH",
    "TRUST_PROXY_HEADERS"
)

if ($DevelopmentIsolation) {
    $isolationEnv = $studentAppMachineEnv + @(
        "STUDENT_APP_VAPID_PRIVATE_KEY",
        "STUDENT_APP_PUSH_ENDPOINT_ALLOWLIST",
        "STUDENT_APP_TEST_INSECURE_COOKIE",
        "STUDENT_APP_ALLOW_INSECURE_COOKIE_FOR_TESTS",
        "STUDENT_APP_INSECURE_COOKIE_FOR_TESTS"
    )
    foreach ($name in $isolationEnv) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }
    $env:STUDENT_APP_PUBLIC_ENABLED = "0"
    $env:STUDENT_APP_LEGACY_REDIRECT_ENABLED = "0"
    $env:STUDENT_APP_TRUSTED_PROXIES = "127.0.0.1/32"
    $env:STUDENT_APP_SESSION_COOKIE_SECURE = "1"
    $env:STUDENT_APP_SESSION_SAMESITE = "Lax"
    $env:STUDENT_APP_DASHBOARD_ENABLED = "0"
    $env:STUDENT_APP_HOMEWORK_ENABLED = "0"
    $env:STUDENT_APP_REMINDERS_ENABLED = "0"
    $env:STUDENT_APP_FOCUS_ENABLED = "0"
    # The public-surface policy requires ProxyFix provenance. Waitress first
    # filters proxy headers to the loopback tunnel, then ProxyFix records the
    # original peer/scheme values consumed by the Flask boundary.
    $env:TRUST_PROXY_HEADERS = "1"
    foreach ($name in @("ACADEMY_ADMIN_USERNAME", "ACADEMY_ADMIN_PASSWORD_HASH")) {
        $value = [Environment]::GetEnvironmentVariable($name, "Machine")
        if ($null -ne $value) {
            Set-Item -LiteralPath "Env:$name" -Value $value
        }
    }
} else {
    foreach ($name in $studentAppMachineEnv) {
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
if ($PSBoundParameters.ContainsKey("DashboardEnabledOverride")) {
    $env:STUDENT_APP_DASHBOARD_ENABLED = $DashboardEnabledOverride
}
if ($PSBoundParameters.ContainsKey("HomeworkEnabledOverride")) {
    $env:STUDENT_APP_HOMEWORK_ENABLED = $HomeworkEnabledOverride
}
if ($PSBoundParameters.ContainsKey("RemindersEnabledOverride")) {
    $env:STUDENT_APP_REMINDERS_ENABLED = $RemindersEnabledOverride
}
if ($PSBoundParameters.ContainsKey("FocusEnabledOverride")) {
    $env:STUDENT_APP_FOCUS_ENABLED = $FocusEnabledOverride
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
        $developmentInstanceRoot = [IO.Path]::GetFullPath((Join-Path $serverRoot "instance"))
        $developmentInstancePrefix = $developmentInstanceRoot.TrimEnd("\") + "\"
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
        throw "RuntimeRootOverride must be an existing directory: $runtimeRoot"
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

$authSecret = [Environment]::GetEnvironmentVariable("AUTH_SECRET", "Machine")
if ([string]::IsNullOrWhiteSpace($authSecret) -or $authSecret -eq "CHANGE_ME_AUTH_SECRET") {
    $authSecret = [Environment]::GetEnvironmentVariable("AUTH_SECRET", "User")
}
if ([string]::IsNullOrWhiteSpace($authSecret) -or $authSecret -eq "CHANGE_ME_AUTH_SECRET") {
    Remove-Item -LiteralPath "Env:AUTH_SECRET" -ErrorAction SilentlyContinue
    throw "AUTH_SECRET Machine or User environment variable must contain a persistent secret."
}
Set-Item -LiteralPath "Env:AUTH_SECRET" -Value $authSecret

$masterPassword = [Environment]::GetEnvironmentVariable("MASTER_PW", "Machine")
if ([string]::IsNullOrWhiteSpace($masterPassword)) {
    $masterPassword = [Environment]::GetEnvironmentVariable("MASTER_PW", "User")
}
if ([string]::IsNullOrWhiteSpace($masterPassword)) {
    Remove-Item -LiteralPath "Env:MASTER_PW" -ErrorAction SilentlyContinue
} else {
    Set-Item -LiteralPath "Env:MASTER_PW" -Value $masterPassword
}

$kollusCallbackSecret = [Environment]::GetEnvironmentVariable("KOLLUS_CALLBACK_SECRET", "Machine")
if ([string]::IsNullOrWhiteSpace($kollusCallbackSecret)) {
    $kollusCallbackSecret = [Environment]::GetEnvironmentVariable("KOLLUS_CALLBACK_SECRET", "User")
}
if ([string]::IsNullOrWhiteSpace($kollusCallbackSecret) -or $kollusCallbackSecret.Length -lt 32) {
    Remove-Item -LiteralPath "Env:KOLLUS_CALLBACK_SECRET" -ErrorAction SilentlyContinue
    if ($env:STUDENT_APP_PUBLIC_ENABLED -eq "1") {
        throw "KOLLUS_CALLBACK_SECRET Machine or User environment variable must contain at least 32 characters."
    }
} else {
    Set-Item -LiteralPath "Env:KOLLUS_CALLBACK_SECRET" -Value $kollusCallbackSecret
}

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
$shadowGuard = $null
if ($Listen -eq "0.0.0.0:8003") {
    # Windows may allow a later 127.0.0.1 bind beside this wildcard socket;
    # Cloudflare would then route production traffic to that shadow listener.
    $guardPath = Join-Path $PSScriptRoot "guard_waitress_shadow_listener.ps1"
    if (Test-Path -LiteralPath $guardPath -PathType Leaf) {
        try {
            $parentStartTicks = (Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks
            $windowsPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
            $guardArguments = @(
                "-NoProfile"
                "-WindowStyle Hidden"
                "-ExecutionPolicy Bypass"
                "-File `"$guardPath`""
                "-Port $listenPort"
                "-ParentProcessId $PID"
                "-ParentStartTimeUtcTicks $parentStartTicks"
                "-ServerRoot `"$serverRoot`""
            ) -join " "
            $shadowGuard = Start-Process `
                -FilePath $windowsPowerShell `
                -ArgumentList $guardArguments `
                -WindowStyle Hidden `
                -PassThru
        } catch {
            Write-Warning "Waitress shadow-listener guard could not start: $($_.Exception.Message)"
        }
    }
}

$waitressExitCode = 1
try {
    & $waitressPath `
        "--listen=$Listen" `
        "--threads=$Threads" `
        "--connection-limit=$ConnectionLimit" `
        "--channel-timeout=$ChannelTimeout" `
        "--cleanup-interval=15" `
        "--channel-request-lookahead=1" `
        "--trusted-proxy=127.0.0.1" `
        "--trusted-proxy-count=1" `
        "--trusted-proxy-headers=x-forwarded-proto" `
        "--clear-untrusted-proxy-headers" `
        "app:app"
    $waitressExitCode = $LASTEXITCODE
} finally {
    if ($shadowGuard -and -not $shadowGuard.HasExited) {
        Stop-Process -Id $shadowGuard.Id -Force -ErrorAction SilentlyContinue
    }
}
exit $waitressExitCode
