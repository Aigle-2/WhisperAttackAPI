"""Composition root: wire the driven adapters into the application use cases.

This is the one place that knows every concrete adapter. It depends on
infrastructure, application, and domain alike (it sits outside the layered contract),
keeping the inner layers free of wiring concerns.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from threading import Event

from vaivox.application.add_vocabulary import AddWordMapping
from vaivox.application.ports import (
    AudioRecorder,
    Clock,
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
from vaivox.application.reconcile_text import ReconcileText
from vaivox.application.record_command import (
    SimulateUtterance,
    StartRecording,
    StopAndReconcile,
)
from vaivox.application.refresh_vocabulary import RefreshVocabulary, ReloadVocabulary
from vaivox.application.shutdown import Shutdown
from vaivox.application.usage_stamping import UsageStamper
from vaivox.domain.reconciliation.snapper import (
    DEFAULT_HIGH,
    DEFAULT_LOW,
    DEFAULT_MARGIN,
    PhraseSnapper,
)
from vaivox.domain.vocabulary.governor import VocabularyGovernor
from vaivox.domain.vocabulary.model import EvictionPolicy, VocabularyKind
from vaivox.infrastructure.api.introspection import IntrospectionServer
from vaivox.infrastructure.audio.recorder import SoundDeviceRecorder
from vaivox.infrastructure.config.identity import VAIVOX
from vaivox.infrastructure.config.settings import VaivoxConfiguration
from vaivox.infrastructure.inbound.control_server import ControlSocketServer
from vaivox.infrastructure.kneeboard.sink import KneeboardSink
from vaivox.infrastructure.reload.phrase_snapper import ReloadablePhraseSnapper
from vaivox.infrastructure.stt.factory import create_stt_backend
from vaivox.infrastructure.system_clock import SystemClock
from vaivox.infrastructure.telemetry.jsonl_reader import JsonlTelemetryReader
from vaivox.infrastructure.telemetry.jsonl_sink import JsonlTelemetrySink
from vaivox.infrastructure.telemetry.null_sink import NullTelemetrySink
from vaivox.infrastructure.vocabulary.jsonl_repository import JsonlVocabularyRepository
from vaivox.infrastructure.vocabulary.migration import migrate_legacy_vocabulary
from vaivox.infrastructure.vocabulary.phrase_index import load_phrase_index
from vaivox.infrastructure.vocabulary.repository_provider import RepositoryVocabularyProvider
from vaivox.infrastructure.vocabulary.vaicom_generator import VaicomVocabularyGenerator
from vaivox.infrastructure.voiceattack.sink import VoiceAttackCommandSink

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
        add_word_mapping: The use case the UI "Add word mapping" action drives, writing the
            mapping into the :class:`VocabularyRepository` source of truth (ADR-0004).
        api_server: The introspection API server, or ``None`` when disabled.
    """

    control_server: ControlSocketServer
    phrase_snapper: ReloadablePhraseSnapper
    refresh_vocabulary: RefreshVocabulary
    add_word_mapping: AddWordMapping
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
    snapper = build_phrase_snapper(config, recorder, reporter)

    # The structured JSONL repository is the single source of truth for the reconciliation
    # vocabulary (ADR-0004). Auto-seed it from the legacy flat files on first launch, then
    # project it down to the flat reads the pipeline consumes — so the engine and the
    # introspection GET /vocabulary read the same store and can never diverge.
    vocabulary_repository = build_vocabulary_repository(config, clock)
    vocabulary = RepositoryVocabularyProvider(vocabulary_repository, clock)
    reconcile_text = ReconcileText(vocabulary)
    add_word_mapping = AddWordMapping(vocabulary_repository, clock)

    # Governance write-back (ADR-0004 Axis A): on a VoiceAttack dispatch, credit the
    # vocabulary entries whose surface form survived (Tier 1 attribution) and stamp their
    # recency/hits. The LRU eviction pass is wired but inert by default (no cap) so the seed
    # vocabulary is never evicted — see build_usage_stamper. Until the C# return channel
    # ships (ADR-0006) this credits on dispatch, not on a confirmed match.
    usage_stamper = build_usage_stamper(config, vocabulary_repository, clock)

    start_recording = StartRecording(recorder, reporter)
    stop_and_reconcile = StopAndReconcile(
        recorder,
        speech_to_text,
        command_sink,
        kneeboard_sink,
        reconcile_text,
        reporter,
        clock,
        telemetry,
        snapper,
        usage_stamper,
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

    generator = VaicomVocabularyGenerator(config.app_data_location)

    def apply_phrase_index() -> int:
        phrases = load_phrase_index(config.app_data_location)
        snapper.reload(phrases)
        return len(phrases)

    refresh_vocabulary = RefreshVocabulary(generator, reporter, apply_phrase_index)

    api_server: IntrospectionServer | None = None
    if config.get_bool_setting("api_enabled", False):
        data_dir = config.app_data_location
        telemetry_reader = JsonlTelemetryReader(data_dir)
        api_server = IntrospectionServer(
            DescribeStatus(recorder, config),
            DryRunReconcile(vocabulary),
            ListRecentReconciliations(telemetry_reader),
            ComputeMetrics(telemetry_reader),
            DescribeVocabulary(vocabulary_repository),
            refresh_vocabulary,
            ReloadVocabulary(apply_phrase_index, reporter),
            SimulateUtterance(
                reconcile_text,
                snapper,
                command_sink,
                kneeboard_sink,
                telemetry,
                reporter,
                usage_stamper,
            ),
            host=config.get_setting("api_host", VAIVOX.api_host),
            port=config.get_int_setting("api_port", VAIVOX.api_port),
            token=config.get_setting("api_token", ""),
            actions_enabled=config.get_bool_setting("api_actions_enabled", False),
        )

    return WiredApp(
        control_server=control_server,
        phrase_snapper=snapper,
        refresh_vocabulary=refresh_vocabulary,
        add_word_mapping=add_word_mapping,
        api_server=api_server,
    )


def build_vocabulary_repository(
    config: VaivoxConfiguration, clock: Clock
) -> JsonlVocabularyRepository:
    """Build the JSONL vocabulary repository, auto-seeding it on first launch (ADR-0004).

    The repository is the single source of truth for the reconciliation vocabulary. On a
    fresh install no ``<kind>.jsonl`` source exists yet, so this seeds it once from the
    legacy flat ``word_mappings.txt`` / ``fuzzy_words.txt`` (the shipped defaults merged with
    any per-user overrides, exactly as the legacy loader read them) via the one-shot
    migration — the "auto-run on first launch waits on the composition" follow-up ADR-0004
    deferred. Seeding is idempotent (the migration skips ids already present) and gated on
    the source files being absent, so a user's curated/learned entries are never overwritten
    on a later launch.

    Args:
        config: The effective application configuration (data-dir location + the legacy
            flat vocabulary to seed from).
        clock: The clock used to stamp the seeded entries' creation time.

    Returns:
        The :class:`~vaivox.infrastructure.vocabulary.jsonl_repository.JsonlVocabularyRepository`
        bound to the per-user data directory, seeded if it was empty.
    """
    data_dir = config.app_data_location
    repository = JsonlVocabularyRepository(data_dir)
    if _vocabulary_source_exists(data_dir):
        return repository

    report = migrate_legacy_vocabulary(
        config.get_word_mappings(),
        config.get_fuzzy_words(),
        repository,
        clock.now(),
    )
    _LOGGER.info(
        "Seeded vocabulary repository from the legacy flat files: %d fuzzy words + "
        "%d word mappings (%d entries).",
        report.fuzzy_words,
        report.word_mappings,
        report.total,
    )
    return repository


def _vocabulary_source_exists(data_dir: str) -> bool:
    """Whether any structured JSONL source file already exists in ``data_dir``.

    Args:
        data_dir: The per-user data directory the repository persists into.

    Returns:
        ``True`` if at least one ``<kind>.jsonl`` source is present (already seeded), so the
        auto-seed is skipped; ``False`` on a fresh install.
    """
    root = Path(data_dir)
    return any((root / f"{kind.value}.jsonl").is_file() for kind in VocabularyKind)


def build_usage_stamper(
    config: VaivoxConfiguration,
    repository: JsonlVocabularyRepository,
    clock: Clock,
) -> UsageStamper:
    """Build the vocabulary usage stamper, wiring an inert-by-default LRU pass (ADR-0004).

    Stamping (Tier 1 attribution -> ``mark_used``) is always active: every VoiceAttack
    dispatch credits the entries whose surface form survived. The LRU eviction pass is wired
    through the same stamper but **inert unless a cap is configured**: with no
    ``vocab_max_entries`` (the default) the per-kind :class:`EvictionPolicy` carries no cap,
    so :meth:`~vaivox.domain.vocabulary.governor.VocabularyGovernor.govern` evicts nothing —
    and ``DEFAULT`` (seed) entries are protected even when a cap is set. Eviction therefore
    only ever touches ``LEARNED`` entries, which do not exist until near-miss capture lands
    (gated on the C# return channel, ADR-0006).

    A configured ``vocab_max_entries`` caps every kind; ``vocab_grace_days`` shields a
    just-stamped entry from eviction for that many days (the grace window, ADR-0004 §3).

    Args:
        config: The effective application configuration (the optional LRU cap / grace window).
        repository: The vocabulary repository the stamps and any eviction write back through.
        clock: The clock supplying the stamp time.

    Returns:
        A :class:`~vaivox.application.usage_stamping.UsageStamper` over the repository and a
        fresh :class:`~vaivox.domain.vocabulary.governor.VocabularyGovernor`, with eviction
        inert unless ``vocab_max_entries`` is set.
    """
    max_entries = config.get_int_setting("vocab_max_entries", 0)
    eviction_policies: dict[VocabularyKind, EvictionPolicy] | None = None
    if max_entries > 0:
        grace_days = config.get_int_setting("vocab_grace_days", 0)
        grace_window = timedelta(days=grace_days) if grace_days > 0 else None
        policy = EvictionPolicy(max_entries=max_entries, grace_window=grace_window)
        eviction_policies = dict.fromkeys(VocabularyKind, policy)
        _LOGGER.info(
            "Vocabulary LRU eviction enabled: cap=%d per kind, grace=%s (LEARNED entries "
            "only; DEFAULT seeds protected).",
            max_entries,
            grace_window,
        )

    return UsageStamper(
        repository,
        VocabularyGovernor(),
        clock,
        eviction_policies=eviction_policies,
    )


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
    high = config.get_float_setting("snap_high", DEFAULT_HIGH)
    low = config.get_float_setting("snap_low", DEFAULT_LOW)
    margin = config.get_float_setting("snap_margin", DEFAULT_MARGIN)

    def build(index: Sequence[str]) -> PhraseSnapper:
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
