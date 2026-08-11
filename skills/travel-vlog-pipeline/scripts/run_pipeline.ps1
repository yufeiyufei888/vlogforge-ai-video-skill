param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PipelineArgs
)

$ErrorActionPreference = 'Stop'
Remove-Item Env:TRAVEL_VLOG_WORKSPACE -ErrorAction SilentlyContinue
$SkillDir = Split-Path -Parent $PSScriptRoot
$SkillRoot = Get-Item -LiteralPath $SkillDir -Force
$SkillAncestor = $SkillRoot
while ($SkillAncestor) {
    if (($SkillAncestor.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Secure launch blocked: the local skill path traverses a reparse point: $($SkillAncestor.FullName)"
    }
    $SkillAncestor = $SkillAncestor.Parent
}
$SkillPrefix = [System.IO.Path]::GetFullPath($SkillDir).TrimEnd([char[]]'\/') + [System.IO.Path]::DirectorySeparatorChar

$Forbidden = @()
$Pending = New-Object 'System.Collections.Generic.Stack[System.IO.DirectoryInfo]'
$Pending.Push([System.IO.DirectoryInfo]$SkillRoot)
while ($Pending.Count -gt 0) {
    $Directory = $Pending.Pop()
    foreach ($Entry in $Directory.EnumerateFileSystemInfos()) {
        $EntryPath = [System.IO.Path]::GetFullPath($Entry.FullName)
        if (-not $EntryPath.StartsWith($SkillPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Skill scan escaped the skill directory: $EntryPath"
        }
        if (($Entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            $Forbidden += $Entry
            continue
        }
        if (($Entry.Attributes -band [System.IO.FileAttributes]::Directory) -ne 0) {
            if ($Entry.Name -eq '__pycache__') {
                $Forbidden += $Entry
            } else {
                $Pending.Push([System.IO.DirectoryInfo]$Entry)
            }
        } elseif ($Entry.Extension -in @('.pyc', '.pyo')) {
            $Forbidden += $Entry
        }
    }
}
if ($Forbidden.Count -gt 0) {
    $Examples = @($Forbidden | Select-Object -First 5 -ExpandProperty FullName)
    throw "Secure launch blocked: remove local bytecode caches or reparse points first: $($Examples -join ', ')"
}

$Cursor = Get-Item -LiteralPath $SkillDir
while ($Cursor -and -not (Test-Path -LiteralPath (Join-Path $Cursor.FullName '.vendor\video-editing-skill-main') -PathType Container)) {
    $Cursor = $Cursor.Parent
}
if (-not $Cursor) {
    throw 'Could not locate the workspace containing the pinned vendor sources.'
}
$Workspace = $Cursor.FullName
$env:TRAVEL_VLOG_WORKSPACE = $Workspace
$PythonExe = Join-Path $Workspace '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Approved project-local Python is missing: $PythonExe"
}

foreach ($Variable in @('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONINSPECT', 'PYTHONPYCACHEPREFIX')) {
    Remove-Item "Env:$Variable" -ErrorAction SilentlyContinue
}
$env:TRAVEL_VLOG_SECURE_LAUNCH = '1'

$PipelineScript = Join-Path $PSScriptRoot 'pipeline.py'
$SitePackages = Join-Path $Workspace '.venv\Lib\site-packages'
$Bootstrap = 'import pathlib,runpy,sys; script=sys.argv[1]; packages=sys.argv[2]; argv=sys.argv[3:]; sys.path[:0]=[str(pathlib.Path(script).parent),packages]; sys.argv=[script,*argv]; runpy.run_path(script,run_name=__name__)'
& $PythonExe -X utf8 -I -S -B -c $Bootstrap $PipelineScript $SitePackages @PipelineArgs
exit $LASTEXITCODE
