param(
    [string]$Workspace,
    [string]$Python,
    [switch]$WithAsr
)

$ErrorActionPreference = 'Stop'
foreach ($Variable in @('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONINSPECT', 'PYTHONPYCACHEPREFIX')) {
    Remove-Item "Env:$Variable" -ErrorAction SilentlyContinue
}
$env:PYTHONDONTWRITEBYTECODE = '1'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
$SkillDir = Split-Path -Parent $PSScriptRoot
$SkillRoot = Get-Item -LiteralPath $SkillDir -Force
$SkillAncestor = $SkillRoot
while ($SkillAncestor) {
    if (($SkillAncestor.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Runtime setup blocked: the local skill path traverses a reparse point: $($SkillAncestor.FullName)"
    }
    $SkillAncestor = $SkillAncestor.Parent
}
$PipelineLauncher = Join-Path $PSScriptRoot 'run_pipeline.ps1'
if (-not (Test-Path -LiteralPath $PipelineLauncher -PathType Leaf)) {
    throw "Secure pipeline launcher is missing: $PipelineLauncher"
}

function Assert-FileSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label is missing: $Path"
    }
    $Actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToUpperInvariant()
    $NormalizedExpected = $Expected.ToUpperInvariant()
    if ($Actual -ne $NormalizedExpected) {
        throw "$Label checksum mismatch. Expected $NormalizedExpected, got $Actual. Refusing to use the file."
    }
    return $Actual
}

function Assert-ToolVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedPrefix,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $VersionOutput = @(& $Path -version 2>&1)
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0 -or $VersionOutput.Count -eq 0) {
        throw "$Label could not report its version (exit code $ExitCode)."
    }
    $VersionLine = ([string]$VersionOutput[0]).Trim()
    if (-not $VersionLine.StartsWith($ExpectedPrefix, [System.StringComparison]::Ordinal)) {
        throw "$Label version mismatch. Expected prefix '$ExpectedPrefix', got '$VersionLine'."
    }
    return $VersionLine
}

if (-not $Workspace) {
    $Cursor = Get-Item -LiteralPath $SkillDir
    while ($Cursor -and -not (Test-Path -LiteralPath (Join-Path $Cursor.FullName '.vendor\video-editing-skill-main'))) {
        $Cursor = $Cursor.Parent
    }
    if (-not $Cursor) {
        throw 'Could not locate the workspace containing .vendor\video-editing-skill-main.'
    }
    $Workspace = $Cursor.FullName
}
$Workspace = [System.IO.Path]::GetFullPath($Workspace)

