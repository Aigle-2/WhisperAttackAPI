import os
import tempfile
import unittest

from configuration import WhisperAttackConfiguration
from stt_backends.keyterms import KeytermBudget, apply_keyterm_budget


class WhisperAttackConfigurationTests(unittest.TestCase):
    def create_config(self, settings: str) -> WhisperAttackConfiguration:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        app_dir = os.path.join(self.temp_dir.name, "app")
        data_dir = os.path.join(self.temp_dir.name, "data")
        os.makedirs(app_dir)
        os.makedirs(data_dir)
        with open(os.path.join(app_dir, "settings.cfg"), "w", encoding="utf-8") as settings_file:
            settings_file.write(settings)
        with open(os.path.join(app_dir, "word_mappings.txt"), "w", encoding="utf-8") as word_mappings_file:
            word_mappings_file.write("inter=Enter\n")
        with open(os.path.join(app_dir, "fuzzy_words.txt"), "w", encoding="utf-8") as fuzzy_words_file:
            fuzzy_words_file.write("Kobuleti\n")
        return WhisperAttackConfiguration(app_dir, data_dir)

    def test_stt_settings_are_parsed(self):
        config = self.create_config(
            "\n".join([
                "stt_backend=elevenlabs",
                "stt_language=en",
                "stt_timeout_seconds=42",
                "stt_keyterm_sources=custom",
                "stt_keyterms=Texaco, Overlord, request startup",
                "elevenlabs_no_verbatim=true",
            ])
        )

        self.assertEqual(config.get_stt_backend(), "elevenlabs")
        self.assertEqual(config.get_stt_language(), "en")
        self.assertEqual(config.get_stt_timeout_seconds(), 42)
        self.assertEqual(config.get_stt_keyterms(), ["Texaco", "Overlord", "request startup"])
        self.assertTrue(config.get_provider_bool("elevenlabs", "no_verbatim", False))

    def test_stt_keyterms_are_built_from_configured_sources(self):
        config = self.create_config(
            "\n".join([
                "stt_keyterm_sources=phonetic_alphabet,fuzzy_words,word_mapping_replacements,dcs_default,custom",
                "stt_keyterms_extra=Texaco",
            ])
        )

        keyterms = config.get_stt_keyterms()

        self.assertIn("Alpha", keyterms)
        self.assertIn("Kobuleti", keyterms)
        self.assertIn("Enter", keyterms)
        self.assertIn("request startup", keyterms)
        self.assertIn("Texaco", keyterms)
        self.assertNotIn("inter", keyterms)

    def test_budgeted_stt_keyterms_apply_provider_limits(self):
        config = self.create_config(
            "\n".join([
                "stt_keyterm_sources=custom",
                "stt_keyterms=Alpha, Very Long Phrase, Bravo, Golf",
            ])
        )

        keyterms = config.get_budgeted_stt_keyterms("test", max_terms=2, max_term_chars=7)

        self.assertEqual(keyterms, ["Alpha", "Bravo"])

    def test_provider_budgeted_keyterm_details_use_configured_limits(self):
        config = self.create_config(
            "\n".join([
                "stt_keyterm_sources=custom",
                "stt_keyterms=Alpha, Bravo, Charlie",
                "elevenlabs_max_keyterms=2",
                "elevenlabs_max_keyterm_chars=5",
            ])
        )

        result = config.get_provider_budgeted_stt_keyterm_details("elevenlabs", log_result=False)

        self.assertEqual(result.keyterms, ["Alpha", "Bravo"])
        self.assertEqual(result.skipped_too_long, 1)
        self.assertEqual(result.omitted_by_term_limit, 0)

    def test_stt_keyterm_source_counts_are_reported(self):
        config = self.create_config(
            "\n".join([
                "stt_keyterm_sources=phonetic_alphabet,fuzzy_words,word_mapping_replacements,custom",
                "stt_keyterms=Texaco, Overlord",
            ])
        )

        counts = config.get_stt_keyterm_source_counts()

        self.assertEqual(counts["phonetic_alphabet"], 26)
        self.assertEqual(counts["fuzzy_words"], 1)
        self.assertEqual(counts["word_mapping_replacements"], 1)
        self.assertEqual(counts["custom"], 2)

    def test_apply_keyterm_budget_reports_omissions(self):
        result = apply_keyterm_budget(
            ["Alpha", "Very Long Phrase", "Bravo", "Golf"],
            KeytermBudget(max_terms=2, max_term_chars=7),
        )

        self.assertEqual(result.keyterms, ["Alpha", "Bravo"])
        self.assertEqual(result.skipped_too_long, 1)
        self.assertEqual(result.omitted_by_term_limit, 1)

    def test_safe_configuration_redacts_direct_secret_values_but_not_env_names(self):
        config = self.create_config(
            "\n".join([
                "elevenlabs_api_key_env=ELEVENLABS_API_KEY",
                "example_api_key=secret-value",
            ])
        )

        safe_config = config.get_safe_configuration()

        self.assertEqual(safe_config["elevenlabs_api_key_env"], "ELEVENLABS_API_KEY")
        self.assertEqual(safe_config["example_api_key"], "<redacted>")


if __name__ == "__main__":
    unittest.main()
