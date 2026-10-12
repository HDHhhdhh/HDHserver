param(
    [string]$ManagerSourcePath = "",
    [switch]$ExpectUnsafeBaseline
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$taskManagerSourcePath = if ($ManagerSourcePath) {
    [IO.Path]::GetFullPath($ManagerSourcePath)
} else {
    Join-Path $PSScriptRoot "manage_isolated_design_server.ps1"
}
$taskTokens = $null
$taskParseErrors = $null
$taskAst = [System.Management.Automation.Language.Parser]::ParseFile(
    $taskManagerSourcePath, [ref]$taskTokens, [ref]$taskParseErrors
)
if ($taskParseErrors.Count) { throw "Manager source did not parse." }
foreach ($taskFunction in $taskAst.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
    }, $false)) {
    . ([ScriptBlock]::Create($taskFunction.Extent.Text))
}

$Port = 8004
$sourceRoot = "synthetic-source-root"
$isolatedBase = "synthetic-isolated-base"
$codeRoot = "synthetic-isolated-root"
$waitressPath = $taskManagerSourcePath
$receiptPath = "synthetic-unused-receipt"
$Action = "Status"
$Restart = $false
$KollusVideoQa = $false
$script:taskNetworkDenied = $false
$script:taskListeners = @()
$script:taskMutationCalls = 0
$script:taskReceipt = [PSCustomObject]@{
    port = 8004
    codeRoot = $codeRoot
    sourceRoot = $sourceRoot
    listenerProcessId = 41
    listenerStartTimeUtc = "synthetic"
}
function Read-Receipt { return $script:taskReceipt }
function Test-SameStartTime { param($ProcessId, $ExpectedUtc) return $true }
function Get-HttpStatus { return 200 }
function Sync-CodeSnapshot { $script:taskMutationCalls++; throw "Unexpected mutation." }
function Start-Process { $script:taskMutationCalls++; throw "Unexpected process start." }
function Stop-Process { $script:taskMutationCalls++; throw "Unexpected process stop." }
function Remove-Item { $script:taskMutationCalls++; throw "Unexpected receipt deletion." }
function Get-NetTCPConnection {
    [CmdletBinding()]
    param($State, $LocalPort)
    if ($script:taskNetworkDenied) {
        Write-Error -Message "synthetic-listener-query-denied" -Category PermissionDenied
        return
    }
    return $script:taskListeners
}

$script:taskListeners = @(
    [PSCustomObject]@{LocalAddress="0.0.0.0";LocalPort=8003;OwningProcess=99},
    [PSCustomObject]@{LocalAddress="127.0.0.1";LocalPort=8004;OwningProcess=41}
)
$taskResult = @(Get-Listeners)
if ($taskResult.Count -ne 1 -or $taskResult[0].OwningProcess -ne 41) {
    throw "Listeners must be filtered to the requested port."
}
$taskStatus = Get-ManagedStatus
if (-not $taskStatus.managed -or -not $taskStatus.running -or $taskStatus.httpStatus -ne 200) {
    throw "One receipt-matched loopback listener must be reusable."
}
$taskReuse = Start-ManagedServer
if (-not $taskReuse.managed -or $script:taskMutationCalls -ne 0) {
    throw "An existing managed listener must be reused without mutation."
}
$script:taskListeners += [PSCustomObject]@{LocalAddress="0.0.0.0";LocalPort=8004;OwningProcess=42}
$taskStatus = Get-ManagedStatus
if ($taskStatus.managed -or -not $taskStatus.running) {
    throw "An unexpected listener set must be occupied but unmanaged."
}
$script:taskListeners = @([PSCustomObject]@{LocalAddress="0.0.0.0";LocalPort=8004;OwningProcess=42})
$taskStatus = Get-ManagedStatus
if ($taskStatus.managed -or -not $taskStatus.running) {
    throw "A non-loopback listener must not be reported as an unused port."
}
$script:taskListeners = @()
$taskStatus = Get-ManagedStatus
if ($taskStatus.managed -or $taskStatus.running) {
    throw "A successful empty listener query must report a stopped server."
}
$script:taskNetworkDenied = $true
foreach ($taskOperation in @("Get-Listeners", "Get-ManagedStatus", "Start-ManagedServer", "Stop-ManagedServer")) {
    $taskDenied = $false
    try { & $taskOperation | Out-Null }
    catch {
        $taskDenied = $_.ToString().Contains("synthetic-listener-query-denied")
    }
    if (-not $taskDenied) { throw "$taskOperation must preserve the ownership-query failure." }
    if ($script:taskMutationCalls -ne 0) { throw "$taskOperation mutated after a failed ownership query." }
}
Write-Output "isolated manager checks passed: port filter, reuse, unexpected listeners, query failure without mutation"