$UpstreamLockPath = Join-Path $SkillDir 'assets\upstream-lock.json'
if (-not (Test-Path -LiteralPath $UpstreamLockPath -PathType Leaf)) {
    throw "Pinned upstream lock is missing: $UpstreamLockPath"
}
$UpstreamLock = Get-Content -LiteralPath $UpstreamLockPath -Raw | ConvertFrom-Json
if ([string]$UpstreamLock.schema_version -ne 'travel-vlog-upstream-lock/2') {
    throw "Unsupported upstream lock schema: $($UpstreamLock.schema_version)"
}
$RequiredUpstreamScriptKeys = @(
    'maxazure-video-editing-skill|scripts/project_bootstrap.py',
    'maxazure-video-editing-skill|scripts/edit_preflight.py',
    'maxazure-video-editing-skill|scripts/render_final.py',
    'maxazure-video-editing-skill|scripts/render_qa.py',
    'maxazure-video-editing-skill|scripts/utils.py',
    'vlog-auto-edit|scripts/gen_dashboard.py',
    'vlog-auto-edit|scripts/gen_storyboard.py'
)
$VerifiedUpstreamScripts = @()
$VerifiedUpstreamScriptKeys = @()
$VerifiedVendorRoots = @()
$WorkspacePrefix = $Workspace.TrimEnd([char[]]'\/') + [System.IO.Path]::DirectorySeparatorChar
$WorkspaceVendorRoot = [System.IO.Path]::GetFullPath((Join-Path $Workspace '.vendor'))
$WorkspaceVendorPrefix = $WorkspaceVendorRoot.TrimEnd([char[]]'\/') + [System.IO.Path]::DirectorySeparatorChar
foreach ($Source in @($UpstreamLock.sources)) {
    $SourceName = [string]$Source.name
    $LocalPath = [string]$Source.local_path
    if (-not $SourceName -or -not $LocalPath) {
        throw 'Each pinned upstream source must define name and local_path.'
    }
    $VendorRoot = [System.IO.Path]::GetFullPath((Join-Path $Workspace $LocalPath))
    if (-not $VendorRoot.StartsWith($WorkspacePrefix, [System.StringComparison]::OrdinalIgnoreCase) -or -not $VendorRoot.StartsWith($WorkspaceVendorPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Pinned upstream source escapes the workspace .vendor directory: $LocalPath"
    }
    $VerifiedVendorRoots += $VendorRoot
    $VendorPrefix = $VendorRoot.TrimEnd([char[]]'\/') + [System.IO.Path]::DirectorySeparatorChar
    $ScriptEntries = @($Source.script_sha256.PSObject.Properties)
    if ($ScriptEntries.Count -eq 0) {
        throw "Pinned upstream source '$SourceName' does not record any script hashes."
    }
    foreach ($Entry in $ScriptEntries) {
        $RelativeScript = [string]$Entry.Name
        $ExpectedScriptHash = ([string]$Entry.Value).ToUpperInvariant()
        if ($ExpectedScriptHash -notmatch '^[0-9A-F]{64}$') {
            throw "Pinned SHA-256 for '$SourceName/$RelativeScript' is malformed."
        }
        $ScriptPath = [System.IO.Path]::GetFullPath((Join-Path $VendorRoot $RelativeScript))
        if (-not $ScriptPath.StartsWith($VendorPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Pinned upstream script escapes its source directory: $SourceName/$RelativeScript"
        }
        $ActualScriptHash = Assert-FileSha256 -Path $ScriptPath -Expected $ExpectedScriptHash -Label "Pinned upstream script '$SourceName/$RelativeScript'"
        $NormalizedRelativeScript = $RelativeScript.Replace('\', '/')
        $VerifiedUpstreamScriptKeys += "$SourceName|$NormalizedRelativeScript"
        $VerifiedUpstreamScripts += [ordered]@{
            source = $SourceName
            relative_path = $NormalizedRelativeScript
            path = $ScriptPath
            sha256 = $ActualScriptHash
        }
    }
}
$MissingScriptLocks = @($RequiredUpstreamScriptKeys | Where-Object { $VerifiedUpstreamScriptKeys -notcontains $_ })
$UnexpectedScriptLocks = @($VerifiedUpstreamScriptKeys | Where-Object { $RequiredUpstreamScriptKeys -notcontains $_ })
if ($VerifiedUpstreamScriptKeys.Count -ne $RequiredUpstreamScriptKeys.Count -or $MissingScriptLocks.Count -gt 0 -or $UnexpectedScriptLocks.Count -gt 0) {
    throw "Pinned upstream script set mismatch. Missing: $($MissingScriptLocks -join ', '); unexpected: $($UnexpectedScriptLocks -join ', ')."
}

$SkillPrefix = [System.IO.Path]::GetFullPath($SkillDir).TrimEnd([char[]]'\/') + [System.IO.Path]::DirectorySeparatorChar
$SkillUnsafe = @()
$SkillPending = New-Object 'System.Collections.Generic.Stack[System.IO.DirectoryInfo]'
$SkillPending.Push([System.IO.DirectoryInfo]$SkillRoot)
while ($SkillPending.Count -gt 0) {
    $Directory = $SkillPending.Pop()
    foreach ($Entry in $Directory.EnumerateFileSystemInfos()) {
        $EntryPath = [System.IO.Path]::GetFullPath($Entry.FullName)
        if (-not $EntryPath.StartsWith($SkillPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Skill scan escaped the skill directory: $EntryPath"
        }
        if (($Entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            $SkillUnsafe += $Entry
            continue
        }
        if (($Entry.Attributes -band [System.IO.FileAttributes]::Directory) -ne 0) {
            if ($Entry.Name -eq '__pycache__') {
                $SkillUnsafe += $Entry
            } else {
                $SkillPending.Push([System.IO.DirectoryInfo]$Entry)
            }
        } elseif ($Entry.Extension -in @('.pyc', '.pyo')) {
            $SkillUnsafe += $Entry
        }
    }
}
if ($SkillUnsafe.Count -gt 0) {
    $Examples = @($SkillUnsafe | Select-Object -First 5 -ExpandProperty FullName)
    throw "Runtime setup blocked by local skill bytecode or reparse points: $($Examples -join ', ')"
}

if ($Python) {
    $PythonExe = [System.IO.Path]::GetFullPath($Python)
} else {
    $Candidates = @(
        (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
    )
    $PythonExe = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $PythonExe) {
        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($PythonCommand) {
            $PythonExe = $PythonCommand.Source
        }
    }
}

if (-not $PythonExe -or -not (Test-Path -LiteralPath $PythonExe)) {
    throw 'Python 3.12+ was not found. Supply -Python with an absolute interpreter path.'
}

$VersionText = (& $PythonExe -E --version 2>&1).ToString().Replace('Python ', '').Trim()
if ($LASTEXITCODE -ne 0) {
    throw 'The selected Python interpreter could not run.'
}
$VersionParts = $VersionText.Trim().Split('.')
if ([int]$VersionParts[0] -lt 3 -or ([int]$VersionParts[0] -eq 3 -and [int]$VersionParts[1] -lt 12)) {
    throw "Python 3.12+ is required; selected version is $VersionText."
}

$RuntimeIntegrityScript = Join-Path $SkillDir 'scripts\runtime_integrity.py'
$VendorIntegrityJson = Join-Path ([System.IO.Path]::GetTempPath()) ("travel-vlog-vendor-{0}.json" -f [Guid]::NewGuid().ToString('N'))
try {
    & $PythonExe -E -s -B $RuntimeIntegrityScript --workspace $Workspace --lock $UpstreamLockPath --output $VendorIntegrityJson
    if ($LASTEXITCODE -ne 0) {
        throw 'Pinned vendor tree verification failed.'
    }
    $VendorIntegrity = Get-Content -LiteralPath $VendorIntegrityJson -Raw -Encoding UTF8 | ConvertFrom-Json
} finally {
    if (Test-Path -LiteralPath $VendorIntegrityJson) {
        Remove-Item -LiteralPath $VendorIntegrityJson -Force
    }
}
if (@($VendorIntegrity.errors).Count -gt 0) {
    throw "Pinned vendor tree verification reported errors: $(@($VendorIntegrity.errors) -join ', ')"
}

$VenvDir = Join-Path $Workspace '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $VenvPython)) {
    & $PythonExe -E -s -B -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to create the project-local virtual environment.'
    }
}

$PackageLock = if ($WithAsr) {
    Join-Path $SkillDir 'assets\requirements-windows-py312.lock.txt'
} else {
    Join-Path $SkillDir 'assets\requirements-core.txt'
}
if ($WithAsr) {
    & $VenvPython -E -s -B -m pip install --disable-pip-version-check -r $PackageLock
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to install the locked Windows Python requirements.'
    }
} else {
    & $VenvPython -E -s -B -m pip install --disable-pip-version-check -r $PackageLock
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to install core Python requirements.'
    }
}

$DistributionJson = Join-Path ([System.IO.Path]::GetTempPath()) ("travel-vlog-distributions-{0}.json" -f [Guid]::NewGuid().ToString('N'))
try {
    & $VenvPython -E -s -B $RuntimeIntegrityScript --distributions --output $DistributionJson
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to inventory installed Python distributions.'
    }
    $DistributionIntegrity = Get-Content -LiteralPath $DistributionJson -Raw -Encoding UTF8 | ConvertFrom-Json
} finally {
    if (Test-Path -LiteralPath $DistributionJson) {
        Remove-Item -LiteralPath $DistributionJson -Force
    }
}
if (-not $DistributionIntegrity.sha256 -or @($DistributionIntegrity.distributions).Count -eq 0) {
    throw 'Installed Python distribution inventory is empty or malformed.'
}

