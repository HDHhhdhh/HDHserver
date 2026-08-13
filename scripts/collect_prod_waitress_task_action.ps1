[CmdletBinding()]
param(
    [string]$TaskName = "Academy Server Waitress",
    [string]$ServerRoot = "C:\server",
    [int]$OriginPort = 8003,
    [string]$OutFile = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Resolve-FullPath([string]$Path) {
    [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($Path)).TrimEnd('\')
}

function Get-XmlChildText([System.Xml.XmlNode]$Node, [string]$Name) {
    $child = $Node.SelectSingleNode("./*[local-name()='$Name']")
    if ($child) { return [string]$child.InnerText }
    return ""
}

if ([string]::IsNullOrWhiteSpace($OutFile)) {
    $OutFile = Join-Path ([Environment]::GetFolderPath('UserProfile')) `
        'Downloads\prod-waitress-task-action.json'
}

$resolvedRoot = Resolve-FullPath $ServerRoot
$resolvedOut = Resolve-FullPath $OutFile
$outParent = Split-Path -Parent $resolvedOut
if (-not (Test-Path -LiteralPath $outParent -PathType Container)) {
    throw "Output directory does not exist: $outParent"
}

$tasks = @(Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop)
if ($tasks.Count -ne 1) {
    throw "Expected exactly one scheduled task named '$TaskName'; found $($tasks.Count)."
}
$task = $tasks[0]
$taskInfo = Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath

$actions = @($task.Actions | ForEach-Object {
    [ordered]@{
        execute = [string]$_.Execute
        arguments = [string]$_.Arguments
        workingDirectory = [string]$_.WorkingDirectory
    }
})

$taskXml = [xml](Export-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath)
$xmlActions = @($taskXml.SelectNodes("/*[local-name()='Task']/*[local-name()='Actions']/*[local-name()='Exec']") |
    ForEach-Object {
        [ordered]@{
            command = Get-XmlChildText $_ 'Command'
            arguments = Get-XmlChildText $_ 'Arguments'
            workingDirectory = Get-XmlChildText $_ 'WorkingDirectory'
        }
    })

$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $OriginPort -ErrorAction SilentlyContinue |
    Sort-Object OwningProcess -Unique |
    ForEach-Object {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)" `
            -ErrorAction SilentlyContinue
        [ordered]@{
            localAddress = [string]$_.LocalAddress
            localPort = [int]$_.LocalPort
            processId = [int]$_.OwningProcess
            executablePath = if ($process) { [string]$process.ExecutablePath } else { "" }
        }
    })

$receipt = [ordered]@{
    format = 'student-app-waitress-task-action/v1'
    capturedAtUtc = [DateTime]::UtcNow.ToString('o')
    computer = $env:COMPUTERNAME
    expected = [ordered]@{
        serverRoot = $resolvedRoot
        runner = Join-Path $resolvedRoot 'scripts\run_waitress_server.ps1'
        originPort = $OriginPort
    }
    task = [ordered]@{
        name = [string]$task.TaskName
        path = [string]$task.TaskPath
        state = [string]$task.State
        lastRunTime = $taskInfo.LastRunTime.ToUniversalTime().ToString('o')
        lastTaskResult = [int]$taskInfo.LastTaskResult
        actions = $actions
        xmlActions = $xmlActions
    }
    listeners = $listeners
    privacy = [ordered]@{
        containsRuntimeContents = $false
        containsEnvironmentDump = $false
        containsTaskActionArguments = $true
    }
}

$json = $receipt | ConvertTo-Json -Depth 10
$encoding = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($resolvedOut, $json + [Environment]::NewLine, $encoding)

[ordered]@{
    ok = $true
    outFile = $resolvedOut
    sha256 = (Get-FileHash -LiteralPath $resolvedOut -Algorithm SHA256).Hash
    taskState = [string]$task.State
    actionCount = $actions.Count
    listenerCount = $listeners.Count
} | ConvertTo-Json -Depth 4
