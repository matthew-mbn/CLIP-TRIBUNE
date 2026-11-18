param([switch]$InstallTools)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# Все инструменты проекта лежат внутри .tools. Системный PATH не меняется.
$python = Join-Path $PSScriptRoot '.tools\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $systemPython = $null
    if (Get-Command py -ErrorAction SilentlyContinue) { $systemPython = & py -3.15 -c 'import sys; print(sys.executable)' 2>$null }
    if ($systemPython) { $python = $systemPython.Trim() }
    elseif ($InstallTools) {
        New-Item -ItemType Directory -Force '.tools' | Out-Null
        $installer = Join-Path $PSScriptRoot '.tools\python-installer.exe'
        Invoke-WebRequest 'https://www.python.org/ftp/python/3.15.2/python-3.15.2-amd64.exe' -OutFile $installer
        $target = Join-Path $PSScriptRoot '.tools\python'
        $process = Start-Process -FilePath $installer -ArgumentList @('/quiet','InstallAllUsers=0','Include_launcher=0','PrependPath=0','Include_test=0',"TargetDir=`"$target`"") -PassThru -Wait -WindowStyle Hidden
        if ($process.ExitCode -ne 0) { throw 'Python installation failed.' }
    } else { throw 'Python 3.15 required. Install from https://python.org or run setup_windows.ps1 -InstallTools' }
}
& $python -c 'import sys, tkinter; assert sys.version_info[:2] == (3, 15); print(sys.version)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.15 with Tkinter is required.' }

$localFFmpeg = Get-ChildItem -Path '.tools\ffmpeg' -Filter ffmpeg.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -and -not $localFFmpeg) {
    if (-not $InstallTools) { throw 'FFmpeg required. Run setup_windows.ps1 -InstallTools or install FFmpeg and FFprobe in PATH.' }
    $archive = Join-Path $PSScriptRoot '.tools\ffmpeg.zip'
    Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $archive
    Expand-Archive -LiteralPath $archive -DestinationPath '.tools\ffmpeg' -Force
}
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { & $python -m venv .venv }
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $venvPython -m pip install -r backend/requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
& $venvPython -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
& $venvPython 'scripts\check_environment.py'
if ($LASTEXITCODE -ne 0) { throw 'FFmpeg/FFprobe check failed.' }
if (Get-Command docker -ErrorAction SilentlyContinue) { Write-Host 'Docker available (optional PostgreSQL/Redis).' }
else { Write-Host 'Docker absent: standalone SQLite mode is available. Docker Desktop: https://docker.com/products/docker-desktop/' }
Write-Host 'Node.js is not required: this application uses Python/Tkinter.'
Write-Host 'Ready. Run: .\start_windows.ps1'
