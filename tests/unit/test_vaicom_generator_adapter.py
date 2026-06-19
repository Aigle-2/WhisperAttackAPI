"""Unit tests for the VAICOM generator adapter's staleness logic (ADR-0005).

Discovery is injected so the staleness rule (missing outputs, or an install source newer
than the outputs) is exercised deterministically without a real VAICOM install. Generation
itself is validated by the generator's own test; here we only pin the no-install branch.
"""

from __future__ import annotations

import os
from pathlib import Path

from vaivox.infrastructure.vocabulary.vaicom_generator import (
    KEYTERMS_FILE,
    PHRASE_INDEX_FILE,
    VaicomVocabularyGenerator,
)


def _write_outputs(data_dir: Path, mtime: float | None = None) -> None:
    (data_dir / KEYTERMS_FILE).write_text("# keyterms\nTexaco\n", encoding="utf-8")
    (data_dir / PHRASE_INDEX_FILE).write_text("# phrases\nTexaco rejoin\n", encoding="utf-8")
    if mtime is not None:
        for name in (KEYTERMS_FILE, PHRASE_INDEX_FILE):
            os.utime(data_dir / name, (mtime, mtime))


def _make_install(root: Path, vap_mtime: float) -> Path:
    profiles = root / "Profiles"
    export = root / "Export"
    profiles.mkdir(parents=True)
    export.mkdir()
    vap = profiles / "VAICOMPRO.vap"
    vap.write_text(
        "<Command><CommandString>Texaco request rejoin</CommandString></Command>",
        encoding="utf-8",
    )
    keywords = export / "keywords.txt"
    keywords.write_text("[Texaco;request rejoin]\n", encoding="utf-8")
    for source in (vap, keywords):
        os.utime(source, (vap_mtime, vap_mtime))
    return root


def test_is_stale_when_outputs_missing(tmp_path):
    generator = VaicomVocabularyGenerator(str(tmp_path), discover=lambda: None)

    assert generator.is_stale() is True  # nothing generated yet -> first run


def test_not_stale_when_outputs_present_and_no_install(tmp_path):
    _write_outputs(tmp_path)
    generator = VaicomVocabularyGenerator(str(tmp_path), discover=lambda: None)

    assert generator.is_stale() is False  # present, and nothing to regenerate against


def test_stale_when_install_source_is_newer_than_outputs(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_outputs(data_dir, mtime=1000.0)
    install = _make_install(tmp_path / "install", vap_mtime=2000.0)
    generator = VaicomVocabularyGenerator(
        str(data_dir), saved_games=tmp_path / "sg", discover=lambda: install
    )

    assert generator.is_stale() is True  # the install changed since the last generation


def test_not_stale_when_outputs_are_newer_than_install_source(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_outputs(data_dir, mtime=3000.0)
    install = _make_install(tmp_path / "install", vap_mtime=2000.0)
    generator = VaicomVocabularyGenerator(
        str(data_dir), saved_games=tmp_path / "sg", discover=lambda: install
    )

    assert generator.is_stale() is False


def test_generate_reports_no_install_when_discovery_finds_nothing(tmp_path):
    generator = VaicomVocabularyGenerator(str(tmp_path), discover=lambda: None)

    result = generator.generate()

    assert result.generated is False
    assert result.reason == "no VAICOM install found"


def test_generate_writes_keyterms_and_phrase_index_from_packaged_generator(tmp_path):
    data_dir = tmp_path / "data"
    install = _make_install(tmp_path / "install", vap_mtime=2000.0)
    generator = VaicomVocabularyGenerator(
        str(data_dir), saved_games=tmp_path / "sg", discover=lambda: install
    )

    result = generator.generate()

    assert result.generated is True
    assert (data_dir / KEYTERMS_FILE).is_file()
    assert (data_dir / PHRASE_INDEX_FILE).is_file()
    assert "Texaco" in (data_dir / KEYTERMS_FILE).read_text(encoding="utf-8")
    assert "Texaco request rejoin" in (data_dir / PHRASE_INDEX_FILE).read_text(encoding="utf-8")
