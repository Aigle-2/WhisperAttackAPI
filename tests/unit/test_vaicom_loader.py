"""Tests for the locally-generated VAICOM keyterm loader (ADR-0005).

No VAICOM-derived data ships in the repo; the loader reads a file the generator writes
into the per-user data directory. These tests use synthetic content so nothing
VAICOM-derived is committed.
"""

from __future__ import annotations

from vaivox.infrastructure.vocabulary.vaicom_keyterms import (
    VAICOM_KEYTERMS_ENV,
    load_vaicom_keyterms,
)

_SYNTHETIC = "# generated\nAlpha\n\n  Bravo  \n# comment\nCharlie\n"


def test_missing_file_returns_empty_seed_fallback() -> None:
    # Before the first generation there is no file; the loader degrades to [] so the
    # generic seed (DEFAULT_DCS_KEYTERMS + phonetic alphabet) covers the gap.
    assert load_vaicom_keyterms(None) == []


def test_loads_generated_file_from_data_dir(tmp_path) -> None:
    (tmp_path / "vaicom_keyterms.txt").write_text(_SYNTHETIC, encoding="utf-8")

    assert load_vaicom_keyterms(str(tmp_path)) == ["Alpha", "Bravo", "Charlie"]


def test_env_override_takes_precedence(tmp_path, monkeypatch) -> None:
    override = tmp_path / "custom.txt"
    override.write_text("Delta\nEcho\n", encoding="utf-8")
    monkeypatch.setenv(VAICOM_KEYTERMS_ENV, str(override))

    # Even with a different (here empty) data dir, the env override wins.
    assert load_vaicom_keyterms(str(tmp_path / "nonexistent")) == ["Delta", "Echo"]


def test_config_vaicom_source_reads_generated_file(tmp_path) -> None:
    from vaivox.infrastructure.config.settings import VaivoxConfiguration

    app_dir = tmp_path / "app"
    data_dir = tmp_path / "data"
    app_dir.mkdir()
    data_dir.mkdir()
    (app_dir / "settings.cfg").write_text("stt_keyterm_sources=vaicom\n", encoding="utf-8")
    (app_dir / "word_mappings.txt").write_text("", encoding="utf-8")
    (app_dir / "fuzzy_words.txt").write_text("", encoding="utf-8")
    (data_dir / "vaicom_keyterms.txt").write_text("Texaco\nOverlord\n", encoding="utf-8")

    config = VaivoxConfiguration(str(app_dir), str(data_dir))

    assert config.get_stt_keyterms() == ["Texaco", "Overlord"]
