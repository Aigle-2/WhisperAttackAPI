"""ElevenLabs Scribe speech-to-text adapter."""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any
from urllib import error, parse, request

from vaivox.application.ports import SpeechToTextError
from vaivox.domain.reconciliation.model import Transcription
from vaivox.infrastructure.stt.http_utils import build_multipart_body

if TYPE_CHECKING:
    from vaivox.infrastructure.config.settings import VaivoxConfiguration


class ElevenLabsBackend:
    """ElevenLabs Scribe speech-to-text backend."""

    provider_name = "elevenlabs"
    DEFAULT_API_URL = "https://api.elevenlabs.io/v1/speech-to-text"

    def __init__(self, config: VaivoxConfiguration) -> None:
        """Read the ElevenLabs provider settings from ``config``.

        Args:
            config: The effective application configuration.
        """
        self.config = config
        self.model = config.get_provider_setting("elevenlabs", "model", "scribe_v2")
        self.api_url = config.get_provider_setting("elevenlabs", "api_url", self.DEFAULT_API_URL)
        self.api_key_env = config.get_provider_setting(
            "elevenlabs", "api_key_env", "ELEVENLABS_API_KEY"
        )
        self.language = config.get_stt_language()
        self.timeout_seconds = config.get_provider_int(
            "elevenlabs", "timeout_seconds", config.get_stt_timeout_seconds()
        )
        self.enable_logging = config.get_provider_bool("elevenlabs", "enable_logging", True)
        self.no_verbatim = config.get_provider_bool("elevenlabs", "no_verbatim", True)
        self.tag_audio_events = config.get_provider_bool("elevenlabs", "tag_audio_events", False)
        self.timestamps_granularity = config.get_provider_setting(
            "elevenlabs", "timestamps_granularity", "none"
        )
        self.temperature = config.get_provider_setting("elevenlabs", "temperature", "")
        self.max_keyterms = config.get_provider_int("elevenlabs", "max_keyterms", 900)
        self.max_keyterm_chars = config.get_provider_int("elevenlabs", "max_keyterm_chars", 50)
        self.keyterms = config.get_budgeted_stt_keyterms(
            self.provider_name,
            max_terms=self.max_keyterms,
            max_term_chars=self.max_keyterm_chars,
        )
        self.api_key = ""

    def load(self) -> None:
        """Validate the API key.

        Raises:
            SpeechToTextError: If the API key environment variable is unset.
        """
        self.api_key = os.getenv(self.api_key_env, "").strip()
        if not self.api_key:
            raise SpeechToTextError(
                f"Missing ElevenLabs API key. Set the {self.api_key_env} environment variable."
            )
        if self.config.get_stt_prompt():
            logging.warning(
                "ElevenLabs does not support stt_prompt; use keyterm sources for "
                "provider-side biasing."
            )
        logging.info("Loaded ElevenLabs backend with model '%s'", self.model)

    def transcribe(self, audio_path: str) -> Transcription:
        """Transcribe ``audio_path`` via the ElevenLabs Scribe API.

        Args:
            audio_path: Path to the recorded audio file.

        Returns:
            The transcript returned by ElevenLabs.

        Raises:
            SpeechToTextError: On HTTP errors or an unparseable response.
        """
        fields: list[tuple[str, str | None]] = [
            ("model_id", self.model),
            ("language_code", self.language),
            ("tag_audio_events", self._bool_value(self.tag_audio_events)),
            ("timestamps_granularity", self.timestamps_granularity),
            ("diarize", "false"),
            ("no_verbatim", self._bool_value(self.no_verbatim)),
        ]
        if self.temperature:
            fields.append(("temperature", self.temperature))
        for keyterm in self.keyterms:
            fields.append(("keyterms", keyterm))

        body, content_type = self._build_multipart_body(fields, audio_path)
        url = self._api_url_with_logging_flag()
        request_headers = {
            "Accept": "application/json",
            "Content-Type": content_type,
            "xi-api-key": self.api_key,
        }
        http_request = request.Request(url, data=body, headers=request_headers, method="POST")

        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as http_error:
            error_body = http_error.read().decode("utf-8", errors="replace")
            raise SpeechToTextError(
                f"ElevenLabs transcription failed ({http_error.code}): {error_body}"
            ) from http_error
        except error.URLError as url_error:
            raise SpeechToTextError(f"ElevenLabs request failed: {url_error}") from url_error

        try:
            payload = json.loads(response_body)
        except json.JSONDecodeError as decode_error:
            raise SpeechToTextError("ElevenLabs returned invalid JSON.") from decode_error

        return Transcription(text=self._extract_text(payload))

    def _api_url_with_logging_flag(self) -> str:
        parsed = parse.urlparse(self.api_url)
        query = parse.parse_qsl(parsed.query, keep_blank_values=True)
        query.append(("enable_logging", self._bool_value(self.enable_logging)))
        return parse.urlunparse(parsed._replace(query=parse.urlencode(query)))

    def _build_multipart_body(
        self, fields: list[tuple[str, str | None]], audio_path: str
    ) -> tuple[bytes, str]:
        return build_multipart_body(fields, audio_path)

    def _extract_text(self, payload: dict[str, Any]) -> str:
        if "text" in payload:
            return str(payload["text"])

        transcripts = payload.get("transcripts")
        if isinstance(transcripts, list):
            return " ".join(str(transcript.get("text", "")) for transcript in transcripts).strip()

        raise SpeechToTextError("ElevenLabs response did not contain transcript text.")

    def _bool_value(self, value: bool) -> str:
        return "true" if value else "false"