# Extract the real entrypoint as well as functions; fixtures never dot-source live setup.
$taskFixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ("isolated-manager-fixtures-" + [Guid]::NewGuid().ToString("N"))
[IO.Directory]::CreateDirectory($taskFixtureRoot) | Out-Null
$taskWorkerPath = Join-Path $taskFixtureRoot "worker.ps1"
$taskWorkerSource = @'
param([string]$ManagerPath, [string]$FixturePath, [string]$Label, [string]$Scenario)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($ManagerPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw "Fixture source parse failed." }
foreach ($definition in $ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $false)) {
    . ([ScriptBlock]::Create($definition.Extent.Text))
}
$entrypoint = [ScriptBlock]::Create($ast.EndBlock.Statements[-1].Extent.Text)
$Port = [int](Get-Content -LiteralPath (Join-Path $FixturePath "port.txt") -Raw -Encoding UTF8)
$sourceRoot = Join-Path $FixturePath "source"
$isolatedBase = Join-Path $FixturePath "isolated"
$codeRoot = Join-Path $isolatedBase "app"
$receiptPath = Join-Path $isolatedBase "server.json"
$markerPath = Join-Path $codeRoot ".academy-isolated-server.json"
$stdoutPath = Join-Path $isolatedBase "stdout.log"
$stderrPath = Join-Path $isolatedBase "stderr.log"
$waitressPath = $PSCommandPath
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$Action = "Start"
$Restart = ($Scenario -eq "entry-restart")
$KollusVideoQa = $false
if ($Scenario -eq "entry-status") { $Action = "Status" }
if ($Scenario -eq "entry-stop") { $Action = "Stop" }
if ($Scenario -eq "entry-refresh") { $Action = "Refresh" }
$script:fixtureListenerTimeQueries = 0
$script:fixtureWrapperId = if ($Label -eq "A") { 410001 } else { 420001 }
$script:fixtureListenerId = $script:fixtureWrapperId + 1
$script:fixtureWrapperStart = [DateTime]::Parse("2026-01-01T00:00:00.0000000Z").ToUniversalTime()
$script:fixtureChildStart = $script:fixtureWrapperStart.AddSeconds(1)
$script:fixtureLaunched = $false
$script:fixtureEnvironment = @{}
if ($Scenario -eq "legacy-status") { $Action = "Status" }
if ($Scenario -in @("legacy-restart", "legacy-wrong-source", "legacy-wrong-command", "legacy-wrong-starttime")) { $Restart = $true }
if ($Scenario -like "legacy-*") {
    [IO.Directory]::CreateDirectory($isolatedBase) | Out-Null
    $legacyReceipt = [ordered]@{
        format="academy-isolated-design-server/v1"
        sourceRoot=if ($Scenario -eq "legacy-wrong-source") { "another-source-root" } else { $sourceRoot }
        codeRoot=$codeRoot; port=$Port
        wrapperProcessId=510001; wrapperStartTimeUtc="2025-01-01T00:00:00.0000000Z"
        listenerProcessId=510002; listenerStartTimeUtc=if ($Scenario -eq "legacy-wrong-starttime") { "2025-01-02T00:00:01.0000000Z" } else { "2025-01-01T00:00:01.0000000Z" }
        liveRuntimeCopied=$false; legacyUnknownField="keep"
    }
    [IO.File]::WriteAllText($receiptPath, ($legacyReceipt | ConvertTo-Json), $utf8NoBom)
    [IO.File]::Copy($receiptPath, (Join-Path $FixturePath "legacy-before.json"))
    $legacyListeners = @([PSCustomObject]@{LocalAddress="127.0.0.1";LocalPort=$Port;OwningProcess=510002})
    [IO.File]::WriteAllText((Join-Path $FixturePath "listeners.json"), (ConvertTo-Json -InputObject $legacyListeners))
}

