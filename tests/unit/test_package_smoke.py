"""Smoke test: the vaivox package and every scaffolded subpackage import cleanly."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import tomllib
import zlib
from pathlib import Path

import vaivox


def test_all_vaivox_modules_import() -> None:
    """Importing every module in the vaivox tree must succeed (no import errors)."""
    imported = {vaivox.__name__}
    for module_info in pkgutil.walk_packages(vaivox.__path__, prefix="vaivox."):
        importlib.import_module(module_info.name)
        imported.add(module_info.name)

    # The three hexagonal layers plus the bootstrap modules must all be present.
    for expected in (
        "vaivox.domain",
        "vaivox.application",
        "vaivox.infrastructure",
        "vaivox.composition",
        "vaivox.main",
    ):
        assert expected in imported, f"missing scaffolded module: {expected}"


def test_bootstrap_shim_exposes_src_package_only() -> None:
    """The direct-source bootstrap shim should expose ``src`` without needing ``tools``."""
    from vaivox import main

    src_root = str(Path(main.__file__).resolve().parents[1])
    saved = list(sys.path)
    try:
        sys.path[:] = [path for path in sys.path if path != src_root]
        main._ensure_src_on_path()
        assert src_root in sys.path
    finally:
        sys.path[:] = saved


def test_vaicom_generator_is_packaged_with_vaivox() -> None:
    """The runtime generator must import from ``vaivox`` so frozen builds can refresh."""
    module = importlib.import_module("vaivox.infrastructure.vocabulary.vaicom_generator_core")

    assert module.KEYTERMS_FILE == "vaicom_keyterms.txt"


def test_release_build_script_packages_voiceattack_assets() -> None:
    """The release manifest must include the VoiceAttack profile and plugin DLL."""
    repo_root = Path(__file__).resolve().parents[2]
    build_script = (repo_root / "build_exe.ps1").read_text(encoding="utf-8")

    assert (repo_root / "VAIVOX - VA Profile.vap").is_file()
    assert (repo_root / "plugin" / "VaivoxVAPlugin" / "VaivoxVAPlugin.csproj").is_file()
    assert (
        repo_root / "plugin" / "VaivoxPluginInstaller" / "VaivoxPluginInstaller.csproj"
    ).is_file()
    assert "VoiceAttack\\VAIVOX - VA Profile.vap" in build_script
    assert "VoiceAttack\\Apps\\VAIVOX\\VaivoxVAPlugin.dll" in build_script
    assert "Install VAIVOX VoiceAttack Plugin.exe" in build_script
    assert "plugin\\VaivoxPluginInstaller\\VaivoxPluginInstaller.csproj" in build_script
    assert "function Get-ProjectVersion" in build_script
    assert '[string]$Version = ""' in build_script
    assert '"--copy-metadata", "vaivox"' in build_script


def test_voiceattack_profile_template_uses_vaivox_name() -> None:
    """The bundled profile template must not import under the old product name."""
    repo_root = Path(__file__).resolve().parents[2]
    profile = repo_root / "VAIVOX - VA Profile.vap"
    inflated = zlib.decompress(profile.read_bytes(), -15)
    profile_name = b"VAIVOX for VAICOM"
    old_profile_name = b"VAIVOX Radio!"

    assert b"WhisperAttack" not in inflated
    assert len(profile_name).to_bytes(4, "little") + profile_name in inflated
    assert len(old_profile_name).to_bytes(4, "little") + old_profile_name not in inflated
    assert b"Start VAIVOX Recording" in inflated
    assert b"Stop VAIVOX Recording" in inflated
    assert b"send_command.py" not in inflated


def test_voiceattack_plugin_uses_only_vaivox_context_names() -> None:
    """The VAIVOX plugin must not accept upstream WhisperAttack action names."""
    repo_root = Path(__file__).resolve().parents[2]
    plugin_source = (repo_root / "plugin" / "VaivoxVAPlugin" / "VaivoxVAPlugin.cs").read_text(
        encoding="utf-8"
    )

    assert "Start VAIVOX Recording" in plugin_source
    assert "Stop VAIVOX Recording" in plugin_source
    assert "Start Whisper Recording" not in plugin_source
    assert "Stop Whisper Recording" not in plugin_source


def test_project_version_matches_runtime_identity() -> None:
    """The package metadata and runtime identity share one canonical version."""
    repo_root = Path(__file__).resolve().parents[2]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == vaivox.__version__
