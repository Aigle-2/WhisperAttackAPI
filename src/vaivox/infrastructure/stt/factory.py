"""Factory that builds the configured speech-to-text adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vaivox.application.ports import SpeechToText, SpeechToTextError
from vaivox.infrastructure.stt.deepgram import DeepgramBackend
from vaivox.infrastructure.stt.elevenlabs import ElevenLabsBackend
from vaivox.infrastructure.stt.faster_whisper import FasterWhisperBackend
from vaivox.infrastructure.stt.openai import OpenAIBackend

if TYPE_CHECKING:
    from vaivox.infrastructure.config.settings import WhisperAttackConfiguration

_BackendClass = type[FasterWhisperBackend | DeepgramBackend | ElevenLabsBackend | OpenAIBackend]


def create_stt_backend(config: WhisperAttackConfiguration) -> SpeechToText:
    """Create the speech-to-text adapter named by ``stt_backend`` in the config.

    Args:
        config: The effective application configuration.

    Returns:
        The constructed STT adapter (satisfying the
        :class:`~vaivox.application.ports.SpeechToText` port).

    Raises:
        SpeechToTextError: If the configured backend name is not supported.
    """
    backend_name = config.get_stt_backend()
    backends: dict[str, _BackendClass] = {
        FasterWhisperBackend.provider_name: FasterWhisperBackend,
        DeepgramBackend.provider_name: DeepgramBackend,
        ElevenLabsBackend.provider_name: ElevenLabsBackend,
        OpenAIBackend.provider_name: OpenAIBackend,
    }
    backend_class = backends.get(backend_name)
    if backend_class is None:
        supported = ", ".join(sorted(backends.keys()))
        raise SpeechToTextError(
            f"Unsupported stt_backend '{backend_name}'. Supported backends: {supported}."
        )
    return backend_class(config)
