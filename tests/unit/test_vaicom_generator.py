"""Tests for the VAICOM keyterm + phrase-index generator (ADR-0005 / ADR-0011).

Exercised with synthetic VAICOM-format fixtures so nothing VAICOM-derived is committed
and no real install is needed. End-to-end generation against a real install is the
maintainer's manual step (the parse/transform/discovery logic is what is tested here).
"""

from __future__ import annotations

import vaivox.infrastructure.vocabulary.vaicom_generator_core as generator
from vaivox.infrastructure.vocabulary.phrase_index import load_phrase_index
from vaivox.infrastructure.vocabulary.vaicom_generator_core import (
    discover_vaicom_root,
    generate_keyterms,
    generate_phrase_index,
    write_phrase_index,
)


def _make_vaicom_root(tmp_path):
    root = tmp_path / "VAICOMPRO"
    (root / "Export").mkdir(parents=True)
    (root / "Profiles").mkdir()
    (root / "Export" / "keywords.txt").write_text(
        "[Texaco;Arco;Shell]\n[request rejoin;rejoin]\n", encoding="utf-8"
    )
    vap = (
        "<Command><CommandString>"
        "Texaco request rejoin;Texaco request fuel"
        "</CommandString></Command>"
    )
    (root / "Profiles" / "test.vap").write_text(vap, encoding="utf-8")
    return root


def test_generate_keyterms_emits_single_words(tmp_path):
    root = _make_vaicom_root(tmp_path)

    keyterms = generate_keyterms(root, tmp_path / "saved")

    assert "Texaco" in keyterms
    assert all(" " not in term for term in keyterms)  # keyterms are single words


def test_generate_phrase_index_keeps_command_phrases_drops_single_words(tmp_path):
    root = _make_vaicom_root(tmp_path)

    index = generate_phrase_index(root, tmp_path / "saved")

    assert "Texaco request rejoin" in index
    assert "Texaco request fuel" in index
    assert "request rejoin" in index
    # Single-word entries are not phrases (they would over-trigger the snapper).
    assert "Texaco" not in index
    assert "rejoin" not in index
    assert index == sorted(index, key=str.lower)  # deterministic order


def test_phrase_index_round_trips_through_the_app_loader(tmp_path):
    root = _make_vaicom_root(tmp_path)
    data_dir = tmp_path / "data"
    index = generate_phrase_index(root, tmp_path / "saved")

    write_phrase_index(data_dir / "phrase_index.txt", index, root, tmp_path / "saved")

    # The app's loader reads exactly what the generator wrote (comments/blanks skipped).
    assert load_phrase_index(str(data_dir)) == index


def test_discover_vaicom_root_via_env_override(tmp_path, monkeypatch):
    root = _make_vaicom_root(tmp_path)
    monkeypatch.setenv("VAICOMPRO_DIR", str(root))

    assert discover_vaicom_root() == root


def test_discover_vaicom_root_returns_none_when_absent(monkeypatch):
    monkeypatch.setattr(generator, "_discovery_candidates", list)

    assert discover_vaicom_root() is None
