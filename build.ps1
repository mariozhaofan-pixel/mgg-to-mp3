param(
    [string]$PythonExe = 'python',
    [string]$FFmpegExe = ''
)
$ErrorActionPreference = 'Stop'
if (-not $FFmpegExe) { $FFmpegExe = (Get-Command ffmpeg.exe -ErrorAction Stop).Source }
$appRoot = $PSScriptRoot
$releaseRoot = Join-Path (Split-Path -Parent $appRoot) '发布'
    & $PythonExe -m PyInstaller --noconfirm --onefile --windowed --noupx `
        --name '音乐批量转MP3' `
        --distpath $releaseRoot --workpath (Join-Path $appRoot '.build') --specpath $appRoot `
        --paths $appRoot --icon (Join-Path $appRoot 'icon.ico') `
        --version-file (Join-Path $appRoot 'version_info.txt') `
        --add-binary "${FFmpegExe}:bin" `
        --add-data "${appRoot}\licenses:licenses" `
        --add-data "${appRoot}\THIRD_PARTY.txt:." `
        --add-data "${appRoot}\SOURCES.md:." `
        --add-data "${appRoot}\LICENSE:." `
        --add-data "${appRoot}\icon.ico:." `
        (Join-Path $appRoot 'launcher.py')
    if ($LASTEXITCODE -ne 0) { throw "Packaging failed: $LASTEXITCODE" }
