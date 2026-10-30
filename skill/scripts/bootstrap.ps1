[CmdletBinding()]
param(
    [string]$ResourcePath,
    [string]$Root,
    [ValidateSet('generic','workbuddy','doubao','codex')][string]$Agent = 'generic',
    [ValidateSet('Doctor','Prepare','Status','Onboard','Credentials','Start','Bind','Verify')][string]$Action = 'Onboard',
    [string]$GroupName,
    [ValidateSet('preserve','on','off')][string]$Proactive = 'preserve',
    [switch]$NoBrowser,
    [switch]$Live,
    [switch]$Probe
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONNOUSERSITE = '1'

function Is-Bundle([string]$Directory) {
    return ((Test-Path -LiteralPath (Join-Path $Directory 'offline-manifest.json') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $Directory 'offline_install.py') -PathType Leaf))
}

function Version-Of([string]$Candidate) {
    if ((Split-Path $Candidate -Leaf) -match 'WeChatGroupAssistant-Offline-(\d+\.\d+\.\d+)') {
        return [version]$Matches[1]
    }
    return [version]'0.0.0'
}

function Is-Installed([string]$Directory) {
    $statePath = Join-Path $Directory 'installation.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { return $false }
    try { $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { return $false }
    return ($state.initialized -and
        (Test-Path -LiteralPath (Join-Path $Directory 'MaiBot/.venv/Scripts/python.exe') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $Directory 'assistant_setup/manage.py') -PathType Leaf))
}

function Resolve-Resource([string]$Given) {
    if ($Given) {
        $item = Get-Item -LiteralPath $Given
        if (-not $item.PSIsContainer) {
            if ($item.Extension -ne '.zip') { throw 'Resource must be an extracted bundle, ZIP or managed installation.' }
            return $item.FullName
        }
        if ((Is-Bundle $item.FullName) -or (Is-Installed $item.FullName)) {
            return $item.FullName
        }
        $children = @(Get-ChildItem -LiteralPath $item.FullName -Directory -Filter 'WeChatGroupAssistant-Offline-*' |
            Where-Object { Is-Bundle $_.FullName } | Sort-Object @{Expression={Version-Of $_.FullName};Descending=$true})
        if ($children.Count) { return $children[0].FullName }
        throw 'The supplied folder does not contain a complete offline bundle.'
    }
    if ($env:WECHAT_ASSISTANT_BUNDLE) { return Resolve-Resource $env:WECHAT_ASSISTANT_BUNDLE }
    if ($Root -and (Is-Installed $Root)) { return (Get-Item -LiteralPath $Root).FullName }
    $defaultRoot = Join-Path $env:LOCALAPPDATA 'WeChatGroupAssistant'
    if (Is-Installed $defaultRoot) { return $defaultRoot }
    $bases = @((Get-Location).Path, (Split-Path $PSScriptRoot -Parent),
        (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent),
        (Join-Path $env:USERPROFILE 'Downloads'), [Environment]::GetFolderPath('Desktop'))
    $candidates = @()
    foreach ($base in ($bases | Select-Object -Unique)) {
        if (-not $base -or -not (Test-Path -LiteralPath $base -PathType Container)) { continue }
        if (Is-Bundle $base) { $candidates += Get-Item -LiteralPath $base }
        # Bounded discovery only: these directories and their deliverables child, never WeChat data.
        foreach ($directory in @($base, (Join-Path $base 'deliverables'))) {
            if (-not (Test-Path -LiteralPath $directory -PathType Container)) { continue }
            $candidates += @(Get-ChildItem -LiteralPath $directory -Directory -Filter 'WeChatGroupAssistant-Offline-*' |
                Where-Object { Is-Bundle $_.FullName })
            $candidates += @(Get-ChildItem -LiteralPath $directory -File -Filter 'WeChatGroupAssistant-Offline-*.zip')
        }
    }
    $ordered = @($candidates | Sort-Object @{Expression={Version-Of $_.FullName};Descending=$true},
        @{Expression={$_.PSIsContainer};Descending=$true}, FullName -Unique)
    if (-not $ordered.Count) { throw 'No local offline bundle was found. Supply its local path; upstream downloads are disabled.' }
    return $ordered[0].FullName
}