$ToolsDir = Join-Path $Workspace '.tools'
$DownloadsDir = Join-Path $ToolsDir 'downloads'
$FfmpegDir = Join-Path $ToolsDir 'ffmpeg'
New-Item -ItemType Directory -Force -Path $DownloadsDir, $FfmpegDir | Out-Null
$Archive = Join-Path $DownloadsDir 'ffmpeg-8.1.1-essentials_build.7z'
$ArchiveUrl = 'https://github.com/GyanD/codexffmpeg/releases/download/8.1.1/ffmpeg-8.1.1-essentials_build.7z'
$ExpectedArchiveSha256 = '23AD8969FBE701D44E6E7E2B97C5FAE4A71224FC33A2560A9034E5110D029D15'
$ExpectedFfmpegSha256 = '228D7A8556258DE907FDB55F36850078EBC7680B84EC30D84EA02E99BEC1D1EB'
$ExpectedFfprobeSha256 = '0FDE260F5ABD35C9CAFD96F594CC76365A780C1B73A90E35B6A3409EA1DB1BF0'
$ExpectedFfmpegVersionPrefix = 'ffmpeg version 8.1.1-essentials_build-www.gyan.dev'
$ExpectedFfprobeVersionPrefix = 'ffprobe version 8.1.1-essentials_build-www.gyan.dev'
$FfmpegBinDir = Join-Path $FfmpegDir 'ffmpeg-8.1.1-essentials_build\bin'
$FfmpegExe = Join-Path $FfmpegBinDir 'ffmpeg.exe'
$FfprobeExe = Join-Path $FfmpegBinDir 'ffprobe.exe'
$HasFfmpeg = Test-Path -LiteralPath $FfmpegExe -PathType Leaf
$HasFfprobe = Test-Path -LiteralPath $FfprobeExe -PathType Leaf
if ($HasFfmpeg -xor $HasFfprobe) {
    throw "Pinned FFmpeg installation is incomplete under $FfmpegBinDir. Refusing to overlay or trust it."
}
if (-not $HasFfmpeg) {
    $NeedDownload = $true
    if (Test-Path -LiteralPath $Archive) {
        $Actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Archive).Hash.ToUpperInvariant()
        $NeedDownload = $Actual -ne $ExpectedArchiveSha256
    }
    if ($NeedDownload) {
        & curl.exe --ssl-no-revoke -L --fail --retry 3 --connect-timeout 20 -o $Archive $ArchiveUrl
        if ($LASTEXITCODE -ne 0) {
            throw 'FFmpeg download failed.'
        }
    }
    $null = Assert-FileSha256 -Path $Archive -Expected $ExpectedArchiveSha256 -Label 'Pinned FFmpeg archive'
    $TarExe = Join-Path $env:WINDIR 'System32\tar.exe'
    if (-not (Test-Path -LiteralPath $TarExe)) {
        throw 'Windows tar.exe is required to extract the pinned FFmpeg 7z archive.'
    }
    & $TarExe -xf $Archive -C $FfmpegDir
    if ($LASTEXITCODE -ne 0) {
        throw 'FFmpeg archive extraction failed.'
    }
}

