"""Unit tests for the vocabulary usage stamper (ADR-0004 governance wiring).

Exercises Tier 1 surface attribution -> credited ids -> ``mark_used``, the
inert-by-default LRU pass, the cap-enabled eviction pass (protecting ``DEFAULT`` seeds),
and the never-fatal guarantee (a repository write failure is swallowed).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from vaivox.application.usage_stamping import UsageStamper
from vaivox.domain.vocabulary.governor import VocabularyGovernor
from vaivox.domain.vocabulary.model import (
    EvictionPolicy,
    GovernedEntry,
    UsageStats,
    VocabularyEntry,
    VocabularyKind,
    VocabularyOrigin,
)

_NOW = datetime(2026, 6, 18, 12, 0, 0)


class FakeClock:
    def __init__(self, now: datetime = _NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeRepository:
    """In-memory repository capturing mark_used / replace_entries, keyed by kind."""

    def __init__(
        self,
        entries_by_kind: dict[VocabularyKind, list[GovernedEntry]] | None = None,
        *,
        fail_on_mark: bool = False,
    ) -> None:
        self._entries: dict[VocabularyKind, list[GovernedEntry]] = {
            kind: [] for kind in VocabularyKind
        }
        if entries_by_kind:
            self._entries.update(entries_by_kind)
        self._fail_on_mark = fail_on_mark
        self.marked: list[tuple[tuple[str, ...], datetime]] = []
        self.replaced: list[tuple[VocabularyKind, tuple[str, ...]]] = []

    def load(self, kind: VocabularyKind) -> list[GovernedEntry]:
        return list(self._entries[kind])

    def mark_used(self, ids, when) -> None:
        if self._fail_on_mark:
            raise OSError("disk full")
        self.marked.append((tuple(ids), when))

    def add(self, entry, when) -> None:  # pragma: no cover - unused here
        raise NotImplementedError

    def replace_entries(self, kind, kept) -> None:
        self.replaced.append((kind, tuple(g.id for g in kept)))
        self._entries[kind] = list(kept)


def _governed(
    entry_id: str,
    *,
    kind: VocabularyKind,
    term: str,
    aliases: tuple[str, ...] = (),
    last_used: datetime = _NOW,
    hits: int = 0,
    origin: VocabularyOrigin = VocabularyOrigin.LEARNED,
) -> GovernedEntry:
    return GovernedEntry(
        entry=VocabularyEntry(id=entry_id, kind=kind, term=term, aliases=aliases, origin=origin),
        usage=UsageStats(last_used=last_used, hits=hits),
    )


def _fuzzy(entry_id: str, *, term: str | None = None, **kwargs) -> GovernedEntry:
    """A ``FUZZY_WORD`` governed entry; ``term`` defaults to a title-cased ``entry_id``."""
    return _governed(entry_id, kind=VocabularyKind.FUZZY_WORD, term=term or entry_id, **kwargs)


def _stamper(repo: FakeRepository, **kwargs) -> UsageStamper:
    return UsageStamper(repo, VocabularyGovernor(), FakeClock(), **kwargs)


# -- stamping (Tier 1 surface attribution) -------------------------------------------


def test_stamps_entries_whose_surface_survives_in_sent_text() -> None:
    repo = FakeRepository(
        {
            VocabularyKind.FUZZY_WORD: [
                _governed("kobuleti", kind=VocabularyKind.FUZZY_WORD, term="Kobuleti"),
                _governed("senaki", kind=VocabularyKind.FUZZY_WORD, term="Senaki"),
            ]
        }
    )

    _stamper(repo).stamp("Kobuleti tower")

    # Only the surviving surface form ("Kobuleti") is credited; "Senaki" is not.
    assert repo.marked == [(("kobuleti",), _NOW)]


def test_stamp_matches_aliases_not_just_term() -> None:
    repo = FakeRepository(
        {
            VocabularyKind.WORD_MAPPING: [
                _governed(
                    "rejoin",
                    kind=VocabularyKind.WORD_MAPPING,
                    term="rejoin",
                    aliases=("rejon", "re-join"),
                )
            ]
        }
    )

    # The dispatched text contains an alias token; the entry is still credited.
    _stamper(repo).stamp("texaco rejon now")

    assert repo.marked == [(("rejoin",), _NOW)]


def test_stamp_is_case_insensitive() -> None:
    repo = FakeRepository({VocabularyKind.FUZZY_WORD: [_fuzzy("krymsk", term="Krymsk")]})

    _stamper(repo).stamp("krymsk inbound")

    assert repo.marked == [(("krymsk",), _NOW)]


def test_stamp_credits_multiword_term_on_any_surviving_token() -> None:
    repo = FakeRepository(
        {
            VocabularyKind.WORD_MAPPING: [
                _governed("bogeydope", kind=VocabularyKind.WORD_MAPPING, term="bogey dope")
            ]
        }
    )

    # Only one token of the multi-word term survives; the entry is still credited.
    _stamper(repo).stamp("request bogey")

    assert repo.marked == [(("bogeydope",), _NOW)]


def test_no_surviving_surface_marks_nothing() -> None:
    repo = FakeRepository({VocabularyKind.FUZZY_WORD: [_fuzzy("kobuleti", term="Kobuleti")]})

    _stamper(repo).stamp("texaco request fuel")

    assert repo.marked == []


def test_empty_repository_marks_nothing() -> None:
    repo = FakeRepository()

    _stamper(repo).stamp("anything at all")

    assert repo.marked == []


def test_stamp_spans_multiple_kinds() -> None:
    repo = FakeRepository(
        {
            VocabularyKind.FUZZY_WORD: [
                _governed("texaco", kind=VocabularyKind.FUZZY_WORD, term="Texaco")
            ],
            VocabularyKind.WORD_MAPPING: [
                _governed("rejoin", kind=VocabularyKind.WORD_MAPPING, term="rejoin")
            ],
        }
    )

    _stamper(repo).stamp("Texaco rejoin")

    assert len(repo.marked) == 1
    credited, when = repo.marked[0]
    assert set(credited) == {"texaco", "rejoin"}
    assert when == _NOW


# -- never fatal ---------------------------------------------------------------------


def test_repository_failure_is_swallowed() -> None:
    repo = FakeRepository(
        {VocabularyKind.FUZZY_WORD: [_fuzzy("kobuleti", term="Kobuleti")]},
        fail_on_mark=True,
    )

    # Must not raise — stamping is best-effort and never breaks dispatch.
    _stamper(repo).stamp("Kobuleti tower")

    assert repo.marked == []


# -- LRU pass (inert by default) -----------------------------------------------------


def test_no_policy_never_evicts() -> None:
    # Five learned entries, no eviction policy: the LRU pass is inert.
    entries = [_fuzzy(f"e{i}", last_used=_NOW - timedelta(days=i)) for i in range(5)]
    repo = FakeRepository({VocabularyKind.FUZZY_WORD: entries})

    _stamper(repo).stamp("e0")

    assert repo.replaced == []  # nothing rewritten -> nothing evicted


def test_uncapped_policy_is_explicitly_inert() -> None:
    # An explicit policy with no cap (max_entries=None) is the same as no policy: the pass
    # short-circuits before touching the repository.
    entries = [_fuzzy(f"e{i}", last_used=_NOW - timedelta(days=i)) for i in range(5)]
    repo = FakeRepository({VocabularyKind.FUZZY_WORD: entries})
    policies = dict.fromkeys(VocabularyKind, EvictionPolicy(max_entries=None))

    _stamper(repo, eviction_policies=policies).stamp("e0")

    assert repo.replaced == []


def test_cap_evicts_least_recently_used_learned_entry() -> None:
    fresh = _fuzzy("fresh", last_used=_NOW)
    stale = _fuzzy("stale", last_used=_NOW - timedelta(days=30))
    repo = FakeRepository({VocabularyKind.FUZZY_WORD: [fresh, stale]})
    policy = EvictionPolicy(max_entries=1)
    policies = dict.fromkeys(VocabularyKind, policy)

    _stamper(repo, eviction_policies=policies).stamp("nothing matches")

    assert len(repo.replaced) == 1
    kind, kept_ids = repo.replaced[0]
    assert kind is VocabularyKind.FUZZY_WORD
    assert kept_ids == ("fresh",)  # stale learned entry evicted under the cap


def test_cap_never_evicts_default_seeds() -> None:
    seed = _fuzzy("seed", last_used=_NOW - timedelta(days=100), origin=VocabularyOrigin.DEFAULT)
    other_seed = _fuzzy(
        "seed2", last_used=_NOW - timedelta(days=200), origin=VocabularyOrigin.DEFAULT
    )
    repo = FakeRepository({VocabularyKind.FUZZY_WORD: [seed, other_seed]})
    policy = EvictionPolicy(max_entries=1)
    policies = dict.fromkeys(VocabularyKind, policy)

    _stamper(repo, eviction_policies=policies).stamp("nothing matches")

    # Both are DEFAULT and protected; the over-cap pass evicts nobody -> no rewrite.
    assert repo.replaced == []
