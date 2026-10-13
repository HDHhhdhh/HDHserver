[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8003,
    [ValidateRange(250, 60000)]
    [int]$PollMilliseconds = 2000,
    [int]$ParentProcessId = 0,
    [long]$ParentStartTimeUtcTicks = 0,
    [string]$ServerRoot = "",
    [switch]$Once,
    [switch]$ReportOnly
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ServerRoot)) {
    $ServerRoot = Split-Path -Parent $PSScriptRoot
}
$resolvedServerRoot = [IO.Path]::GetFullPath($ServerRoot).TrimEnd('\')
$waitressPath = Join-Path $resolvedServerRoot "venv\Scripts\waitress-serve.exe"
$waitressPattern = [regex]::Escape($waitressPath)
$logPath = Join-Path $resolvedServerRoot "instance\waitress-shadow-guard.log"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-GuardLog {
    param(
        [string]$Event,
        [object]$Details = $null
    )

    if ($Once -and $ReportOnly) { return }

    try {
        [IO.Directory]::CreateDirectory((Split-Path -Parent $logPath)) | Out-Null
        $record = [ordered]@{
            atUtc = [DateTime]::UtcNow.ToString("o")
            event = $Event
            port = $Port
            details = $Details
        }
        $line = $record | ConvertTo-Json -Depth 8 -Compress
        [IO.File]::AppendAllText($logPath, $line + [Environment]::NewLine, $utf8NoBom)
    } catch {
        # A log failure must never take down the production listener guard.
    }
}

function Get-ProcessSnapshot {
    param([int]$ProcessId)

    if ($ProcessId -le 0) { return $null }
    Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

function Test-ParentStillAlive {
    if ($ParentProcessId -le 0) { return $true }

    $parent = Get-Process -Id $ParentProcessId -ErrorAction SilentlyContinue
    if (-not $parent) { return $false }
    if ($ParentStartTimeUtcTicks -le 0) { return $true }

    try {
        return $parent.StartTime.ToUniversalTime().Ticks -eq $ParentStartTimeUtcTicks
    } catch {
        return $false
    }
}

function Invoke-GuardIteration {
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop)
    $productionListeners = @($listeners | Where-Object { $_.LocalAddress -eq "0.0.0.0" })
    $shadowListeners = @($listeners | Where-Object { $_.LocalAddress -eq "127.0.0.1" })

    $productionPid = 0
    $productionVerified = $false
    if ($productionListeners.Count -eq 1) {
        $productionPid = [int]$productionListeners[0].OwningProcess
        $productionProcess = Get-ProcessSnapshot -ProcessId $productionPid
        if ($productionProcess) {
            $commandLine = [string]$productionProcess.CommandLine
            $productionVerified = (
                $commandLine -match $waitressPattern -and
                $commandLine -match ("--listen=0\.0\.0\.0:" + [regex]::Escape([string]$Port)) -and
                $commandLine -match "--threads=16" -and
                $commandLine -match "\sapp:app(?:\s|$)"
            )
        }
    }

    $actions = @()
    foreach ($listener in $shadowListeners) {
        $shadowPid = [int]$listener.OwningProcess
        if ($shadowPid -eq $productionPid) { continue }

        $shadowProcess = Get-ProcessSnapshot -ProcessId $shadowPid
        $shadowCommandLine = if ($shadowProcess) { [string]$shadowProcess.CommandLine } else { "" }
        $knownVerificationWaitress = (
            $shadowCommandLine -match $waitressPattern -and
            $shadowCommandLine -match ("--listen=127\.0\.0\.1:" + [regex]::Escape([string]$Port)) -and
            $shadowCommandLine -match "\sapp:app(?:\s|$)"
        )

        $action = "unrecognized-no-action"
        if (-not $productionVerified) {
            $action = "production-unverified-no-action"
        } elseif ($knownVerificationWaitress -and $ReportOnly) {
            $action = "would-stop-verification-waitress"
        } elseif ($knownVerificationWaitress) {
            # A loopback-specific Waitress can shadow the healthy wildcard
            # listener on Windows, so stop only this exact repo QA command.
            Stop-Process -Id $shadowPid -Force -ErrorAction Stop
            $action = "stopped-verification-waitress"
        }

        $actions += [ordered]@{
            processId = $shadowPid
            recognizedVerificationWaitress = $knownVerificationWaitress
            action = $action
        }
    }

    $status = if (-not $productionVerified) {
        "production-unverified"
    } elseif ($shadowListeners.Count -eq 0) {
        "healthy"
    } elseif (@($actions | Where-Object { $_.action -eq "stopped-verification-waitress" }).Count -gt 0) {
        "shadow-remediated"
    } elseif ($ReportOnly) {
        "shadow-reported"
    } else {
        "shadow-unrecognized"
    }

    [ordered]@{
        status = $status
        productionVerified = $productionVerified
        productionProcessId = $productionPid
        shadowListenerCount = $shadowListeners.Count
        actions = $actions
    }
}

Write-GuardLog -Event "guard-started" -Details ([ordered]@{
    parentProcessId = $ParentProcessId
    reportOnly = [bool]$ReportOnly
    once = [bool]$Once
})

$lastStateKey = ""
try {
    while (Test-ParentStillAlive) {
        try {
            $result = Invoke-GuardIteration
            $stateKey = $result | ConvertTo-Json -Depth 8 -Compress
            if ($stateKey -ne $lastStateKey) {
                Write-GuardLog -Event "listener-state" -Details $result
                $lastStateKey = $stateKey
            }
            if ($Once) {
                $result | ConvertTo-Json -Depth 8
                break
            }
        } catch {
            $errorDetails = [ordered]@{
                type = $_.Exception.GetType().FullName
                message = $_.Exception.Message
            }
            Write-GuardLog -Event "guard-error" -Details $errorDetails
            if ($Once) { throw }
        }

        Start-Sleep -Milliseconds $PollMilliseconds
    }
} finally {
    Write-GuardLog -Event "guard-stopped"
}
