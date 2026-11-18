param([switch]$Infrastructure)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup_windows.ps1 first.' }
if ($Infrastructure) {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install Docker Desktop to use PostgreSQL/Redis.' }
    docker compose up -d --wait
    if ($LASTEXITCODE -ne 0) { throw 'Infrastructure did not start.' }
    $env:DATABASE_URL = 'postgresql+psycopg://tribune:tribune_local@127.0.0.1:54329/tribune'
    $env:REDIS_URL = 'redis://127.0.0.1:63799/0'
}
# Python открывает пользовательское окно; backend и worker запускаются скрыто.
& $python launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Clip Tribune exited with an error. See storage/logs.' }
