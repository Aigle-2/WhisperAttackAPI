import os
import tempfile
import unittest
from urllib import parse

from vaivox.application.ports import SpeechToTextError
from vaivox.infrastructure.config.settings import VaivoxConfiguration
from vaivox.infrastructure.stt.deepgram import DeepgramBackend
from vaivox.infrastructure.stt.elevenlabs import ElevenLabsBackend
from vaivox.infrastructure.stt.factory import create_stt_backend
from vaivox.infrastructure.stt.openai import OpenAIBackend


class SttBackendTests(unittest.TestCase):
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
            word_mappings_file.write("")
        with open(os.path.join(app_dir, "fuzzy_words.txt"), "w", encoding="utf-8") as fuzzy_words_file:
            fuzzy_words_file.write("")
        return VaivoxConfiguration(app_dir, data_dir)

    def test_factory_creates_elevenlabs_backend(self):
        config = self.create_config("stt_backend=elevenlabs\n")

        backend = create_stt_backend(config)

        self.assertIsInstance(backend, ElevenLabsBackend)

    def test_factory_creates_openai_backend(self):
        config = self.create_config("stt_backend=openai\n")

        backend = create_stt_backend(config)

        self.assertIsInstance(backend, OpenAIBackend)

    def test_factory_creates_deepgram_backend(self):
        config = self.create_config("stt_backend=deepgram\n")

        backend = create_stt_backend(config)

        self.assertIsInstance(backend, DeepgramBackend)

    def test_elevenlabs_load_requires_api_key_environment_variable(self):
        config = self.create_config(
            "\n".join([
                "stt_backend=elevenlabs",
                "elevenlabs_api_key_env=WHISPERATTACK_TEST_MISSING_KEY",
            ])
        )
        backend = ElevenLabsBackend(config)

        with self.assertRaises(SpeechToTextError):
            backend.load()

    def test_elevenlabs_extracts_single_channel_text(self):
        config = self.create_config("stt_backend=elevenlabs\n")
        backend = ElevenLabsBackend(config)

        text = backend._extract_text({"text": "Texaco request rejoin"})

        self.assertEqual(text, "Texaco request rejoin")

    def test_elevenlabs_logging_flag_is_sent_as_query_parameter(self):
        config = self.create_config(
            "\n".join([
                "stt_backend=elevenlabs",
                "elevenlabs_api_url=https://example.test/speech-to-text?existing=value",
                "elevenlabs_enable_logging=false",
            ])
        )
        backend = ElevenLabsBackend(config)

        parsed_url = parse.urlparse(backend._api_url_with_logging_flag())
        query = dict(parse.parse_qsl(parsed_url.query))

        self.assertEqual(query["existing"], "value")
        self.assertEqual(query["enable_logging"], "false")

    def test_elevenlabs_multipart_body_keeps_repeated_keyterms(self):
        config = self.create_config("stt_backend=elevenlabs\n")
        backend = ElevenLabsBackend(config)
        audio_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        self.addCleanup(lambda: os.path.exists(audio_file.name) and os.remove(audio_file.name))
        try:
            audio_file.write(b"RIFF")
        finally:
            audio_file.close()

        body, content_type = backend._build_multipart_body(
            [("keyterms", "Texaco"), ("keyterms", "request rejoin")],
            audio_file.name,
        )

        self.assertIn("multipart/form-data", content_type)
        self.assertEqual(body.count(b'name="keyterms"'), 2)
        self.assertIn(b"Texaco", body)
        self.assertIn(b"request rejoin", body)

    def test_elevenlabs_keyterms_are_budgeted(self):
        config = self.create_config(
            "\n".join([
                "stt_backend=elevenlabs",
                "stt_keyterm_sources=custom",
                "stt_keyterms=Alpha, Bravo, Charlie",
                "elevenlabs_max_keyterms=2",
            ])
        )
        backend = ElevenLabsBackend(config)

        self.assertEqual(backend.keyterms, ["Alpha", "Bravo"])

    def test_openai_load_requires_api_key_environment_variable(self):
        config = self.create_config(
            "\n".join([
                "stt_backend=openai",
                "openai_api_key_env=WHISPERATTACK_TEST_MISSING_KEY",
            ])
        )
        backend = OpenAIBackend(config)

        with self.assertRaises(SpeechToTextError):
            backend.load()

    def test_openai_load_rejects_unsupported_response_format_for_default_model(self):
        os.environ["WHISPERATTACK_TEST_OPENAI_KEY"] = "test-key"
        self.addCleanup(lambda: os.environ.pop("WHISPERATTACK_TEST_OPENAI_KEY", None))
        config = self.create_config(
            "\n".join([
                "stt_backend=openai",
                "openai_api_key_env=WHISPERATTACK_TEST_OPENAI_KEY",
                "openai_model=gpt-4o-transcribe",
                "openai_response_format=text",
            ])
        )
        backend = OpenAIBackend(config)

        with self.assertRaisesRegex(SpeechToTextError, "does not support response_format"):
            backend.load()

    def test_openai_prompt_includes_generated_keyterms(self):
        config = self.create_config(
            "\n".join([
                "stt_backend=openai",
                "stt_keyterm_sources=custom",
                "stt_keyterms=Texaco, request rejoin",
                "stt_prompt=English DCS radio command.",
            ])
        )
        backend = OpenAIBackend(config)

        prompt = backend._build_prompt()

        self.assertIn("English DCS radio command.", prompt)
        self.assertIn("Texaco", prompt)
        self.assertIn("request rejoin", prompt)

    def test_openai_prompt_keyterms_are_budgeted_by_context_chars(self):
        config = self.create_config(
            "\n".join([
                "stt_backend=openai",
                "stt_keyterm_sources=custom",
                "stt_keyterms=Alpha, Bravo, Charlie",
                "stt_prompt=English DCS radio command.",
                "openai_max_prompt_keyterms=10",
                "openai_prompt_keyterm_char_budget=12",
            ])
        )
        backend = OpenAIBackend(config)

        prompt = backend._build_prompt()

        self.assertIn("Alpha", prompt)
        self.assertIn("Bravo", prompt)
        self.assertNotIn("Charlie", prompt)

    def test_openai_extracts_text(self):
        config = self.create_config("stt_backend=openai\n")
        backend = OpenAIBackend(config)

        text = backend._extract_text({"text": "Overlord bogey dope"})

        self.assertEqual(text, "Overlord bogey dope")

    def test_deepgram_load_requires_api_key_environment_variable(self):
        config = self.create_config(
            "\n".join([
                "stt_backend=deepgram",
                "deepgram_api_key_env=WHISPERATTACK_TEST_MISSING_KEY",
            ])
        )
        backend = DeepgramBackend(config)

        with self.assertRaises(SpeechToTextError):
            backend.load()

    def test_deepgram_url_uses_repeated_keyterm_parameters(self):
        config = self.create_config(
            "\n".join([
                "stt_backend=deepgram",
                "stt_keyterm_sources=custom",
                "stt_keyterms=Texaco, request rejoin",
                "deepgram_api_url=https://example.test/listen?existing=value",
                "deepgram_model=nova-3",
                "deepgram_smart_format=false",
            ])
        )
        backend = DeepgramBackend(config)

        parsed_url = parse.urlparse(backend._build_url())
        query = parse.parse_qs(parsed_url.query)

        self.assertEqual(query["existing"], ["value"])
        self.assertEqual(query["model"], ["nova-3"])
        self.assertEqual(query["smart_format"], ["false"])
        self.assertEqual(query["language"], ["en"])
        self.assertEqual(query["keyterm"], ["Texaco", "request rejoin"])

    def test_deepgram_extracts_channel_transcript(self):
        config = self.create_config("stt_backend=deepgram\n")
        backend = DeepgramBackend(config)

        text = backend._extract_text({
            "results": {
                "channels": [
                    {"alternatives": [{"transcript": "Magic ready to copy"}]},
                ]
            }
        })

        self.assertEqual(text, "Magic ready to copy")


if __name__ == "__main__":
    unittest.main()
