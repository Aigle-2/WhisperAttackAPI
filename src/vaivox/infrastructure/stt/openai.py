"""OpenAI Audio API speech-to-text adapter."""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any
from urllib import error, request

from vaivox.application.ports import SpeechToTextError
from vaivox.domain.reconciliation.model import Transcription
from vaivox.infrastructure.stt.http_utils import build_multipart_body
from vaivox.infrastructure.stt.prompts import DEFAULT_DCS_PROMPT

if TYPE_CHECKING:
    from vaivox.infrastructure.config.settings import WhisperAttackConfiguration


class OpenAIBackend:
    """OpenAI Audio API speech-to-text backend."""

    provider_name = "openai"
    DEFAULT_API_URL = "https://api.openai.com/v1/audio/transcriptions"

    def __init__(self, config: WhisperAttackConfiguration) -> None:
        """Read the OpenAI provider settings from ``config``.

        Args:
            config: The effective application configuration.
        """
        self.config = config
        self.model = config.get_provider_setting("openai", "model", "gpt-4o-transcribe")
        self.api_url = config.get_provider_setting("openai", "api_url", self.DEFAULT_API_URL)
        self.api_key_env = config.get_provider_setting("openai", "api_key_env", "OPENAI_API_KEY")
        self.language = config.get_stt_language()
        self.timeout_seconds = config.get_provider_int(
            "openai", "timeout_seconds", config.get_stt_timeout_seconds()
        )
        self.response_format = (
            config.get_provider_setting("openai", "response_format", "json").strip().lower()
        )
        self.temperature = config.get_provider_setting("openai", "temperature", "")
        self.include_keyterms_in_prompt = config.get_provider_bool(
            "openai", "include_keyterms_in_prompt", True
        )
        self.max_prompt_keyterms = config.get_provider_int("openai", "max_prompt_keyterms", 300)
        self.prompt_keyterm_char_budget = config.get_provider_int(
            "openai", "prompt_keyterm_char_budget", 6000
        )
        self.keyterms = config.get_budgeted_stt_keyterms(
            self.provider_name,
            max_terms=self.max_prompt_keyterms,
            max_total_chars=self.prompt_keyterm_char_budget,
        )
        self.api_key = ""

    def load(self) -> None:
        """Validate the API key and response format.

        Raises:
            SpeechToTextError: If the API key env var is unset or the response format
                is unsupported for the configured model.
        """
        self.api_key = os.getenv(self.api_key_env, "").strip()
        if not self.api_key:
            raise SpeechToTextError(
                f"Missing OpenAI API key. Set the {self.api_key_env} environment variable."
            )
        self._validate_response_format()
        logging.info("Loaded OpenAI backend with model '%s'", self.model)

    def transcribe(self, audio_path: str) -> Transcription:
        """Transcribe ``audio_path`` via the OpenAI Audio API.

        Args:
            audio_path: Path to the recorded audio file.

        Returns:
            The transcript returned by OpenAI.

        Raises:
            SpeechToTextError: On HTTP errors or an unparseable response.
        """
        fields: list[tuple[str, str | None]] = [
            ("model", self.model),
            ("language", self.language),
            ("response_format", self.response_format),
        ]
        prompt = self._build_prompt()
        if prompt:
            fields.append(("prompt", prompt))
        if self.temperature:
            fields.append(("temperature", self.temperature))

        body, content_type = build_multipart_body(fields, audio_path)
        request_headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": content_type,
        }
        http_request = request.Request(
            self.api_url, data=body, headers=request_headers, method="POST"
        )

        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as http_error:
            error_body = http_error.read().decode("utf-8", errors="replace")
            raise SpeechToTextError(
                f"OpenAI transcription failed ({http_error.code}): {error_body}"
            ) from http_error
        except error.URLError as url_error:
            raise SpeechToTextError(f"OpenAI request failed: {url_error}") from url_error

        if self.response_format in ("text", "srt", "vtt"):
            return Transcription(text=response_body.strip())

        try:
            payload = json.loads(response_body)
        except json.JSONDecodeError as decode_error:
            raise SpeechToTextError("OpenAI returned invalid JSON.") from decode_error

        return Transcription(text=self._extract_text(payload))

    def _build_prompt(self) -> str:
        prompt = self.config.get_stt_prompt() or DEFAULT_DCS_PROMPT
        if not self.include_keyterms_in_prompt or not self.keyterms:
            return prompt
        return f"{prompt} Expected DCS/VAICOM keyterms and phrases: {', '.join(self.keyterms)}."

    def _validate_response_format(self) -> None:
        supported_formats = self._supported_response_formats()
        if self.response_format not in supported_formats:
            supported = ", ".join(sorted(supported_formats))
            raise SpeechToTextError(
                f"OpenAI model '{self.model}' does not support response_format "
                f"'{self.response_format}'. Supported values: {supported}."
            )

    def _supported_response_formats(self) -> set[str]:
        model = self.model.strip().lower()
        if model in (
            "gpt-4o-transcribe",
            "gpt-4o-mini-transcribe",
            "gpt-4o-mini-transcribe-2025-12-15",
        ):
            return {"json"}
        if model == "gpt-4o-transcribe-diarize":
            return {"json", "text", "diarized_json"}
        return {"json", "text", "srt", "verbose_json", "vtt"}

    def _extract_text(self, payload: dict[str, Any]) -> str:
        if "text" in payload:
            return str(payload["text"])
        raise SpeechToTextError("OpenAI response did not contain transcript text.")
