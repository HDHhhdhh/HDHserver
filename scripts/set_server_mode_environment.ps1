param(
    [scriptblock]$ReadEnvironment = {
        param($Name, $Target)
        [Environment]::GetEnvironmentVariable($Name, $Target)
    }
)

$ErrorActionPreference = "Stop"
$modeValues = @{}
foreach ($name in @(
    "ADMIN_API_GUARD", "LOG_STORE_MODE", "LOG_JSON_EXPORT",
    "UPDATES_GET_ENSURE", "JSON_STORE_REVISION_MODE", "DATA_MIRROR_SYNC"
)) {
    $value = & $ReadEnvironment $name "Machine"
    if ([string]::IsNullOrWhiteSpace($value)) {
        $value = & $ReadEnvironment $name "User"
    }
    $modeValues[$name] = $value
}
foreach ($name in $modeValues.Keys) {
    if ([string]::IsNullOrWhiteSpace($modeValues[$name])) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    } else {
        Set-Item -LiteralPath "Env:$name" -Value $modeValues[$name]
    }
}
