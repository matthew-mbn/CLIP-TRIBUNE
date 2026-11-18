$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Сначала запустите setup_windows.ps1" }
& $python -m pip install -r build-requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Не удалось установить сборщик" }
& $python scripts/build_brand.py
& $python -m PyInstaller --noconfirm clip_tribune.spec
if ($LASTEXITCODE -ne 0) { throw "Сборка EXE завершилась ошибкой" }
Get-FileHash -LiteralPath (Join-Path $PSScriptRoot "dist\CLIP TRIBUNE.exe") -Algorithm SHA256
