param(
    [ValidateSet("api", "full")]
    [string]$Profile = "api",

    [string]$Version = "1.2.2",

    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

function Compress-ArchiveWithRetry {
    param(
        [string]$LiteralPath,
        [string]$DestinationPath,
        [int]$Attempts = 5
    )

    for ($Attempt = 1; $Attempt -le $Attempts; $Attempt++) {
        try {
            Compress-Archive -LiteralPath $LiteralPath -DestinationPath $DestinationPath -Force
            return
        }
        catch {
            if ($Attempt -eq $Attempts) {
                throw
            }
            Start-Sleep -Seconds $Attempt
        }
    }
}

# The "api" profile installs the GUI/audio runtime only (uv extra `app`); "full" adds
# the local faster-whisper STT stack (uv extra `full`). Dependencies and the Python
# version come from pyproject.toml + uv.lock + .python-version — no requirements*.txt.
$AppName = "VAIVOX"
$SyncExtra = "app"
$ExcludeModules = @(
    "--exclude-module", "torch",
    "--exclude-module", "faster_whisper",
    "--exclude-module", "transformers",
    "--exclude-module", "ctranslate2"
)
# VAICOM-derived vocabulary is not shipped (ADR-0005); it is generated locally into
# %LOCALAPPDATA%\VAIVOX on demand. The app runs on the generic seed until then.
$DataFiles = @()

if ($Profile -eq "full") {
    $AppName = "VAIVOX-Full"
    $SyncExtra = "full"
    $ExcludeModules = @()
}

$PackageRoot = Join-Path $ProjectRoot "build\pyinstaller-dist"
$PackagePath = Join-Path $PackageRoot $AppName
$LegacyDistPath = Join-Path $ProjectRoot "dist\$AppName"
$ReleaseRoot = Join-Path $ProjectRoot "dist\release"
$ReleaseFolderName = "$AppName v$Version"
$ReleasePath = Join-Path $ReleaseRoot $ReleaseFolderName
$ZipPath = Join-Path $ReleaseRoot "$ReleaseFolderName.zip"
$VoiceAttackReleasePath = Join-Path $ReleasePath "VoiceAttack"
$VoiceAttackAppsPath = Join-Path $VoiceAttackReleasePath "Apps\VAIVOX"
$VoiceAttackProfilePath = Join-Path $ProjectRoot "VAIVOX - VA Profile.vap"
$PluginProjectPath = Join-Path $ProjectRoot "plugin\VaivoxVAPlugin\VaivoxVAPlugin.csproj"
$PluginDllPath = Join-Path $ProjectRoot "plugin\VaivoxVAPlugin\bin\Release\net48\VaivoxVAPlugin.dll"

if ($Clean) {
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

# Provision the pinned Python (.python-version) and the locked deps for this profile,
# plus the PyInstaller build group. --frozen builds strictly from the committed lock.
uv sync --frozen --extra $SyncExtra --group build

if (Get-Command dotnet -ErrorAction SilentlyContinue) {
    dotnet build $PluginProjectPath -c Release
}
elseif (!(Test-Path $PluginDllPath)) {
    throw "VaivoxVAPlugin.dll is missing and dotnet is not available to build it."
}
else {
    Write-Warning "dotnet not found; packaging existing plugin DLL at $PluginDllPath"
}

$PyInstallerArgs = @(
    "pyinstaller",
    "--noconfirm",
    "--clean",
    "--onedir",
    "--noconsole",
    "--distpath", $PackageRoot,
    "--name", $AppName
) + $ExcludeModules + $DataFiles + @("--paths", "src", "src\vaivox\main.py")

uv run @PyInstallerArgs

$Assets = @(
    "settings.cfg",
    "fuzzy_words.txt",
    "word_mappings.txt",
    "vaivox_icon.png",
    "add_icon.png",
    "Set STT API Key.cmd",
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

if (!(Test-Path $VoiceAttackProfilePath)) {
    throw "Release package is missing source profile: $VoiceAttackProfilePath"
}
if (!(Test-Path $PluginDllPath)) {
    throw "Release package is missing built plugin DLL: $PluginDllPath"
}

New-Item -ItemType Directory -Path $VoiceAttackAppsPath -Force | Out-Null
Copy-Item -LiteralPath $VoiceAttackProfilePath -Destination $VoiceAttackReleasePath -Force
Copy-Item -LiteralPath $PluginDllPath -Destination $VoiceAttackAppsPath -Force

$ExpectedReleaseItems = @(
    "_internal",
    "$AppName.exe",
    "settings.cfg",
    "fuzzy_words.txt",
    "word_mappings.txt",
    "vaivox_icon.png",
    "add_icon.png",
    "Set STT API Key.cmd",
    "README_FIRST.txt",
    "VoiceAttack\VAIVOX - VA Profile.vap",
    "VoiceAttack\Apps\VAIVOX\VaivoxVAPlugin.dll"
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
Compress-ArchiveWithRetry -LiteralPath $ReleasePath -DestinationPath $ZipPath

if (Test-Path $LegacyDistPath) {
    Remove-Item -LiteralPath $LegacyDistPath -Recurse -Force
}

Write-Host ""
Write-Host "Build complete."
Write-Host "Profile: $Profile"
Write-Host "Executable: $(Join-Path $ReleasePath "$AppName.exe")"
Write-Host "Release folder: $ReleasePath"
Write-Host "Release zip: $ZipPath"