if (-not (Test-Path -LiteralPath $FfmpegExe -PathType Leaf) -or -not (Test-Path -LiteralPath $FfprobeExe -PathType Leaf)) {
    throw 'FFmpeg extraction completed without ffmpeg.exe and ffprobe.exe.'
}

$FfmpegSha256 = Assert-FileSha256 -Path $FfmpegExe -Expected $ExpectedFfmpegSha256 -Label 'Pinned ffmpeg.exe'
$FfprobeSha256 = Assert-FileSha256 -Path $FfprobeExe -Expected $ExpectedFfprobeSha256 -Label 'Pinned ffprobe.exe'
$FfmpegVersion = Assert-ToolVersion -Path $FfmpegExe -ExpectedPrefix $ExpectedFfmpegVersionPrefix -Label 'Pinned ffmpeg.exe'
$FfprobeVersion = Assert-ToolVersion -Path $FfprobeExe -ExpectedPrefix $ExpectedFfprobeVersionPrefix -Label 'Pinned ffprobe.exe'
$Runtime = [ordered]@{
    schema_version = 'travel-vlog-runtime/2'
    generated_at = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    python = $VenvPython
    python_version = $VersionText.Trim()
    python_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $VenvPython).Hash.ToUpperInvariant()
    ffmpeg = $FfmpegExe
    ffmpeg_version = $FfmpegVersion
    ffmpeg_sha256 = $FfmpegSha256
    ffprobe = $FfprobeExe
    ffprobe_version = $FfprobeVersion
    ffprobe_sha256 = $FfprobeSha256
    ffmpeg_archive_sha256 = $ExpectedArchiveSha256
    package_lock = $PackageLock
    package_lock_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $PackageLock).Hash.ToUpperInvariant()
    python_distributions = @($DistributionIntegrity.distributions)
    python_distributions_sha256 = ([string]$DistributionIntegrity.sha256).ToUpperInvariant()
    runtime_integrity = $RuntimeIntegrityScript
    runtime_integrity_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $RuntimeIntegrityScript).Hash.ToUpperInvariant()
    pipeline_launcher = $PipelineLauncher
    pipeline_launcher_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $PipelineLauncher).Hash.ToUpperInvariant()
    upstream_lock = $UpstreamLockPath
    upstream_lock_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $UpstreamLockPath).Hash.ToUpperInvariant()
    upstream_scripts = $VerifiedUpstreamScripts
    upstream_trees = @($VendorIntegrity.records)
    asr_installed = [bool]$WithAsr
}
$Runtime | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $ToolsDir 'travel-vlog-runtime.json') -Encoding UTF8
$Runtime | ConvertTo-Json -Depth 4
