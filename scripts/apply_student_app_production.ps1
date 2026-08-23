param(
    [Parameter(Mandatory = $true)]
    [string]$StageReceiptPath,
    [Parameter(Mandatory = $true)]
    [string]$BundlePath,
    [Parameter(Mandatory = $true)]
    [string]$ChecksumPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9A-Fa-f]{64}$')]
    [string]$ExpectedBundleSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9A-Fa-f]{64}$')]
    [string]$ExpectedStageReceiptSha256,
    [string]$ServerRoot = "C:\server",
    [string]$WaitressTaskName = "Academy Server Waitress",
    [string]$PushTaskName = "Academy Student Push Delivery",
    [int]$OriginPort = 8003,
    [string]$RuntimeBackupRoot = "C:\server-runtime-backups",
    [string]$CodeRollbackRoot = "C:\server-code-rollback",
    [string]$OutFile = "",
    [switch]$ConfirmApply
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$deploymentId = Get-Date -Format "yyyyMMdd-HHmmss"
$startedAtUtc = [DateTime]::UtcNow.ToString("o")
$expectedHash = $ExpectedBundleSha256.ToUpperInvariant()
$expectedStageReceiptHash = $ExpectedStageReceiptSha256.ToUpperInvariant()

function Resolve-FullPath([string]$Path) {
    [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Test-IsWithin([string]$Child, [string]$Parent) {
    $childPath = Resolve-FullPath $Child
    $parentPath = Resolve-FullPath $Parent
    $prefix = $parentPath + [IO.Path]::DirectorySeparatorChar
    $childPath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NoReparsePath([string]$Path, [string]$Label) {
    $full = Resolve-FullPath $Path
    $root = [IO.Path]::GetPathRoot($full)
    $current = $root
    $tail = $full.Substring($root.Length)
    foreach ($segment in @($tail.Split('\') | Where-Object { $_ })) {
        $current = Join-Path $current $segment
        if (-not (Test-Path -LiteralPath $current)) { continue }
        $item = Get-Item -LiteralPath $current -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Label crosses a filesystem reparse point: $current"
        }
    }
}

function Assert-OutsideServerRoot([string]$Path, [string]$Label) {
    $full = Resolve-FullPath $Path
    if ($full.Equals($script:ServerRoot, [StringComparison]::OrdinalIgnoreCase) -or
        (Test-IsWithin $full $script:ServerRoot)) {
        throw "$Label must be outside ServerRoot: $full"
    }
}

function Convert-ManifestRelativePath([string]$RawPath) {
    if ([string]::IsNullOrWhiteSpace($RawPath)) { throw "Manifest contains an empty path." }
    $path = $RawPath.Trim()
    if ($path -ne $path.Replace('\', '/')) { throw "Manifest path must use forward slashes: $path" }
    if ([IO.Path]::IsPathRooted($path) -or $path.StartsWith('/') -or $path.Contains(':')) {
        throw "Manifest contains a rooted or drive-qualified path: $path"
    }
    $segments = @($path.Split('/') | Where-Object { $_ -ne '' })
    if ($segments.Count -eq 0 -or $segments.Count -ne $path.Split('/').Count -or
        @($segments | Where-Object { $_ -in @('.', '..') }).Count -gt 0) {
        throw "Manifest contains an unsafe relative path: $path"
    }
    $forbidden = @(
        '(?i)(^|/)(\.env|instance|files|data|_runtime_backups|_data_mirror)(/|$)',
        '(?i)\.(sqlite|sqlite-wal|sqlite-shm|db|pem|zip|tmp|log)$',
        '(?i)(^|/)(students|auth_accounts|updates|progress|logs)\.json$'
    )
    foreach ($pattern in $forbidden) {
        if ($path -match $pattern) { throw "Manifest contains a forbidden runtime path: $path" }
    }
    $path
}

function Join-ContainedPath([string]$Root, [string]$RelativePath) {
    $relative = Convert-ManifestRelativePath $RelativePath
    $candidate = Resolve-FullPath (Join-Path $Root ($relative.Replace('/', '\')))
    if (-not (Test-IsWithin $candidate $Root)) { throw "Resolved path escaped its root: $relative" }
    $candidate
}

function Assert-NoReparseAncestors([string]$Root, [string]$RelativePath) {
    Assert-NoReparsePath $Root 'Deployment root'
    $current = Resolve-FullPath $Root
    $segments = @((Convert-ManifestRelativePath $RelativePath).Split('/'))
    for ($index = 0; $index -lt ($segments.Count - 1); $index++) {
        $current = Join-Path $current $segments[$index]
        if (-not (Test-Path -LiteralPath $current)) { continue }
        $item = Get-Item -LiteralPath $current -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Deployment path crosses a reparse point: $current"
        }
    }
}

function New-PrivateDirectory([string]$Path) {
    if (Test-Path -LiteralPath $Path) { throw "Private backup directory already exists: $Path" }
    $null = New-Item -ItemType Directory -Path $Path
    $security = [Security.AccessControl.DirectorySecurity]::new()
    $security.SetAccessRuleProtection($true, $false)
    $inheritance = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor `
        [Security.AccessControl.InheritanceFlags]::ObjectInherit
    $propagation = [Security.AccessControl.PropagationFlags]::None
    $allow = [Security.AccessControl.AccessControlType]::Allow
    $sids = @(
        [Security.Principal.SecurityIdentifier]::new('S-1-5-18'),
        [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'),
        [Security.Principal.WindowsIdentity]::GetCurrent().User
    )
    foreach ($sid in @($sids | Select-Object -Unique)) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $sid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            $propagation,
            $allow
        )
        $security.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $security
    Assert-NoReparsePath $Path 'Private runtime backup directory'
    $acl = Get-Acl -LiteralPath $Path
    if (-not $acl.AreAccessRulesProtected) { throw "Runtime backup ACL still inherits permissions." }
    $broad = @('S-1-1-0', 'S-1-5-11', 'S-1-5-32-545', 'S-1-5-32-546')
    foreach ($rule in $acl.Access) {
        if ($rule.AccessControlType -ne 'Allow') { continue }
        try { $sidValue = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value }
        catch { $sidValue = $rule.IdentityReference.Value }
        if ($broad -contains $sidValue) { throw "Runtime backup ACL grants broad access to $sidValue." }
    }
}

function Get-Sha256([string]$Path) {
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Get-StringSha256([string]$Value) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
        ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '')
    } finally {
        $sha.Dispose()
    }
}

function Get-StreamSha256([IO.Stream]$Stream) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        ([BitConverter]::ToString($sha.ComputeHash($Stream))).Replace('-', '')
    } finally {
        $sha.Dispose()
    }
}

function Get-RuntimeFingerprints([string]$Root) {
    $paths = @(
        'students.json', 'auth_accounts.json', 'updates.json', 'progress.json', 'logs.json',
        'app.sqlite', 'watch.json', 'attendance.json', 'contact.json', 'arrive_time.json',
        'extra_attend.json', 'absent.json', 'weekend_slots.json',
        'school_calendar.json', 'tests.json', 'announcements.json', 'announce_status.json',
        'data/today_order.json'
    )
    $items = [ordered]@{}
    foreach ($relative in $paths) {
        $full = Join-Path $Root ($relative.Replace('/', '\'))
        if (Test-Path -LiteralPath $full -PathType Leaf) {
            $file = Get-Item -LiteralPath $full
            $items[$relative] = [ordered]@{ size = $file.Length; sha256 = Get-Sha256 $full }
        } else {
            $items[$relative] = $null
        }
    }
    $items
}

function Compare-FingerprintMaps($Before, $After) {
    $differences = @()
    foreach ($property in $Before.PSObject.Properties) {
        $path = $property.Name
        $left = $property.Value
        $rightProperty = $After.PSObject.Properties[$path]
        $right = if ($rightProperty) { $rightProperty.Value } else { $null }
        $leftText = if ($null -eq $left) { '<missing>' } else { "$($left.size)|$($left.sha256)" }
        $rightText = if ($null -eq $right) { '<missing>' } else { "$($right.size)|$($right.sha256)" }
        if ($leftText -ne $rightText) {
            $differences += [ordered]@{ path = $path; before = $leftText; after = $rightText }
        }
    }
    @($differences)
}

function Get-FullRuntimeInventory([string]$Root) {
    $rootSuffixes = @(
        '.json', '.sqlite', '.sqlite-wal', '.sqlite-shm', '.db', '.db-wal', '.db-shm', '.csv', '.tmp'
    )
    $skipParts = @('.git', '.pytest_cache', '__pycache__', 'venv', '_data_mirror', '_runtime_backups')
    $files = [Collections.Generic.List[IO.FileInfo]]::new()
    foreach ($file in @(Get-ChildItem -LiteralPath $Root -File -Force)) {
        if ($rootSuffixes -contains $file.Extension.ToLowerInvariant()) { $files.Add($file) }
    }
    foreach ($directoryName in @('data', 'files', 'instance')) {
        $directory = Join-Path $Root $directoryName
        if (-not (Test-Path -LiteralPath $directory -PathType Container)) { continue }
        foreach ($file in @(Get-ChildItem -LiteralPath $directory -Recurse -File -Force)) {
            $relativeParts = @($file.FullName.Substring((Resolve-FullPath $Root).Length + 1).Split('\'))
            if (@($relativeParts | Where-Object { $skipParts -contains $_ }).Count -gt 0) { continue }
            $files.Add($file)
        }
    }
    $inventory = [ordered]@{}
    $rootPrefixLength = (Resolve-FullPath $Root).Length + 1
    foreach ($file in @($files | Sort-Object FullName -Unique)) {
        $relative = $file.FullName.Substring($rootPrefixLength).Replace('\', '/')
        if ($relative -eq 'instance/student-app-vapid-private.pem' -or
            $relative.StartsWith('instance/student-app-vapid-private.pem.', [StringComparison]::Ordinal)) {
            continue
        }
        $pathDigest = Get-StringSha256 $relative
        $inventory[$pathDigest] = [ordered]@{ size = $file.Length; sha256 = Get-Sha256 $file.FullName }
    }
    $inventory
}

function Compare-RuntimeInventories($Before, $After) {
    $beforeObject = [pscustomobject]$Before
    $afterObject = [pscustomobject]$After
    $keys = @(
        @($beforeObject.PSObject.Properties.Name) + @($afterObject.PSObject.Properties.Name) |
            Sort-Object -Unique
    )
    $differences = @()
    foreach ($key in $keys) {
        $leftProperty = $beforeObject.PSObject.Properties[$key]
        $rightProperty = $afterObject.PSObject.Properties[$key]
        $left = if ($leftProperty) { $leftProperty.Value } else { $null }
        $right = if ($rightProperty) { $rightProperty.Value } else { $null }
        $leftText = if ($null -eq $left) { '<missing>' } else { "$($left.size)|$($left.sha256)" }
        $rightText = if ($null -eq $right) { '<missing>' } else { "$($right.size)|$($right.sha256)" }
        if ($leftText -ne $rightText) {
            $differences += [ordered]@{ pathDigest = $key; before = $leftText; after = $rightText }
        }
    }
    @($differences)
}

function Get-ListenerPids([int]$Port) {
    @(
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
    )
}

function Wait-ForListenerState([int]$Port, [bool]$ShouldListen, [int]$TimeoutSeconds) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $listening = @(Get-ListenerPids $Port).Count -gt 0
        if ($listening -eq $ShouldListen) { return $true }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    $false
}

function Get-ExactTask([string]$Name) {
    $tasks = @(Get-ScheduledTask -TaskName $Name -ErrorAction Stop)
    if ($tasks.Count -ne 1) { throw "Expected exactly one scheduled task named '$Name'; found $($tasks.Count)." }
    $tasks[0]
}

function Stop-WaitressTask([object]$Task, [int]$Port) {
    Stop-ScheduledTask -TaskName $Task.TaskName -TaskPath $Task.TaskPath
    if (-not (Wait-ForListenerState $Port $false 45)) {
        throw "Waitress task stopped but port $Port is still listening. No code was changed."
    }
}

function Start-WaitressTask([object]$Task, [int]$Port) {
    Start-ScheduledTask -TaskName $Task.TaskName -TaskPath $Task.TaskPath
    if (-not (Wait-ForListenerState $Port $true 60)) {
        throw "Waitress task did not restore a listener on port $Port within 60 seconds."
    }
}

function Ensure-WaitressStoppedForRollback([object]$Task, [int]$Port) {
    Stop-ScheduledTask -TaskName $Task.TaskName -TaskPath $Task.TaskPath -ErrorAction SilentlyContinue
    if (-not (Wait-ForListenerState $Port $false 45)) {
        throw "Cannot rollback code while port $Port still has a listener."
    }
}

function Get-PushTaskState([string]$Name) {
    $tasks = @(Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue)
    if ($tasks.Count -gt 1) { throw "Expected zero or one push task named '$Name'; found $($tasks.Count)." }
    if ($tasks.Count -eq 0) { return [ordered]@{ name = $Name; present = $false; state = 'Absent'; enabled = $false } }
    $task = $tasks[0]
    $enabled = $true
    if ($task.Settings -and $null -ne $task.Settings.Enabled) { $enabled = [bool]$task.Settings.Enabled }
    $state = $task.State.ToString()
    if ($state -ne 'Disabled' -or $enabled) {
        throw "Push delivery task must be absent or Disabled before code apply; found state=$state enabled=$enabled."
    }
    [ordered]@{ name = $Name; present = $true; state = $state; enabled = $enabled }
}

function Assert-WaitressTaskTargetsServer([object]$Task, [string]$Root) {
    $actions = @($Task.Actions)
    if ($actions.Count -ne 1) { throw "Waitress task must have exactly one action." }
    $action = $actions[0]
    $executeName = [IO.Path]::GetFileName(([string]$action.Execute)).ToLowerInvariant()
    if ($executeName -notin @('powershell.exe', 'pwsh.exe')) {
        throw "Waitress task action must execute PowerShell."
    }
    if ([string]::IsNullOrWhiteSpace([string]$action.WorkingDirectory) -or
        -not (Resolve-FullPath ([string]$action.WorkingDirectory)).Equals(
            (Resolve-FullPath $Root), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Waitress task WorkingDirectory does not match ServerRoot."
    }
    $runner = Resolve-FullPath (Join-Path $Root 'scripts\run_waitress_server.ps1')
    if ([string]$action.Arguments -notmatch [regex]::Escape($runner)) {
        throw "Waitress task arguments do not reference the ServerRoot Waitress runner."
    }
    [ordered]@{ execute = $executeName; workingDirectoryMatches = $true; runnerMatches = $true }
}

function Invoke-LocalProbe([string]$HostHeader, [string]$Path, [int]$Port) {
    $curl = Get-Command curl.exe -ErrorAction Stop
    $uri = "http://127.0.0.1:$Port$Path"
    $output = & $curl.Source '-sS' '--max-time' '10' '-o' 'NUL' '-w' '%{http_code}' `
        '-H' "Host: $HostHeader" '-H' 'X-Forwarded-Proto: https' $uri
    $exitCode = $LASTEXITCODE
    $status = 0
    [void][int]::TryParse((@($output) | Select-Object -Last 1), [ref]$status)
    [ordered]@{ host = $HostHeader; path = $Path; status = $status; curlExitCode = $exitCode }
}

function Invoke-DisabledPublicHealthProbes([int]$Port) {
    @(
        (Invoke-LocalProbe "127.0.0.1:$Port" '/' $Port),
        (Invoke-LocalProbe 'app.5a-math.com' '/app' $Port),
        (Invoke-LocalProbe 'dev-app.5a-math.com' '/app' $Port)
    )
}

function Assert-DisabledPublicHealthProbes([array]$Probes, [string]$Context) {
    if ($Probes.Count -ne 3 -or
        $Probes[0].curlExitCode -ne 0 -or $Probes[0].status -ne 200 -or
        $Probes[1].curlExitCode -ne 0 -or $Probes[1].status -ne 404 -or
        $Probes[2].curlExitCode -ne 0 -or $Probes[2].status -ne 404) {
        throw "$Context health probes failed; expected 200/404/404."
    }
}

function Write-Receipt([hashtable]$Receipt, [string]$Path) {
    $Receipt.completedAtUtc = [DateTime]::UtcNow.ToString('o')
    $parent = Split-Path -Parent $Path
    if ($parent) { $null = New-Item -ItemType Directory -Path $parent -Force }
    [IO.File]::WriteAllText(
        $Path,
        (($Receipt | ConvertTo-Json -Depth 12) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )
}

function Verify-BackupArchive([string]$ArchivePath, [string]$ExpectedRoot, $RuntimeBefore, $FullRuntimeBefore) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $entryNames = @{}
        foreach ($zipEntry in @($zip.Entries)) {
            if ($entryNames.ContainsKey($zipEntry.FullName)) { throw "Runtime backup contains duplicate ZIP paths." }
            $entryNames[$zipEntry.FullName] = $zipEntry
        }
        $entry = @($zip.Entries | Where-Object { $_.FullName -eq 'MANIFEST.json' })
        if ($entry.Count -ne 1) { throw "Runtime backup is missing its unique MANIFEST.json." }
        $reader = [IO.StreamReader]::new($entry[0].Open(), [Text.Encoding]::UTF8)
        try { $manifest = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        if (-not (Resolve-FullPath ([string]$manifest.root)).Equals(
            (Resolve-FullPath $ExpectedRoot), [StringComparison]::OrdinalIgnoreCase)) {
            throw "Runtime backup manifest root does not match ServerRoot."
        }
        $records = @{}
        $manifestInventory = [ordered]@{}
        foreach ($item in @($manifest.files)) {
            $relative = ([string]$item.path).Replace('\', '/')
            $segments = @($relative.Split('/') | Where-Object { $_ })
            if ([string]::IsNullOrWhiteSpace($relative) -or [IO.Path]::IsPathRooted($relative) -or
                $relative.StartsWith('/') -or $relative.Contains(':') -or
                $segments.Count -ne $relative.Split('/').Count -or
                @($segments | Where-Object { $_ -in @('.', '..') }).Count -gt 0) {
                throw "Runtime backup manifest contains an unsafe path."
            }
            if ($records.ContainsKey($relative)) { throw "Runtime backup manifest contains duplicate paths." }
            if (-not $entryNames.ContainsKey($relative)) { throw "Runtime backup ZIP omitted a manifest data entry." }
            $dataEntry = $entryNames[$relative]
            if ([long]$dataEntry.Length -ne [long]$item.size) { throw "Runtime backup ZIP size mismatch." }
            $dataStream = $dataEntry.Open()
            try { $entryHash = Get-StreamSha256 $dataStream } finally { $dataStream.Dispose() }
            if ($entryHash -ne ([string]$item.sha256).ToUpperInvariant()) {
                throw "Runtime backup ZIP content hash mismatch."
            }
            $records[$relative] = $item
            $manifestInventory[(Get-StringSha256 $relative)] = [ordered]@{
                size = [long]$item.size
                sha256 = ([string]$item.sha256).ToUpperInvariant()
            }
        }
        if ($zip.Entries.Count -ne ($records.Count + 1)) { throw "Runtime backup ZIP has unmanifested entries." }
        $inventoryDifferences = @(Compare-RuntimeInventories $FullRuntimeBefore $manifestInventory)
        if ($inventoryDifferences.Count -gt 0) { throw "Runtime backup does not exactly cover the pre-deploy runtime inventory." }
        foreach ($property in ([pscustomobject]$RuntimeBefore).PSObject.Properties) {
            if ($null -eq $property.Value) { continue }
            if (-not $records.ContainsKey($property.Name)) {
                throw "Runtime backup omitted an existing protected file: $($property.Name)"
            }
            $record = $records[$property.Name]
            if ([string]$record.sha256 -ne [string]$property.Value.sha256 -or
                [long]$record.size -ne [long]$property.Value.size) {
                throw "Runtime backup fingerprint mismatch: $($property.Name)"
            }
        }
        [ordered]@{
            manifestVerified = $true
            fullInventoryVerified = $true
            entryBytesVerified = $true
            fileCount = @($manifest.files).Count
            createdAt = $manifest.createdAt
        }
    } finally {
        $zip.Dispose()
    }
}

function New-RuntimeBackup([string]$PythonPath, [string]$BackupScript, [string]$Root, [string]$OutDir) {
    $oldScript = $env:STUDENT_APP_DEPLOY_BACKUP_SCRIPT
    $oldRoot = $env:STUDENT_APP_DEPLOY_SERVER_ROOT
    $oldOut = $env:STUDENT_APP_DEPLOY_BACKUP_ROOT
    try {
        $env:STUDENT_APP_DEPLOY_BACKUP_SCRIPT = $BackupScript
        $env:STUDENT_APP_DEPLOY_SERVER_ROOT = $Root
        $env:STUDENT_APP_DEPLOY_BACKUP_ROOT = $OutDir
        $driver = @'
import importlib.util, json, os
from pathlib import Path
script = Path(os.environ['STUDENT_APP_DEPLOY_BACKUP_SCRIPT'])
spec = importlib.util.spec_from_file_location('student_app_runtime_backup', script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.ROOT = Path(os.environ['STUDENT_APP_DEPLOY_SERVER_ROOT'])
archive = module.make_backup(Path(os.environ['STUDENT_APP_DEPLOY_BACKUP_ROOT']))
print(json.dumps({'archive': str(archive.resolve())}))
'@
        $output = & $PythonPath -c $driver
        if ($LASTEXITCODE -ne 0) { throw "Runtime backup command failed with exit code $LASTEXITCODE." }
        $result = (@($output) | Select-Object -Last 1) | ConvertFrom-Json
        Resolve-FullPath ([string]$result.archive)
    } finally {
        if ($null -eq $oldScript) { Remove-Item Env:STUDENT_APP_DEPLOY_BACKUP_SCRIPT -ErrorAction SilentlyContinue } else { $env:STUDENT_APP_DEPLOY_BACKUP_SCRIPT = $oldScript }
        if ($null -eq $oldRoot) { Remove-Item Env:STUDENT_APP_DEPLOY_SERVER_ROOT -ErrorAction SilentlyContinue } else { $env:STUDENT_APP_DEPLOY_SERVER_ROOT = $oldRoot }
        if ($null -eq $oldOut) { Remove-Item Env:STUDENT_APP_DEPLOY_BACKUP_ROOT -ErrorAction SilentlyContinue } else { $env:STUDENT_APP_DEPLOY_BACKUP_ROOT = $oldOut }
    }
}

function Copy-VerifiedFile(
    [string]$Source,
    [string]$Destination,
    [string]$ExpectedSha256,
    [string]$Token,
    [string]$ReplacementBackupPath,
    [string]$FailedTempRoot
) {
    $parent = Split-Path -Parent $Destination
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        $null = New-Item -ItemType Directory -Path $parent -Force
    }
    $temp = Join-Path $parent (".student-app-deploy-$Token-" + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        Copy-Item -LiteralPath $Source -Destination $temp
        if ((Get-Sha256 $temp) -ne $ExpectedSha256) { throw "Temporary copy hash mismatch: $Destination" }
        if (Test-Path -LiteralPath $Destination) {
            if (-not (Test-Path -LiteralPath $Destination -PathType Leaf)) { throw "Destination is not a file: $Destination" }
            $replacementParent = Split-Path -Parent $ReplacementBackupPath
            $null = New-Item -ItemType Directory -Path $replacementParent -Force
            [IO.File]::Replace($temp, $Destination, $ReplacementBackupPath, $true)
        } else {
            [IO.File]::Move($temp, $Destination)
        }
        if ((Get-Sha256 $Destination) -ne $ExpectedSha256) { throw "Applied file hash mismatch: $Destination" }
    } catch {
        if (Test-Path -LiteralPath $temp -PathType Leaf) {
            $null = New-Item -ItemType Directory -Path $FailedTempRoot -Force
            $failedTemp = Join-Path $FailedTempRoot ([Guid]::NewGuid().ToString('N') + '.pending')
            Move-Item -LiteralPath $temp -Destination $failedTemp
        }
        throw
    }
}

function Restore-Code([string]$Root, [string]$RollbackRoot, [array]$AppliedPaths, [array]$OriginalPaths, [array]$MovedRemovedPaths) {
    $errors = @()
    $originalSet = @{}
    foreach ($item in $OriginalPaths) { $originalSet[[string]$item.path] = $item }
    foreach ($relative in @($AppliedPaths | Select-Object -Unique)) {
        try {
            $destination = Join-ContainedPath $Root $relative
            if (Test-Path -LiteralPath $destination -PathType Leaf) {
                $failedPath = Join-ContainedPath (Join-Path $RollbackRoot 'failed-deployed') $relative
                $failedParent = Split-Path -Parent $failedPath
                $null = New-Item -ItemType Directory -Path $failedParent -Force
                Move-Item -LiteralPath $destination -Destination $failedPath -Force
            }
            if ($originalSet.ContainsKey($relative)) {
                $backup = Join-ContainedPath (Join-Path $RollbackRoot 'original') $relative
                $parent = Split-Path -Parent $destination
                $null = New-Item -ItemType Directory -Path $parent -Force
                Copy-Item -LiteralPath $backup -Destination $destination
                if ((Get-Sha256 $destination) -ne [string]$originalSet[$relative].sha256) {
                    throw "Restored original hash mismatch: $relative"
                }
            }
        } catch { $errors += $_.Exception.Message }
    }
    foreach ($record in @($MovedRemovedPaths)) {
        try {
            $relative = [string]$record.path
            $source = Join-ContainedPath (Join-Path $RollbackRoot 'removed') $relative
            $destination = Join-ContainedPath $Root $relative
            if (-not (Test-Path -LiteralPath $source -PathType Leaf) -or
                (Get-Item -LiteralPath $source).Length -ne [long]$record.size -or
                (Get-Sha256 $source) -ne [string]$record.sha256) {
                throw "Removed-path rollback source fingerprint mismatch: $relative"
            }
            if (Test-Path -LiteralPath $destination) { throw "Cannot restore removed path because destination exists: $relative" }
            $parent = Split-Path -Parent $destination
            $null = New-Item -ItemType Directory -Path $parent -Force
            Move-Item -LiteralPath $source -Destination $destination
            if ((Get-Item -LiteralPath $destination).Length -ne [long]$record.size -or
                (Get-Sha256 $destination) -ne [string]$record.sha256) {
                throw "Restored removed-path fingerprint mismatch: $relative"
            }
        } catch { $errors += $_.Exception.Message }
    }
    if ($errors.Count) { throw ("Code rollback failed: " + ($errors -join ' | ')) }
}

$ServerRoot = Resolve-FullPath $ServerRoot
$StageReceiptPath = Resolve-FullPath $StageReceiptPath
$BundlePath = Resolve-FullPath $BundlePath
$ChecksumPath = Resolve-FullPath $ChecksumPath
$RuntimeBackupRoot = Resolve-FullPath $RuntimeBackupRoot
$CodeRollbackRoot = Resolve-FullPath $CodeRollbackRoot
Assert-OutsideServerRoot $RuntimeBackupRoot 'RuntimeBackupRoot'
Assert-OutsideServerRoot $CodeRollbackRoot 'CodeRollbackRoot'
Assert-NoReparsePath $ServerRoot 'ServerRoot'
Assert-NoReparsePath $RuntimeBackupRoot 'RuntimeBackupRoot'
Assert-NoReparsePath $CodeRollbackRoot 'CodeRollbackRoot'
if (-not ([IO.Path]::GetPathRoot($CodeRollbackRoot)).Equals(
    [IO.Path]::GetPathRoot($ServerRoot), [StringComparison]::OrdinalIgnoreCase)) {
    throw "CodeRollbackRoot must be on the same filesystem volume as ServerRoot."
}
if (-not $ConfirmApply) { throw "Refusing to change production without -ConfirmApply." }
if (-not (Test-Path -LiteralPath $ServerRoot -PathType Container)) { throw "ServerRoot not found: $ServerRoot" }
if (-not (Test-Path -LiteralPath $StageReceiptPath -PathType Leaf)) { throw "Stage receipt not found: $StageReceiptPath" }
if (-not (Test-Path -LiteralPath $BundlePath -PathType Leaf)) { throw "Bundle not found: $BundlePath" }
if (-not (Test-Path -LiteralPath $ChecksumPath -PathType Leaf)) { throw "Checksum not found: $ChecksumPath" }

$deploymentRoot = Join-Path $CodeRollbackRoot $deploymentId
if (Test-Path -LiteralPath $deploymentRoot) { throw "Deployment rollback root already exists: $deploymentRoot" }
$null = New-Item -ItemType Directory -Path $deploymentRoot
Assert-NoReparsePath $deploymentRoot 'Deployment rollback root'
if (-not $OutFile) { $OutFile = Join-Path $deploymentRoot 'prod-code-apply.json' }
$OutFile = Resolve-FullPath $OutFile
if (-not (Test-IsWithin $OutFile $deploymentRoot)) { throw "OutFile must stay inside this deployment rollback root: $deploymentRoot" }

$receipt = [ordered]@{
    format = 'student-app-production-apply/v1'
    deploymentId = $deploymentId
    startedAtUtc = $startedAtUtc
    completedAtUtc = $null
    computer = $env:COMPUTERNAME
    serverRoot = $ServerRoot
    approvedBundleSha256 = $expectedHash
    approvedStageReceiptSha256 = $expectedStageReceiptHash
    stage = $null
    task = [ordered]@{
        name = $WaitressTaskName
        wasRunning = $false
        restarted = $false
        stateAfter = $null
        actionVerified = $false
        action = $null
    }
    pushTask = $null
    runtimeBackup = $null
    code = [ordered]@{
        manifestFiles = 0
        overwritten = 0
        created = 0
        removedMoved = 0
        applyAttempted = 0
        applied = 0
        rollbackRoot = $deploymentRoot
    }
    runtimeIntegrity = [ordered]@{
        protectedBefore = $null
        protectedAfter = $null
        protectedDifferences = @()
        fullBeforeCount = 0
        fullAfterCount = 0
        fullDifferences = @()
        pathDisclosure = 'sha256-digest-only-for-full-inventory'
    }
    probes = @()
    rollback = [ordered]@{ attempted = $false; succeeded = $false; healthProbes = @(); error = $null }
    externalChanges = [ordered]@{ cloudflare = $false; dns = $false; vapid = $false; taskDefinition = $false; runtimeRestore = $false }
    result = 'started'
    error = $null
}

$task = $null
$taskStopped = $false
$taskWasRunning = $false
$waitressStopIssued = $false
$codeMutationStarted = $false
$appliedPaths = [Collections.Generic.List[string]]::new()
$originalPaths = [Collections.Generic.List[object]]::new()
$movedRemovedPaths = [Collections.Generic.List[object]]::new()
$fullRuntimeBefore = $null
$applyAttemptedCount = 0
$confirmedAppliedCount = 0

try {
    if ((Get-Sha256 $StageReceiptPath) -ne $expectedStageReceiptHash) {
        throw "Stage receipt bytes do not match the approved receipt hash."
    }
    $stageReceipt = Get-Content -LiteralPath $StageReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($stageReceipt.format -ne 'student-app-production-stage/v1' -or -not $stageReceipt.readyForApply) {
        throw "Stage receipt is not an approved ready-for-apply receipt."
    }
    if ([string]$stageReceipt.computer -ne $env:COMPUTERNAME) { throw "Stage receipt belongs to a different computer." }
    if (-not (Resolve-FullPath ([string]$stageReceipt.serverRoot)).Equals($ServerRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Stage receipt ServerRoot does not match this deployment."
    }
    if ($stageReceipt.productionChanged -or $stageReceipt.productionRuntimeRead -or $stageReceipt.productionRuntimeWritten) {
        throw "Stage receipt reports production access or mutation."
    }
    if (@($stageReceipt.checks | Where-Object { -not $_.passed }).Count -gt 0) {
        throw "Stage receipt contains failed checks."
    }
    $stageRoot = Resolve-FullPath ([string]$stageReceipt.stageRoot)
    Assert-OutsideServerRoot $stageRoot 'StageRoot'
    Assert-NoReparsePath $stageRoot 'StageRoot'
    $stageSourceRoot = Join-Path $stageRoot 'source'
    if (-not (Test-Path -LiteralPath $stageSourceRoot -PathType Container)) { throw "Staged source is missing: $stageSourceRoot" }
    Assert-NoReparsePath $stageSourceRoot 'Staged source root'
    if ([string]$stageReceipt.bundle.sha256 -ne $expectedHash) { throw "Stage receipt bundle hash is not the approved hash." }

    $checksumLine = (Get-Content -LiteralPath $ChecksumPath -Encoding ASCII | Select-Object -First 1).Trim()
    if ($checksumLine -notmatch '^([0-9A-Fa-f]{64})\s+(.+)$') { throw "Checksum file format is invalid." }
    if ($matches[1].ToUpperInvariant() -ne $expectedHash) { throw "Checksum file does not contain the approved hash." }
    if ((Get-Sha256 $BundlePath) -ne $expectedHash) { throw "Bundle bytes do not match the approved hash." }

    $sourceRoot = Join-Path $deploymentRoot 'release-source'
    if (Test-Path -LiteralPath $sourceRoot) { throw "Deployment-owned release source already exists." }
    Expand-Archive -LiteralPath $BundlePath -DestinationPath $sourceRoot
    $manifestPath = Join-Path $sourceRoot 'RELEASE-MANIFEST.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "Staged release manifest is missing." }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.format -ne 'student-app-code-release/v1' -or
        $manifest.policy.containsRuntimeData -or $manifest.policy.containsCredentials) {
        throw "Release manifest policy is invalid."
    }
    if (@($manifest.files).Count -ne [int]$stageReceipt.bundle.fileCount -or
        @($manifest.removedPaths).Count -ne [int]$stageReceipt.bundle.removedPathCount) {
        throw "Staged manifest counts differ from the preflight receipt."
    }
    $stageManifestPath = Join-Path $stageSourceRoot 'RELEASE-MANIFEST.json'
    if (-not (Test-Path -LiteralPath $stageManifestPath -PathType Leaf) -or
        (Get-Sha256 $stageManifestPath) -ne (Get-Sha256 $manifestPath)) {
        throw "Mutable staging manifest differs from the approved bundle manifest."
    }

    $pythonPath = Join-Path $ServerRoot 'venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { throw "Production venv Python is missing." }
    $releaseVerifier = Join-Path $sourceRoot 'scripts\build_student_app_code_release.py'
    & $pythonPath $releaseVerifier '--verify-only' $BundlePath | Out-File -LiteralPath (Join-Path $deploymentRoot 'release-verify.log') -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "Release verifier rejected the approved bundle." }

    $verifiedFiles = @()
    foreach ($item in @($manifest.files)) {
        $relative = Convert-ManifestRelativePath ([string]$item.path)
        Assert-NoReparseAncestors $sourceRoot $relative
        Assert-NoReparseAncestors $ServerRoot $relative
        $source = Join-ContainedPath $sourceRoot $relative
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Staged source file is missing: $relative" }
        $sourceItem = Get-Item -LiteralPath $source -Force
        if (($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Staged file is a reparse point: $relative" }
        $itemHash = ([string]$item.sha256).ToUpperInvariant()
        if ($sourceItem.Length -ne [long]$item.size -or (Get-Sha256 $source) -ne $itemHash) {
            throw "Staged source fingerprint mismatch: $relative"
        }
        $verifiedFiles += [ordered]@{ path = $relative; source = $source; sha256 = $itemHash; size = [long]$item.size }
    }
    $verifiedRemoved = @()
    foreach ($raw in @($manifest.removedPaths)) {
        $relative = Convert-ManifestRelativePath ([string]$raw)
        Assert-NoReparseAncestors $ServerRoot $relative
        $verifiedRemoved += $relative
    }
    $receipt.stage = [ordered]@{
        receipt = $StageReceiptPath
        receiptSha256 = Get-Sha256 $StageReceiptPath
        stageRoot = $stageRoot
        sourceCommit = $manifest.source.commit
        sourceDirty = [bool]$manifest.source.dirty
        fileCount = $verifiedFiles.Count
        removedPathCount = $verifiedRemoved.Count
    }
    $receipt.code.manifestFiles = $verifiedFiles.Count

    $receipt.pushTask = Get-PushTaskState $PushTaskName
    $task = Get-ExactTask $WaitressTaskName
    $receipt.task.action = Assert-WaitressTaskTargetsServer $task $ServerRoot
    $receipt.task.actionVerified = $true
    $taskInfo = Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath
    $taskWasRunning = $task.State -eq 'Running'
    if (-not $taskWasRunning -or @(Get-ListenerPids $OriginPort).Count -ne 1) {
        throw "Production Waitress must start in Running state with exactly one listener on port $OriginPort."
    }
    $receipt.task.wasRunning = $true
    $receipt.task.taskPath = $task.TaskPath

    $waitressStopIssued = $true
    Stop-WaitressTask $task $OriginPort
    $taskStopped = $true
    $runtimeBefore = Get-RuntimeFingerprints $ServerRoot
    $fullRuntimeBefore = Get-FullRuntimeInventory $ServerRoot
    $receipt.runtimeIntegrity.protectedBefore = $runtimeBefore
    $receipt.runtimeIntegrity.fullBeforeCount = @(([pscustomobject]$fullRuntimeBefore).PSObject.Properties).Count

    $runtimeOut = Join-Path $RuntimeBackupRoot $deploymentId
    New-PrivateDirectory $runtimeOut
    $backupScript = Join-Path $sourceRoot 'scripts\backup_runtime_data.py'
    $archive = New-RuntimeBackup $pythonPath $backupScript $ServerRoot $runtimeOut
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) { throw "Runtime backup archive was not created." }
    if (-not (Test-IsWithin $archive $runtimeOut)) { throw "Runtime backup archive escaped its private output directory." }
    Assert-NoReparsePath $archive 'Runtime backup archive'
    $backupVerification = Verify-BackupArchive $archive $ServerRoot $runtimeBefore $fullRuntimeBefore
    $archiveItem = Get-Item -LiteralPath $archive
    $receipt.runtimeBackup = [ordered]@{
        path = $archive
        size = $archiveItem.Length
        sha256 = Get-Sha256 $archive
        manifestVerified = $backupVerification.manifestVerified
        fullInventoryVerified = $backupVerification.fullInventoryVerified
        entryBytesVerified = $backupVerification.entryBytesVerified
        fileCount = $backupVerification.fileCount
        createdAt = $backupVerification.createdAt
        waitressStopped = $true
    }

    $originalRoot = Join-Path $deploymentRoot 'original'
    $removedRoot = Join-Path $deploymentRoot 'removed'
    foreach ($item in $verifiedFiles) {
        $destination = Join-ContainedPath $ServerRoot $item.path
        if (Test-Path -LiteralPath $destination) {
            if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) { throw "Production destination is not a file: $($item.path)" }
            $destinationItem = Get-Item -LiteralPath $destination -Force
            if (($destinationItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Production file is a reparse point: $($item.path)"
            }
            $backupPath = Join-ContainedPath $originalRoot $item.path
            $backupParent = Split-Path -Parent $backupPath
            $null = New-Item -ItemType Directory -Path $backupParent -Force
            $originalHash = Get-Sha256 $destination
            Copy-Item -LiteralPath $destination -Destination $backupPath
            if ((Get-Item -LiteralPath $backupPath).Length -ne $destinationItem.Length -or
                (Get-Sha256 $backupPath) -ne $originalHash) {
                throw "Code rollback source backup fingerprint mismatch: $($item.path)"
            }
            $original = [ordered]@{ path = $item.path; size = $destinationItem.Length; sha256 = $originalHash }
            $originalPaths.Add($original)
        }
    }
    $receipt.code.overwritten = $originalPaths.Count
    $receipt.code.created = $verifiedFiles.Count - $originalPaths.Count

    $codeMutationStarted = $true
    foreach ($relative in $verifiedRemoved) {
        Assert-NoReparseAncestors $ServerRoot $relative
        $destination = Join-ContainedPath $ServerRoot $relative
        if (-not (Test-Path -LiteralPath $destination)) { continue }
        if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) { throw "Removed manifest path is not a file: $relative" }
        $rollbackPath = Join-ContainedPath $removedRoot $relative
        $rollbackParent = Split-Path -Parent $rollbackPath
        $null = New-Item -ItemType Directory -Path $rollbackParent -Force
        $removedItem = Get-Item -LiteralPath $destination
        $removedRecord = [ordered]@{ path = $relative; size = $removedItem.Length; sha256 = Get-Sha256 $destination }
        Move-Item -LiteralPath $destination -Destination $rollbackPath
        $movedRemovedPaths.Add($removedRecord)
        if ((Get-Item -LiteralPath $rollbackPath).Length -ne $removedRecord.size -or
            (Get-Sha256 $rollbackPath) -ne $removedRecord.sha256) {
            throw "Moved removed-path rollback fingerprint mismatch: $relative"
        }
    }
    $receipt.code.removedMoved = $movedRemovedPaths.Count

    foreach ($item in $verifiedFiles) {
        Assert-NoReparseAncestors $ServerRoot $item.path
        $destination = Join-ContainedPath $ServerRoot $item.path
        $appliedPaths.Add($item.path)
        $applyAttemptedCount += 1
        $replacementBackup = Join-ContainedPath (Join-Path $deploymentRoot 'replaced-live') $item.path
        Copy-VerifiedFile $item.source $destination $item.sha256 $deploymentId `
            $replacementBackup (Join-Path $deploymentRoot 'failed-temp')
        $confirmedAppliedCount += 1
    }
    $receipt.code.applyAttempted = $applyAttemptedCount
    $receipt.code.applied = $confirmedAppliedCount

    Start-WaitressTask $task $OriginPort
    $taskStopped = $false
    $receipt.task.restarted = $true
    $receipt.task.stateAfter = (Get-ExactTask $WaitressTaskName).State.ToString()

    $probes = @(Invoke-DisabledPublicHealthProbes $OriginPort)
    $receipt.probes = $probes
    Assert-DisabledPublicHealthProbes $probes 'Applied code'

    $runtimeAfter = Get-RuntimeFingerprints $ServerRoot
    $runtimeDifferences = @(Compare-FingerprintMaps ([pscustomobject]$runtimeBefore) ([pscustomobject]$runtimeAfter))
    $fullRuntimeAfter = Get-FullRuntimeInventory $ServerRoot
    $fullRuntimeDifferences = @(Compare-RuntimeInventories $fullRuntimeBefore $fullRuntimeAfter)
    $receipt.runtimeIntegrity.protectedAfter = $runtimeAfter
    $receipt.runtimeIntegrity.protectedDifferences = $runtimeDifferences
    $receipt.runtimeIntegrity.fullAfterCount = @(([pscustomobject]$fullRuntimeAfter).PSObject.Properties).Count
    $receipt.runtimeIntegrity.fullDifferences = $fullRuntimeDifferences
    if ($runtimeDifferences.Count -gt 0 -or $fullRuntimeDifferences.Count -gt 0) {
        throw "Runtime fingerprints changed during code-only deployment. Runtime was backed up but will not be auto-restored."
    }

    $receipt.result = 'success_code_applied_public_disabled'
    Write-Receipt $receipt $OutFile
    [ordered]@{
        ok = $true
        result = $receipt.result
        receipt = $OutFile
        receiptSha256 = Get-Sha256 $OutFile
        runtimeBackup = $archive
        runtimeBackupSha256 = $receipt.runtimeBackup.sha256
        rollbackRoot = $deploymentRoot
    } | ConvertTo-Json -Depth 5
    exit 0
} catch {
    $receipt.error = $_.Exception.Message
    if ($codeMutationStarted) {
        $receipt.code.applyAttempted = $applyAttemptedCount
        $receipt.code.applied = $confirmedAppliedCount
        $receipt.code.removedMoved = $movedRemovedPaths.Count
        $receipt.rollback.attempted = $true
        try {
            Ensure-WaitressStoppedForRollback $task $OriginPort
            $taskStopped = $true
            Restore-Code $ServerRoot $deploymentRoot @($appliedPaths) @($originalPaths) @($movedRemovedPaths)
            if ($taskWasRunning) {
                Start-WaitressTask $task $OriginPort
                $taskStopped = $false
                $receipt.task.restarted = $true
            }
            $rollbackProbes = @(Invoke-DisabledPublicHealthProbes $OriginPort)
            $receipt.rollback.healthProbes = $rollbackProbes
            Assert-DisabledPublicHealthProbes $rollbackProbes 'Rolled-back code'
            $receipt.rollback.succeeded = $true
            $receipt.result = 'failed_code_rolled_back'
        } catch {
            $receipt.rollback.error = $_.Exception.Message
            $receipt.result = 'failed_rollback_incomplete'
        }
    } else {
        if ($waitressStopIssued -and $taskWasRunning) {
            try {
                $listenerCount = @(Get-ListenerPids $OriginPort).Count
                if ($listenerCount -eq 0) {
                    Start-WaitressTask $task $OriginPort
                    $receipt.task.restarted = $true
                } elseif ($listenerCount -ne 1) {
                    throw "Unexpected listener count after failed stop: $listenerCount"
                }
                $restoreProbes = @(Invoke-DisabledPublicHealthProbes $OriginPort)
                $receipt.rollback.healthProbes = $restoreProbes
                Assert-DisabledPublicHealthProbes $restoreProbes 'Restored Waitress task'
                $taskStopped = $false
                $receipt.result = 'failed_before_code_task_restored'
            } catch {
                $receipt.rollback.error = $_.Exception.Message
                $receipt.result = 'failed_before_code_task_restart_failed'
            }
        } else {
            $receipt.result = 'failed_before_code_change'
        }
    }
    try {
        if ($task) { $receipt.task.stateAfter = (Get-ExactTask $WaitressTaskName).State.ToString() }
        if ($receipt.runtimeIntegrity.protectedBefore) {
            $afterFailure = Get-RuntimeFingerprints $ServerRoot
            $receipt.runtimeIntegrity.protectedAfter = $afterFailure
            $receipt.runtimeIntegrity.protectedDifferences = @(Compare-FingerprintMaps `
                ([pscustomobject]$receipt.runtimeIntegrity.protectedBefore) ([pscustomobject]$afterFailure))
            if ($fullRuntimeBefore) {
                $fullAfterFailure = Get-FullRuntimeInventory $ServerRoot
                $receipt.runtimeIntegrity.fullAfterCount = @(([pscustomobject]$fullAfterFailure).PSObject.Properties).Count
                $receipt.runtimeIntegrity.fullDifferences = @(Compare-RuntimeInventories $fullRuntimeBefore $fullAfterFailure)
            }
        }
        Write-Receipt $receipt $OutFile
    } catch {}
    [ordered]@{ ok = $false; result = $receipt.result; error = $receipt.error; receipt = $OutFile; rollback = $receipt.rollback } |
        ConvertTo-Json -Depth 6
    exit 1
}
