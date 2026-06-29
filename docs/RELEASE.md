# Release Procedure

Run the automated gates from the repository root:

The VoiceAttack 2 plugin targets `net8.0`, so the `dotnet build
plugin/VaivoxVAPlugin/...` step requires the .NET 8 SDK on `PATH`.

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run lint-imports --config pyproject.toml --no-cache
uv run pytest --cov=vaivox
dotnet build plugin/VaivoxVAPlugin/VaivoxVAPlugin.csproj -c Release
dotnet build plugin/VaivoxPluginInstaller/VaivoxPluginInstaller.csproj -c Release
```

Build the release artifact:

```powershell
.\build_exe.ps1 -Profile api -Clean
```

The build script creates:

```text
dist\release\VAIVOX v<version>\
dist\release\VAIVOX v<version>.zip
```

Verify the ZIP contains:

```text
VAIVOX.exe
Install VAIVOX VoiceAttack Plugin.exe
_internal\
settings.cfg
fuzzy_word.jsonl
word_mapping.jsonl
README_FIRST.txt
VoiceAttack\VAIVOX - VA Profile.vap
VoiceAttack\Apps\VAIVOX\VaivoxVAPlugin.dll
VoiceAttack\Apps\VAIVOX\VaivoxVAPlugin.deps.json
```

Before publishing, run dependency audits:

```powershell
uv export --locked --no-emit-project --extra app --extra mcp --group dev --group build --format requirements-txt --output-file requirements-audit.txt
uvx pip-audit -r requirements-audit.txt
dotnet list plugin/VaivoxVAPlugin/VaivoxVAPlugin.csproj package --vulnerable --include-transitive
dotnet list plugin/VaivoxPluginInstaller/VaivoxPluginInstaller.csproj package --vulnerable --include-transitive
```

Manual release checks that require the real user stack:

- Import `VoiceAttack\VAIVOX - VA Profile.vap`.
- Run `Install VAIVOX VoiceAttack Plugin.exe` and confirm it installs
  `%APPDATA%\VoiceAttack2\Apps\VAIVOX\VaivoxVAPlugin.dll` and removes any stale
  duplicate `Apps\VAIVOX\VaivoxVAPlugin.dll` under the real VoiceAttack install folder.
- Confirm `Start VAIVOX Recording` and `Stop VAIVOX Recording` point to the VAIVOX
  plugin.
- Run a known VAICOM command in DCS and confirm in-game action, `matched=true`,
  telemetry, and usage stamping.
- Run an unknown command and confirm `matched=false`, near-miss telemetry, and no usage
  stamp.
- Verify VAICOM vocabulary generation against a real VAICOM install:
  - VAICOM Config points at the active Saved Games profile (`DCS.openbeta` for OpenBeta).
  - VAICOM Editor -> FINISH has exported `Export\keywords.txt` or `Export\keywords.html`.
  - The FINISH clipboard payload has been pasted into VoiceAttack's `AI Communications`
    command (`Keyword Collections` -> `When I Say`; identifiable by the leading keywords
    `*AAA*; *Abort Inbound*; *Abort Refuel*; ...`) and the profile has been saved.
  - VAIVOX refresh imports module-specific phrases such as `Ground Air Connect Left`.
  - Speaking one imported phrase does not produce `Command '<phrase>' not found`.

VAICOM-derived data is generated locally and must not be redistributed in the release ZIP.
