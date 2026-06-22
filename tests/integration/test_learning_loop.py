"""AC2 — the vocabulary learning loop, proven end-to-end in memory (ADR-0006).

The headline acceptance test of the return-channel plan: the full loop

    utterance -> reconcile -> snap -> dispatch -> match outcome
              -> match-gated stamping + near-miss -> LEARNED -> eviction

is exercised at the **application level** with STT and VAICOM mocked **at the port level**.
A :class:`FakeCommandSink` debits scripted :class:`MatchOutcome` values (VAICOM mocked); the
utterance text is fed in directly through :class:`SimulateUtterance`, so STT is absent
entirely. The store is the **real** :class:`JsonlVocabularyRepository` on a ``tmp_path``, time
is a deterministic ``FakeClock``, and the governor is the **real** ``VocabularyGovernor``.

There is **no socket, no microphone, and no VoiceAttack** anywhere in this module — that is
the whole point: the learning logic lives a full layer above the wire and is proven in CI
Linux before any C# exists (RETURN_CHANNEL_PLAN.md, layer 2 / M2).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from vaivox.application.learn_from_outcome import ApplyPolicy, LearnFromOutcome
from vaivox.application.reconcile_text import ReconcileText
from vaivox.application.record_command import SimulateUtterance
from vaivox.application.usage_stamping import UsageStamper
from vaivox.domain.reconciliation.snapper import PhraseSnapper
from vaivox.domain.telemetry.model import MatchOutcome
from vaivox.domain.vocabulary.governor import VocabularyGovernor
from vaivox.domain.vocabulary.model import (
    EvictionPolicy,
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


class ScriptedCommandSink:
    """VAICOM mocked at the port: returns the scripted ``MatchOutcome`` for each send.

    Each :meth:`send` pops the next outcome from the script (``None`` = unknown once the
    script is exhausted), so a test replays an exact ``(text, MatchOutcome)`` sequence with
    no socket and no VoiceAttack.
    """

    def __init__(self, script: list[MatchOutcome | None] | None = None) -> None:
        self.sent: list[str] = []
        self._script = list(script or [])

    def queue(self, outcome: MatchOutcome | None) -> None:
        self._script.append(outcome)

    def send(self, command: str) -> MatchOutcome | None:
        self.sent.append(command)
        return self._script.pop(0) if self._script else None


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


class FakeConfig:
    """Minimal ConfigProvider for ReconcileText (no fuzzy words; let the snapper do the work)."""

    def get_word_mappings(self):
        return {}

    def get_fuzzy_words(self):
        return []


def _simulate(
    repo: JsonlVocabularyRepository,
    clock: FakeClock,
    sink: ScriptedCommandSink,
    telemetry: RecordingTelemetry,
    *,
    eviction_policies=None,
    policy: ApplyPolicy = ApplyPolicy.AUTO_APPLY,
) -> SimulateUtterance:
    """Wire the full routing path against the real repo/governor and the fakes.

    Uses :class:`SimulateUtterance` (text in directly, STT absent) so the utterance flows
    through the *same* shared ``route_command`` the PTT path uses — stamper + learner fanned
    out from one place.
    """
    governor = VocabularyGovernor()
    stamper = UsageStamper(repo, governor, clock, eviction_policies=eviction_policies)
    learner = LearnFromOutcome(repo, clock, policy=policy)
    return SimulateUtterance(
        ReconcileText(FakeConfig()),
        PhraseSnapper(_PHRASES),
        sink,
        FakeKneeboardSink(),
        telemetry,
        FakeReporter(),
        stamper,
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


# -- point 1: stamping only on a confirmed match -------------------------------------


def test_stamping_happens_only_on_matched_true(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = FakeClock()
    sink = ScriptedCommandSink()
    telemetry = RecordingTelemetry()
    seed_id = _seed_mapping(repo, clock.now())

    sim = _simulate(repo, clock, sink, telemetry)

    # 1a. matched=True -> the surviving surface form ("Texaco request rejoin") is stamped.
    sink.queue(MatchOutcome(matched=True, resolved_command="Texaco request rejoin"))
    sim.execute("Texaco request rejoin")
    usage = _usage(repo, VocabularyKind.WORD_MAPPING, seed_id)
    assert usage is not None
    assert usage.hits == 1
    assert usage.last_used == _START

    # 1b. matched=False -> a near-miss, NOT a credit: hits/last_used do not move.
    clock.advance(timedelta(hours=1))
    sink.queue(MatchOutcome(matched=False))
    sim.execute("Texaco request rejoin")
    usage = _usage(repo, VocabularyKind.WORD_MAPPING, seed_id)
    assert usage is not None
    assert usage.hits == 1  # unchanged
    assert usage.last_used == _START  # unchanged

    # 1c. None (unknown) -> also no credit (distinct from matched=False; neither stamps).
    clock.advance(timedelta(hours=1))
    sink.queue(None)
    sim.execute("Texaco request rejoin")
    usage = _usage(repo, VocabularyKind.WORD_MAPPING, seed_id)
    assert usage is not None
    assert usage.hits == 1


# -- point 2: near-miss -> LEARNED entry (auto-apply) --------------------------------


def test_near_miss_creates_learned_entry(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = FakeClock()
    sink = ScriptedCommandSink()
    telemetry = RecordingTelemetry()

    sim = _simulate(repo, clock, sink, telemetry, policy=ApplyPolicy.AUTO_APPLY)

    # An utterance close to "Texaco request rejoin" that VoiceAttack reports as not matched.
    sink.queue(MatchOutcome(matched=False))
    sim.execute("texaco request rejon")

    learned = [
        governed
        for governed in repo.load(VocabularyKind.WORD_MAPPING)
        if governed.entry.origin is VocabularyOrigin.LEARNED
    ]
    assert len(learned) == 1
    entry = learned[0].entry
    assert entry.term == "Texaco request rejoin"  # nearest valid phrase = replacement
    assert "texaco request rejon" in entry.aliases  # spoken near-miss = alias
    # Seeded recency = creation time, so the grace window can protect it (point 4).
    assert learned[0].usage.last_used == _START


def test_propose_only_writes_nothing(tmp_path) -> None:
    # The default policy is human-in-the-loop: a near-miss is proposed but never written.
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = FakeClock()
    sink = ScriptedCommandSink()
    telemetry = RecordingTelemetry()

    sim = _simulate(repo, clock, sink, telemetry, policy=ApplyPolicy.PROPOSE_ONLY)

    sink.queue(MatchOutcome(matched=False))
    sim.execute("texaco request rejon")

    assert repo.load(VocabularyKind.WORD_MAPPING) == []  # nothing written


# -- point 3 + 4: eviction (LRU, DEFAULT protected, grace window) --------------------


def test_eviction_drops_least_recently_used_learned_protecting_defaults(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = FakeClock()
    sink = ScriptedCommandSink()
    telemetry = RecordingTelemetry()

    # A protected DEFAULT seed plus two LEARNED entries at different recencies.
    repo.add(
        VocabularyEntry(
            id="seed",
            kind=VocabularyKind.WORD_MAPPING,
            term="Magic declare bogey dope",
            origin=VocabularyOrigin.DEFAULT,
        ),
        clock.now(),
    )
    repo.add(
        VocabularyEntry(
            id="learned-old",
            kind=VocabularyKind.WORD_MAPPING,
            term="Texaco request fuel",
            aliases=("texaco fuel",),
            origin=VocabularyOrigin.LEARNED,
        ),
        clock.now(),
    )
    clock.advance(timedelta(days=10))
    repo.add(
        VocabularyEntry(
            id="learned-new",
            kind=VocabularyKind.WORD_MAPPING,
            term="Texaco request rejoin",
            aliases=("texaco rejoin",),
            origin=VocabularyOrigin.LEARNED,
        ),
        clock.now(),
    )

    # A cap of 2 with a grace window; advance well past the grace so both learned entries
    # are evictable on age, but the cap only forces one eviction.
    policy = EvictionPolicy(max_entries=2, grace_window=timedelta(days=2))
    policies = dict.fromkeys(VocabularyKind, policy)
    clock.advance(timedelta(days=30))

    # A matched dispatch that credits nothing (no surface overlap) just to drive the LRU pass.
    sim = _simulate(repo, clock, sink, telemetry, eviction_policies=policies)
    sink.queue(MatchOutcome(matched=True, resolved_command="unrelated"))
    sim.execute("unrelated text")

    ids = {governed.id for governed in repo.load(VocabularyKind.WORD_MAPPING)}
    assert "seed" in ids  # DEFAULT protected regardless of recency
    assert "learned-new" in ids  # most-recently-used learned entry kept
    assert "learned-old" not in ids  # least-recently-used learned entry evicted


def test_grace_window_protects_a_fresh_learned_entry(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = FakeClock()
    sink = ScriptedCommandSink()
    telemetry = RecordingTelemetry()

    # Two learned entries over a cap of 1, but BOTH were just added (inside the grace window),
    # so neither is evictable yet — the fresh entry is protected.
    repo.add(
        VocabularyEntry(
            id="learned-a",
            kind=VocabularyKind.WORD_MAPPING,
            term="Texaco request fuel",
            origin=VocabularyOrigin.LEARNED,
        ),
        clock.now(),
    )
    repo.add(
        VocabularyEntry(
            id="learned-b",
            kind=VocabularyKind.WORD_MAPPING,
            term="Texaco request rejoin",
            origin=VocabularyOrigin.LEARNED,
        ),
        clock.now(),
    )

    policy = EvictionPolicy(max_entries=1, grace_window=timedelta(days=7))
    policies = dict.fromkeys(VocabularyKind, policy)

    # Only one hour later: both entries are still inside the 7-day grace window.
    clock.advance(timedelta(hours=1))
    sim = _simulate(repo, clock, sink, telemetry, eviction_policies=policies)
    sink.queue(MatchOutcome(matched=True, resolved_command="unrelated"))
    sim.execute("unrelated text")

    ids = {governed.id for governed in repo.load(VocabularyKind.WORD_MAPPING)}
    assert ids == {"learned-a", "learned-b"}  # grace window protected both, cap notwithstanding


# -- point 5: abstain recorded in telemetry ------------------------------------------


def test_abstain_is_recorded_in_telemetry(tmp_path) -> None:
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = FakeClock()
    sink = ScriptedCommandSink()
    telemetry = RecordingTelemetry()

    sim = _simulate(repo, clock, sink, telemetry, policy=ApplyPolicy.PROPOSE_ONLY)

    # A near-miss the snapper abstains on (close, but below the snap-high band): telemetry
    # records the abstain decision with the near-miss candidates and the match outcome.
    sink.queue(MatchOutcome(matched=False))
    sim.execute("texaco rejon")

    assert len(telemetry.outcomes) == 1
    outcome = telemetry.outcomes[0]
    assert outcome.destination == "voiceattack"
    assert outcome.snap is not None
    assert outcome.snap.decision == "abstained"
    assert outcome.snap.near_misses  # the abstain-band candidates were recorded
    assert outcome.match == MatchOutcome(matched=False)


# -- the full loop, in one replay ----------------------------------------------------


def test_full_loop_replay(tmp_path) -> None:
    """One replay covering stamping-on-match, learning-on-near-miss, and eviction together."""
    repo = JsonlVocabularyRepository(str(tmp_path))
    clock = FakeClock()
    sink = ScriptedCommandSink()
    telemetry = RecordingTelemetry()
    seed_id = _seed_mapping(repo, clock.now())  # DEFAULT, protected

    policy = EvictionPolicy(max_entries=2, grace_window=timedelta(days=1))
    policies = dict.fromkeys(VocabularyKind, policy)
    sim = _simulate(repo, clock, sink, telemetry, eviction_policies=policies)

    # 1) A confirmed match stamps the seed (the alias surface form survives into sent text).
    sink.queue(MatchOutcome(matched=True, resolved_command="Texaco request rejoin"))
    sim.execute("texaco rejoin")
    assert _usage(repo, VocabularyKind.WORD_MAPPING, seed_id).hits == 1

    # 2) A near-miss is learned as a LEARNED entry (auto-apply, default policy here).
    #    (advance time so each learned entry has a distinct recency for the LRU order)
    clock.advance(timedelta(days=2))
    sink.queue(MatchOutcome(matched=False))
    sim.execute("texaco request fuell")  # close to "Texaco request fuel"
    learned_after_one = [
        g.id for g in repo.load(VocabularyKind.WORD_MAPPING) if g.entry.is_evictable
    ]
    assert len(learned_after_one) == 1

    # 3) Another near-miss learns a second LEARNED entry, taking us over the cap of 2 (1 seed +
    #    2 learned = 3). The grace window has passed for the first learned entry, so the LRU
    #    pass on this matched dispatch evicts the least-recently-used learned entry, never the
    #    DEFAULT seed.
    clock.advance(timedelta(days=5))
    sink.queue(MatchOutcome(matched=False))
    sim.execute("magic declare bogey dopee")  # close to "Magic declare bogey dope"

    clock.advance(timedelta(days=5))
    sink.queue(MatchOutcome(matched=True, resolved_command="Texaco request rejoin"))
    sim.execute("texaco rejoin")  # a matched dispatch -> drives the eviction pass

    governed = repo.load(VocabularyKind.WORD_MAPPING)
    ids = {g.id for g in governed}
    assert seed_id in ids  # DEFAULT never evicted
    learned_ids = [g.id for g in governed if g.entry.is_evictable]
    assert len(learned_ids) == 1  # over the cap of 2 -> one learned entry evicted
