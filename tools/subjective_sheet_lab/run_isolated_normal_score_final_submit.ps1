param(
    [Parameter(Mandatory = $true)]
    [string]$SandboxRoot,
    [string]$RepoRoot = "C:\server"
)

$ErrorActionPreference = "Stop"

function Get-FreeTcpPort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try { return ([Net.IPEndPoint]$listener.LocalEndpoint).Port }
    finally { $listener.Stop() }
}

function Test-PortOpen([int]$Port, [int]$TimeoutMs = 300) {
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        return $task.Wait($TimeoutMs) -and $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Find-Chrome {
    foreach ($path in @(
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    )) {
        if (Test-Path -LiteralPath $path -PathType Leaf) { return $path }
    }
    throw "Chrome executable not found"
}

function Stop-OwnedProcess([Diagnostics.Process]$Process) {
    if ($null -eq $Process -or $Process.HasExited) { return }
    try { & taskkill /PID $Process.Id /T /F | Out-Null } catch {}
    try { $Process.WaitForExit(5000) | Out-Null } catch {}
}

$appRoot = Join-Path $SandboxRoot "app"
$stateRoot = Join-Path $SandboxRoot "final_submit_state"
$driverPath = Join-Path $RepoRoot "tools\subjective_sheet_lab\run_isolated_normal_score_final_submit_driver.js"
if (-not (Test-Path -LiteralPath $appRoot -PathType Container)) { throw "Sandbox app root missing" }
if (-not (Test-Path -LiteralPath $driverPath -PathType Leaf)) { throw "CDP driver missing" }
New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null

$serverPort = Get-FreeTcpPort
$cdpPort = Get-FreeTcpPort
$resultPath = Join-Path $stateRoot "final_submit_result.json"
$serverOut = Join-Path $stateRoot "flask_stdout.log"
$serverErr = Join-Path $stateRoot "flask_stderr.log"
$chromeOut = Join-Path $stateRoot "chrome_stdout.log"
$chromeErr = Join-Path $stateRoot "chrome_stderr.log"
$driverOut = Join-Path $stateRoot "driver_stdout.log"
$profile = Join-Path $stateRoot "chrome_profile"
$serverProcess = $null
$chromeProcess = $null

$oldEnv = @{}
foreach ($name in @(
    "DB_PATH",
    "FLASK_DEBUG",
    "PYTHONDONTWRITEBYTECODE",
    "OCR_PHASE2E_GEMINI_LIVE_ENABLED",
    "OCR_PHASE2E_PROVIDER_CALLS_ALLOWED",
    "OCR_PHASE2E_MAX_PROVIDER_CALLS_PER_REQUEST",
    "OCR_PHASE2E_CACHE_WRITE_ENABLED"
)) {
    $oldEnv[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    $env:DB_PATH = Join-Path $appRoot "app.sqlite"
    $env:FLASK_DEBUG = "0"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:OCR_PHASE2E_GEMINI_LIVE_ENABLED = "false"
    $env:OCR_PHASE2E_PROVIDER_CALLS_ALLOWED = "false"
    $env:OCR_PHASE2E_MAX_PROVIDER_CALLS_PER_REQUEST = "0"
    $env:OCR_PHASE2E_CACHE_WRITE_ENABLED = "false"

    $serverArgs = @{
        FilePath = "python"
        ArgumentList = @(
            "-m", "flask", "--app", "app", "run",
            "--host", "127.0.0.1", "--port", "$serverPort",
            "--no-debugger", "--no-reload"
        )
        WorkingDirectory = $appRoot
        WindowStyle = "Hidden"
        RedirectStandardOutput = $serverOut
        RedirectStandardError = $serverErr
        PassThru = $true
    }
    $serverProcess = Start-Process @serverArgs

    $deadline = (Get-Date).AddSeconds(30)
    while (
        (Get-Date) -lt $deadline -and
        -not $serverProcess.HasExited -and
        -not (Test-PortOpen -Port $serverPort)
    ) {
        Start-Sleep -Milliseconds 300
    }
    if (-not (Test-PortOpen -Port $serverPort)) {
        $serverError = if (Test-Path -LiteralPath $serverErr) {
            Get-Content -LiteralPath $serverErr -Raw
        } else {
            ""
        }
        throw "Flask server failed to start: $($serverError -replace '\s+', ' ')"
    }

    if (Test-Path -LiteralPath $profile -PathType Container) {
        Remove-Item -LiteralPath $profile -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $profile | Out-Null
    $chromeArgs = @{
        FilePath = Find-Chrome
        ArgumentList = @(
            "--headless=new",
            "--disable-gpu",
            "--disable-background-networking",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-debugging-port=$cdpPort",
            "--user-data-dir=$profile",
            "about:blank"
        )
        WindowStyle = "Hidden"
        RedirectStandardOutput = $chromeOut
        RedirectStandardError = $chromeErr
        PassThru = $true
    }
    $chromeProcess = Start-Process @chromeArgs

    $pageUrl = "http://127.0.0.1:$serverPort/student/auto?ocr=1"
    $driverOutput = & node $driverPath $cdpPort $pageUrl $appRoot $resultPath 2>&1
    $driverOutput | Set-Content -LiteralPath $driverOut -Encoding UTF8
    if ($LASTEXITCODE -ne 0) {
        $safeResult = if (Test-Path -LiteralPath $resultPath) {
            Get-Content -LiteralPath $resultPath -Raw
        } else {
            "missing"
        }
        throw "CDP driver failed: $safeResult"
    }
} finally {
    Stop-OwnedProcess $chromeProcess
    Stop-OwnedProcess $serverProcess
    foreach ($name in $oldEnv.Keys) {
        [Environment]::SetEnvironmentVariable($name, $oldEnv[$name], "Process")
    }
}

if (Test-Path -LiteralPath $profile -PathType Container) {
    Remove-Item -LiteralPath $profile -Recurse -Force
}
if (-not (Test-Path -LiteralPath $resultPath -PathType Leaf)) { throw "Result file missing" }

$result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
if ($result.status -ne "PASS") { throw "Driver result was not PASS" }
Write-Host "STATUS: PASS"
Write-Host "CLASSIFICATION: $($result.classification)"
Write-Host "ANSWER_LINE_COUNT: $($result.answerLineCount)"
Write-Host "EXPECTED_ACTUAL_SCORE_MATCH: $($result.expectedScore -eq $result.browserResult.response.score)"
Write-Host "ASSIGNMENT_PROGRESS_STATUS: $($result.browserResult.response.assignmentProgress.status)"
Write-Host "TS_SUBMIT_CLICK_COUNT: $($result.browserResult.submitClicks)"
Write-Host "SUBMIT_TEST_CALL_COUNT: $($result.browserResult.submitCalls)"
Write-Host "GEMINI_API_PROVIDER_CALL_COUNT: $($result.geminiApiProviderCalls)"
Write-Host "RESULT_FILE: $resultPath"
