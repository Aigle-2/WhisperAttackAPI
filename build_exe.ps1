param(
    [ValidateSet("api", "full")]
    [string]$Profile = "api",

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
$DistPath = Join-Path $ProjectRoot "dist\$AppName"

if ($Clean) {
    if (Test-Path $VenvPath) {
        Remove-Item -LiteralPath $VenvPath -Recurse -Force
    }
    if (Test-Path $DistPath) {
        Remove-Item -LiteralPath $DistPath -Recurse -Force
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
    --name $AppName `
    @ExcludeModules `
    whisper_attack.py

$Assets = @(
    "settings.cfg",
    "fuzzy_words.txt",
    "word_mappings.txt",
    "whisper_attack_icon.png",
    "add_icon.png"
)

foreach ($Asset in $Assets) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot $Asset) -Destination $DistPath -Force
}

Write-Host ""
Write-Host "Build complete."
Write-Host "Profile: $Profile"
Write-Host "Executable: $(Join-Path $DistPath "$AppName.exe")"
