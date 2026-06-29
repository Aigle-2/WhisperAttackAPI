"""Unit tests for the ElevenLabs speech-to-text adapter."""

from __future__ import annotations

from vaivox.infrastructure.config.settings import VaivoxConfiguration
from vaivox.infrastructure.stt.elevenlabs import ElevenLabsBackend
from vaivox.infrastructure.stt.keyterms import SttKeyterms


class EmptyVocabulary:
    """Empty reconciliation vocabulary for keyterm-builder tests."""

    def get_word_mappings(self):
        return {}

    def get_fuzzy_words(self):
        return []


def make_config(tmp_path, settings: str) -> VaivoxConfiguration:
    app_dir = tmp_path / "app"
    data_dir = tmp_path / "data"
    app_dir.mkdir()
    data_dir.mkdir()
    (app_dir / "settings.cfg").write_text(settings, encoding="utf-8")
    return VaivoxConfiguration(str(app_dir), str(data_dir))


def test_elevenlabs_keyterms_drop_terms_with_more_than_four_spaces(tmp_path) -> None:
    config = make_config(
        tmp_path,
        "\n".join(
            [
                "stt_backend=elevenlabs",
                "stt_keyterm_sources=custom",
                (
                    "stt_keyterms=Alpha Bravo Charlie Delta Echo,"
                    "Alpha Bravo Charlie Delta Echo Foxtrot,Texaco"
                ),
                "",
            ]
        ),
    )
    keyterms = SttKeyterms(config, EmptyVocabulary())
    backend = ElevenLabsBackend(config, keyterms)

    assert backend._budgeted_keyterms() == ["Alpha Bravo Charlie Delta Echo", "Texaco"]


def test_elevenlabs_keyterm_space_limit_is_configurable(tmp_path) -> None:
    config = make_config(
        tmp_path,
        "\n".join(
            [
                "stt_backend=elevenlabs",
                "stt_keyterm_sources=custom",
                "stt_keyterms=Alpha Bravo Charlie Delta Echo Foxtrot",
                "elevenlabs_max_keyterm_spaces=5",
                "",
            ]
        ),
    )
    keyterms = SttKeyterms(config, EmptyVocabulary())
    backend = ElevenLabsBackend(config, keyterms)

    assert backend._budgeted_keyterms() == ["Alpha Bravo Charlie Delta Echo Foxtrot"]
