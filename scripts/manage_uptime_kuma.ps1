[CmdletBinding()]
param([ValidateSet('Install','Start','Stop','Status','Configure','EnableAutoStart','DisableAutoStart')][string]$Action = 'Status')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$serviceRoot = Join-Path $repository 'instance\uptime-kuma'
$appRoot = Join-Path $serviceRoot 'app'
$dataRoot = Join-Path $serviceRoot 'data'
$receiptFile = Join-Path $serviceRoot 'process.json'
$credentialFile = Join-Path $serviceRoot 'credential.clixml'
$taskName = 'Academy-Uptime-Kuma-Local'
$version = '2.5.7'
$commit = 'd54e4619e52553416e292549f435cc7e57330c29'
$serverFile = Join-Path $appRoot 'server\server.js'

function Read-ManagedState {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 3001 -ErrorAction SilentlyContinue)
    $receipt = if (Test-Path -LiteralPath $receiptFile) { Get-Content -LiteralPath $receiptFile -Raw | ConvertFrom-Json } else { $null }
    $process = if ($receipt) { Get-CimInstance Win32_Process -Filter "ProcessId=$($receipt.processId)" -ErrorAction SilentlyContinue } else { $null }
    $owned = $false
    if ($process -and $receipt.root -eq $appRoot -and $process.Name -eq 'node.exe') {
        $owned = $process.CommandLine.Contains($serverFile) -and $process.CommandLine.Contains('--host=127.0.0.1') -and $process.CommandLine.Contains('--port=3001') -and $process.CreationDate.ToUniversalTime().ToString('o') -eq $receipt.createdAt
    }
    $healthy = $false
    if ($owned -and $listeners.Count -eq 1 -and $listeners[0].LocalAddress -eq '127.0.0.1' -and $listeners[0].OwningProcess -eq $receipt.processId) {
        try { $healthy = (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:3001/' -TimeoutSec 5).StatusCode -eq 200 } catch {}
    }
    return [pscustomobject]@{ managed = $owned; healthy = $healthy; listeners = $listeners.Count; processId = $(if ($owned) { $receipt.processId } else { $null }); root = $appRoot; url = 'http://127.0.0.1:3001/status/academy'; version = $version }
}

if ($Action -eq 'Install') {
    $state = Read-ManagedState
    if ($state.managed -or $state.listeners -gt 0) { throw 'Stop the receipt-matched service before installing dependencies.' }
    New-Item -ItemType Directory -Path $serviceRoot -Force | Out-Null
    if (-not (Test-Path -LiteralPath $appRoot)) {
        & git clone --depth 1 --branch $version https://github.com/louislam/uptime-kuma.git $appRoot
        if ($LASTEXITCODE -ne 0) { throw 'Uptime Kuma clone failed.' }
    }
    $installed = & git -C $appRoot rev-parse HEAD
    if ($installed -ne $commit) { throw 'Existing checkout differs from the pinned version; leave it unchanged.' }
    Push-Location $appRoot
    try {
        & npm.cmd ci --omit=dev --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'Dependency install failed.' }
        & npm.cmd run download-dist
        if ($LASTEXITCODE -ne 0) { throw 'Distribution download failed.' }
    } finally { Pop-Location }
}
elseif ($Action -eq 'Start') {
    $state = Read-ManagedState
    if ($state.healthy) { $state | ConvertTo-Json; exit 0 }
    if ($state.listeners -gt 0 -or $state.managed) { throw 'Port 3001 or the managed process already exists. Inspect Status and logs; no process was stopped.' }
    if (-not (Test-Path -LiteralPath $serverFile)) { throw 'Run Install first.' }
    New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
    $dbConfig = Join-Path $dataRoot 'db-config.json'
    if (-not (Test-Path -LiteralPath $dbConfig)) { [IO.File]::WriteAllText($dbConfig, '{"type":"sqlite"}', [Text.UTF8Encoding]::new($false)) }
    $node = (Get-Command node.exe).Source
    $child = Start-Process -FilePath $node -ArgumentList @(('"' + $serverFile + '"'), '--host=127.0.0.1', '--port=3001', ('--data-dir="' + $dataRoot + '"')) -WorkingDirectory $appRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $serviceRoot 'stdout.log') -RedirectStandardError (Join-Path $serviceRoot 'stderr.log')
    $native = Get-CimInstance Win32_Process -Filter "ProcessId=$($child.Id)"
    @{ processId=$child.Id; root=$appRoot; createdAt=$native.CreationDate.ToUniversalTime().ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $receiptFile -Encoding UTF8
    for ($attempt=0; $attempt -lt 25; $attempt++) { Start-Sleep -Milliseconds 500; if ((Read-ManagedState).healthy) { break } }
    if (-not (Read-ManagedState).healthy) { throw 'Uptime Kuma has not become healthy. Inspect instance/uptime-kuma/stderr.log.' }
}
elseif ($Action -eq 'Stop') {
    $state = Read-ManagedState
    if ($state.managed) { Stop-Process -Id $state.processId; Remove-Item -LiteralPath $receiptFile }
    elseif ($state.listeners -gt 0) { throw 'Unknown port owner; nothing was stopped.' }
}
elseif ($Action -eq 'Configure') {
    if (-not (Read-ManagedState).healthy) { throw 'Start the managed service first.' }
    if (Test-Path -LiteralPath $credentialFile) { $credential = Import-Clixml -LiteralPath $credentialFile }
    else {
        $secret = ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N') + '!aA9') | ConvertTo-SecureString -AsPlainText -Force
        $credential = [pscredential]::new('academy-admin', $secret)
        $credential | Export-Clixml -LiteralPath $credentialFile
    }
    $previousSecret = $env:ACADEMY_KUMA_SETUP_PASSWORD
    try {
        $env:ACADEMY_KUMA_SETUP_PASSWORD = $credential.GetNetworkCredential().Password
        & node (Join-Path $PSScriptRoot 'configure_uptime_kuma.cjs') $appRoot $credential.UserName
        if ($LASTEXITCODE -ne 0) { throw 'Uptime Kuma configuration failed; existing credentials were preserved.' }
    } finally { $env:ACADEMY_KUMA_SETUP_PASSWORD = $previousSecret }
}
elseif ($Action -eq 'EnableAutoStart') {
    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    $scriptPath = Join-Path $PSScriptRoot 'manage_uptime_kuma.ps1'
    if ($existingTask -and -not ($existingTask.Actions.Arguments -like ('*' + $scriptPath + '*'))) { throw 'A different task owns this name.' }
    $actionSpec = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -WindowStyle Hidden -File "' + $scriptPath + '" Start')
    $userId = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([timespan]::Zero)
    Register-ScheduledTask -TaskName $taskName -Action $actionSpec -Trigger $trigger -Settings $settings -User $userId -RunLevel Limited -Force | Out-Null
}
elseif ($Action -eq 'DisableAutoStart') {
    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existingTask) {
        if (-not ($existingTask.Actions.Arguments -like ('*' + (Join-Path $PSScriptRoot 'manage_uptime_kuma.ps1') + '*'))) { throw 'A different task owns this name.' }
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
}
Read-ManagedState | ConvertTo-Json
