"""Composition root: wire the driven adapters into the application use cases.

This is the one place that knows every concrete adapter. It depends on
infrastructure, application, and domain alike (it sits outside the layered contract),
keeping the inner layers free of wiring concerns.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from threading import Event, Lock

from vaivox.application.ports import (
    AudioRecorder,
    MissionVocabularySnapshot,
    SpeechToText,
    SpeechToTextError,
    StatusLevel,
    StatusReporter,
    TelemetrySink,
)
from vaivox.application.queries import (
    ComputeMetrics,
    DescribeStatus,
    DescribeVocabulary,
    DryRunReconcile,
    ListRecentReconciliations,
)
from vaivox.application.record_command import (
    SimulateUtterance,
    StartRecording,
    StopAndReconcile,
)
from vaivox.application.refresh_vocabulary import (
    RefreshMissionVocabulary,
    RefreshVocabulary,
    ReloadVocabulary,
)
from vaivox.application.shutdown import Shutdown
from vaivox.application.vocabulary_commands import AddWordMapping
from vaivox.domain.commands.model import CommandSurface, MissionMenuEntry, VoiceAttackCommand
from vaivox.domain.commands.resolver import CommandSurfaceResolver
from vaivox.domain.reconciliation.snapper import (
    DEFAULT_HIGH,
    DEFAULT_LOW,
    DEFAULT_MARGIN,
    PhraseSnapper,
)
from vaivox.infrastructure.api.introspection import IntrospectionServer
from vaivox.infrastructure.audio.recorder import SoundDeviceRecorder
from vaivox.infrastructure.config.settings import VaivoxConfiguration
from vaivox.infrastructure.dcs.hook_installer import (
    DcsHookInstaller,
    discover_dcs_install_dir,
    discover_panel_path,
)
from vaivox.infrastructure.dcs.menu_listener import MissionMenuListener, menu_file_path
from vaivox.infrastructure.inbound.control_server import ControlSocketServer
from vaivox.infrastructure.kneeboard.sink import KneeboardSink
from vaivox.infrastructure.reload.command_surface_resolver import (
    ReloadableCommandSurfaceResolver,
)
from vaivox.infrastructure.reload.phrase_snapper import ReloadablePhraseSnapper
from vaivox.infrastructure.stt.factory import create_stt_backend
from vaivox.infrastructure.stt.keyterms import SttKeyterms
from vaivox.infrastructure.system_clock import SystemClock
from vaivox.infrastructure.telemetry.jsonl_reader import JsonlTelemetryReader
from vaivox.infrastructure.telemetry.jsonl_sink import JsonlTelemetrySink
from vaivox.infrastructure.telemetry.null_sink import NullTelemetrySink
from vaivox.infrastructure.vocabulary.jsonl_repository import JsonlVocabularyRepository
from vaivox.infrastructure.vocabulary.legacy_files import load_legacy_vocabulary
from vaivox.infrastructure.vocabulary.migration import migrate_legacy_vocabulary
from vaivox.infrastructure.vocabulary.mission_f10 import (
    DEFAULT_MAX_MISSION_F10_PHRASES,
    VaicomF10MissionVocabulary,
)
from vaivox.infrastructure.vocabulary.phrase_index import load_phrase_index
from vaivox.infrastructure.vocabulary.reconciliation_vocabulary import (
    RepositoryReconciliationVocabulary,
)
from vaivox.infrastructure.vocabulary.vaicom_action_aliases import VaicomActionAliasCatalog
from vaivox.infrastructure.vocabulary.vaicom_generator import VaicomVocabularyGenerator
from vaivox.infrastructure.voiceattack.dispatcher import TypedCommandDispatcher
from vaivox.infrastructure.voiceattack.sink import VoiceAttackCommandSink
from vaivox.infrastructure.voiceattack.vaicom_f10_sink import UdpVaicomF10ActionSink

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WiredApp:
    """The wired application surface the entry point drives.

    Attributes:
        control_server: The inbound control socket server, ready to ``run()``.
        phrase_snapper: The idle-hot-reloadable phrase snapper (ADR-0009). Held so a
            later trigger (background generation, the reload API action) can call
            ``reload(...)`` to swap in a regenerated index without a restart.
        refresh_vocabulary: The VAICOM vocabulary refresh use case (ADR-0005). The entry
            point runs it on a background thread at startup; a UI action can run it with
            ``force=True``. It hot-applies the regenerated phrase index via
            ``phrase_snapper`` on success.
        refresh_mission_vocabulary: The current-mission F10 overlay refresh use case. It
            polls VAICOM's live log, keeps the phrases out of permanent vocabulary, and
            hot-applies the overlay through ``phrase_snapper``.
        reconciliation_vocabulary: Projection of structured vocabulary used by the runtime
            reconciliation pipeline.
        stt_keyterms: Provider keyterm builder used by STT adapters and startup diagnostics.
        add_word_mapping: Use case backing the UI "Add mapping" action.
        get_core_phrases: Live permanent command phrases (the merged snap index minus the
            mission overlay) — the "Core" tab of the UI commands browser.
        get_mission_phrases: Live mission-scoped F10 command phrases — the "F10" tab of the
            UI commands browser.
        api_server: The introspection API server, or ``None`` when disabled.
        menu_listener: The live F10 menu UDP listener (ADR-0012), or ``None`` when the live
            menu is disabled. The entry point starts it on a daemon thread.
        hook_installer: The DCS panel hook self-healer (ADR-0012), or ``None`` when no DCS
            install is configured/found. The entry point runs it once at startup.
    """

    control_server: ControlSocketServer
    phrase_snapper: ReloadablePhraseSnapper
    refresh_vocabulary: RefreshVocabulary
    refresh_mission_vocabulary: RefreshMissionVocabulary
    reconciliation_vocabulary: RepositoryReconciliationVocabulary
    stt_keyterms: SttKeyterms
    add_word_mapping: AddWordMapping
    get_core_phrases: Callable[[], tuple[str, ...]]
    get_mission_phrases: Callable[[], tuple[str, ...]]
    get_mission_display_phrases: Callable[[], tuple[str, ...]]
    api_server: IntrospectionServer | None = None
    menu_listener: MissionMenuListener | None = None
    hook_installer: DcsHookInstaller | None = None


def build(
    config: VaivoxConfiguration,
    reporter: StatusReporter,
    exit_event: Event,
    request_shutdown: Callable[[], None],
    host: str | None = None,
    port: int | None = None,
) -> WiredApp:
    """Construct the adapters, use cases, and control server.

    Args:
        config: The effective application configuration.
        reporter: The user-facing status reporter (the UI writer in production).
        exit_event: Signalled to stop the control loop.
        request_shutdown: Callback that tears the application down.
        host: Optional control-socket bind address override.
        port: Optional control-socket bind port override.

    Returns:
        The wired application surface.
    """
    control_host = host or config.get_control_host()
    control_port = port or config.get_control_port()
    recorder = SoundDeviceRecorder()
    clock = SystemClock()
    # The structured-vocabulary store is on the reconciliation and routing path. Shipped
    # defaults are read from the app directory; user additions, usage sidecars, and legacy
    # upgrade imports are written to the per-user data directory.
    vocabulary_repository = JsonlVocabularyRepository(
        config.app_data_location,
        default_source_dir=config.app_location,
    )
    legacy_word_mappings, legacy_fuzzy_words = load_legacy_vocabulary(
        [config.app_location, config.app_data_location]
    )
    migrate_legacy_vocabulary(
        legacy_word_mappings,
        legacy_fuzzy_words,
        vocabulary_repository,
        clock.now(),
    )
    reconciliation_vocabulary = RepositoryReconciliationVocabulary(vocabulary_repository)
    mission_phrase_lock = Lock()
    mission_phrases: tuple[str, ...] = ()
    mission_display_phrases: tuple[str, ...] = ()
    mission_surfaces: tuple[CommandSurface, ...] = ()

    def get_mission_phrases() -> tuple[str, ...]:
        with mission_phrase_lock:
            return mission_phrases

    def get_mission_surfaces() -> tuple[CommandSurface, ...]:
        with mission_phrase_lock:
            return mission_surfaces

    def get_mission_display_phrases() -> tuple[str, ...]:
        with mission_phrase_lock:
            return mission_display_phrases

    def get_mission_keyterms() -> list[str]:
        return _mission_keyterms_from_phrases(get_mission_phrases())

    # Build the authoritative live-index provider before the dispatcher. Both vocabulary
    # overlay and send-time dispatch consult the same current-session map (ADR-0012).
    menu_listener: MissionMenuListener | None = None
    hook_installer: DcsHookInstaller | None = None
    live_index: Callable[[], Mapping[str, int]] | None = None
    live_entries: Callable[[], Sequence[MissionMenuEntry]] | None = None
    if config.get_bool_setting("vaicom_f10_live_menu", True):
        menu_port = config.get_vaicom_f10_menu_port()
        menu_listener = MissionMenuListener(
            port=menu_port,
            persist_path=menu_file_path(config.app_data_location),
            on_update=lambda count: reporter.report(
                f"F10 live menu active: {count} dispatchable commands", StatusLevel.DETAIL
            ),
            on_error=lambda message: reporter.report(message, StatusLevel.WARNING),
        )
        live_index = menu_listener.get_menu
        live_entries = menu_listener.get_entries
        install_dir = (
            config.get_setting("dcs_install_dir", "").strip() or discover_dcs_install_dir()
        )
        panel_path = discover_panel_path(install_dir)
        if panel_path is not None:
            hook_installer = DcsHookInstaller(panel_path, menu_port)

    stt_keyterms = SttKeyterms(config, reconciliation_vocabulary, get_mission_keyterms)
    speech_to_text = create_stt_backend(config, stt_keyterms)
    command_sink = VoiceAttackCommandSink(
        config.get_voiceattack_host(), config.get_voiceattack_port(), reporter
    )
    vaicom_f10_sink = UdpVaicomF10ActionSink(
        config.get_vaicom_f10_host(),
        config.get_vaicom_f10_port(),
        reporter,
        live_index=live_index,
        live_entries=live_entries,
    )
    command_dispatcher = TypedCommandDispatcher(command_sink, vaicom_f10_sink)
    kneeboard_sink = KneeboardSink(config.get_text_line_length, reporter)
    telemetry = build_telemetry_sink(config)
    snapper = build_phrase_snapper(config, recorder, reporter)
    surface_resolver = build_command_surface_resolver(config)
    add_word_mapping = AddWordMapping(vocabulary_repository, clock)

    start_recording = StartRecording(recorder, reporter)
    stop_and_reconcile = StopAndReconcile(
        recorder,
        speech_to_text,
        command_dispatcher,
        kneeboard_sink,
        reconciliation_vocabulary,
        reporter,
        clock,
        telemetry,
        surface_resolver,
        snapper,
        vocabulary_repository,
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
        host=control_host,
        port=control_port,
    )

    generator = VaicomVocabularyGenerator(config.app_data_location)

    def apply_phrase_index() -> int:
        base_phrases = load_phrase_index(config.app_data_location)
        phrases = _merge_phrase_indexes(base_phrases, get_mission_phrases())
        snapper.reload(phrases)
        surface_resolver.reload(
            _merge_command_surfaces(
                _voiceattack_surfaces(base_phrases),
                get_mission_surfaces(),
            )
        )
        return len(phrases)

    def apply_mission_phrase_index(snapshot: MissionVocabularySnapshot) -> int:
        nonlocal mission_display_phrases, mission_phrases, mission_surfaces
        with mission_phrase_lock:
            mission_phrases = snapshot.phrases
            mission_surfaces = snapshot.surfaces
            mission_display_phrases = snapshot.display_phrases or snapshot.phrases
        return apply_phrase_index()

    def get_core_phrases() -> tuple[str, ...]:
        # The snapper's live index is the permanent vocabulary merged with the mission
        # overlay; subtract the overlay so the "Core" tab shows only permanent commands.
        mission_keys = {phrase.strip().lower() for phrase in get_mission_phrases()}
        return tuple(
            phrase for phrase in snapper.phrase_index if phrase.strip().lower() not in mission_keys
        )

    refresh_vocabulary = RefreshVocabulary(generator, reporter, apply_phrase_index)
    mission_log_path = config.get_setting("mission_f10_log_path", "").strip() or None
    mission_max_phrases = config.get_int_setting(
        "mission_f10_max_phrases",
        DEFAULT_MAX_MISSION_F10_PHRASES,
        min_value=1,
        max_value=5000,
    )
    refresh_mission_vocabulary = RefreshMissionVocabulary(
        VaicomF10MissionVocabulary(
            mission_log_path,
            max_phrases=mission_max_phrases,
            live_index=live_index,
            live_entries=live_entries,
            action_aliases=VaicomActionAliasCatalog().load,
        ),
        reporter,
        apply_mission_phrase_index,
        verbose=lambda: config.get_bool_setting("mission_f10_verbose_logging", False),
    )

    api_server: IntrospectionServer | None = None
    if config.get_bool_setting("api_enabled", False):
        telemetry_reader = JsonlTelemetryReader(config.app_data_location)
        api_server = IntrospectionServer(
            DescribeStatus(recorder, config),
            DryRunReconcile(reconciliation_vocabulary, surface_resolver),
            ListRecentReconciliations(telemetry_reader),
            ComputeMetrics(telemetry_reader),
            DescribeVocabulary(vocabulary_repository),
            refresh_vocabulary,
            ReloadVocabulary(apply_phrase_index, reporter),
            SimulateUtterance(
                reconciliation_vocabulary,
                surface_resolver,
                snapper,
                command_dispatcher,
                kneeboard_sink,
                telemetry,
                reporter,
                vocabulary_repository,
                clock,
            ),
            host=config.get_api_host(),
            port=config.get_api_port(),
            token=config.get_setting("api_token", ""),
            actions_enabled=config.get_bool_setting("api_actions_enabled", False),
            max_post_bytes=config.get_api_max_post_bytes(),
        )

    return WiredApp(
        control_server=control_server,
        phrase_snapper=snapper,
        refresh_vocabulary=refresh_vocabulary,
        refresh_mission_vocabulary=refresh_mission_vocabulary,
        reconciliation_vocabulary=reconciliation_vocabulary,
        stt_keyterms=stt_keyterms,
        add_word_mapping=add_word_mapping,
        get_core_phrases=get_core_phrases,
        get_mission_phrases=get_mission_phrases,
        get_mission_display_phrases=get_mission_display_phrases,
        api_server=api_server,
        menu_listener=menu_listener,
        hook_installer=hook_installer,
    )


def _merge_phrase_indexes(base: Sequence[str], mission: Sequence[str]) -> list[str]:
    """Merge permanent and mission-scoped phrase indexes without duplicating phrases."""
    merged: list[str] = []
    seen: set[str] = set()
    for phrase in (*base, *mission):
        normalized = phrase.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
    return merged


def _voiceattack_surfaces(phrases: Sequence[str]) -> list[CommandSurface]:
    """Build static VoiceAttack command surfaces from the permanent phrase index."""
    surfaces: list[CommandSurface] = []
    seen: set[str] = set()
    for phrase in phrases:
        label = phrase.strip()
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        surfaces.append(
            CommandSurface(
                id=f"voiceattack:{_surface_key(label)}",
                label=label,
                aliases=(),
                source="voiceattack",
                scope="global",
                dispatch_target=VoiceAttackCommand(label),
            )
        )
    return surfaces


def _merge_command_surfaces(
    base: Sequence[CommandSurface],
    mission: Sequence[CommandSurface],
) -> list[CommandSurface]:
    """Merge permanent and mission command surfaces without duplicating ids."""
    merged: list[CommandSurface] = []
    seen: set[str] = set()
    for surface in (*base, *mission):
        if surface.id in seen:
            continue
        seen.add(surface.id)
        merged.append(surface)
    return merged


def _surface_key(value: str) -> str:
    key = "".join(character if character.isalnum() else "-" for character in value.casefold())
    return "-".join(part for part in key.split("-") if part) or "unnamed"


def _mission_keyterms_from_phrases(phrases: Sequence[str]) -> list[str]:
    """Build STT keyterms from mission F10 phrases, including raw names without Action."""
    keyterms: list[str] = []
    for phrase in phrases:
        normalized = phrase.strip()
        if not normalized:
            continue
        keyterms.append(normalized)
        if normalized.lower().startswith("action "):
            keyterms.append(normalized[7:].strip())
    return keyterms


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


def build_phrase_snapper(
    config: VaivoxConfiguration,
    recorder: AudioRecorder,
    reporter: StatusReporter,
) -> ReloadablePhraseSnapper:
    """Build the idle-hot-reloadable phrase snapper from the generated index (ADR-0011/0009).

    The phrase index is read once here for the initial snapper. It is **not** shipped
    (ADR-0005): until the generator writes ``phrase_index.txt`` into the per-user data
    directory the loader returns an empty list, which makes the snapper a no-op (every
    command is sent raw) so behaviour parity is preserved on a fresh install.

    The snapper is wrapped in a :class:`~vaivox.infrastructure.reload.phrase_snapper.\
ReloadablePhraseSnapper` so a regenerated index can be swapped in at idle without a
    restart (ADR-0009): the swap is gated on the recorder being idle (never mid-utterance)
    and surfaces a "vocabulary refreshed" status line. The reload is dormant until a
    trigger calls ``reload(...)`` (background generation / the reload API action); in this
    session it behaves exactly like the frozen snapper it wraps.

    Args:
        config: The effective application configuration (for the data-dir location).
        recorder: The audio recorder, read for the idle gate (``not is_recording``).
        reporter: The status reporter, signalled when an index actually swaps in.

    Returns:
        A :class:`~vaivox.infrastructure.reload.phrase_snapper.ReloadablePhraseSnapper`
        over the generated phrase index, with the snap thresholds resolved from settings.
    """
    phrases = load_phrase_index(config.app_data_location)
    if phrases:
        _LOGGER.info("Loaded %d phrase-index entries for the snapper.", len(phrases))
    else:
        _LOGGER.debug("No phrase index present; the snapper is a no-op.")

    # The three conservative snap thresholds (ADR-0011) are overridable in settings.cfg —
    # tune against the eval / telemetry without a code change. Defaults are the
    # eval-calibrated constants. The same builder seeds the initial snapper and every
    # hot-reload, so a regenerated index keeps the configured calibration (ADR-0009).
    def build(index: Sequence[str]) -> PhraseSnapper:
        high = config.get_float_setting("snap_high", DEFAULT_HIGH, min_value=0.0, max_value=100.0)
        low = config.get_float_setting("snap_low", DEFAULT_LOW, min_value=0.0, max_value=100.0)
        margin = config.get_float_setting(
            "snap_margin", DEFAULT_MARGIN, min_value=0.0, max_value=100.0
        )
        return PhraseSnapper(index, high=high, low=low, margin=margin)

    def announce_reload(count: int) -> None:
        _LOGGER.info("Phrase index hot-reloaded: %d phrases.", count)
        reporter.report(f"Vocabulary refreshed: {count} phrases", StatusLevel.SUCCESS)

    return ReloadablePhraseSnapper(
        build(phrases),
        is_idle=lambda: not recorder.is_recording,
        on_reload=announce_reload,
        build=build,
    )


def build_command_surface_resolver(config: VaivoxConfiguration) -> ReloadableCommandSurfaceResolver:
    """Build the hot-reloadable command-surface resolver from the generated index."""
    phrases = load_phrase_index(config.app_data_location)

    def build(index: Sequence[CommandSurface]) -> CommandSurfaceResolver:
        high = config.get_float_setting("snap_high", DEFAULT_HIGH, min_value=0.0, max_value=100.0)
        low = config.get_float_setting("snap_low", DEFAULT_LOW, min_value=0.0, max_value=100.0)
        margin = config.get_float_setting(
            "snap_margin", DEFAULT_MARGIN, min_value=0.0, max_value=100.0
        )
        return CommandSurfaceResolver(index, high=high, low=low, margin=margin)

    return ReloadableCommandSurfaceResolver(_voiceattack_surfaces(phrases), build=build)


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