# Environment transport is outside this race oracle; keep it deterministic in the fixture.
function Get-Item {
    [CmdletBinding()]
    param([string]$LiteralPath)
    if (-not $LiteralPath.StartsWith("Env:")) { throw "Unexpected fixture Get-Item." }
    $name = $LiteralPath.Substring(4)
    if ($script:fixtureEnvironment.ContainsKey($name)) {
        [PSCustomObject]@{Value=$script:fixtureEnvironment[$name]}
    }
}
function Set-Item {
    [CmdletBinding()]
    param([string]$LiteralPath, [string]$Value)
    if (-not $LiteralPath.StartsWith("Env:")) { throw "Unexpected fixture Set-Item." }
    $script:fixtureEnvironment[$LiteralPath.Substring(4)] = $Value
}
function Remove-Item {
    [CmdletBinding()]
    param([string]$LiteralPath, [switch]$Force)
    if ($LiteralPath.StartsWith("Env:")) {
        $script:fixtureEnvironment.Remove($LiteralPath.Substring(4))
    } else {
        $target = [IO.Path]::GetFullPath($LiteralPath)
        $prefix = [IO.Path]::GetFullPath($FixturePath).TrimEnd("\") + "\"
        if (-not $target.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Fixture deletion escaped the OS temporary directory."
        }
        Microsoft.PowerShell.Management\Remove-Item -LiteralPath $target -Force:$Force -ErrorAction Stop
    }
}

function Get-Process {
    [CmdletBinding()]
    param([int]$Id)
    $start = if ($Id -eq 410001 -or $Id -eq 420001) {
        $script:fixtureWrapperStart
    } else {
        $script:fixtureChildStart
    }
    if ($Id -eq 510001) { $start = [DateTime]::Parse("2025-01-01T00:00:00.0000000Z").ToUniversalTime() }
    if ($Id -eq 510002) { $start = [DateTime]::Parse("2025-01-01T00:00:01.0000000Z").ToUniversalTime() }
    if ($Scenario -eq "reused-wrapper" -and $script:fixtureLaunched -and $Id -eq $script:fixtureWrapperId) {
        $start = $start.AddHours(1)
    }
    if ($Scenario -eq "older-child" -and $Id -eq $script:fixtureListenerId) {
        $start = $script:fixtureWrapperStart.AddHours(-1)
    }
    if ($Scenario -eq "listener-reused" -and $Id -eq $script:fixtureListenerId) {
        $script:fixtureListenerTimeQueries++
        if ($script:fixtureListenerTimeQueries -gt 1) { $start = $start.AddHours(1) }
    }
    [PSCustomObject]@{Id=$Id;StartTime=$start}
}
function Get-CimInstance {
    [CmdletBinding()]
    param($ClassName, [string]$Filter)
    if ($Scenario -eq "cim-failure") {
        Write-Error -Message "fixture-cim-failure" -Category PermissionDenied
        return
    }
    $processId = [int]($Filter -replace "^ProcessId=", "")
    $parentId = switch ($processId) {
        410002 { if ($Scenario -eq "multi-hop") { 410003 } else { 410001 } }
        410003 { 410001 }
        510002 { 510001 }
        420002 { 420001 }
        default { 999998 }
    }
    $created = if ($processId -eq 410003) {
        $script:fixtureWrapperStart.AddMilliseconds(500)
    } else { $script:fixtureChildStart }
    if ($Scenario -eq "older-child" -and $processId -eq $script:fixtureListenerId) {
        $created = $script:fixtureWrapperStart.AddHours(-1)
    }
    [PSCustomObject]@{
        ProcessId=$processId;ParentProcessId=$parentId;CreationDate=$created
        CommandLine=if ($Scenario -eq "legacy-wrong-command" -and $processId -eq 510002) {
            "python --listen=127.0.0.1:$Port another:app"
        } else { "python --listen=127.0.0.1:$Port --threads=8 app:app" }
    }
}
function Get-NetTCPConnection {
    [CmdletBinding()]
    param($State, $LocalPort)
    [IO.File]::WriteAllText((Join-Path $FixturePath ("query-" + $Label)), "queried")
    if ($script:fixtureLaunched -and $Scenario -eq "query-failure") {
        Write-Error -Message "fixture-query-failure" -Category PermissionDenied
        return
    }
    if ($Scenario -eq "owner-replaced" -and (Test-Path -LiteralPath $receiptPath)) {
        return [PSCustomObject]@{LocalAddress="127.0.0.1";LocalPort=$Port;OwningProcess=999999}
    }
    $statePath = Join-Path $FixturePath "listeners.json"
    if (Test-Path -LiteralPath $statePath) {
        $fixtureListeners = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($fixtureListener in $fixtureListeners) { $fixtureListener }
    }
}
function Get-HttpStatus {
    if ($Scenario -eq "unknown-health-failure" -or $Scenario -eq "health-failure") { return 503 }
    return 200
}
function Sync-CodeSnapshot {
    [IO.File]::WriteAllText((Join-Path $FixturePath ("sync-" + $Label)), "entered")
    if ($Scenario -eq "concurrent") {
        $releasePath = Join-Path $FixturePath ("release-" + $Label)
        $deadline = [DateTime]::UtcNow.AddSeconds(15)
        while (-not (Test-Path -LiteralPath $releasePath)) {
            if ([DateTime]::UtcNow -gt $deadline) { throw "Fixture release timed out." }
            Microsoft.PowerShell.Utility\Start-Sleep -Milliseconds 20
        }
    }
}
function Start-Process {
    [CmdletBinding()]
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$PassThru,
          $RedirectStandardOutput, $RedirectStandardError)
    if ($WindowStyle -ne "Hidden") { throw "Fixture launch must retain a hidden window." }
    Add-Content -LiteralPath (Join-Path $FixturePath "launches.txt") -Value $Label -Encoding UTF8
    $script:fixtureLaunched = $true
    $listenerId = if ($Scenario -like "unknown-*") { 999999 } else { $script:fixtureListenerId }
    if ($Scenario -eq "same-process") { $listenerId = $script:fixtureWrapperId }
    $listeners = @([PSCustomObject]@{LocalAddress="127.0.0.1";LocalPort=$Port;OwningProcess=$listenerId})
    if ($Scenario -eq "mixed-listeners") {
        $listeners += [PSCustomObject]@{LocalAddress="0.0.0.0";LocalPort=$Port;OwningProcess=999999}
    }
    [IO.File]::WriteAllText((Join-Path $FixturePath "listeners.json"), ($listeners | ConvertTo-Json))
    $wrapper = [PSCustomObject]@{
        Id=$script:fixtureWrapperId;HasExited=$false;StartTime=$script:fixtureWrapperStart
    }
    $wrapper | Add-Member -MemberType ScriptMethod -Name Refresh -Value { }
    return $wrapper
}
function Stop-Process {
    [CmdletBinding()]
    param([int]$Id, [switch]$Force)
    Add-Content -LiteralPath (Join-Path $FixturePath "stops.txt") -Value $Id -Encoding UTF8
    $statePath = Join-Path $FixturePath "listeners.json"
    if (Test-Path -LiteralPath $statePath) {
        $fixtureListeners = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $remaining = @($fixtureListeners | Where-Object { $_.OwningProcess -ne $Id })
        [IO.File]::WriteAllText($statePath, (ConvertTo-Json -InputObject $remaining))
    }
}
function Start-Sleep { param($Milliseconds) }
if ($Scenario -eq "receipt-failure") {
    function Write-JsonFile { param($Path, $Value) throw "fixture-receipt-failure" }
}
[IO.File]::WriteAllText((Join-Path $FixturePath ("requested-" + $Label)), "requested")
try {
    $entryOutput = $null
    if ($Scenario -eq "mutex-holder" -or $Scenario -eq "mutex-abandon") {
        Invoke-WithManagerLock -Operation {
            [IO.File]::WriteAllText((Join-Path $FixturePath "lock-held"), "held")
            $release = Join-Path $FixturePath "release-holder"
            $deadline = [DateTime]::UtcNow.AddSeconds(15)
            while (-not (Test-Path -LiteralPath $release)) {
                if ([DateTime]::UtcNow -gt $deadline) { throw "Fixture holder timed out." }
                Microsoft.PowerShell.Utility\Start-Sleep -Milliseconds 20
            }
            if ($Scenario -eq "mutex-abandon") { [Environment]::Exit(0) }
        }
    } elseif ($Scenario -eq "mutex-timeout") {
        # This manager addresses a different snapshot root on the same synthetic port.
        $codeRoot = Join-Path $FixturePath "another-root"
        Invoke-WithManagerLock -TimeoutMilliseconds 100 -Operation {
            [IO.File]::WriteAllText((Join-Path $FixturePath "unexpected-body"), "entered")
        }
    } elseif ($Scenario -eq "mutex-error") {
        Invoke-WithManagerLock -Operation { throw "fixture-operation-failure" }
    } elseif ($Scenario -eq "mutex-success") {
        Invoke-WithManagerLock -Operation {
            [IO.File]::WriteAllText((Join-Path $FixturePath "success-body"), "entered")
        }
    } else {
        $entryOutput = & $entrypoint
    }
    $entryStatus = if ($entryOutput) { ($entryOutput -join [Environment]::NewLine) | ConvertFrom-Json } else { $null }
    $outcome = @{success=$true;error="";managed=if ($entryStatus) { [bool]$entryStatus.managed } else { $false }}
} catch {
    $outcome = @{success=$false;error=$_.Exception.Message;managed=$null}
}
[IO.File]::WriteAllText((Join-Path $FixturePath ("outcome-" + $Label + ".json")), ($outcome | ConvertTo-Json))
'@
[IO.File]::WriteAllText($taskWorkerPath, $taskWorkerSource, (New-Object Text.UTF8Encoding($false)))
$taskPowerShellPath = Join-Path $PSHOME "powershell.exe"
if (-not (Test-Path -LiteralPath $taskPowerShellPath)) {
    $taskPowerShellPath = Join-Path $PSHOME "pwsh.exe"
}
$script:taskFixtureProcesses = @()
$script:taskOracleChecks = 0

