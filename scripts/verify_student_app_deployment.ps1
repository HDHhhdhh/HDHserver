param(
    [switch]$DryRun,
    [ValidateSet("Preflight", "Canary", "Expanded")][string]$Phase = "Preflight",
    [switch]$RolloutApproved,
    [ValidateSet("app.5a-math.com", "dev-app.5a-math.com")][string]$PublicHost = "app.5a-math.com",
    [string]$Root = "",
    [string]$EnvironmentFile = "",
    [string]$PrivateKeyPath = "",
    [string]$PythonSnapshotPath = "",
    [string]$KeyPolicySnapshotPath = "",
    [string]$TaskXmlPath = "",
    [string]$TunnelConfigPath = "",
    [string]$ListenerSnapshotPath = "",
    [string]$HealthSnapshotPath = "",
    [switch]$FixtureMode
)

$ErrorActionPreference = "Stop"; $serverRoot = if ($Root) { [IO.Path]::GetFullPath($Root) } else { Split-Path -Parent $PSScriptRoot }
$originPort = if ($PublicHost -eq "dev-app.5a-math.com") { 8004 } else { 8003 }
$results = [Collections.Generic.List[object]]::new()
$blocked = $false
$failed = $false

function Add-Check([string]$Name, [string]$Status, [string]$Code) {
    $script:results.Add([ordered]@{ name = $Name; status = $Status; code = $Code })
    if ($Status -eq "BLOCKED") { $script:blocked = $true }
    if ($Status -eq "FAIL") { $script:failed = $true }
}

function Read-Environment {
    $values = @{}
    if ($EnvironmentFile) {
        if (-not (Test-Path -LiteralPath $EnvironmentFile -PathType Leaf)) { return $values }
        foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $EnvironmentFile) {
            if ($line -match '^([A-Z0-9_]+)=(.*)$') { $values[$Matches[1]] = $Matches[2] }
        }
        return $values
    }
    foreach ($name in @(
        "STUDENT_APP_PUBLIC_ENABLED", "STUDENT_APP_PUBLIC_HOST", "STUDENT_APP_LEGACY_HOST", "STUDENT_APP_LEGACY_REDIRECT_ENABLED", "STUDENT_APP_TRUSTED_PROXIES",
        "STUDENT_APP_CANARY_SIDS", "STUDENT_APP_SESSION_COOKIE_SECURE", "STUDENT_APP_SESSION_SAMESITE",
        "STUDENT_APP_VAPID_SUBJECT", "STUDENT_APP_VAPID_PRIVATE_KEY_PATH", "ACADEMY_ADMIN_USERNAME",
        "ACADEMY_ADMIN_PASSWORD_HASH", "TRUST_PROXY_HEADERS"
    )) { $values[$name] = [Environment]::GetEnvironmentVariable($name, "Process") }
    return $values
}

function Test-KeyAcl([string]$Path) {
    try {
        $acl = Get-Acl -LiteralPath $Path
        $broad = @("S-1-1-0", "S-1-5-11", "S-1-5-32-545", "S-1-5-32-546")
        foreach ($rule in $acl.Access) {
            if ($rule.AccessControlType -ne "Allow") { continue }
            try { $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value }
            catch { $sid = $rule.IdentityReference.Value }
            if ($broad -contains $sid) { return $false }
        }
        return $true
    } catch { return $false }
}

