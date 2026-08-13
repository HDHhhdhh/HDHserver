param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$serverRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $serverRoot "venv\Scripts\python.exe"
$legacyWorkerPath = Join-Path $PSScriptRoot "deliver_student_push_outbox.py"
$reminderScannerPath = Join-Path $PSScriptRoot "enqueue_student_reminders.py"
$notificationWorkerPath = Join-Path $PSScriptRoot "deliver_student_notification_outbox.py"
$mutex = $null
$ownsMutex = $false

try {
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "The server virtual-environment Python is unavailable."
    }
    foreach ($workerPath in @($legacyWorkerPath, $reminderScannerPath, $notificationWorkerPath)) {
        if (-not (Test-Path -LiteralPath $workerPath -PathType Leaf)) {
            throw "A student notification worker is unavailable."
        }
    }

    $mutex = [Threading.Mutex]::new($false, "Global\AcademyStudentPushDelivery-v1")
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
        Write-Output '{"ok":true,"mode":"dry-run","commands":["venv-python deliver_student_push_outbox.py --once","venv-python enqueue_student_reminders.py --once","venv-python deliver_student_notification_outbox.py --once"]}'
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
