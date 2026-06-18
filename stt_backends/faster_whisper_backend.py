import logging

from configuration import WhisperAttackConfiguration
from stt_backends.base import SpeechToTextBackend, SpeechToTextBackendError, SpeechToTextResult
from stt_backends.prompts import DEFAULT_DCS_PROMPT


class FasterWhisperBackend(SpeechToTextBackend):
    """
    Local faster-whisper backend used by the original WhisperAttack workflow.
    """
    provider_name = "faster_whisper"

    def __init__(self, config: WhisperAttackConfiguration):
        self.config = config
        self.model = None

    def load(self) -> None:
        whisper_model = self.config.get_whisper_model()
        whisper_device = self.config.get_whisper_device()
        whisper_compute_type = self.config.get_whisper_compute_type()
        whisper_core_type = self.config.get_whisper_core_type()

        try:
            import torch
            from faster_whisper import WhisperModel
        except ImportError as import_error:
            raise SpeechToTextBackendError(
                "The faster_whisper backend requires the full build with torch and faster-whisper installed. "
                "Use the API build with stt_backend=elevenlabs, or rebuild with the full profile."
            ) from import_error

        if whisper_device.upper() == "GPU":
            if torch.cuda.is_available():
                compute_type = whisper_compute_type
                if whisper_core_type.lower() == "standard":
                    compute_type = "int8"
                    logging.info("whisper_core_type is 'standard' so using compute_type '%s'", compute_type)
                device = torch.device("cuda")
                major, minor = torch.cuda.get_device_capability(device)
                logging.info("GPU has cuda capability major=%s minor=%s", major, minor)
                if whisper_core_type.lower() == "tensor" and major < 7:
                    compute_type = "int8"
                    logging.warning(
                        "GPU does not have tensor cores, major=%s, minor=%s so using compute_type '%s'",
                        major,
                        minor,
                        compute_type
                    )
                logging.info(
                    "Loading Whisper model (%s), device=%s, core_type=%s, compute_type=%s ...",
                    whisper_model,
                    whisper_device,
                    whisper_core_type,
                    compute_type
                )
                self.model = WhisperModel(whisper_model, device="cuda", compute_type=compute_type)
                logging.info("Successfully loaded Whisper model")
                return

            logging.error("cuda not available so using CPU")

        compute_type = "int8"
        logging.info("Loading Whisper model (%s), device=%s, compute_type=%s ...", whisper_model, "cpu", compute_type)
        self.model = WhisperModel(whisper_model, device="cpu", compute_type=compute_type)

    def transcribe(self, audio_path: str) -> SpeechToTextResult:
        segments, _ = self.model.transcribe(
            audio_path,
            language=self.config.get_stt_language(),
            beam_size=5,
            suppress_tokens=[0, 11, 13, 30, 986],
            initial_prompt=self.config.get_stt_prompt() or DEFAULT_DCS_PROMPT
        )
        text = ""
        for segment in segments:
            text += f"{segment.text}"
        return SpeechToTextResult(text=text)
