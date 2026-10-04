# Build from bundled data/core; -RefreshData optionally exports the author's local Skill data.
#   pwsh -File build.ps1
param([switch]$RefreshData)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$Dist = Join-Path $PSScriptRoot 'build\dist'
$Out = Join-Path $Dist 'CWTranslator'

if (-not (Test-Path $Python)) {
    python -m venv .venv
    & $Python -m pip install -q -r requirements.txt
    if ($LASTEXITCODE) { throw 'Dependency installation failed' }
}

Write-Host '== 1/5 Bundled data'
if ($RefreshData) {
    & $Python prepare_data.py | Out-Null
    if ($LASTEXITCODE) { throw 'prepare_data failed' }
}
if (-not (Test-Path 'data\cw-chat-dict.sqlite3')) { throw 'Bundled dictionary missing' }

Write-Host '== 2/5 Tests'
& $Python -m unittest discover -s tests -p 'test_*.py'
if ($LASTEXITCODE) { throw 'Unit tests failed' }
& $Python tests\smoke_app.py | Out-Null
if ($LASTEXITCODE) { throw 'Window smoke test failed' }

Write-Host '== 3/5 PyInstaller'
& $Python version_file.py | Out-Null  # X.Y.Z from app.py into the exe's file properties
if ($LASTEXITCODE) { throw 'APP_VERSION must be X.Y.Z' }
& $Python -m PyInstaller --noconfirm --clean --windowed --name CWTranslator `
    --version-file (Join-Path $PSScriptRoot 'build\version_info.txt') `
    --icon (Join-Path $PSScriptRoot 'data\icon.ico') --paths (Join-Path $PSScriptRoot 'vendor') `
    --hidden-import pystray._win32 `
    --distpath $Dist --workpath build\work --specpath build (Join-Path $PSScriptRoot 'app.py')
if ($LASTEXITCODE) { throw 'PyInstaller failed' }
New-Item -ItemType Directory -Force (Join-Path $Out 'data') | Out-Null
Copy-Item data\cw-chat-dict.sqlite3, data\默认喊话表.csv, data\icon.png, data\logo-leaf.png (Join-Path $Out 'data')
Copy-Item 使用说明.txt $Out
Copy-Item README.md, LICENSE, THIRD_PARTY_NOTICES.md $Out
Copy-Item -LiteralPath docs, licenses -Destination $Out -Recurse -Force

Write-Host '== 4/5 Secret scan'
& $Python tools\scan_public.py $Out
if ($LASTEXITCODE) { throw 'Possible secret or user data in package' }

Write-Host '== 5/5 Zip'
& $Python make_zip.py
if ($LASTEXITCODE) { throw 'Zip failed' }
