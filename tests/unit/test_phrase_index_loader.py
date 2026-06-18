"""Tests for the locally-generated phrase-index loader (Axis B, ADR-0011 / ADR-0005).

No VAICOM-derived data ships in the repo; the loader reads a file the generator writes
into the per-user data directory. These tests use synthetic content so nothing
VAICOM-derived is committed.
"""

from __future__ import annotations

from vaivox.infrastructure.vocabulary.phrase_index import (
    PHRASE_INDEX_ENV,
    load_phrase_index,
)

_SYNTHETIC = (
    "# generated phrase index\n"
    "Texaco request rejoin\n"
    "\n"
    "  Overlord bogey dope  \n"
    "# comment\n"
    "Colt request startup\n"
)


def test_missing_file_returns_empty_so_snapper_is_no_op() -> None:
    # Before the first generation there is no file; the loader returns [] so the snapper
    # becomes a no-op (behaviour parity, ADR-0011).
    assert load_phrase_index(None) == []


def test_loads_generated_file_from_data_dir(tmp_path) -> None:
    (tmp_path / "phrase_index.txt").write_text(_SYNTHETIC, encoding="utf-8")

    assert load_phrase_index(str(tmp_path)) == [
        "Texaco request rejoin",
        "Overlord bogey dope",
        "Colt request startup",
    ]


def test_env_override_takes_precedence(tmp_path, monkeypatch) -> None:
    override = tmp_path / "custom_index.txt"
    override.write_text("Magic ready to copy\nKobuleti inbound\n", encoding="utf-8")
    monkeypatch.setenv(PHRASE_INDEX_ENV, str(override))

    # Even with a different (here nonexistent) data dir, the env override wins.
    assert load_phrase_index(str(tmp_path / "nonexistent")) == [
        "Magic ready to copy",
        "Kobuleti inbound",
    ]


def test_missing_data_dir_file_falls_through_to_empty(tmp_path) -> None:
    # A data dir with no phrase-index file degrades to [] (not an error).
    assert load_phrase_index(str(tmp_path)) == []
