param(
  [string]$Mirror = "https://pypi.tuna.tsinghua.edu.cn/simple",
  [string]$AppName = "AILock"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not $env:UV_CACHE_DIR) {
  $env:UV_CACHE_DIR = "E:\codex\backage\cache"
}
$env:UV_HTTP_TIMEOUT = "180"

Write-Host "[AILock] Sync dependencies via $Mirror"
uv sync --index-url $Mirror

Write-Host "[AILock] Run tests"
uv run python -m unittest discover -s tests -v

Write-Host "[AILock] Build executable with PyInstaller"
uv run --with pyinstaller --index-url $Mirror pyinstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name $AppName `
  --paths "src" `
  --add-data "config.toml;." `
  "scripts\ailock_entry.py"

$ReleaseRoot = Join-Path $ProjectRoot "release"
$PackageRoot = Join-Path $ReleaseRoot $AppName
$PreservedData = Join-Path $env:TEMP "AILock-preserved-data"
if (Test-Path $PreservedData) {
  Remove-Item -LiteralPath $PreservedData -Recurse -Force
}
if (Test-Path (Join-Path $PackageRoot "data")) {
  Copy-Item -LiteralPath (Join-Path $PackageRoot "data") -Destination $PreservedData -Recurse
}
if (Test-Path $PackageRoot) {
  Remove-Item -LiteralPath $PackageRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot "dist\$AppName") -Destination $PackageRoot -Recurse
Copy-Item -LiteralPath (Join-Path $ProjectRoot "config.toml") -Destination (Join-Path $PackageRoot "config.toml") -Force

$ReadmePath = Join-Path $PackageRoot "README-usage.txt"
@"
AILock - executable package

How to use:
1. Double-click AILock.exe
2. Enter your API Key in the app
3. Edit config.toml if you need to change model/base_url
4. Import local strategy screenshots/text files
5. Click screenshot analysis or use the global hotkey

Privacy:
- Do not share data/settings.json if it contains your API Key.
- data/captures/ stores screenshot history.
- This build does not use OCR. Screenshots are sent directly to the model API configured in config.toml.

Default model config:
- model: gpt-5.5
- base_url: https://api.asxs.top/v1
- wire_api: responses
"@ | Set-Content -LiteralPath $ReadmePath -Encoding UTF8

$ZipPath = Join-Path $ReleaseRoot "$AppName.zip"
if (Test-Path $ZipPath) {
  Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -LiteralPath $PackageRoot -DestinationPath $ZipPath -Force

if (Test-Path $PreservedData) {
  Copy-Item -LiteralPath $PreservedData -Destination (Join-Path $PackageRoot "data") -Recurse
  Remove-Item -LiteralPath $PreservedData -Recurse -Force
}

Write-Host "[AILock] Release package ready:"
Write-Host $PackageRoot
Write-Host $ZipPath
