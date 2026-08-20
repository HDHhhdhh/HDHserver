param(
    [Parameter(Mandatory = $true)]
    [string]$BundlePath,
    [Parameter(Mandatory = $true)]
    [string]$ChecksumPath,
    [string]$ServerRoot = "C:\server",
    [string]$StageRoot = "",
    [string]$OutFile = ""
)

$ErrorActionPreference = "Stop"
$BundlePath = [IO.Path]::GetFullPath($BundlePath)
$ChecksumPath = [IO.Path]::GetFullPath($ChecksumPath)
$ServerRoot = [IO.Path]::GetFullPath($ServerRoot).TrimEnd('\')
if (-not $StageRoot) {
    $StageRoot = "C:\student-app-stage\" + (Get-Date -Format "yyyyMMdd-HHmmss")
}
$StageRoot = [IO.Path]::GetFullPath($StageRoot).TrimEnd('\')
$serverPrefix = $ServerRoot + [IO.Path]::DirectorySeparatorChar
if ($StageRoot.Equals($ServerRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $StageRoot.StartsWith($serverPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "StageRoot must be outside the production ServerRoot."
}
if (-not (Test-Path -LiteralPath $BundlePath -PathType Leaf)) { throw "Bundle not found: $BundlePath" }
if (-not (Test-Path -LiteralPath $ChecksumPath -PathType Leaf)) { throw "Checksum not found: $ChecksumPath" }
if (Test-Path -LiteralPath $StageRoot) { throw "StageRoot already exists; choose a new empty path: $StageRoot" }

$null = New-Item -ItemType Directory -Path $StageRoot
$sourceRoot = Join-Path $StageRoot "source"
$logRoot = Join-Path $StageRoot "logs"
$null = New-Item -ItemType Directory -Path $logRoot

function Invoke-StageCheck(
    [string]$Name,
    [string]$Executable,
    [string[]]$Arguments,
    [string]$WorkingDirectory
) {
    $logPath = Join-Path $logRoot ($Name + ".log")
    Push-Location -LiteralPath $WorkingDirectory
    try {
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $Executable @Arguments *> $logPath
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousPreference
    } catch {
        $_ | Out-String | Set-Content -LiteralPath $logPath -Encoding UTF8
        $exitCode = 1
        $ErrorActionPreference = $previousPreference
    } finally {
        Pop-Location
    }
    [ordered]@{ name = $Name; passed = ($exitCode -eq 0); exitCode = $exitCode; log = $logPath }
}

$expectedLine = (Get-Content -LiteralPath $ChecksumPath -Encoding ASCII | Select-Object -First 1).Trim()
if ($expectedLine -notmatch '^([0-9A-Fa-f]{64})\s+') { throw "Checksum file has an invalid format." }
$expectedHash = $matches[1].ToUpperInvariant()
$actualHash = (Get-FileHash -LiteralPath $BundlePath -Algorithm SHA256).Hash
$checksumPassed = $actualHash -eq $expectedHash
if (-not $checksumPassed) { throw "Bundle SHA-256 does not match the checksum file." }

Expand-Archive -LiteralPath $BundlePath -DestinationPath $sourceRoot
$manifestPath = Join-Path $sourceRoot "RELEASE-MANIFEST.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "Release manifest is missing." }
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.format -ne "student-app-code-release/v1") { throw "Unsupported release manifest format." }
if ($manifest.policy.containsRuntimeData -or $manifest.policy.containsCredentials) {
    throw "Release policy does not certify runtime and credential exclusion."
}
$forbidden = @(
    '(?i)(^|/)(\.env|instance|files|data|_runtime_backups|_data_mirror)(/|$)',
    '(?i)\.(sqlite|sqlite-wal|sqlite-shm|db|pem|zip|tmp|log)$',
    '(?i)(^|/)(students|auth_accounts|updates|progress|logs)\.json$'
)
foreach ($item in @($manifest.files)) {
    $path = [string]$item.path
    if ([IO.Path]::IsPathRooted($path) -or $path -match '(^|/)\.\.(/|$)') { throw "Unsafe manifest path: $path" }
    foreach ($pattern in $forbidden) {
        if ($path -match $pattern) { throw "Forbidden runtime path in release: $path" }
    }
}

$pythonPath = Join-Path $ServerRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { throw "Production venv Python is missing: $pythonPath" }
$stageVenvPath = Join-Path $sourceRoot "venv"
if (Test-Path -LiteralPath $stageVenvPath) { throw "Release unexpectedly contains a venv path." }
$null = New-Item -ItemType Junction -Path $stageVenvPath -Target (Join-Path $ServerRoot "venv")
$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
$checks = @()
$checks += Invoke-StageCheck "release-verify" $pythonPath @(
    "scripts\build_student_app_code_release.py", "--verify-only", $BundlePath
) $sourceRoot
$checks += Invoke-StageCheck "compileall" $pythonPath @(
    "-m", "compileall", "-q", "app.py", "routes", "core", "scripts"
) $sourceRoot
$checks += Invoke-StageCheck "stage-runtime-seed" $pythonPath @(
    "-c", "import core.paths"
) $sourceRoot
$checks += Invoke-StageCheck "backend-focused-all" $pythonPath @(
    "scripts\verify_student_mobile_app.py", "--only", "all"
) $sourceRoot
if ($nodeCommand) {
    $checks += Invoke-StageCheck "frontend-focused-all" $nodeCommand.Source @(
        "scripts\verify_student_mobile_app.mjs", "--only", "all"
    ) $sourceRoot
} else {
    $checks += [ordered]@{ name = "frontend-focused-all"; passed = $false; exitCode = 127; log = "node.exe missing" }
}

$ready = $checksumPassed -and (@($checks | Where-Object { -not $_.passed }).Count -eq 0)
$receipt = [ordered]@{
    format = "student-app-production-stage/v1"
    capturedAtUtc = [DateTime]::UtcNow.ToString("o")
    computer = $env:COMPUTERNAME
    serverRoot = $ServerRoot
    stageRoot = $StageRoot
    bundle = [ordered]@{
        name = Split-Path -Leaf $BundlePath
        size = (Get-Item -LiteralPath $BundlePath).Length
        sha256 = $actualHash
        checksumPassed = $checksumPassed
        source = $manifest.source
        fileCount = @($manifest.files).Count
        removedPathCount = @($manifest.removedPaths).Count
    }
    checks = $checks
    readyForApply = $ready
    productionChanged = $false
    productionRuntimeRead = $false
    productionRuntimeWritten = $false
    stageRuntimeSeeded = $true
    stageVenvLinked = $true
}

if (-not $OutFile) { $OutFile = Join-Path $StageRoot "prod-stage-preflight.json" }
$OutFile = [IO.Path]::GetFullPath($OutFile)
$outParent = Split-Path -Parent $OutFile
if ($outParent) { $null = New-Item -ItemType Directory -Path $outParent -Force }
[IO.File]::WriteAllText(
    $OutFile,
    (($receipt | ConvertTo-Json -Depth 8) + [Environment]::NewLine),
    [Text.UTF8Encoding]::new($false)
)
[ordered]@{
    ok = $ready
    receipt = $OutFile
    receiptSha256 = (Get-FileHash -LiteralPath $OutFile -Algorithm SHA256).Hash
    productionChanged = $false
} | ConvertTo-Json
if (-not $ready) { exit 1 }
