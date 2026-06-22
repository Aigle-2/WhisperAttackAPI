import os
import tempfile
import unittest

from vaivox.domain.vocabulary.keyterms import KeytermBudget, apply_keyterm_budget
from vaivox.infrastructure.config.settings import VaivoxConfiguration


class WhisperAttackConfigurationTests(unittest.TestCase):
    def create_config(self, settings: str) -> VaivoxConfiguration:
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
        return VaivoxConfiguration(app_dir, data_dir)

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
        self.assertEqual(
            config.keyterms.get_stt_keyterms(), ["Texaco", "Overlord", "request startup"]
        )
        self.assertTrue(config.get_provider_bool("elevenlabs", "no_verbatim", False))

    def test_stt_keyterms_are_built_from_configured_sources(self):
        config = self.create_config(
            "\n".join([
                "stt_keyterm_sources=phonetic_alphabet,fuzzy_words,word_mapping_replacements,dcs_default,custom",
                "stt_keyterms_extra=Texaco",
            ])
        )

        keyterms = config.keyterms.get_stt_keyterms()

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

        keyterms = config.keyterms.get_budgeted_stt_keyterms("test", max_terms=2, max_term_chars=7)

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

        result = config.keyterms.get_provider_budgeted_stt_keyterm_details(
            "elevenlabs", log_result=False
        )

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

        counts = config.keyterms.get_stt_keyterm_source_counts()

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

    def test_safe_configuration_exposes_allowlisted_settings(self):
        config = self.create_config(
            "\n".join([
                "stt_backend=elevenlabs",
                "stt_language=en",
                "stt_prompt=DCS radio",
                "stt_keyterm_sources=phonetic_alphabet",
                "stt_timeout_seconds=42",
                "whisper_model=small.en",
                "whisper_device=GPU",
                "theme=dark",
                "voiceattack_host=127.0.0.1",
                "voiceattack_port=65433",
                "text_line_length=53",
                "telemetry_enabled=true",
                "api_enabled=true",
                "api_host=127.0.0.1",
                "api_port=8765",
                "api_actions_enabled=false",
            ])
        )

        safe_config = config.get_safe_configuration()

        self.assertEqual(safe_config["stt_backend"], "elevenlabs")
        self.assertEqual(safe_config["stt_prompt"], "DCS radio")
        self.assertEqual(safe_config["whisper_model"], "small.en")
        self.assertEqual(safe_config["whisper_device"], "GPU")
        self.assertEqual(safe_config["voiceattack_port"], "65433")
        self.assertEqual(safe_config["text_line_length"], "53")
        self.assertEqual(safe_config["telemetry_enabled"], "true")
        self.assertEqual(safe_config["api_enabled"], "true")
        self.assertEqual(safe_config["api_host"], "127.0.0.1")
        self.assertEqual(safe_config["api_actions_enabled"], "false")

    def test_safe_configuration_redacts_arbitrarily_named_secrets_by_default(self):
        # An allowlist is the whole point: a secret named in an unanticipated way (none of
        # api_key/secret/token/password) must still be redacted because it is not allowed.
        config = self.create_config(
            "\n".join([
                "deepgram_key=super-secret-value",
                "auth=hunter2",
                "api_token=bearer-xyz",
                "snap_high=0.92",
                "elevenlabs_max_keyterms=900",
            ])
        )

        safe_config = config.get_safe_configuration()

        self.assertEqual(safe_config["deepgram_key"], "<redacted>")
        self.assertEqual(safe_config["auth"], "<redacted>")
        self.assertEqual(safe_config["api_token"], "<redacted>")
        self.assertEqual(safe_config["snap_high"], "<redacted>")
        self.assertEqual(safe_config["elevenlabs_max_keyterms"], "<redacted>")


if __name__ == "__main__":
    unittest.main()
