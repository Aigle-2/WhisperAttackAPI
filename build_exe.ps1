param(
    [ValidateSet("api", "full")]
    [string]$Profile = "api",

    [string]$Version = "1.2.2-api.1",

    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$AppName = "WhisperAttackAPI"
$RequirementsFile = "requirements-api.txt"
$VenvPath = Join-Path $ProjectRoot ".venv-build-api"
$ExcludeModules = @(
    "--exclude-module", "torch",
    "--exclude-module", "faster_whisper",
    "--exclude-module", "transformers",
    "--exclude-module", "ctranslate2"
)

if ($Profile -eq "full") {
    $AppName = "WhisperAttackAPI-Full"
    $RequirementsFile = "requirements.txt"
    $VenvPath = Join-Path $ProjectRoot ".venv-build-full"
    $ExcludeModules = @()
}

$PythonPath = Join-Path $VenvPath "Scripts\python.exe"
$PackageRoot = Join-Path $ProjectRoot "build\pyinstaller-dist"
$PackagePath = Join-Path $PackageRoot $AppName
$LegacyDistPath = Join-Path $ProjectRoot "dist\$AppName"
$ReleaseRoot = Join-Path $ProjectRoot "dist\release"
$ReleaseFolderName = "$AppName v$Version"
$ReleasePath = Join-Path $ReleaseRoot $ReleaseFolderName
$ZipPath = Join-Path $ReleaseRoot "$ReleaseFolderName.zip"

if ($Clean) {
    if (Test-Path $VenvPath) {
        Remove-Item -LiteralPath $VenvPath -Recurse -Force
    }
    if (Test-Path $PackagePath) {
        Remove-Item -LiteralPath $PackagePath -Recurse -Force
    }
    if (Test-Path $LegacyDistPath) {
        Remove-Item -LiteralPath $LegacyDistPath -Recurse -Force
    }
    if (Test-Path $ReleasePath) {
        Remove-Item -LiteralPath $ReleasePath -Recurse -Force
    }
    if (Test-Path $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
}

if (!(Test-Path $PythonPath)) {
    python -m venv $VenvPath
}

& $PythonPath -m pip install --upgrade pip
& $PythonPath -m pip install pyinstaller
& $PythonPath -m pip install -r $RequirementsFile

& $PythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --noconsole `
    --distpath $PackageRoot `
    --name $AppName `
    @ExcludeModules `
    whisper_attack.py

$Assets = @(
    "settings.cfg",
    "fuzzy_words.txt",
    "word_mappings.txt",
    "whisper_attack_icon.png",
    "add_icon.png",
    "Set STT API Key.cmd",
    "Set ElevenLabs API Key.cmd",
    "README_FIRST.txt"
)

foreach ($Asset in $Assets) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot $Asset) -Destination $PackagePath -Force
}

if (Test-Path $ReleasePath) {
    Remove-Item -LiteralPath $ReleasePath -Recurse -Force
}
if (!(Test-Path $ReleaseRoot)) {
    New-Item -ItemType Directory -Path $ReleaseRoot | Out-Null
}
Copy-Item -LiteralPath $PackagePath -Destination $ReleasePath -Recurse -Force

$ExpectedReleaseItems = @(
    "_internal",
    "$AppName.exe",
    "settings.cfg",
    "fuzzy_words.txt",
    "word_mappings.txt",
    "whisper_attack_icon.png",
    "add_icon.png",
    "Set STT API Key.cmd",
    "Set ElevenLabs API Key.cmd",
    "README_FIRST.txt"
)

foreach ($Item in $ExpectedReleaseItems) {
    $ItemPath = Join-Path $ReleasePath $Item
    if (!(Test-Path $ItemPath)) {
        throw "Release package is missing expected item: $Item"
    }
}

if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -LiteralPath $ReleasePath -DestinationPath $ZipPath -Force

if (Test-Path $LegacyDistPath) {
    Remove-Item -LiteralPath $LegacyDistPath -Recurse -Force
}

Write-Host ""
Write-Host "Build complete."
Write-Host "Profile: $Profile"
Write-Host "Executable: $(Join-Path $ReleasePath "$AppName.exe")"
Write-Host "Release folder: $ReleasePath"
Write-Host "Release zip: $ZipPath"