function Expand-OfflineBundle([string]$Archive) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $file = Get-Item -LiteralPath $Archive
    $target = Join-Path $file.DirectoryName ('.wga-expanded-' + $file.BaseName)
    $stage = $target + '.extracting'
    $zip = [IO.Compression.ZipFile]::OpenRead($file.FullName)
    try {
        $entryNames = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        [long]$total = 0
        $manifestEntries = @()
        foreach ($entry in $zip.Entries) {
            $name = $entry.FullName
            if ($name -match '(^/|\\|:)' -or @($name.Split('/') | Where-Object { $_ -eq '..' }).Count) {
                throw 'Unsafe ZIP member path; nothing was extracted.'
            }
            $absolute = [IO.Path]::GetFullPath((Join-Path $stage $name))
            $inside = [IO.Path]::GetFullPath($stage).TrimEnd('\') + '\'
            if (-not $absolute.StartsWith($inside, [StringComparison]::OrdinalIgnoreCase)) { throw 'ZIP path escapes its extraction folder.' }
            $unixKind = (($entry.ExternalAttributes -shr 16) -band 0xF000)
            if ($unixKind -eq 0xA000 -or ($entry.ExternalAttributes -band 0x400)) { throw 'Links are not allowed in the outer offline ZIP.' }
            if (-not $entryNames.Add($name.TrimEnd('/'))) { throw 'Duplicate ZIP path.' }
            $total += $entry.Length
            if ($total -gt 6442450944 -or $entryNames.Count -gt 100000) { throw 'Offline ZIP exceeds extraction limits.' }
            if ($name -match '(^|/)offline-manifest\.json$') { $manifestEntries += $name }
        }
        if ($manifestEntries.Count -ne 1) { throw 'ZIP must contain exactly one offline manifest.' }
        $prefix = $manifestEntries[0].Substring(0, $manifestEntries[0].Length - 'offline-manifest.json'.Length)
        foreach ($required in @('offline_install.py','runtimes/python312/python.exe','skill/SKILL.md')) {
            if (-not $entryNames.Contains($prefix + $required)) { throw 'ZIP is not a complete offline bundle.' }
        }
    } finally { $zip.Dispose() }
    if (Test-Path -LiteralPath $target) {
        $existing = Join-Path $target $prefix
        if (Is-Bundle $existing) { return $existing }
        throw 'An incomplete extraction folder exists; choose a fresh location and preserve the old folder for diagnosis.'
    }
    if (Test-Path -LiteralPath $stage) { throw 'An interrupted extraction folder exists; no files were overwritten.' }
    [IO.Compression.ZipFile]::ExtractToDirectory($file.FullName, $stage)
    Move-Item -LiteralPath $stage -Destination $target
    return (Join-Path $target $prefix)
}

try {
    if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) { throw 'Use a local Windows x64 task instead of a cloud/Linux sandbox.' }
    $session = [Diagnostics.Process]::GetCurrentProcess().SessionId
    if ($session -eq 0) { throw 'An interactive Windows user session is required.' }
    $resource = Resolve-Resource $ResourcePath
    if ($Probe) {
        @{agent=$Agent;resource=$resource;is_zip=([IO.Path]::GetExtension($resource) -eq '.zip');local_windows=$true} |
            ConvertTo-Json -Compress
        exit 0
    }
    if ([IO.Path]::GetExtension($resource) -eq '.zip') { $resource = Expand-OfflineBundle $resource }
    # Windows PowerShell 5 quotes a spaced argument ending in a backslash incorrectly.
    # Canonical directory names without trailing separators keep the native argv intact.
    $resource = (Get-Item -LiteralPath $resource).FullName.TrimEnd([char[]]@('\','/'))
    if ($Root) {
        $Root = [IO.Path]::GetFullPath($Root)
        if ($Root -eq [IO.Path]::GetPathRoot($Root)) { throw 'Choose a dedicated installation subdirectory instead of a drive root.' }
        $Root = $Root.TrimEnd([char[]]@('\','/'))
    }
    $python = Join-Path $resource 'runtimes/python312/python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { $python = Join-Path $resource 'MaiBot/.venv/Scripts/python.exe' }
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'The resource has no bundled Python; restore the complete offline package.' }
    $arguments = @('-I','-X','utf8','-B',(Join-Path $PSScriptRoot 'agent_entry.py'),$resource,'--host',$Agent)
    if ($Root) { $arguments += @('--root',$Root) }
    if ($GroupName) { $arguments += @('--group-name',$GroupName) }
    if ($Proactive -eq 'on') { $arguments += '--proactive' }
    if ($Proactive -eq 'off') { $arguments += '--no-proactive' }
    if ($NoBrowser) { $arguments += '--no-browser' }
    $arguments += $Action.ToLowerInvariant()
    if ($Live) { $arguments += '--live' }
    & $python @arguments
    exit $LASTEXITCODE
} catch {
    # Our own messages contain only local resource/permission guidance, never model or bridge payloads.
    Write-Error ('Bootstrap did not complete: ' + $_.Exception.Message)
    exit 1
}
