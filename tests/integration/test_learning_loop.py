"""AC2 — the vocabulary learning loop, proven end-to-end in memory (ADR-0006).

The headline acceptance test of the return-channel plan: the full loop

    utterance -> reconcile -> snap -> dispatch -> match outcome
              -> match-gated stamping + near-miss -> LEARNED proposal

is exercised at the **application level** with STT and VAICOM mocked **at the port level**.
The utterance text is fed in directly through :class:`SimulateUtterance`, so STT is absent
entirely; a scripted :class:`CommandDispatcher` returns the scripted
:class:`MatchOutcome` for each VoiceAttack dispatch (VAICOM mocked at the wire). The store
is the **real** :class:`JsonlVocabularyRepository` on a ``tmp_path``, time is a
deterministic ``FakeClock``, and stamping runs through the same real ``VocabularyGovernor``
the production ``route_command`` uses.

There is **no socket, no microphone, and no VoiceAttack** anywhere in this module — that is
the whole point: the learning logic lives a full layer above the wire and is proven in CI
before any C# exists.

**Adapted from v2 (``refactor/vaivox-hexagonal``).** This branch keeps the F10 /
typed-dispatch architecture (ADR-0012): ``route_command`` routes through the
``CommandDispatcher`` and reads ``dispatch_result.match`` rather than calling
``command_sink.send()`` directly, and it stamps usage inline (no ``UsageStamper`` module).
Critically, this branch's ``route_command`` does **not** run an LRU/eviction pass on
dispatch — it only ``mark_used``-stamps a matched command. v2's eviction / grace-window
replay tests therefore have no seam to exercise here and are intentionally omitted; the
governance/eviction behaviour is covered by the dedicated governor unit tests. What this
test pins is the *learning loop wiring*: stamp only on ``matched=True``, a near-miss ->
``LEARNED`` ``WORD_MAPPING`` under auto-apply, propose-only writes nothing, and the abstain
recorded in telemetry.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from vaivox.application.learn_from_outcome import ApplyPolicy, LearnFromOutcome
from vaivox.application.ports import CommandDispatchResult
from vaivox.application.record_command import SimulateUtterance
from vaivox.domain.commands.model import (
    CommandResolution,
    CommandResolutionDecision,
    DispatchOutcome,
    DispatchTargetKind,
    VoiceAttackCommand,
)
from vaivox.domain.reconciliation.snapper import PhraseSnapper
from vaivox.domain.telemetry.model import MatchOutcome
from vaivox.domain.vocabulary.model import (
    VocabularyEntry,
    VocabularyKind,
    VocabularyOrigin,
)
from vaivox.infrastructure.vocabulary.jsonl_repository import JsonlVocabularyRepository

_START = datetime(2026, 6, 22, 12, 0, 0)

# Valid command phrases the snapper scores against (a tiny frozen "VAICOM" phrase index).
_PHRASES = [
    "Texaco request rejoin",
    "Texaco request fuel",
    "Magic declare bogey dope",
]


class FakeClock:
    """A deterministic, advanceable clock (no wall-clock anywhere in the loop)."""

    def __init__(self, now: datetime = _START) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class ScriptedCommandDispatcher:
    """VAICOM mocked at the dispatcher port: returns the scripted outcome for each send.

    Mirrors this branch's :class:`CommandDispatcher`: a
    :class:`~vaivox.domain.commands.model.VoiceAttackCommand` dispatch records the sent
    command name and returns a :class:`CommandDispatchResult` carrying the next scripted
    :class:`MatchOutcome` (``None`` once the script is exhausted, i.e. unknown). No socket,
    no VoiceAttack — the learner reads ``dispatch_result.match`` exactly as in production.
    """

    def __init__(self, script: list[MatchOutcome | None] | None = None) -> None:
        self.sent: list[str] = []
        self._script = list(script or [])

    def queue(self, outcome: MatchOutcome | None) -> None:
        self._script.append(outcome)

    def dispatch(self, target: object) -> CommandDispatchResult:
        assert isinstance(target, VoiceAttackCommand)
        self.sent.append(target.command_name)
        match = self._script.pop(0) if self._script else None
        return CommandDispatchResult(
            dispatch=DispatchOutcome(
                target_kind=DispatchTargetKind.VOICEATTACK.value,
                accepted=True if match is None else match.matched,
                resolved_target=target.command_name,
            ),
            match=match,
        )


class RawSurfaceMatcher:
    """Always abstains to RAW so routing falls through to the legacy snap -> VoiceAttack path."""

    def resolve(self, text: str) -> CommandResolution:
        return CommandResolution(CommandResolutionDecision.RAW)


class FakeKneeboardSink:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, note_text: str) -> None:  # pragma: no cover - unused in this loop
        self.sent.append(note_text)


class FakeReporter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def report(self, message: str, level=None) -> None:
        self.lines.append(message)


class RecordingTelemetry:
    def __init__(self) -> None:
        self.outcomes: list[object] = []

    def record(self, outcome) -> None:
        self.outcomes.append(outcome)


class FakeVocabulary:
    """Minimal ReconciliationVocabulary (no fuzzy words; let the snapper do the work)."""

    def get_word_mappings(self):
        return {}

    def get_fuzzy_words(self):
        return []


def _simulate(
    repo: JsonlVocabularyRepository,
    clock: FakeClock,
    dispatcher: ScriptedCommandDispatcher,
    telemetry: RecordingTelemetry,
    *,
    policy: ApplyPolicy = ApplyPolicy.AUTO_APPLY,
) -> SimulateUtterance:
    """Wire the full routing path against the real repo/governor and the fakes.

    Uses :class:`SimulateUtterance` (text in directly, STT absent) so the utterance flows
    through the *same* shared ``route_command`` the PTT path uses — inline stamping + the
    learner fan out from one place.
    """
    learner = LearnFromOutcome(repo, clock, policy=policy)
    return SimulateUtterance(
        FakeVocabulary(),
        RawSurfaceMatcher(),
        PhraseSnapper(_PHRASES),
        dispatcher,
        FakeKneeboardSink(),
        telemetry,
        FakeReporter(),
        repo,
        clock,
        learner,
    )


def _seed_mapping(repo: JsonlVocabularyRepository, when: datetime) -> str:
    """Seed one DEFAULT word-mapping whose surface form we can later stamp, return its id."""
    entry = VocabularyEntry(
        id="texaco",
        kind=VocabularyKind.WORD_MAPPING,
        term="Texaco request rejoin",
        aliases=("texaco rejoin",),
        origin=VocabularyOrigin.DEFAULT,
    )
    repo.add(entry, when)
    return entry.id


def _usage(repo: JsonlVocabularyRepository, kind: VocabularyKind, entry_id: str):
    """Return the UsageStats for ``entry_id`` of ``kind`` (or None if absent)."""
    for governed in repo.load(kind):
        if governed.id == entry_id:
            return governed.usage
    return None


def _learned(repo: JsonlVocabularyRepository) -> list:
    """Return every LEARNED WORD_MAPPING governed entry currently in the store."""
    return [
        governed
        for governed in repo.load(VocabularyKind.WORD_MAPPING)
        if governed.entry.origin is VocabularyOrigin.LEARNED
    ]


# -- point 1: stamping only on a confirmed match -------------------------------------


def test_stamping_happens_only_on_matched_true(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = FakeClock()
    dispatcher = ScriptedCommandDispatcher()
    telemetry = RecordingTelemetry()
    seed_id = _seed_mapping(repo, clock.now())

    sim = _simulate(repo, clock, dispatcher, telemetry)

    # 1a. matched=True -> the surviving surface form ("Texaco request rejoin") is stamped.
    dispatcher.queue(MatchOutcome(matched=True, resolved_command="Texaco request rejoin"))
    sim.execute("Texaco request rejoin")
    usage = _usage(repo, VocabularyKind.WORD_MAPPING, seed_id)
    assert usage is not None
    assert usage.hits == 1
    assert usage.last_used == _START

    # 1b. matched=False -> a near-miss, NOT a credit: hits/last_used do not move.
    clock.advance(timedelta(hours=1))
    dispatcher.queue(MatchOutcome(matched=False))
    sim.execute("Texaco request rejoin")
    usage = _usage(repo, VocabularyKind.WORD_MAPPING, seed_id)
    assert usage is not None
    assert usage.hits == 1  # unchanged
    assert usage.last_used == _START  # unchanged

    # 1c. None (unknown) -> also no credit (distinct from matched=False; neither stamps).
    clock.advance(timedelta(hours=1))
    dispatcher.queue(None)
    sim.execute("Texaco request rejoin")
    usage = _usage(repo, VocabularyKind.WORD_MAPPING, seed_id)
    assert usage is not None
    assert usage.hits == 1


# -- point 2: near-miss -> LEARNED entry (auto-apply) --------------------------------


def test_near_miss_creates_learned_entry(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = FakeClock()
    dispatcher = ScriptedCommandDispatcher()
    telemetry = RecordingTelemetry()

    sim = _simulate(repo, clock, dispatcher, telemetry, policy=ApplyPolicy.AUTO_APPLY)

    # An utterance close to "Texaco request rejoin" that VoiceAttack reports as not matched.
    dispatcher.queue(MatchOutcome(matched=False))
    sim.execute("texaco request rejon")

    learned = _learned(repo)
    assert len(learned) == 1
    entry = learned[0].entry
    assert entry.term == "Texaco request rejoin"  # nearest valid phrase = replacement
    assert "texaco request rejon" in entry.aliases  # spoken near-miss = alias
    # Seeded recency = creation time, so the grace window can protect it.
    assert learned[0].usage.last_used == _START


def test_propose_only_writes_nothing(tmp_path) -> None:
    # The default policy is human-in-the-loop: a near-miss is proposed but never written.
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = FakeClock()
    dispatcher = ScriptedCommandDispatcher()
    telemetry = RecordingTelemetry()

    sim = _simulate(repo, clock, dispatcher, telemetry, policy=ApplyPolicy.PROPOSE_ONLY)

    dispatcher.queue(MatchOutcome(matched=False))
    sim.execute("texaco request rejon")

    assert repo.load(VocabularyKind.WORD_MAPPING) == []  # nothing written


def test_matched_true_never_learns(tmp_path) -> None:
    # A confirmed match is not a near-miss: even on auto-apply, nothing is learned.
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = FakeClock()
    dispatcher = ScriptedCommandDispatcher()
    telemetry = RecordingTelemetry()

    sim = _simulate(repo, clock, dispatcher, telemetry, policy=ApplyPolicy.AUTO_APPLY)

    dispatcher.queue(MatchOutcome(matched=True, resolved_command="Texaco request rejoin"))
    sim.execute("texaco request rejon")

    assert _learned(repo) == []  # a match never learns


def test_unknown_outcome_never_learns(tmp_path) -> None:
    # An unknown (None) outcome with no snap signal is no signal at all: nothing learned.
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = FakeClock()
    dispatcher = ScriptedCommandDispatcher()
    telemetry = RecordingTelemetry()

    sim = _simulate(repo, clock, dispatcher, telemetry, policy=ApplyPolicy.AUTO_APPLY)

    # An exact phrase -> the snapper snaps (no abstain near-miss); an unknown match outcome
    # carries no learnable signal, so nothing is written.
    dispatcher.queue(None)
    sim.execute("Texaco request rejoin")

    assert _learned(repo) == []


# -- point 5: abstain recorded in telemetry ------------------------------------------


def test_abstain_is_recorded_in_telemetry(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = FakeClock()
    dispatcher = ScriptedCommandDispatcher()
    telemetry = RecordingTelemetry()

    sim = _simulate(repo, clock, dispatcher, telemetry, policy=ApplyPolicy.PROPOSE_ONLY)

    # A near-miss the snapper abstains on (close, but below the snap-high band): telemetry
    # records the abstain decision with the near-miss candidates and the match outcome.
    dispatcher.queue(MatchOutcome(matched=False))
    sim.execute("texaco rejon")

    assert len(telemetry.outcomes) == 1
    outcome = telemetry.outcomes[0]
    assert outcome.destination == "voiceattack"
    assert outcome.snap is not None
    assert outcome.snap.decision == "abstained"
    assert outcome.snap.near_misses  # the abstain-band candidates were recorded
    assert outcome.match == MatchOutcome(matched=False)


def test_abstain_alone_learns_even_when_match_unknown(tmp_path) -> None:
    # A snap abstain is itself a learnable near-miss: even with an unknown (None) match
    # outcome, the abstain-band candidates drive a LEARNED proposal on auto-apply.
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = FakeClock()
    dispatcher = ScriptedCommandDispatcher()
    telemetry = RecordingTelemetry()

    sim = _simulate(repo, clock, dispatcher, telemetry, policy=ApplyPolicy.AUTO_APPLY)

    dispatcher.queue(None)  # unknown match; the abstain is the signal
    sim.execute("texaco rejon")

    learned = _learned(repo)
    assert len(learned) == 1
    assert learned[0].entry.term == "Texaco request rejoin"
