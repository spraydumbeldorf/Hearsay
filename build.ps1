# Builds dist\YouTube Transcript Extractor.exe
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}
$py = ".venv\Scripts\python.exe"
& $py -m pip install -q --upgrade pip
& $py -m pip install -q -r requirements.txt
& $py tools\make_assets.py
& $py -m PyInstaller --noconfirm --clean ytx.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$exe = Get-Item "dist\YouTube Transcript Extractor.exe"
"Built {0} ({1:N0} MB)" -f $exe.FullName, ($exe.Length / 1MB)
