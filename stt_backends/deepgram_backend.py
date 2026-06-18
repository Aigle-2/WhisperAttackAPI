import json
import logging
import mimetypes
import os
from urllib import error, parse, request

from configuration import WhisperAttackConfiguration
from stt_backends.base import SpeechToTextBackend, SpeechToTextBackendError, SpeechToTextResult


class DeepgramBackend(SpeechToTextBackend):
    """
    Deepgram prerecorded speech-to-text backend.
    """
    provider_name = "deepgram"
    DEFAULT_API_URL = "https://api.deepgram.com/v1/listen"

    def __init__(self, config: WhisperAttackConfiguration):
        self.config = config
        self.model = config.get_provider_setting("deepgram", "model", "nova-3")
        self.api_url = config.get_provider_setting("deepgram", "api_url", self.DEFAULT_API_URL)
        self.api_key_env = config.get_provider_setting("deepgram", "api_key_env", "DEEPGRAM_API_KEY")
        self.language = config.get_stt_language()
        self.timeout_seconds = config.get_provider_int("deepgram", "timeout_seconds", config.get_stt_timeout_seconds())
        self.smart_format = config.get_provider_bool("deepgram", "smart_format", True)
        self.detect_language = config.get_provider_bool("deepgram", "detect_language", False)
        self.max_keyterms = config.get_provider_int("deepgram", "max_keyterms", 100)
        self.keyterms = config.get_stt_keyterms()
        self.api_key = ""

    def load(self) -> None:
        self.api_key = os.getenv(self.api_key_env, "").strip()
        if not self.api_key:
            raise SpeechToTextBackendError(
                f"Missing Deepgram API key. Set the {self.api_key_env} environment variable."
            )
        logging.info("Loaded Deepgram backend with model '%s'", self.model)

    def transcribe(self, audio_path: str) -> SpeechToTextResult:
        with open(audio_path, "rb") as audio_file:
            audio_bytes = audio_file.read()

        content_type = mimetypes.guess_type(audio_path)[0] or "audio/wav"
        request_headers = {
            "Accept": "application/json",
            "Authorization": f"Token {self.api_key}",
            "Content-Type": content_type,
        }
        http_request = request.Request(
            self._build_url(),
            data=audio_bytes,
            headers=request_headers,
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as http_error:
            error_body = http_error.read().decode("utf-8", errors="replace")
            raise SpeechToTextBackendError(
                f"Deepgram transcription failed ({http_error.code}): {error_body}"
            ) from http_error
        except error.URLError as url_error:
            raise SpeechToTextBackendError(f"Deepgram request failed: {url_error}") from url_error

        try:
            payload = json.loads(response_body)
        except json.JSONDecodeError as decode_error:
            raise SpeechToTextBackendError("Deepgram returned invalid JSON.") from decode_error

        return SpeechToTextResult(text=self._extract_text(payload))

    def _build_url(self) -> str:
        parsed = parse.urlparse(self.api_url)
        query = parse.parse_qsl(parsed.query, keep_blank_values=True)
        query.extend([
            ("model", self.model),
            ("smart_format", self._bool_value(self.smart_format)),
        ])
        if self.detect_language:
            query.append(("detect_language", "true"))
        elif self.language:
            query.append(("language", self.language))

        for keyterm in self.keyterms[:max(self.max_keyterms, 0)]:
            query.append(("keyterm", keyterm))

        return parse.urlunparse(parsed._replace(query=parse.urlencode(query)))

    def _extract_text(self, payload: dict) -> str:
        channels = payload.get("results", {}).get("channels", [])
        if not isinstance(channels, list):
            raise SpeechToTextBackendError("Deepgram response did not contain transcript channels.")

        transcripts = []
        for channel in channels:
            alternatives = channel.get("alternatives", [])
            if alternatives:
                transcript = alternatives[0].get("transcript", "")
                if transcript:
                    transcripts.append(str(transcript))

        if transcripts:
            return " ".join(transcripts).strip()
        raise SpeechToTextBackendError("Deepgram response did not contain transcript text.")

    def _bool_value(self, value: bool) -> str:
        return "true" if value else "false"
