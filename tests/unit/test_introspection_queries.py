"""Unit tests for the read-only introspection query use cases (ADR-0010).

Exercises the recent-events, live-metrics, and vocabulary queries through in-memory
fakes for the ``TelemetryReader`` and ``VocabularyRepository`` ports — no I/O — pinning
the band derivation, ordering, and grouping behaviour.
"""

from __future__ import annotations

from datetime import datetime

from vaivox.application.queries import (
    ComputeMetrics,
    DescribeVocabulary,
    DryRunReconcile,
    ListRecentReconciliations,
)
from vaivox.domain.commands.model import CommandSurface, VaicomF10Action
from vaivox.domain.commands.resolver import CommandSurfaceResolver
from vaivox.domain.telemetry.model import MatchOutcome, ReconciliationOutcome, SnapSummary
from vaivox.domain.vocabulary.model import (
    GovernedEntry,
    UsageStats,
    VocabularyEntry,
    VocabularyKind,
    VocabularyOrigin,
)


def _outcome(raw="x", sent="x", matched=None, resolved=None, snap_decision=None):
    match = None if matched is None else MatchOutcome(matched=matched, resolved_command=resolved)
    snap = None if snap_decision is None else SnapSummary(decision=snap_decision)
    return ReconciliationOutcome(
        raw_text=raw,
        cleaned_text=raw,
        command_text=raw,
        sent_text=sent,
        destination="voiceattack",
        match=match,
        snap=snap,
    )


class FakeTelemetryReader:
    def __init__(self, outcomes=None):
        self._outcomes = outcomes or []
        self.requested_limit = None

    def recent(self, limit):
        self.requested_limit = limit
        if limit <= 0:
            return []
        return list(self._outcomes[-limit:])


class FakeVocabularyRepository:
    def __init__(self, entries=None):
        self._entries = entries or {}

    def load(self, kind):
        return list(self._entries.get(kind, []))


class FakeReconciliationVocabulary:
    def get_word_mappings(self):
        return {}

    def get_fuzzy_words(self):
        return []


def _governed(entry_id, kind, term, hits, last_used, origin=VocabularyOrigin.DEFAULT, aliases=()):
    return GovernedEntry(
        entry=VocabularyEntry(id=entry_id, kind=kind, term=term, aliases=aliases, origin=origin),
        usage=UsageStats(last_used=last_used, hits=hits),
    )


def test_dry_run_adds_surface_alias_path_and_reason_diagnostics():
    surface = CommandSurface(
        id="mission_f10:engine",
        label="Request Engine Start",
        aliases=("Action Request Engine Start",),
        semantic_aliases=("Request To Start Engines",),
        source="mission_f10",
        scope="mission",
        dispatch_target=VaicomF10Action(
            "Action Request Engine Start",
            "Request Engine Start",
            action_index=4,
            menu_path=("AI ATC", "Ground"),
        ),
    )
    query = DryRunReconcile(FakeReconciliationVocabulary(), CommandSurfaceResolver([surface]))

    result = query.execute("Ground Uzi 61 request to start engines")

    assert result.resolution is not None
    assert result.resolution.decision == "resolved"
    assert result.resolution.matched_alias == "Request To Start Engines"
    assert result.resolution.menu_path == ("AI ATC", "Ground")


# -- ListRecentReconciliations --------------------------------------------------------


def test_recent_reconciliations_returns_events_and_count():
    reader = FakeTelemetryReader([_outcome(raw="a"), _outcome(raw="b")])

    report = ListRecentReconciliations(reader).execute(limit=5)

    assert report.limit == 5
    assert report.count == 2
    assert [event.raw_text for event in report.events] == ["a", "b"]
    assert reader.requested_limit == 5


def test_recent_reconciliations_uses_default_limit():
    reader = FakeTelemetryReader([])

    report = ListRecentReconciliations(reader).execute()

    assert report.count == 0
    assert report.events == ()
    assert reader.requested_limit == 20


# -- ComputeMetrics -------------------------------------------------------------------


