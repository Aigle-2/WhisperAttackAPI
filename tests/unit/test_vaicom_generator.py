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
    generate_command_catalog,
    generate_keyterms,
    generate_phrase_index,
    write_phrase_index,
)


def _make_vaicom_root_at(root):
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


def _make_vaicom_root(tmp_path):
    return _make_vaicom_root_at(tmp_path / "VAICOMPRO")


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


def test_generate_phrase_index_keeps_balanced_parameter_slots(tmp_path):
    root = tmp_path / "VAICOMPRO"
    (root / "Export").mkdir(parents=True)
    (root / "Profiles").mkdir()
    (root / "Export" / "keywords.txt").write_text("", encoding="utf-8")
    vap = (
        "<Command><CommandString>"
        "[Radio] [Channel] [1..18];Radar Focus Target [1..20]"
        "</CommandString></Command>"
    )
    (root / "Profiles" / "test.vap").write_text(vap, encoding="utf-8")

    index = generate_phrase_index(root, tmp_path / "saved")

    # The parameter slots are kept and balanced (the old strip("[]") unbalanced them into
    # "Radio] [Channel] [1..18" / "Radar Focus Target [1..20").
    assert "Radar Focus Target [1..20]" in index
    assert "[Radio] [Channel] [1..18]" in index
    assert all(phrase.count("[") == phrase.count("]") for phrase in index)


def test_generate_phrase_index_does_not_fragment_bracketed_alternation(tmp_path):
    root = tmp_path / "VAICOMPRO"
    (root / "Export").mkdir(parents=True)
    (root / "Profiles").mkdir()
    (root / "Export" / "keywords.txt").write_text("", encoding="utf-8")
    vap = (
        "<Command><CommandString>"
        "Will Let You Know [Alpha;Bravo;Zulu] [0..1]"
        "</CommandString></Command>"
    )
    (root / "Profiles" / "test.vap").write_text(vap, encoding="utf-8")

    index = generate_phrase_index(root, tmp_path / "saved")

    # The "[Alpha;Bravo;Zulu]" alternation is one slot, not three ";"-split fragments, so the
    # phrase stays one balanced entry with no dangling-bracket garbage ("[Alpha", "Zulu]").
    assert "Will Let You Know [Alpha;Bravo;Zulu] [0..1]" in index
    assert all(phrase.count("[") == phrase.count("]") for phrase in index)
    assert not any(phrase.startswith("]") or phrase.endswith("[") for phrase in index)


def test_generate_phrase_index_keeps_long_dynamic_voiceattack_patterns(tmp_path):
    root = tmp_path / "VAICOMPRO"
    (root / "Export").mkdir(parents=True)
    (root / "Profiles").mkdir()
    (root / "Export" / "keywords.txt").write_text("", encoding="utf-8")
    pattern = (
        "[WSO; Wizzo; Boots;] [Set; Select] TACAN [channel] "
        "[zero;0;1] [0..9] [0..9] [X-ray; Yankee]"
    )
    (root / "Profiles" / "f4.vap").write_text(
        f"<Command><CommandString>{pattern}</CommandString><Category>F-4E WSO</Category></Command>",
        encoding="utf-8",
    )

    index = generate_phrase_index(root, tmp_path / "saved")
    catalog = generate_command_catalog(root, tmp_path / "saved")

    assert pattern in index
    assert {entry.phrase: entry for entry in catalog}[pattern].aircraft == ("F-4E",)


def test_generate_phrase_index_reads_keywords_html_when_txt_is_missing(tmp_path):
    root = tmp_path / "VAICOMPRO"
    (root / "Export").mkdir(parents=True)
    (root / "Profiles").mkdir()
    (root / "Export" / "keywords.html").write_text(
        """
        <table>
          <tr>
            <td class="action">WSO Ground Connect Air Left</td>
            <td class="group"><div>F-4E AI WSO | Ground Crew</div></td>
            <td class="aliases">
              <span class="alias-item">Ground Air Connect Left</span>
            </td>
          </tr>
        </table>
        """,
        encoding="utf-8",
    )

    index = generate_phrase_index(root, tmp_path / "saved")

    assert "Ground Air Connect Left" in index


def test_generate_command_catalog_tags_aircraft_specific_keywords_html_rows(tmp_path):
    root = tmp_path / "VAICOMPRO"
    (root / "Export").mkdir(parents=True)
    (root / "Profiles").mkdir()
    (root / "Export" / "keywords.html").write_text(
        """
        <table>
          <tr>
            <td class="action">WSO Ground Connect Power</td>
            <td class="group"><div>F-4E AI WSO | Ground Crew</div></td>
            <td class="aliases">
              <span class="alias-item">Ground Power Connect</span>
            </td>
          </tr>
          <tr>
            <td class="action">Ground Power On</td>
            <td class="group"><div>AI Comms | Crew</div></td>
            <td class="aliases">
              <span class="alias-item">Ground Power On</span>
            </td>
          </tr>
        </table>
        """,
        encoding="utf-8",
    )

    catalog = generate_command_catalog(root, tmp_path / "saved")
    by_phrase = {entry.phrase: entry for entry in catalog}

    assert by_phrase["Ground Power Connect"].aircraft == ("F-4E",)
    assert by_phrase["Ground Power Connect"].groups == ("F-4E AI WSO | Ground Crew",)
    assert by_phrase["Ground Power On"].aircraft == ()


def test_clean_term_unwraps_a_single_bracket_group_but_not_a_multi_slot_phrase():
    assert generator.clean_term("[Channel]") == "Channel"
    assert generator.clean_term("[Radio] [Channel] [1..18]") == "[Radio] [Channel] [1..18]"
    assert generator.clean_term("Radar Focus Target [1..20]") == "Radar Focus Target [1..20]"


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


def test_discover_vaicom_root_from_user_voiceattack2_apps(tmp_path, monkeypatch):
    appdata = tmp_path / "Roaming"
    root = _make_vaicom_root_at(appdata / "VoiceAttack2" / "Apps" / "VAICOMPRO")
    monkeypatch.delenv("VAICOMPRO_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(generator, "_program_files_roots", list)
    monkeypatch.setattr(generator, "_steam_common_roots", list)

    assert discover_vaicom_root() == root


def test_discover_vaicom_root_from_custom_steam_library(tmp_path, monkeypatch):
    steam_root = tmp_path / "Steam"
    library_root = tmp_path / "DCS STEAM"
    steamapps = steam_root / "steamapps"
    steamapps.mkdir(parents=True)
    escaped_library = str(library_root).replace("\\", "\\\\")
    (steamapps / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n  "1"\n  {{\n    "path" "{escaped_library}"\n  }}\n}}\n',
        encoding="utf-8",
    )
    root = _make_vaicom_root_at(
        library_root / "steamapps" / "common" / "VoiceAttack 2" / "Apps" / "VAICOMPRO"
    )
    monkeypatch.delenv("VAICOMPRO_DIR", raising=False)
    monkeypatch.setattr(generator, "_appdata_roots", list)
    monkeypatch.setattr(generator, "_program_files_roots", list)
    monkeypatch.setattr(generator, "_steam_roots", lambda: [steam_root])

    assert discover_vaicom_root() == root


def test_discover_vaicom_root_returns_none_when_absent(monkeypatch):
    monkeypatch.setattr(generator, "_discovery_candidates", list)

    assert discover_vaicom_root() is None
