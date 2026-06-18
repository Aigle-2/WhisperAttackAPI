from configuration import WhisperAttackConfiguration
from stt_backends.base import SpeechToTextBackend, SpeechToTextBackendError
from stt_backends.deepgram_backend import DeepgramBackend
from stt_backends.elevenlabs_backend import ElevenLabsBackend
from stt_backends.faster_whisper_backend import FasterWhisperBackend
from stt_backends.openai_backend import OpenAIBackend


def create_stt_backend(config: WhisperAttackConfiguration) -> SpeechToTextBackend:
    """
    Creates the configured speech-to-text backend.
    """
    backend_name = config.get_stt_backend()
    backends = {
        FasterWhisperBackend.provider_name: FasterWhisperBackend,
        DeepgramBackend.provider_name: DeepgramBackend,
        ElevenLabsBackend.provider_name: ElevenLabsBackend,
        OpenAIBackend.provider_name: OpenAIBackend,
    }
    backend_class = backends.get(backend_name)
    if backend_class is None:
        supported = ", ".join(sorted(backends.keys()))
        raise SpeechToTextBackendError(f"Unsupported stt_backend '{backend_name}'. Supported backends: {supported}.")
    return backend_class(config)
