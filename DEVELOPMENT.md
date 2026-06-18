# Building a VAIVOX / WhisperAttack executable

How to build a standalone application executable (exe) that runs without a
system-wide Python install. For the day-to-day contributor workflow (quality gates,
project layout, the dependency rule) see **[AGENTS.md](AGENTS.md)** — this file only
covers running locally and producing the exe.

## Requirements

- **Python 3.12** — but you do **not** install it yourself. The project is managed by
  [uv](https://docs.astral.sh/uv/); uv reads [`.python-version`](.python-version) and
  downloads/pins the exact interpreter automatically. Install uv from
  <https://docs.astral.sh/uv/getting-started/installation/>.
- Every dependency version is frozen in [`uv.lock`](uv.lock), so builds are
  reproducible. (The old `requirements*.txt` files are gone — dependencies live in
  [`pyproject.toml`](pyproject.toml).)

## Logging

Because the executable does not run as a console application, logging goes to
`C:\Users\<username>\AppData\Local\WhisperAttack\WhisperAttack.log`. The log file is
overwritten every time the server starts.

## Running locally (no build)

Install the app runtime (GUI + audio) and launch it:

```console
uv sync --extra app        # API backends (elevenlabs/openai/deepgram)
uv run vaivox              # or:  uv run python whisper_attack.py
```

For the local on-device faster-whisper backend, sync the full extra instead:

```console
uv sync --extra full       # adds torch / faster-whisper / transformers
```

> CUDA torch wheels come from the PyTorch index, e.g.
> `uv sync --extra full --index pytorch=https://download.pytorch.org/whl/cu126`.

## Creating the executable

The recommended build is the **API-only** executable. It excludes Torch,
faster-whisper, and related local-model dependencies, so the package is smaller and
does not reserve GPU resources DCS needs.

Double-click:

```console
build_api_only.cmd
```

This creates:

```console
dist\release\WhisperAttackAPI v1.2.2-api.1\WhisperAttackAPI.exe
dist\release\WhisperAttackAPI v1.2.2-api.1.zip
```

For the larger offline-capable build with local `faster_whisper` support, double-click:

```console
build_full.cmd
```

Both wrappers call [`build_exe.ps1`](build_exe.ps1), which uses uv end to end:
`uv sync --frozen --extra app|full --group build` to install the locked deps + the
PyInstaller toolchain, then `uv run pyinstaller … src\vaivox\main.py`. The build
bundles assets (`settings.cfg`, `fuzzy_words.txt`, `word_mappings.txt`, the icons, the
API-key `.cmd` helpers, `README_FIRST.txt`) and verifies them, then zips the release.

### Manual PyInstaller flow (debugging the build)

```console
uv sync --frozen --extra app --group build
uv run pyinstaller --onedir --noconsole --paths src --name WhisperAttackAPI src\vaivox\main.py
```

`--noconsole` hides the console window; a VAIVOX icon appears in the Windows system
tray. The entry point is `src\vaivox\main.py` (the single `vaivox.main` bootstrap);
`whisper_attack.py` remains as a thin launcher into it.

### Cleaning up

`build_exe.ps1 -Clean` removes the build/release output. uv manages the `.venv`
in-place, so there is nothing else to deactivate or delete; re-running a build
re-syncs from `uv.lock` automatically.
