param(
    [string]$Workspace,
    [string]$Python,
    [switch]$WithAsr,
    [switch]$SkipRuntime
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$SkillDir = Join-Path $RepoRoot 'skills\travel-vlog-pipeline'
if (-not $Workspace) {
    $Workspace = $RepoRoot
}
$Workspace = [System.IO.Path]::GetFullPath($Workspace)

if (-not (Test-Path -LiteralPath $SkillDir -PathType Container)) {
    throw "Skill directory is missing: $SkillDir"
}
if (-not (Test-Path -LiteralPath $Workspace -PathType Container)) {
    New-Item -ItemType Directory -Path $Workspace -Force | Out-Null
}

$WorkspaceItem = Get-Item -LiteralPath $Workspace -Force
if (($WorkspaceItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "Workspace must not be a symlink, junction, or other reparse point: $Workspace"
}

function Resolve-Python312 {
    param([string]$Requested)

    $Candidates = @()
    if ($Requested) {
        $Candidates += [System.IO.Path]::GetFullPath($Requested)
    } else {
        $Candidates += @(
            (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'),
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
        )
    }

    foreach ($Candidate in @($Candidates | Select-Object -Unique)) {
        if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            continue
        }
        & $Candidate -E -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            return [System.IO.Path]::GetFullPath($Candidate)
        }
    }

    if (-not $Requested) {
        $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
        if ($PyLauncher) {
            $PreviousErrorAction = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            $ViaLauncher = (& $PyLauncher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null | Select-Object -First 1)
            $LauncherExitCode = $LASTEXITCODE
            $ErrorActionPreference = $PreviousErrorAction
            if ($LauncherExitCode -eq 0 -and $ViaLauncher -and (Test-Path -LiteralPath $ViaLauncher -PathType Leaf)) {
                return [System.IO.Path]::GetFullPath([string]$ViaLauncher)
            }
        }

        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($PythonCommand -and (Test-Path -LiteralPath $PythonCommand.Source -PathType Leaf)) {
            & $PythonCommand.Source -E -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) {
                return [System.IO.Path]::GetFullPath($PythonCommand.Source)
            }
        }
    }
    throw 'Python 3.12+ was not found. Supply -Python with an absolute interpreter path.'
}

$PythonExe = Resolve-Python312 -Requested $Python

$Sources = @(
    [ordered]@{
        Name = 'maxazure-video-editing-skill'
        Repository = 'https://github.com/maxazure/video-editing-skill'
        Commit = 'b3d80f9a9b6eb79b8aa0a9881bbf7b0c115d23ce'
        Destination = 'video-editing-skill-main'
    },
    [ordered]@{
        Name = 'vlog-auto-edit'
        Repository = 'https://github.com/znyupup/ai-video-editing-skill'
        Commit = 'b6429ab550a64c595dc68d42c47cf2b489a50619'
        Destination = 'ai-video-editing-skill-main'
    }
)

$VendorRoot = Join-Path $Workspace '.vendor'
New-Item -ItemType Directory -Path $VendorRoot -Force | Out-Null
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("vlogforge-bootstrap-{0}" -f [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null

try {
    foreach ($Source in $Sources) {
        $Destination = Join-Path $VendorRoot $Source.Destination
        if (Test-Path -LiteralPath $Destination) {
            Write-Host "Using existing pinned source candidate: $Destination"
            continue
        }

        $Archive = Join-Path $TempRoot ("{0}.zip" -f $Source.Name)
        $ExtractRoot = Join-Path $TempRoot ("extract-{0}" -f $Source.Name)
        New-Item -ItemType Directory -Path $ExtractRoot -Force | Out-Null
        $ArchiveUrl = "{0}/archive/{1}.zip" -f $Source.Repository, $Source.Commit

        Write-Host "Downloading $($Source.Name) at $($Source.Commit)..."
        & curl.exe --ssl-no-revoke -L --fail --retry 3 --connect-timeout 20 -o $Archive $ArchiveUrl
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Archive -PathType Leaf)) {
            throw "Download failed: $ArchiveUrl"
        }

        & tar.exe -xf $Archive -C $ExtractRoot
        if ($LASTEXITCODE -ne 0) {
            throw "Extraction failed: $Archive"
        }
        $Extracted = @(Get-ChildItem -LiteralPath $ExtractRoot -Force -Directory)
        if ($Extracted.Count -ne 1) {
            throw "Expected exactly one root directory in $Archive, found $($Extracted.Count)."
        }
        Move-Item -LiteralPath $Extracted[0].FullName -Destination $Destination
    }

    $IntegrityScript = Join-Path $SkillDir 'scripts\runtime_integrity.py'
    $Lock = Join-Path $SkillDir 'assets\upstream-lock.json'
    & $PythonExe -E -s -B $IntegrityScript --workspace $Workspace --lock $Lock
    if ($LASTEXITCODE -ne 0) {
        throw 'Pinned upstream tree verification failed. Remove the rejected .vendor directories and retry.'
    }

    if (-not $SkipRuntime) {
        $Setup = Join-Path $SkillDir 'scripts\setup_runtime.ps1'
        $SetupArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Setup, '-Workspace', $Workspace)
        $SetupArgs += @('-Python', $PythonExe)
        if ($WithAsr) {
            $SetupArgs += '-WithAsr'
        }
        & powershell.exe @SetupArgs
        if ($LASTEXITCODE -ne 0) {
            throw 'Runtime setup failed.'
        }
    }
} finally {
    $ExpectedTempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd([char[]]'\/') + [System.IO.Path]::DirectorySeparatorChar
    $ResolvedTempRoot = [System.IO.Path]::GetFullPath($TempRoot)
    if ($ResolvedTempRoot.StartsWith($ExpectedTempParent, [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $ResolvedTempRoot)) {
        Remove-Item -LiteralPath $ResolvedTempRoot -Recurse -Force
    }
}

Write-Host "VlogForge workspace is ready: $Workspace"
