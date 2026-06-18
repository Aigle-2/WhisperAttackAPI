from abc import ABC, abstractmethod
from dataclasses import dataclass


class SpeechToTextBackendError(Exception):
    """
    Raised when a speech-to-text backend cannot load or transcribe audio.
    """


@dataclass(frozen=True)
class SpeechToTextResult:
    """
    Normalized speech-to-text result returned by every backend.
    """
    text: str


class SpeechToTextBackend(ABC):
    """
    Common contract for all speech-to-text providers.
    """
    provider_name = "unknown"

    def load(self) -> None:
        """
        Prepare the backend for transcription.
        """

    @abstractmethod
    def transcribe(self, audio_path: str) -> SpeechToTextResult:
        """
        Transcribe an audio file and return normalized text.
        """