function Assert-Fixture {
    param([bool]$Condition, [string]$Message)
    $script:taskOracleChecks++
    if (-not $Condition) { throw $Message }
}
function New-ManagerFixture {
    param([string]$Name)
    $path = Join-Path $taskFixtureRoot $Name
    [IO.Directory]::CreateDirectory($path) | Out-Null
    # Synthetic port identities only: every network query and launch is mocked.
    [IO.File]::WriteAllText((Join-Path $path "port.txt"), ([string](Get-Random -Minimum 49152 -Maximum 65535)))
    return $path
}
function Start-FixtureWorker {
    param([string]$FixturePath, [string]$Label, [string]$Scenario)
    $arguments = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"' + $taskWorkerPath + '"'),
        "-ManagerPath", ('"' + $taskManagerSourcePath + '"'),
        "-FixturePath", ('"' + $FixturePath + '"'), "-Label", $Label, "-Scenario", $Scenario
    )
    $launch = New-Object Diagnostics.ProcessStartInfo
    $launch.FileName = $taskPowerShellPath
    $launch.Arguments = $arguments -join " "
    $launch.WorkingDirectory = $FixturePath
    $launch.UseShellExecute = $false
    $launch.CreateNoWindow = $true
    $launch.RedirectStandardOutput = $true
    $launch.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($launch)
    $process | Add-Member -NotePropertyName TaskStdoutPath -NotePropertyValue (Join-Path $FixturePath ($Label + ".stdout.log"))
    $process | Add-Member -NotePropertyName TaskStderrPath -NotePropertyValue (Join-Path $FixturePath ($Label + ".stderr.log"))
    $null = $process.Handle
    $script:taskFixtureProcesses += $process
    return $process
}
function Wait-FixtureFile {
    param([string]$Path, [int]$Milliseconds = 10000)
    $deadline = [DateTime]::UtcNow.AddMilliseconds($Milliseconds)
    while (-not (Test-Path -LiteralPath $Path)) {
        if ([DateTime]::UtcNow -gt $deadline) { return $false }
        Microsoft.PowerShell.Utility\Start-Sleep -Milliseconds 20
    }
    return $true
}
function Read-FixtureOutcome {
    param([string]$FixturePath, [string]$Label, [object]$Process)
    Assert-Fixture ($Process.WaitForExit(10000)) "Fixture worker $Label did not finish."
    [IO.File]::WriteAllText($Process.TaskStdoutPath, $Process.StandardOutput.ReadToEnd(), (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText($Process.TaskStderrPath, $Process.StandardError.ReadToEnd(), (New-Object Text.UTF8Encoding($false)))
    Assert-Fixture ($Process.ExitCode -eq 0) ("Fixture worker failed: " +
        (Get-Content -LiteralPath (Join-Path $FixturePath ($Label + ".stderr.log")) -Raw -Encoding UTF8))
    Get-Content -LiteralPath (Join-Path $FixturePath ("outcome-" + $Label + ".json")) -Raw -Encoding UTF8 | ConvertFrom-Json
}
function Get-FixtureSha256 {
    param([string]$Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { [BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($Path))).Replace("-", "") }
    finally { $sha.Dispose() }
}
function Read-FixtureLines {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) { Get-Content -LiteralPath $Path -Encoding UTF8 }
}
try {
    if (-not $ExpectUnsafeBaseline) {
        $script:taskNetworkDenied = $false
        $script:taskListeners = @([PSCustomObject]@{LocalAddress="127.0.0.1";LocalPort=8004;OwningProcess=41})
        foreach ($taskWrongReceipt in @("port", "codeRoot", "sourceRoot")) {
            $script:taskReceipt.port = if ($taskWrongReceipt -eq "port") { 8005 } else { 8004 }
            $script:taskReceipt.codeRoot = if ($taskWrongReceipt -eq "codeRoot") { "another-snapshot-root" } else { $codeRoot }
            $script:taskReceipt.sourceRoot = if ($taskWrongReceipt -eq "sourceRoot") { "another-source-root" } else { $sourceRoot }
            $taskRejected = $false
            try { Stop-ManagedServer } catch {
                $taskRejected = $_.Exception.Message.Contains("another port or snapshot root")
            }
            Assert-Fixture $taskRejected "Stop accepted a receipt for another port/snapshot root."
            Assert-Fixture ($script:taskMutationCalls -eq 0) "Mismatched receipt caused a mutation."
        }
    }
    $taskConcurrent = New-ManagerFixture "concurrent"
    $taskWorkerA = Start-FixtureWorker $taskConcurrent "A" "concurrent"
    Assert-Fixture (Wait-FixtureFile (Join-Path $taskConcurrent "sync-A")) "First Start did not reach snapshot synchronization."
    $taskWorkerB = Start-FixtureWorker $taskConcurrent "B" "concurrent"
    Assert-Fixture (Wait-FixtureFile (Join-Path $taskConcurrent "requested-B")) "Second Start was not submitted."
    $taskBEntered = Wait-FixtureFile (Join-Path $taskConcurrent "sync-B") 800
    Assert-Fixture ($taskBEntered -eq [bool]$ExpectUnsafeBaseline) "Second Start crossed the snapshot boundary while the first was paused."
    [IO.File]::WriteAllText((Join-Path $taskConcurrent "release-A"), "released")
    $taskResultA = Read-FixtureOutcome $taskConcurrent "A" $taskWorkerA
    [IO.File]::WriteAllText((Join-Path $taskConcurrent "release-B"), "released")
    $taskResultB = Read-FixtureOutcome $taskConcurrent "B" $taskWorkerB
    Assert-Fixture ($taskResultA.success -and $taskResultB.success) "Concurrent Start/reuse did not succeed."
    $taskLaunches = @(Read-FixtureLines (Join-Path $taskConcurrent "launches.txt"))
    $taskExpectedLaunches = if ($ExpectUnsafeBaseline) { 2 } else { 1 }
    Assert-Fixture ($taskLaunches.Count -eq $taskExpectedLaunches) "Concurrent Starts launched an unexpected number of wrappers."
    $taskConcurrentReceipt = Get-Content -LiteralPath (Join-Path $taskConcurrent "isolated\server.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $taskExpectedOwner = if ($ExpectUnsafeBaseline) { 420002 } else { 410002 }
    Assert-Fixture ($taskConcurrentReceipt.listenerProcessId -eq $taskExpectedOwner) "Concurrent receipt owner changed unexpectedly."
    Write-Output "concurrent source entrypoints: starts=$($taskLaunches.Count), receiptOwner=$($taskConcurrentReceipt.listenerProcessId), secondCrossedCheck=$taskBEntered"

    foreach ($taskScenario in @("unknown-healthy", "unknown-health-failure", "mixed-listeners", "owner-replaced",
                                  "query-failure", "health-failure", "receipt-failure", "reused-wrapper", "older-child",
                                  "cim-failure", "listener-reused", "healthy", "same-process", "multi-hop")) {
        $taskCase = New-ManagerFixture $taskScenario
        $taskProcess = Start-FixtureWorker $taskCase "A" $taskScenario
        $taskOutcome = Read-FixtureOutcome $taskCase "A" $taskProcess
        $taskStops = @(Read-FixtureLines (Join-Path $taskCase "stops.txt"))
        $taskCaseReceiptPath = Join-Path $taskCase "isolated\server.json"
        $taskHasReceipt = Test-Path -LiteralPath $taskCaseReceiptPath
        if ($taskScenario -in @("healthy", "same-process", "multi-hop")) {
            Assert-Fixture ([bool]$taskOutcome.success) "$taskScenario launch should succeed."
            Assert-Fixture ([bool]$taskHasReceipt) "$taskScenario launch should publish its verified receipt."
            Assert-Fixture ($taskStops.Count -eq 0) "$taskScenario launch should not stop any process."
            $taskOwnReceipt = Get-Content -LiteralPath $taskCaseReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $taskOwnId = if ($taskScenario -eq "same-process") { 410001 } else { 410002 }
            Assert-Fixture ($taskOwnReceipt.listenerProcessId -eq $taskOwnId) "$taskScenario receipt owner mismatch."
        } elseif ($ExpectUnsafeBaseline) {
            if ($taskScenario -in @("unknown-healthy", "mixed-listeners", "owner-replaced", "reused-wrapper", "older-child", "cim-failure", "listener-reused")) {
                Assert-Fixture ([bool]$taskOutcome.success) "$taskScenario baseline no longer reproduces unsafe success."
                Assert-Fixture ([bool]$taskHasReceipt) "$taskScenario baseline did not publish a receipt."
            } elseif ($taskScenario -eq "unknown-health-failure") {
                Assert-Fixture (-not $taskOutcome.success) "Baseline health failure unexpectedly succeeded."
                Assert-Fixture ($taskStops -contains "999999") "Baseline did not reproduce an unknown-owner stop."
            }
        } else {
            Assert-Fixture (-not $taskOutcome.success) "$taskScenario must fail closed."
            Assert-Fixture (-not $taskHasReceipt) "$taskScenario left an unverified receipt."
            Assert-Fixture ($taskStops -notcontains "999999") "$taskScenario stopped an unknown port owner."
            if ($taskScenario -eq "reused-wrapper") {
                Assert-Fixture ($taskStops.Count -eq 0) "A recycled wrapper PID must not be stopped."
            } else {
                Assert-Fixture ($taskStops -contains "410001") "$taskScenario did not clean up its own wrapper."
            }
            if ($taskScenario -eq "listener-reused") {
                Assert-Fixture ($taskStops -notcontains "410002") "Recycled listener PID was stopped."
            }
            if ($taskScenario -eq "mixed-listeners") {
                Assert-Fixture ($taskStops -contains "410002") "Mixed listeners left the launch-owned listener running."
            }
            if ($taskScenario -eq "query-failure") {
                Assert-Fixture ($taskOutcome.error.Contains("fixture-query-failure")) "Ownership query failure was hidden."
            }
        }
        Write-Output ("fixture {0}: success={1}, receipt={2}, stops=[{3}]" -f
            $taskScenario, $taskOutcome.success, $taskHasReceipt, ($taskStops -join ","))
    }

    foreach ($taskLegacyScenario in @("legacy-status", "legacy-reuse", "legacy-restart", "legacy-wrong-source", "legacy-wrong-command", "legacy-wrong-starttime")) {
        $taskCase = New-ManagerFixture $taskLegacyScenario
        $taskWorker = Start-FixtureWorker $taskCase "A" $taskLegacyScenario
        $taskOutcome = Read-FixtureOutcome $taskCase "A" $taskWorker
        $taskStops = @(Read-FixtureLines (Join-Path $taskCase "stops.txt"))
        $taskLaunches = @(Read-FixtureLines (Join-Path $taskCase "launches.txt"))
        $taskReceipt = Join-Path $taskCase "isolated\server.json"
        $taskBeforeHash = Get-FixtureSha256 -Path (Join-Path $taskCase "legacy-before.json")
        $taskAfterHash = Get-FixtureSha256 -Path $taskReceipt
        if (($taskLegacyScenario -eq "legacy-wrong-source" -and -not $ExpectUnsafeBaseline) -or
            $taskLegacyScenario -in @("legacy-wrong-command", "legacy-wrong-starttime")) {
            Assert-Fixture (-not $taskOutcome.success) "Invalid legacy ownership metadata was accepted."
            Assert-Fixture ($taskStops.Count -eq 0 -and $taskLaunches.Count -eq 0) "Foreign legacy receipt caused process mutation."
            Assert-Fixture ($taskBeforeHash -eq $taskAfterHash) "Foreign legacy receipt was rewritten."
        } else {
            Assert-Fixture ($taskOutcome.success -and $taskOutcome.managed) "Valid pre-lineage legacy receipt is no longer managed."
            if ($taskLegacyScenario -in @("legacy-status", "legacy-reuse")) {
                Assert-Fixture ($taskStops.Count -eq 0 -and $taskLaunches.Count -eq 0) "Legacy status/reuse caused process mutation."
                Assert-Fixture ($taskBeforeHash -eq $taskAfterHash) "Legacy status/reuse rewrote unknown receipt metadata."
            } else {
                Assert-Fixture ($taskStops.Count -eq 2 -and $taskStops -contains "510001" -and $taskStops -contains "510002") "Legacy restart did not stop exactly the verified legacy pair."
                Assert-Fixture ($taskLaunches.Count -eq 1) "Legacy restart did not launch exactly one replacement."
            }
        }
        Write-Output ("legacy fixture {0}: success={1}, managed={2}, starts={3}, stops=[{4}]" -f
            $taskLegacyScenario,$taskOutcome.success,$taskOutcome.managed,$taskLaunches.Count,($taskStops -join ","))
    }

    if (-not $ExpectUnsafeBaseline) {
        foreach ($taskEntryCase in @("entry-status", "entry-stop", "entry-refresh", "entry-restart", "mutex-timeout")) {
            $taskCase = New-ManagerFixture $taskEntryCase
            $taskHolder = Start-FixtureWorker $taskCase "A" "mutex-holder"
            Assert-Fixture (Wait-FixtureFile (Join-Path $taskCase "lock-held")) "Mutex holder did not enter."
            $taskContender = Start-FixtureWorker $taskCase "B" $taskEntryCase
            Assert-Fixture (Wait-FixtureFile (Join-Path $taskCase "requested-B")) "Mutex contender was not submitted."
            if ($taskEntryCase -eq "mutex-timeout") {
                $taskContenderResult = Read-FixtureOutcome $taskCase "B" $taskContender
                Assert-Fixture (-not $taskContenderResult.success -and $taskContenderResult.error.Contains("Timed out waiting")) "Mutex timeout did not fail closed."
                Assert-Fixture (-not (Test-Path -LiteralPath (Join-Path $taskCase "unexpected-body"))) "A timed-out manager executed its operation."
            } else {
                $taskPremature = Wait-FixtureFile (Join-Path $taskCase "outcome-B.json") 300
                Assert-Fixture (-not $taskPremature) "$taskEntryCase bypassed the lifecycle mutex."
                Assert-Fixture (-not (Test-Path -LiteralPath (Join-Path $taskCase "query-B"))) "$taskEntryCase queried ownership inside another management operation."
                Assert-Fixture (-not (Test-Path -LiteralPath (Join-Path $taskCase "sync-B"))) "$taskEntryCase changed the snapshot inside another management operation."
            }
            [IO.File]::WriteAllText((Join-Path $taskCase "release-holder"), "released")
            $taskHolderResult = Read-FixtureOutcome $taskCase "A" $taskHolder
            Assert-Fixture ([bool]$taskHolderResult.success) "Mutex holder did not finish."
            if ($taskEntryCase -ne "mutex-timeout") {
                $taskContenderResult = Read-FixtureOutcome $taskCase "B" $taskContender
                Assert-Fixture ([bool]$taskContenderResult.success) "$taskEntryCase did not resume after release."
            }
            Write-Output ("mutex fixture {0}: no operation before lock release" -f $taskEntryCase)
        }

        $taskErrorCase = New-ManagerFixture "mutex-error-release"
        $taskErrorWorker = Start-FixtureWorker $taskErrorCase "A" "mutex-error"
        $taskErrorResult = Read-FixtureOutcome $taskErrorCase "A" $taskErrorWorker
        Assert-Fixture (-not $taskErrorResult.success -and $taskErrorResult.error.Contains("fixture-operation-failure")) "Operation failure was hidden."
        $taskAfterError = Start-FixtureWorker $taskErrorCase "B" "mutex-success"
        $taskAfterErrorResult = Read-FixtureOutcome $taskErrorCase "B" $taskAfterError
        Assert-Fixture ([bool]$taskAfterErrorResult.success) "Operation failure leaked the management lock."

        $taskAbandonCase = New-ManagerFixture "mutex-abandoned"
        $taskAbandonWorker = Start-FixtureWorker $taskAbandonCase "A" "mutex-abandon"
        Assert-Fixture (Wait-FixtureFile (Join-Path $taskAbandonCase "lock-held")) "Abandoning holder did not enter."
        $taskAfterAbandon = Start-FixtureWorker $taskAbandonCase "B" "mutex-success"
        Assert-Fixture (Wait-FixtureFile (Join-Path $taskAbandonCase "requested-B")) "Abandonment contender was not submitted."
        Assert-Fixture (-not (Wait-FixtureFile (Join-Path $taskAbandonCase "success-body") 300)) "Contender entered an owned mutex."
        [IO.File]::WriteAllText((Join-Path $taskAbandonCase "release-holder"), "released")
        Assert-Fixture ($taskAbandonWorker.WaitForExit(10000)) "Abandoning worker did not exit."
        $taskAbandonResult = Read-FixtureOutcome $taskAbandonCase "B" $taskAfterAbandon
        Assert-Fixture ([bool]$taskAbandonResult.success) "Abandoned mutex could not be safely acquired."
        Write-Output "mutex exception/abandonment fixtures: lock released or acquired, no leaked worker"
    }
    Write-Output "isolated manager race oracle passed: $script:taskOracleChecks checks; temp evidence=$taskFixtureRoot"
} finally {
    foreach ($taskProcess in $script:taskFixtureProcesses) {
        $taskProcess.Refresh()
        if (-not $taskProcess.HasExited) {
            Microsoft.PowerShell.Management\Stop-Process -InputObject $taskProcess -Force -ErrorAction SilentlyContinue
        }
        if ($taskProcess.WaitForExit(5000)) {
            if (-not (Test-Path -LiteralPath $taskProcess.TaskStdoutPath)) {
                [IO.File]::WriteAllText($taskProcess.TaskStdoutPath, $taskProcess.StandardOutput.ReadToEnd(), (New-Object Text.UTF8Encoding($false)))
                [IO.File]::WriteAllText($taskProcess.TaskStderrPath, $taskProcess.StandardError.ReadToEnd(), (New-Object Text.UTF8Encoding($false)))
            }
        }
        $taskProcess.Dispose()
    }
}
