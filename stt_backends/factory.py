from configuration import WhisperAttackConfiguration
from stt_backends.base import SpeechToTextBackend, SpeechToTextBackendError
from stt_backends.elevenlabs_backend import ElevenLabsBackend
from stt_backends.faster_whisper_backend import FasterWhisperBackend


def create_stt_backend(config: WhisperAttackConfiguration) -> SpeechToTextBackend:
    """
    Creates the configured speech-to-text backend.
    """
    backend_name = config.get_stt_backend()
    backends = {
        FasterWhisperBackend.provider_name: FasterWhisperBackend,
        ElevenLabsBackend.provider_name: ElevenLabsBackend,
    }
    backend_class = backends.get(backend_name)
    if backend_class is None:
        supported = ", ".join(sorted(backends.keys()))
        raise SpeechToTextBackendError(f"Unsupported stt_backend '{backend_name}'. Supported backends: {supported}.")
    return backend_class(config)
