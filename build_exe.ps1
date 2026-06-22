<#
.SYNOPSIS
    Package VAIVOX into a self-contained release (PyInstaller app + bundled plugin + profile).

.DESCRIPTION
    Builds the PyInstaller one-dir app, copies the runtime assets, and — since M6 — bundles
    the C# VoiceAttack plugin and the VoiceAttack profile under `Apps/VAIVOX/` inside the
    release, then zips it. The release therefore ships app + plugin + profile (the plugin was
    missing before M6).

    Release layout (under "dist\release\<AppName> v<Version>\"):
        <AppName>.exe, _internal\, settings.cfg, *.txt, icons, *.cmd   (the PyInstaller app)
        Apps\VAIVOX\VaivoxVAPlugin.dll                                  (the C# plugin, M6)
        Apps\VAIVOX\VAIVOX - VA Profile.vap                             (the VoiceAttack profile, M6)

    The `Apps\VAIVOX\` layout mirrors where the DLL is installed on the target
    (`<VoiceAttack>\Apps\VAIVOX\`), so deploying is a copy of that subtree.

    Plugin build (M6): delegates to build_plugin.ps1 (`dotnet build -c Release`). The plugin
    needs no VoiceAttack reference, so any machine with the .NET SDK can build it. If the SDK
    is ABSENT the behaviour is governed by -SkipPlugin:
      * default (no -SkipPlugin): HARD FAIL with a clear message — the OFFICIAL release must
        ship the plugin, so a missing SDK is an error, not a silent app-only zip.
      * -SkipPlugin: warn and package the app WITHOUT the plugin (a dev/app-only build); the
        plugin items are then dropped from the post-build verification.
    Rationale: defaulting to a hard fail prevents accidentally publishing a release that
    silently omits the return channel; -SkipPlugin is the explicit, intentional escape hatch.

    Deployment / rollback of the return channel: see docs\RETURN_CHANNEL_E2E_RUNBOOK.md
    (staged rollout — Python first, then the plugin — flip `voiceattack_await_result = true`,
    rollback = restore the prior DLL + flag off + restart VoiceAttack) and
    docs\RETURN_CHANNEL_PLAN.md ("Deployment").

.PARAMETER Profile
    "api" (default) bundles the GUI/audio runtime only; "full" adds the local STT stack.

.PARAMETER Version
    The release version string (folder/zip name).

.PARAMETER Clean
    Remove prior build/release artifacts for this profile before building.

.PARAMETER SkipPlugin
    Package the app WITHOUT the C# plugin. Use for a dev/app-only build, or to package on a
    machine without the .NET SDK. The official release should NOT use this.
#>
param(
    [ValidateSet("api", "full")]
    [string]$Profile = "api",

    [string]$Version = "1.2.2-api.1",

    [switch]$Clean,

    [switch]$SkipPlugin
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

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
    "vaivox_icon.png",
    "add_icon.png",
    "Set STT API Key.cmd",
    "Set ElevenLabs API Key.cmd",
    "README_FIRST.txt"
)

# --- Bundle the C# VoiceAttack plugin + profile under Apps\VAIVOX\ (M6) -----------------
# The plugin (VaivoxVAPlugin.dll) and the VoiceAttack profile (VAIVOX - VA Profile.vap) are
# placed under Apps\VAIVOX\, mirroring the install target <VoiceAttack>\Apps\VAIVOX\ so
# deployment is just a copy of that subtree (see docs\RETURN_CHANNEL_E2E_RUNBOOK.md).
$PluginProfileName = "VAIVOX - VA Profile.vap"
$PluginProfileSource = Join-Path $ProjectRoot $PluginProfileName

if ($SkipPlugin) {
    Write-Warning "Skipping the C# plugin (-SkipPlugin): the release will NOT contain the plugin."
}
else {
    # Build the plugin. Pass -SkipOnMissingSdk so a missing .NET SDK becomes a hard fail
    # HERE (default) with our own clear message, rather than inside build_plugin.ps1 — this
    # is the official-release path, so we do not silently produce an app-only zip.
    $BuildPlugin = Join-Path $ProjectRoot "build_plugin.ps1"
    $PluginDll = & $BuildPlugin -Configuration Release
    if (-not $PluginDll -or !(Test-Path -LiteralPath $PluginDll)) {
        throw @"
The plugin DLL was not produced, so the release cannot bundle it.
Build the official release on a machine with the .NET SDK installed, or re-run with
-SkipPlugin to intentionally package an app-only build without the plugin.
"@
    }
    if (!(Test-Path -LiteralPath $PluginProfileSource)) {
        throw "VoiceAttack profile not found: $PluginProfileSource"
    }

    $AppsPluginDir = Join-Path $ReleasePath "Apps\VAIVOX"
    New-Item -ItemType Directory -Path $AppsPluginDir -Force | Out-Null
    Copy-Item -LiteralPath $PluginDll -Destination $AppsPluginDir -Force
    Copy-Item -LiteralPath $PluginProfileSource -Destination $AppsPluginDir -Force

    # Verify the bundled plugin items at their relative paths under the release root.
    $ExpectedReleaseItems += "Apps\VAIVOX\VaivoxVAPlugin.dll"
    $ExpectedReleaseItems += "Apps\VAIVOX\$PluginProfileName"
    Write-Host "Bundled plugin + profile into: $AppsPluginDir"
}

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
if ($SkipPlugin) {
    Write-Host "Plugin: NOT bundled (-SkipPlugin)"
}
else {
    Write-Host "Plugin: bundled at Apps\VAIVOX\VaivoxVAPlugin.dll (+ profile .vap)"
}
Write-Host "Executable: $(Join-Path $ReleasePath "$AppName.exe")"
Write-Host "Release folder: $ReleasePath"
Write-Host "Release zip: $ZipPath"