def test_metrics_empty_telemetry_is_all_zero():
    metrics = ComputeMetrics(FakeTelemetryReader([])).execute()

    assert metrics.total == 0
    assert metrics.match_rate == 0.0
    assert metrics.match == metrics.wrong_match == metrics.not_found == 0


def test_metrics_classifies_each_band():
    # The match band (match/wrong/not_found/unknown) and the abstain band are independent
    # dimensions: the abstained event below also has no reported match, so it is counted
    # in both ``abstain`` and ``unknown``.
    reader = FakeTelemetryReader(
        [
            _outcome(sent="alpha", matched=True, resolved="alpha"),  # true match
            _outcome(sent="bravo", matched=True, resolved="charlie"),  # wrong match
            _outcome(sent="delta", matched=False),  # not found
            _outcome(sent="echo"),  # unknown (no return channel)
            _outcome(sent="foxtrot", snap_decision="abstained"),  # abstain (+ unknown)
        ]
    )

    metrics = ComputeMetrics(reader).execute()

    assert metrics.total == 5
    assert metrics.match == 1
    assert metrics.wrong_match == 1
    assert metrics.not_found == 1
    assert metrics.unknown == 2  # the bare event + the abstained one (no match reported)
    assert metrics.abstain == 1
    assert metrics.match_rate == 0.2
    assert metrics.wrong_match_rate == 0.2


def test_metrics_matched_without_resolved_command_is_trusted_as_match():
    # No return channel for the resolved command -> a positive match is a true match.
    reader = FakeTelemetryReader([_outcome(sent="alpha", matched=True, resolved=None)])

    metrics = ComputeMetrics(reader).execute()

    assert metrics.match == 1
    assert metrics.wrong_match == 0


def test_metrics_resolved_command_comparison_ignores_case_and_whitespace():
    reader = FakeTelemetryReader(
        [_outcome(sent="Texaco request rejoin", matched=True, resolved="texaco  request  rejoin")]
    )

    metrics = ComputeMetrics(reader).execute()

    assert metrics.match == 1
    assert metrics.wrong_match == 0


def test_metrics_abstain_counted_independently_of_match():
    # An abstained snap on a matched event still increments abstain.
    reader = FakeTelemetryReader(
        [_outcome(sent="alpha", matched=True, resolved="alpha", snap_decision="abstained")]
    )

    metrics = ComputeMetrics(reader).execute()

    assert metrics.match == 1
    assert metrics.abstain == 1


# -- DescribeVocabulary ---------------------------------------------------------------


def test_vocabulary_groups_all_kinds_even_when_empty():
    report = DescribeVocabulary(FakeVocabularyRepository()).execute()

    assert report.total == 0
    assert set(report.by_kind) == {kind.value for kind in VocabularyKind}
    assert all(entries == [] for entries in report.by_kind.values())


def test_vocabulary_flattens_entry_and_usage_fields():
    entry = _governed(
        "senaki",
        VocabularyKind.FUZZY_WORD,
        "Senaki",
        hits=7,
        last_used=datetime(2026, 6, 18, 12, 0, 0),
        aliases=("sen-aki",),
    )
    report = DescribeVocabulary(
        FakeVocabularyRepository({VocabularyKind.FUZZY_WORD: [entry]})
    ).execute()

    assert report.total == 1
    view = report.by_kind["fuzzy_word"][0]
    assert view.id == "senaki"
    assert view.kind == "fuzzy_word"
    assert view.term == "Senaki"
    assert view.aliases == ("sen-aki",)
    assert view.origin == "default"
    assert view.hits == 7
    assert view.last_used == "2026-06-18T12:00:00"


def test_vocabulary_orders_entries_most_recently_used_first():
    older = _governed(
        "old", VocabularyKind.FUZZY_WORD, "Old", hits=1, last_used=datetime(2026, 1, 1)
    )
    newer = _governed(
        "new", VocabularyKind.FUZZY_WORD, "New", hits=1, last_used=datetime(2026, 6, 1)
    )
    report = DescribeVocabulary(
        FakeVocabularyRepository({VocabularyKind.FUZZY_WORD: [older, newer]})
    ).execute()

    assert [view.id for view in report.by_kind["fuzzy_word"]] == ["new", "old"]
