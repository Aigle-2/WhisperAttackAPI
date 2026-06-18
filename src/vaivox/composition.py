"""Composition root: wire the driven adapters into the application use cases.

This is the one place that knows every concrete adapter. It depends on
infrastructure, application, and domain alike (it sits outside the layered contract),
keeping the inner layers free of wiring concerns.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event

from vaivox.application.ports import (
    SpeechToText,
    SpeechToTextError,
    StatusLevel,
    StatusReporter,
)
from vaivox.application.queries import DescribeStatus, DryRunReconcile
from vaivox.application.record_command import StartRecording, StopAndReconcile
from vaivox.application.shutdown import Shutdown
from vaivox.infrastructure.api.introspection import (
    DEFAULT_API_HOST,
    DEFAULT_API_PORT,
    IntrospectionServer,
)
from vaivox.infrastructure.audio.recorder import SoundDeviceRecorder
from vaivox.infrastructure.config.settings import WhisperAttackConfiguration
from vaivox.infrastructure.inbound.control_server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    ControlSocketServer,
)
from vaivox.infrastructure.kneeboard.sink import KneeboardSink
from vaivox.infrastructure.stt.factory import create_stt_backend
from vaivox.infrastructure.system_clock import SystemClock
from vaivox.infrastructure.telemetry.null_sink import NullTelemetrySink
from vaivox.infrastructure.voiceattack.sink import VoiceAttackCommandSink

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WiredApp:
    """The wired application surface the entry point drives.

    Attributes:
        control_server: The inbound control socket server, ready to ``run()``.
        api_server: The introspection API server, or ``None`` when disabled.
    """

    control_server: ControlSocketServer
    api_server: IntrospectionServer | None = None


def build(
    config: WhisperAttackConfiguration,
    reporter: StatusReporter,
    exit_event: Event,
    request_shutdown: Callable[[], None],
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> WiredApp:
    """Construct the adapters, use cases, and control server.

    Args:
        config: The effective application configuration.
        reporter: The user-facing status reporter (the UI writer in production).
        exit_event: Signalled to stop the control loop.
        request_shutdown: Callback that tears the application down.
        host: Control-socket bind address.
        port: Control-socket bind port.

    Returns:
        The wired application surface.
    """
    speech_to_text = create_stt_backend(config)
    recorder = SoundDeviceRecorder()
    command_sink = VoiceAttackCommandSink(
        config.get_voiceattack_host(), config.get_voiceattack_port(), reporter
    )
    kneeboard_sink = KneeboardSink(config.get_text_line_length, reporter)
    telemetry = NullTelemetrySink()
    clock = SystemClock()

    start_recording = StartRecording(recorder, reporter)
    stop_and_reconcile = StopAndReconcile(
        recorder,
        speech_to_text,
        command_sink,
        kneeboard_sink,
        config,
        reporter,
        clock,
        telemetry,
    )
    shutdown = Shutdown(request_shutdown, reporter)

    def on_startup() -> bool:
        return load_speech_to_text(speech_to_text, config.get_stt_backend(), reporter)

    control_server = ControlSocketServer(
        on_start=start_recording.execute,
        on_stop=stop_and_reconcile.execute,
        on_shutdown=shutdown.execute,
        is_recording=lambda: recorder.is_recording,
        exit_event=exit_event,
        reporter=reporter,
        on_startup=on_startup,
        host=host,
        port=port,
    )

    api_server: IntrospectionServer | None = None
    if config.get_bool_setting("api_enabled", False):
        api_server = IntrospectionServer(
            DescribeStatus(recorder, config),
            DryRunReconcile(config),
            host=config.get_setting("api_host", DEFAULT_API_HOST),
            port=config.get_int_setting("api_port", DEFAULT_API_PORT),
            token=config.get_setting("api_token", ""),
        )

    return WiredApp(control_server=control_server, api_server=api_server)


def load_speech_to_text(
    speech_to_text: SpeechToText, backend_name: str, reporter: StatusReporter
) -> bool:
    """Load the STT backend, reporting progress and failures (parity with legacy).

    Args:
        speech_to_text: The STT adapter to load.
        backend_name: The configured backend name (for the status messages).
        reporter: The user-facing status reporter.

    Returns:
        ``True`` if the backend loaded; ``False`` (with an error reported) otherwise.
    """
    _LOGGER.info("Loading STT backend '%s' ...", backend_name)
    reporter.report(f"Loading STT backend ({backend_name}) ...")
    try:
        speech_to_text.load()
    except SpeechToTextError as error:
        _LOGGER.error("Failed to load STT backend: %s", error)
        reporter.report(f"Failed to load STT backend: {error}", StatusLevel.ERROR)
        return False
    except Exception as error:
        _LOGGER.exception("Unexpected failure while loading STT backend.")
        reporter.report(f"Failed to load STT backend: {error}", StatusLevel.ERROR)
        return False
    _LOGGER.info("Successfully loaded STT backend '%s'", backend_name)
    reporter.report(f"Successfully loaded STT backend ({backend_name})", StatusLevel.SUCCESS)
    return True
