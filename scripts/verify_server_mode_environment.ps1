param([Parameter(Mandatory = $true)][string]$FixtureRoot)

$ErrorActionPreference = "Stop"
$helper = Join-Path $PSScriptRoot "set_server_mode_environment.ps1"
$runner = Join-Path $PSScriptRoot "run_waitress_server.ps1"
$names = @("ADMIN_API_GUARD", "LOG_STORE_MODE", "LOG_JSON_EXPORT", "UPDATES_GET_ENSURE", "JSON_STORE_REVISION_MODE", "DATA_MIRROR_SYNC")
$previous = @{}
$unrelated = "ACADEMY_MODE_TEST_UNRELATED"
foreach ($name in ($names + $unrelated)) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, "Process") }
$cases = 0
$guardCases = 0
try {
    Set-Item -LiteralPath "Env:$unrelated" -Value "untouched"
    foreach ($scenario in @(
        @{Machine="machine"; User="user"; Expected="machine"; UserReads=$false},
        @{Machine=$null; User="user"; Expected="user"; UserReads=$true},
        @{Machine="  "; User="user"; Expected="user"; UserReads=$true},
        @{Machine=$null; User=$null; Expected=$null; UserReads=$true},
        @{Machine=" "; User="`t"; Expected=$null; UserReads=$true},
        @{Machine="0"; User="1"; Expected="0"; UserReads=$false},
        @{Machine=$null; User="0"; Expected="0"; UserReads=$true}
    )) {
        foreach ($name in $names) { Set-Item -LiteralPath "Env:$name" -Value "stale-process" }
        $calls = [Collections.Generic.List[string]]::new()
        $reader = {
            param($Name, $Target)
            if ($names -notcontains $Name -or $Target -notin @("Machine", "User")) { throw "Unexpected setting read" }
            $calls.Add("${Name}:${Target}")
            $scenario[$Target]
        }.GetNewClosure()
        & $helper -ReadEnvironment $reader
        foreach ($name in $names) {
            $actual = [Environment]::GetEnvironmentVariable($name, "Process")
            if ($actual -cne $scenario.Expected) { throw "Wrong mode resolution for $name" }
            $trace = @($calls | Where-Object { $_.StartsWith("${name}:") }) -join ","
            $expectedTrace = "${name}:Machine" + $(if ($scenario.UserReads) { ",${name}:User" } else { "" })
            if ($trace -cne $expectedTrace) { throw "Wrong setting precedence for $name" }
            $cases++
        }
        if ([Environment]::GetEnvironmentVariable($unrelated, "Process") -cne "untouched") { throw "Unrelated setting changed" }
    }
    foreach ($name in $names) { Set-Item -LiteralPath "Env:$name" -Value "before-failure" }
    $reachedNext = $false
    $failed = $false
    $failingReader = {
        param($Name, $Target)
        if ($Name -eq $names[-1]) { throw "Synthetic reader failure" }
        "would-change"
    }.GetNewClosure()
    try { & $helper -ReadEnvironment $failingReader; $reachedNext = $true } catch { $failed = $true }
    if (-not $failed -or $reachedNext) { throw "Reader failure did not stop startup" }
    foreach ($name in $names) {
        if ([Environment]::GetEnvironmentVariable($name, "Process") -cne "before-failure") { throw "Failed read partially published modes" }
    }

    $tokens = $null; $errors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile($runner, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw "Runner syntax error" }
    $guard = @($ast.FindAll({ param($node) $node -is [Management.Automation.Language.IfStatementAst] -and $node.Extent.Text.Contains('set_server_mode_environment.ps1') }, $true))
    if ($guard.Count -ne 1) { throw "Mode reload guard missing or duplicated" }
    $fixtureDir = New-Item -ItemType Directory -Path (Join-Path $FixtureRoot "mode-wiring")
    $fixture = Join-Path $fixtureDir.FullName "runner-fragment.ps1"
    $marker = Join-Path $fixtureDir.FullName "called.txt"
    $encoding = [Text.UTF8Encoding]::new($false)
    [IO.File]::WriteAllText($fixture, $ast.ParamBlock.Extent.Text + "`n`$ErrorActionPreference='Stop'`n" + $guard[0].Extent.Text + "`n'stage-ready'", $encoding)
    $fixtureHelper = Join-Path $fixtureDir.FullName "set_server_mode_environment.ps1"
    [IO.File]::WriteAllText($fixtureHelper, '[IO.File]::WriteAllText((Join-Path $PSScriptRoot ''called.txt''), ''called'')', $encoding)
    foreach ($inputCase in @(
        @{Args=@{}; Expected=$true},
        @{Args=@{ReloadServerModes=$true}; Expected=$true},
        @{Args=@{DevelopmentIsolation=$true}; Expected=$false},
        @{Args=@{DevelopmentIsolation=$true; ReloadServerModes=$true}; Expected=$true},
        @{Args=@{DevelopmentIsolation=$false; ReloadServerModes=$false}; Expected=$true},
        @{Args=@{DevelopmentIsolation=$true; ReloadServerModes=$false}; Expected=$false}
    )) {
        Remove-Item -LiteralPath $marker -ErrorAction SilentlyContinue
        $arguments = $inputCase.Args
        $result = & $fixture @arguments
        if ((Test-Path -LiteralPath $marker) -ne $inputCase.Expected -or $result -cne "stage-ready") { throw "Runner mode guard mismatch" }
        $guardCases++
    }
    [IO.File]::WriteAllText($fixtureHelper, 'throw ''Synthetic mode failure''', $encoding)
    $result = $null; $failed = $false
    try { $result = & $fixture -DevelopmentIsolation -ReloadServerModes } catch { $failed = $true }
    if (-not $failed -or $result -eq "stage-ready") { throw "Runner continued after helper failure" }
    [ordered]@{modeCases=$cases; guardCases=$guardCases; failClosed=$true} | ConvertTo-Json -Compress
} finally {
    foreach ($name in $previous.Keys) {
        if ($null -eq $previous[$name]) { Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue }
        else { Set-Item -LiteralPath "Env:$name" -Value $previous[$name] }
    }
}
