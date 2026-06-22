"""Unit tests for the STT keyterm selection/budgeting service.

The service is exercised through a real
:class:`~vaivox.infrastructure.config.settings.VaivoxConfiguration` (which it reads
back through), built over a temporary app/data directory. These reproduce the cases
the keyterm logic was previously covered by indirectly, now isolated on the service:
source resolution, aggregation order, case-insensitive de-duplication, per-provider
budgets, and per-source counts.
"""

from __future__ import annotations

from vaivox.domain.vocabulary.keyterms import KeytermBudget
from vaivox.infrastructure.config.settings import VaivoxConfiguration


def make_config(tmp_path, settings, *, word_mappings="inter=Enter\n", fuzzy_words="Kobuleti\n"):
    app_dir = tmp_path / "app"
    data_dir = tmp_path / "data"
    app_dir.mkdir()
    data_dir.mkdir()
    (app_dir / "settings.cfg").write_text(settings, encoding="utf-8")
    (app_dir / "word_mappings.txt").write_text(word_mappings, encoding="utf-8")
    (app_dir / "fuzzy_words.txt").write_text(fuzzy_words, encoding="utf-8")
    return VaivoxConfiguration(str(app_dir), str(data_dir))


def test_sources_default_when_unset(tmp_path) -> None:
    config = make_config(tmp_path, "")

    # The default source list ships in the domain; the service lowercases/strips it.
    assert config.keyterms.get_stt_keyterm_sources() == [
        "custom",
        "phonetic_alphabet",
        "fuzzy_words",
        "word_mapping_replacements",
        "dcs_default",
        "vaicom",
    ]


def test_sources_are_parsed_and_normalized(tmp_path) -> None:
    config = make_config(tmp_path, "stt_keyterm_sources= Custom , PHONETIC_ALPHABET ,, \n")

    assert config.keyterms.get_stt_keyterm_sources() == ["custom", "phonetic_alphabet"]


def test_keyterms_aggregate_sources_in_order(tmp_path) -> None:
    config = make_config(
        tmp_path,
        "\n".join(
            [
                "stt_keyterm_sources=custom,fuzzy_words,word_mapping_replacements",
                "stt_keyterms=Texaco, Overlord",
            ]
        ),
    )

    # custom first (settings order), then fuzzy_words, then word-mapping replacements.
    assert config.keyterms.get_stt_keyterms() == ["Texaco", "Overlord", "Kobuleti", "Enter"]


def test_keyterms_custom_source_reads_both_settings(tmp_path) -> None:
    config = make_config(
        tmp_path,
        "\n".join(
            [
                "stt_keyterm_sources=custom",
                "stt_keyterms=Alpha, Bravo",
                "stt_keyterms_extra=Charlie",
            ]
        ),
    )

    assert config.keyterms.get_stt_keyterms() == ["Alpha", "Bravo", "Charlie"]


def test_word_mapping_aliases_source(tmp_path) -> None:
    config = make_config(
        tmp_path,
        "stt_keyterm_sources=word_mapping_aliases\n",
        word_mappings="inter;enter=Enter\n",
    )

    assert config.keyterms.get_stt_keyterms() == ["inter", "enter"]


def test_dedupe_is_case_insensitive_and_keeps_first_form(tmp_path) -> None:
    config = make_config(
        tmp_path,
        "\n".join(
            [
                "stt_keyterm_sources=custom",
                "stt_keyterms=Alpha, alpha,   , Bravo, ALPHA",
            ]
        ),
    )

    assert config.keyterms.get_stt_keyterms() == ["Alpha", "Bravo"]


def test_unknown_source_is_dropped(tmp_path) -> None:
    config = make_config(
        tmp_path,
        "\n".join(
            [
                "stt_keyterm_sources=custom,bogus",
                "stt_keyterms=Alpha",
            ]
        ),
    )

    assert config.keyterms.get_stt_keyterms() == ["Alpha"]


def test_source_counts_are_reported_per_source(tmp_path) -> None:
    config = make_config(
        tmp_path,
        "\n".join(
            [
                "stt_keyterm_sources=phonetic_alphabet,fuzzy_words,word_mapping_replacements,custom",
                "stt_keyterms=Texaco, Overlord",
            ]
        ),
    )

    counts = config.keyterms.get_stt_keyterm_source_counts()

    assert counts["phonetic_alphabet"] == 26
    assert counts["fuzzy_words"] == 1
    assert counts["word_mapping_replacements"] == 1
    assert counts["custom"] == 2


def test_provider_budget_elevenlabs_uses_configured_limits(tmp_path) -> None:
    config = make_config(
        tmp_path,
        "\n".join(
            [
                "elevenlabs_max_keyterms=2",
                "elevenlabs_max_keyterm_chars=5",
            ]
        ),
    )

    assert config.keyterms.get_provider_stt_keyterm_budget("elevenlabs") == KeytermBudget(
        max_terms=2, max_term_chars=5
    )


def test_provider_budget_deepgram_and_openai_defaults(tmp_path) -> None:
    config = make_config(tmp_path, "")

    assert config.keyterms.get_provider_stt_keyterm_budget("deepgram") == KeytermBudget(
        max_terms=100
    )
    assert config.keyterms.get_provider_stt_keyterm_budget("openai") == KeytermBudget(
        max_terms=300, max_total_chars=6000
    )


def test_unknown_provider_has_unlimited_budget(tmp_path) -> None:
    config = make_config(tmp_path, "")

    assert config.keyterms.get_provider_stt_keyterm_budget("whatever") == KeytermBudget()


def test_budgeted_keyterms_apply_explicit_limits(tmp_path) -> None:
    config = make_config(
        tmp_path,
        "\n".join(
            [
                "stt_keyterm_sources=custom",
                "stt_keyterms=Alpha, Very Long Phrase, Bravo, Golf",
            ]
        ),
    )

    keyterms = config.keyterms.get_budgeted_stt_keyterms("test", max_terms=2, max_term_chars=7)

    assert keyterms == ["Alpha", "Bravo"]


def test_provider_budgeted_details_report_omissions(tmp_path) -> None:
    config = make_config(
        tmp_path,
        "\n".join(
            [
                "stt_keyterm_sources=custom",
                "stt_keyterms=Alpha, Bravo, Charlie",
                "elevenlabs_max_keyterms=2",
                "elevenlabs_max_keyterm_chars=5",
            ]
        ),
    )

    result = config.keyterms.get_provider_budgeted_stt_keyterm_details(
        "elevenlabs", log_result=False
    )

    assert result.keyterms == ["Alpha", "Bravo"]
    assert result.skipped_too_long == 1
    assert result.omitted_by_term_limit == 0


def test_vaicom_source_reads_generated_file(tmp_path) -> None:
    config = make_config(
        tmp_path,
        "stt_keyterm_sources=vaicom\n",
        word_mappings="",
        fuzzy_words="",
    )
    (tmp_path / "data" / "vaicom_keyterms.txt").write_text("Texaco\nOverlord\n", encoding="utf-8")

    assert config.keyterms.get_stt_keyterms() == ["Texaco", "Overlord"]
