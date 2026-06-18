"""Legacy shim: the STT port, result VO, and error now live in the hexagonal layers.

Retained so legacy modules and the ported tests keep importing from
``stt_backends.base`` during the migration. New code imports the port and error from
:mod:`vaivox.application.ports` and the result VO from
:mod:`vaivox.domain.reconciliation.model`.
"""

from vaivox.application.ports import SpeechToText, SpeechToTextError
from vaivox.domain.reconciliation.model import Transcription

# Backward-compatible aliases for the pre-hexagonal names.
SpeechToTextResult = Transcription
SpeechToTextBackendError = SpeechToTextError
SpeechToTextBackend = SpeechToText

__all__ = [
    "SpeechToTextBackend",
    "SpeechToTextBackendError",
    "SpeechToTextResult",
]
