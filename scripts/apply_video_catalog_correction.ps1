[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Draft,
    [switch]$Apply,
    [switch]$ConfirmApply,
    [string]$TaskName = 'Academy Server Waitress',
    [int]$Port = 8003,
    [string]$BackupDir = ''
)

$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pythonExe = Join-Path $sourceRoot 'venv\Scripts\python.exe'
$applyScript = Join-Path $sourceRoot 'scripts\apply_video_catalog_correction.py'
$backupScript = Join-Path $sourceRoot 'scripts\backup_runtime_data.py'
$draftPath = (Resolve-Path -LiteralPath $Draft).Path
$expectedWaitressPattern = 'waitress-serve\.exe.*--listen=0\.0\.0\.0:' + [regex]::Escape([string]$Port)

foreach ($requiredPath in @($pythonExe, $applyScript, $backupScript, $draftPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required file not found: $requiredPath"
    }
}

function Get-PortListener {
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Wait-PortState([bool]$ShouldListen, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $listener = Get-PortListener
        if ($ShouldListen -eq [bool]$listener) { return $listener }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    if ($ShouldListen) { throw "Port $Port did not start listening." }
    throw "Port $Port did not stop listening."
}

Write-Host 'Video correction dry-run (no runtime writes)'
& $pythonExe $applyScript --draft $draftPath --root $sourceRoot --port $Port
if ($LASTEXITCODE -ne 0) { throw 'Video correction dry-run failed.' }

if (-not $Apply) {
    Write-Host 'Dry-run complete. Re-run with -Apply -ConfirmApply for the approved maintenance window.'
    exit 0
}
if (-not $ConfirmApply) {
    throw 'Live apply requires both -Apply and -ConfirmApply.'
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$listenerBefore = Get-PortListener
if ($listenerBefore) {
    $listenerProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($listenerBefore.OwningProcess)" -ErrorAction SilentlyContinue
    if (-not $listenerProcess -or $listenerProcess.CommandLine -notmatch $expectedWaitressPattern) {
        throw "Port $Port is held by an unexpected process. Nothing was stopped or changed."
    }
}
$shouldRestart = $task.State -eq 'Running' -or $null -ne $listenerBefore
$applyFailure = $null
$backupArchive = $null

try {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    try {
        Wait-PortState -ShouldListen $false -TimeoutSeconds 15 | Out-Null
    } catch {
        $listener = Get-PortListener
        if (-not $listener) { throw }
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
        if (-not $process -or $process.CommandLine -notmatch $expectedWaitressPattern) {
            throw "Port $Port is held by an unexpected process."
        }
        Stop-Process -Id $listener.OwningProcess -Force
        Wait-PortState -ShouldListen $false -TimeoutSeconds 10 | Out-Null
    }

    $backupArgs = @($backupScript)
    if ($BackupDir.Trim()) {
        $backupArgs += @('--out', $BackupDir)
    }
    $backupOutput = @(& $pythonExe @backupArgs)
    if ($LASTEXITCODE -ne 0) { throw 'Runtime backup failed.' }
    $backupArchive = [string]($backupOutput | Select-Object -Last 1)
    $backupArchive = $backupArchive.Trim()
    if (-not $backupArchive -or -not (Test-Path -LiteralPath $backupArchive -PathType Leaf)) {
        throw 'Runtime backup receipt was not produced.'
    }

    Write-Host "Backup verified for apply: $backupArchive"
    & $pythonExe $applyScript --draft $draftPath --root $sourceRoot --port $Port --apply --backup-archive $backupArchive
    if ($LASTEXITCODE -ne 0) { throw 'Offline video correction apply failed.' }
} catch {
    $applyFailure = $_
} finally {
    if ($shouldRestart) {
        Start-ScheduledTask -TaskName $TaskName
        try {
            $listenerAfter = Wait-PortState -ShouldListen $true -TimeoutSeconds 30
            Write-Host "Waitress restarted on port $($listenerAfter.LocalPort), PID $($listenerAfter.OwningProcess)."
        } catch {
            if ($null -eq $applyFailure) { $applyFailure = $_ }
            else { Write-Error $_ }
        }
    }
}

if ($null -ne $applyFailure) {
    throw $applyFailure
}
Write-Host "Video correction completed. Backup: $backupArchive"