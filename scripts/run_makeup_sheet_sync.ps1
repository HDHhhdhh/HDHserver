$ErrorActionPreference = "Stop"
$serverRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $serverRoot "venv\Scripts\python.exe"
$syncScript = Join-Path $PSScriptRoot "sync_makeup_sheet_additive.py"

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Server virtual-environment Python is missing: $pythonPath"
}
if (-not (Test-Path -LiteralPath $syncScript -PathType Leaf)) {
    throw "Makeup sheet sync script is missing: $syncScript"
}

Set-Location -LiteralPath $serverRoot
& $pythonPath $syncScript
exit $LASTEXITCODE
