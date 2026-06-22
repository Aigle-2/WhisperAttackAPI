<#
.SYNOPSIS
    Build the VAIVOX VoiceAttack C# plugin (net48) in Release and return the DLL path.

.DESCRIPTION
    Runs `dotnet build plugin/VaivoxVAPlugin.sln -c Release` and resolves the produced
    `VaivoxVAPlugin.dll`. The plugin talks to VoiceAttack only through `dynamic vaProxy`,
    so it needs NO VoiceAttack.dll reference and the net48 reference assemblies come from
    a NuGet package — `dotnet build` therefore works on any machine that has the .NET SDK,
    with no .NET Framework targeting pack and no VoiceAttack installed (ADR-0006, M4).

    Used by build_exe.ps1 to bundle the plugin into the release under Apps/VAIVOX/ (M6).
    Can also be run standalone to produce the DLL for a manual install.

    Robustness (M6): if the .NET SDK (`dotnet`) is absent, this throws a clear, explicit
    error by default — the OFFICIAL release MUST be built on a machine with the SDK so the
    plugin actually ships. build_exe.ps1 can pass -SkipOnMissingSdk to downgrade that to a
    warning (an app-only build with the plugin deliberately omitted; see its -SkipPlugin).

.PARAMETER Configuration
    The MSBuild configuration to build. Defaults to Release.

.PARAMETER SkipOnMissingSdk
    When set, a missing `dotnet` SDK is a warning that returns $null instead of a hard
    error. The caller is then responsible for treating a $null DLL path as "not bundled".

.OUTPUTS
    [string] The absolute path to the built VaivoxVAPlugin.dll, or $null when the SDK is
    absent and -SkipOnMissingSdk was passed.
#>
param(
    [string]$Configuration = "Release",

    [switch]$SkipOnMissingSdk
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Solution = Join-Path $ProjectRoot "plugin\VaivoxVAPlugin.sln"
$DllPath = Join-Path $ProjectRoot "plugin\VaivoxVAPlugin\bin\$Configuration\net48\VaivoxVAPlugin.dll"

# Detect the .NET SDK. `dotnet --version` is the cheapest reliable probe; Get-Command alone
# can match a shim that is not a working SDK.
$HasDotnet = $false
$DotnetCmd = Get-Command dotnet -ErrorAction SilentlyContinue
if ($DotnetCmd) {
    try {
        & dotnet --version | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $HasDotnet = $true
        }
    }
    catch {
        $HasDotnet = $false
    }
}

if (-not $HasDotnet) {
    $Message = @"
.NET SDK not found ('dotnet' is unavailable or not a working SDK).
The VAIVOX VoiceAttack plugin cannot be compiled on this machine, so the C# plugin
(VaivoxVAPlugin.dll) will NOT be bundled in the release.

The OFFICIAL release MUST be built on a machine with the .NET SDK installed
(https://dotnet.microsoft.com/download) so the plugin ships with the app.
Install the SDK, or build the plugin elsewhere and drop the DLL into
plugin\VaivoxVAPlugin\bin\$Configuration\net48\ before packaging.
"@
    if ($SkipOnMissingSdk) {
        Write-Warning $Message
        return $null
    }
    throw $Message
}

Write-Host "Building the VAIVOX plugin ($Configuration) ..."
# Pipe dotnet's stdout to the host stream (not the pipeline) so the function's only
# pipeline output is the DLL path below — the caller does `$dll = & build_plugin.ps1`.
& dotnet build $Solution --configuration $Configuration --nologo | Write-Host
if ($LASTEXITCODE -ne 0) {
    throw "dotnet build failed for $Solution (exit code $LASTEXITCODE)."
}

if (!(Test-Path -LiteralPath $DllPath)) {
    throw "Plugin build reported success but the DLL is missing: $DllPath"
}

Write-Host "Plugin built: $DllPath"
return $DllPath