function Test-PrivateKey([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Add-Check "vapid_private_key" "BLOCKED" "BLOCKED_NO_VAPID_KEY"; return
    }
    if (-not $FixtureMode -and [IO.Path]::GetFullPath($Path) -ne [IO.Path]::GetFullPath((Join-Path $serverRoot "instance\student-app-vapid-private.pem"))) {
        Add-Check "vapid_private_key" "FAIL" "FAIL_VAPID_KEY_PATH"; return
    }
    if ($FixtureMode -and $KeyPolicySnapshotPath) {
        $policy = Get-Content -Raw -Encoding UTF8 -LiteralPath $KeyPolicySnapshotPath | ConvertFrom-Json
        if (-not $policy.aclPrivate) { Add-Check "vapid_private_key" "FAIL" "FAIL_VAPID_KEY_ACL"; return }
        if ($policy.tracked) { Add-Check "vapid_private_key" "FAIL" "FAIL_VAPID_KEY_TRACKED"; return }
        if (-not $policy.ignored) { Add-Check "vapid_private_key" "FAIL" "FAIL_VAPID_KEY_NOT_IGNORED"; return }
        Add-Check "vapid_private_key" "PASS" "KEY_PRIVATE_NONTRACKED"; return
    }
    if (-not (Test-KeyAcl $Path)) {
        Add-Check "vapid_private_key" "FAIL" "FAIL_VAPID_KEY_ACL"; return
    }
    $full = [IO.Path]::GetFullPath($Path)
    $rootPrefix = $serverRoot.TrimEnd('\') + '\'
    if ($full.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        $relative = $full.Substring($rootPrefix.Length).Replace('\', '/')
        $tracked = @(& git -C $serverRoot ls-files -- $relative)
        if ($LASTEXITCODE -ne 0) { Add-Check "vapid_private_key" "FAIL" "FAIL_VAPID_KEY_TRACKED"; return }
        if ($tracked.Count -gt 0) { Add-Check "vapid_private_key" "FAIL" "FAIL_VAPID_KEY_TRACKED"; return }
        & git -C $serverRoot check-ignore -q -- $relative
        if ($LASTEXITCODE -ne 0) { Add-Check "vapid_private_key" "FAIL" "FAIL_VAPID_KEY_NOT_IGNORED"; return }
    }
    Add-Check "vapid_private_key" "PASS" "KEY_PRIVATE_NONTRACKED"
}

function Test-Python {
    if ($FixtureMode -and $PythonSnapshotPath) {
        $pythonState = Get-Content -Raw -Encoding UTF8 -LiteralPath $PythonSnapshotPath | ConvertFrom-Json
        if (-not $pythonState.exists) { Add-Check "python_dependency" "BLOCKED" "BLOCKED_NO_VENV_PYTHON"; return }
        if (-not $pythonState.pywebpush) { Add-Check "python_dependency" "BLOCKED" "BLOCKED_NO_PYWEBPUSH"; return }
        if ($pythonState.version -ne "3.12" -or $pythonState.pywebpush -ne "2.3.0") {
            Add-Check "python_dependency" "FAIL" "FAIL_PYTHON_OR_PYWEBPUSH_VERSION"; return
        }
        Add-Check "python_dependency" "PASS" "PYTHON_3_12_PYWEBPUSH_2_3_0"; return
    }
    $python = Join-Path $serverRoot "venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        Add-Check "python_dependency" "BLOCKED" "BLOCKED_NO_VENV_PYTHON"; return
    }
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        $probe = & $python -c "import importlib.metadata as m,sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor)+'|'+m.version('pywebpush'))" 2>$null
        $probeExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($probeExit -ne 0) { Add-Check "python_dependency" "BLOCKED" "BLOCKED_NO_PYWEBPUSH"; return }
    if (($probe | Select-Object -Last 1) -ne "3.12|2.3.0") {
        Add-Check "python_dependency" "FAIL" "FAIL_PYTHON_OR_PYWEBPUSH_VERSION"; return
    }
    Add-Check "python_dependency" "PASS" "PYTHON_3_12_PYWEBPUSH_2_3_0"
}

function Test-Environment([hashtable]$EnvMap) {
    $required = @(
        "STUDENT_APP_PUBLIC_ENABLED", "STUDENT_APP_PUBLIC_HOST", "STUDENT_APP_LEGACY_HOST", "STUDENT_APP_LEGACY_REDIRECT_ENABLED", "STUDENT_APP_TRUSTED_PROXIES",
        "STUDENT_APP_CANARY_SIDS", "STUDENT_APP_SESSION_COOKIE_SECURE", "STUDENT_APP_SESSION_SAMESITE",
        "STUDENT_APP_VAPID_SUBJECT", "STUDENT_APP_VAPID_PRIVATE_KEY_PATH", "ACADEMY_ADMIN_USERNAME",
        "ACADEMY_ADMIN_PASSWORD_HASH", "TRUST_PROXY_HEADERS"
    )
    if ($required.Where({ -not $EnvMap.ContainsKey($_) -or ($_ -ne "STUDENT_APP_CANARY_SIDS" -and [string]::IsNullOrWhiteSpace($EnvMap[$_])) }).Count) {
        Add-Check "environment" "BLOCKED" "BLOCKED_MISSING_ENV_NAMES"; return
    }
    $enabled = $EnvMap["STUDENT_APP_PUBLIC_ENABLED"] -in @("1", "true", "yes", "on"); $legacyRedirect = $EnvMap["STUDENT_APP_LEGACY_REDIRECT_ENABLED"] -in @("1", "true", "yes", "on")
    $canary = $EnvMap["STUDENT_APP_CANARY_SIDS"]
    $proxySet = @($EnvMap["STUDENT_APP_TRUSTED_PROXIES"] -split '[,;\s]+' | Where-Object { $_ })
    $proxyOkay = $proxySet.Count -eq 2 -and $proxySet -contains "127.0.0.1/32" -and $proxySet -contains "::1/128"
    $phaseOkay = ($Phase -eq "Preflight" -and -not $enabled -and -not $legacyRedirect -and $canary) -or
        ($Phase -eq "Canary" -and $enabled -and -not $legacyRedirect -and $canary) -or
        ($Phase -eq "Expanded" -and $enabled -and $legacyRedirect -and -not $canary -and $RolloutApproved)
    $keyMatches = $false
    try { $keyMatches = [IO.Path]::GetFullPath($EnvMap["STUDENT_APP_VAPID_PRIVATE_KEY_PATH"]) -eq [IO.Path]::GetFullPath($PrivateKeyPath) } catch {}
    $adminHashOkay = $EnvMap["ACADEMY_ADMIN_PASSWORD_HASH"] -match '^(scrypt|pbkdf2):'
    $valid = $phaseOkay -and $proxyOkay -and $keyMatches -and
        $adminHashOkay -and
        $EnvMap["STUDENT_APP_PUBLIC_HOST"].ToLowerInvariant() -eq $PublicHost -and $EnvMap["STUDENT_APP_LEGACY_HOST"].ToLowerInvariant() -eq "5a-math.com" -and
        $EnvMap["TRUST_PROXY_HEADERS"] -eq "1" -and
        $EnvMap["STUDENT_APP_SESSION_COOKIE_SECURE"] -eq "1" -and
        $EnvMap["STUDENT_APP_SESSION_SAMESITE"] -eq "Lax" -and
        $EnvMap["STUDENT_APP_VAPID_SUBJECT"].StartsWith("mailto:")
    if ($valid) { Add-Check "environment" "PASS" "ENV_PHASE_VALID" }
    else { Add-Check "environment" "FAIL" "FAIL_ENV_OR_ROLLOUT_GATE" }
}

function Test-Task {
    try {
        if ($TaskXmlPath) { $xmlText = Get-Content -Raw -Encoding UTF8 -LiteralPath $TaskXmlPath }
        else {
            $task = Get-ScheduledTask -TaskName "Academy Student Push Delivery" -ErrorAction Stop
            $xmlText = Export-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath
        }
    } catch { Add-Check "scheduled_task" "BLOCKED" "BLOCKED_NO_PUSH_TASK"; return }
    try {
        [xml]$taskDocument = $xmlText
        $exec = $taskDocument.SelectSingleNode("//*[local-name()='Exec']")
        $runnerPath = Join-Path $serverRoot "scripts\run_student_push_worker.ps1"
        $expectedArguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runnerPath`""
        $actionOkay = [IO.Path]::GetFileName([string]$exec.Command) -eq "powershell.exe" -and
            ([string]$exec.Arguments).Trim() -eq $expectedArguments -and
            [IO.Path]::GetFullPath([string]$exec.WorkingDirectory) -eq [IO.Path]::GetFullPath($serverRoot)
    } catch { $actionOkay = $false }
    $valid = $actionOkay -and $xmlText -match '(?i)<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>' -and
        $xmlText -match '(?i)<Interval>PT1M</Interval>'
    if ($valid) { Add-Check "scheduled_task" "PASS" "TASK_ONCE_PER_MINUTE_IGNORE_NEW" }
    else { Add-Check "scheduled_task" "FAIL" "FAIL_PUSH_TASK_CONTRACT" }
}

function Test-Tunnel {
    if (-not $TunnelConfigPath -or -not (Test-Path -LiteralPath $TunnelConfigPath -PathType Leaf)) {
        Add-Check "cloudflare_tunnel" "BLOCKED" "BLOCKED_NO_CLOUDFLARE_AUTH"; return
    }
    $yaml = Get-Content -Raw -Encoding UTF8 -LiteralPath $TunnelConfigPath
    $credentialMatch = [regex]::Match($yaml, '(?im)^\s*credentials-file:\s*["'']?([^"''\r\n]+)')
    if (-not $credentialMatch.Success) { Add-Check "cloudflare_tunnel" "BLOCKED" "BLOCKED_NO_CLOUDFLARE_AUTH"; return }
    $credentialPath = $credentialMatch.Groups[1].Value.Trim()
    if (-not [IO.Path]::IsPathRooted($credentialPath)) { $credentialPath = Join-Path (Split-Path -Parent $TunnelConfigPath) $credentialPath }
    if (-not (Test-Path -LiteralPath $credentialPath -PathType Leaf)) { Add-Check "cloudflare_tunnel" "BLOCKED" "BLOCKED_NO_CLOUDFLARE_AUTH"; return }
    $mapping = $yaml -match "(?im)^\s*-\s*hostname:\s*$([regex]::Escape($PublicHost))\s*\r?\n\s*service:\s*http://127\.0\.0\.1:$originPort\s*$" -and
        $yaml.TrimEnd() -match '(?i)-\s*service:\s*http_status:404\s*$'
    if (-not $mapping) { Add-Check "cloudflare_tunnel" "FAIL" "FAIL_TUNNEL_MAPPING"; return }
    if (-not $FixtureMode -and -not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
        Add-Check "cloudflare_tunnel" "BLOCKED" "BLOCKED_NO_CLOUDFLARED"; return
    }
    Add-Check "cloudflare_tunnel" "PASS" "TUNNEL_MAPPING_EXACT"
}

function Test-ListenerAndHealth {
    if ($ListenerSnapshotPath) { $listener = Get-Content -Raw -Encoding UTF8 -LiteralPath $ListenerSnapshotPath | ConvertFrom-Json }
    else {
        $connections = @(Get-NetTCPConnection -LocalPort $originPort -State Listen -ErrorAction SilentlyContinue)
        $listener = [pscustomobject]@{ port = $originPort; processCount = @($connections.OwningProcess | Select-Object -Unique).Count }
    }
    if ($listener.port -ne $originPort -or $listener.processCount -ne 1) {
        Add-Check "listener" "BLOCKED" "BLOCKED_PORT_8003_DOWN"; return
    }
    Add-Check "listener" "PASS" "SINGLE_LISTENER_8003"
    if ($HealthSnapshotPath) { $health = Get-Content -Raw -Encoding UTF8 -LiteralPath $HealthSnapshotPath | ConvertFrom-Json }
    else {
        try {
            Add-Type -AssemblyName System.Net.Http -ErrorAction Stop
            $client = [Net.Http.HttpClient]::new()
            $request = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get, "http://127.0.0.1:$originPort/app")
            $request.Headers.Host = $PublicHost; $null = $request.Headers.TryAddWithoutValidation("X-Forwarded-Proto", "https")
            $null = $request.Headers.TryAddWithoutValidation("CF-Connecting-IP", "8.8.8.8")
            $response = $client.SendAsync($request).GetAwaiter().GetResult()
            $health = [pscustomobject]@{ host = $PublicHost; scheme = "https"; status = [int]$response.StatusCode; cacheControl = ($response.Headers.CacheControl.ToString()) }
            $request.Dispose(); $response.Dispose(); $client.Dispose()
        } catch { Add-Check "public_host_health" "BLOCKED" "BLOCKED_ORIGIN_HEALTH"; return }
    }
    $expected = if ($Phase -eq "Preflight") { 404 } else { 200 }
    $valid = $health.host -eq $PublicHost -and $health.scheme -eq "https" -and $health.status -eq $expected
    if ($expected -eq 200) { $valid = $valid -and $health.cacheControl -match 'no-store' }
    if ($valid) { Add-Check "public_host_health" "PASS" "PUBLIC_HOST_PHASE_HEALTH" }
    else { Add-Check "public_host_health" "FAIL" "FAIL_PUBLIC_HOST_HEALTH" }
    if ($Phase -eq "Preflight") { Add-Check "public_tls" "PASS" "PUBLIC_TLS_DEFERRED_WHILE_OFF"; return }
    if ($FixtureMode) {
        if ($health.externalStatus -eq 200 -and $health.externalScheme -eq "https" -and $health.externalHost -eq $PublicHost) {
            Add-Check "public_tls" "PASS" "PUBLIC_TLS_HEALTH"; return
        }
        Add-Check "public_tls" "FAIL" "FAIL_PUBLIC_TLS_HEALTH"; return
    }
    try {
        $external = Invoke-WebRequest -UseBasicParsing -Uri "https://$PublicHost/app" -Method Get -MaximumRedirection 0 -TimeoutSec 10
        $tlsValid = [int]$external.StatusCode -eq 200 -and $external.BaseResponse.ResponseUri.Scheme -eq "https" -and
            $external.BaseResponse.ResponseUri.Host -eq $PublicHost -and $external.Headers["Cache-Control"] -match 'no-store'
        if ($tlsValid) { Add-Check "public_tls" "PASS" "PUBLIC_TLS_HEALTH" }
        else { Add-Check "public_tls" "FAIL" "FAIL_PUBLIC_TLS_HEALTH" }
    } catch { Add-Check "public_tls" "BLOCKED" "BLOCKED_TUNNEL_UNREACHABLE" }
}

if (-not $DryRun) { Add-Check "mode" "FAIL" "FAIL_DRY_RUN_REQUIRED" }
else { Add-Check "mode" "PASS" $(if ($FixtureMode) { "DRY_RUN_FIXTURE" } else { "DRY_RUN_LIVE_READ_ONLY" }) }
$environment = Read-Environment
if (-not $PrivateKeyPath -and $environment.ContainsKey("STUDENT_APP_VAPID_PRIVATE_KEY_PATH")) { $PrivateKeyPath = $environment["STUDENT_APP_VAPID_PRIVATE_KEY_PATH"] }
Test-Python
Test-Environment $environment
Test-PrivateKey $PrivateKeyPath
Test-Task
Test-Tunnel
Test-ListenerAndHealth
$status = if ($failed) { "FAIL" } elseif ($blocked) { "BLOCKED" } else { "PASS" }
[ordered]@{ status = $status; phase = $Phase; fixture = [bool]$FixtureMode; checks = $results } | ConvertTo-Json -Depth 5 -Compress
if ($failed) { exit 2 }
if ($blocked) { exit 3 }
exit 0
