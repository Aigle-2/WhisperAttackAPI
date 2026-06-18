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
    TelemetrySink,
)
from vaivox.application.queries import DescribeStatus, DryRunReconcile
from vaivox.application.record_command import StartRecording, StopAndReconcile
from vaivox.application.shutdown import Shutdown
from vaivox.infrastructure.api.introspection import IntrospectionServer
from vaivox.infrastructure.audio.recorder import SoundDeviceRecorder
from vaivox.infrastructure.config.identity import VAIVOX
from vaivox.infrastructure.config.settings import VaivoxConfiguration
from vaivox.infrastructure.inbound.control_server import ControlSocketServer
from vaivox.infrastructure.kneeboard.sink import KneeboardSink
from vaivox.infrastructure.stt.factory import create_stt_backend
from vaivox.infrastructure.system_clock import SystemClock
from vaivox.infrastructure.telemetry.jsonl_sink import JsonlTelemetrySink
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
    config: VaivoxConfiguration,
    reporter: StatusReporter,
    exit_event: Event,
    request_shutdown: Callable[[], None],
    host: str = VAIVOX.control_host,
    port: int = VAIVOX.control_port,
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
    telemetry = build_telemetry_sink(config)
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
            host=config.get_setting("api_host", VAIVOX.api_host),
            port=config.get_int_setting("api_port", VAIVOX.api_port),
            token=config.get_setting("api_token", ""),
        )

    return WiredApp(control_server=control_server, api_server=api_server)


def build_telemetry_sink(config: VaivoxConfiguration) -> TelemetrySink:
    """Select the telemetry sink from configuration (ADR-0006).

    Telemetry is on by default: ADR-0006 step 1 records every reconciliation outcome,
    and the log is a local append-only file in the per-user VAIVOX data directory under
    %LOCALAPPDATA% (no network, no PII beyond transcribed text). The ``telemetry_enabled``
    setting lets a user opt out, in which case the no-op sink preserves legacy behaviour.

    Args:
        config: The effective application configuration.

    Returns:
        A :class:`~vaivox.infrastructure.telemetry.jsonl_sink.JsonlTelemetrySink` writing
        into the per-user data directory when telemetry is enabled, otherwise a
        :class:`~vaivox.infrastructure.telemetry.null_sink.NullTelemetrySink`.
    """
    if config.get_bool_setting("telemetry_enabled", True):
        return JsonlTelemetrySink(config.app_data_location)
    return NullTelemetrySink()


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
