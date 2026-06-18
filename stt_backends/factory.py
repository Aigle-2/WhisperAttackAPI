"""Legacy shim: the STT factory now lives in the infrastructure layer."""

from vaivox.application.ports import SpeechToTextError
from vaivox.infrastructure.stt.factory import create_stt_backend

__all__ = ["SpeechToTextError", "create_stt_backend"]
