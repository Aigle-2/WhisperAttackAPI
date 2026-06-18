"""The vocabulary governance domain service (ADR-0004, Axis A).

:class:`VocabularyGovernor` is a pure domain service (no I/O) with two jobs:

1. **LRU governance** — cap each vocabulary at ``max_entries`` and evict the
   least-recently-used entries when over cap, protecting ``DEFAULT`` entries and any
   entry still inside its grace window (ADR-0004 §2-3).
2. **Tier 1 attribution** — decide *which* entries earned the usage credit for a
   matched utterance via token provenance: an edit is credited iff one of its output
   tokens survives into the final matched text (ADR-0004 "Attribution").

The governor never touches disk or the clock; ``now`` is passed in so eviction is
deterministic and testable. Persisting the result (``mark_used`` / writing the kept
set) is the caller's job through the :class:`~vaivox.application.ports.VocabularyRepository`
port. Tier 2 counterfactual attribution is intentionally deferred (see
:meth:`VocabularyGovernor.attribute_tier1`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

from vaivox.domain.vocabulary.model import (
    EvictionPolicy,
    EvictionResult,
    GovernedEntry,
)


class VocabularyGovernor:
    """Pure governance: LRU eviction and Tier 1 usage attribution.

    The service is stateless; every method takes the data it needs so it can be
    exercised with zero I/O (Cockburn's test, ADR-0001).
    """

    def rank(self, entries: Iterable[GovernedEntry]) -> list[GovernedEntry]:
        """Order entries most-useful-first (recency, then frequency, then id).

        The ranking is the basis for both retention and eviction: the head is kept,
        the evictable tail is dropped. ``DEFAULT`` entries are *not* given priority
        here — protection is applied during :meth:`govern`, not by reordering — so the
        ranking stays a stable, total order independent of origin.

        Args:
            entries: The governed entries to order.

        Returns:
            A new list sorted by descending ``last_used``, then descending ``hits``,
            then ascending ``id`` (a deterministic tie-break).
        """
        return sorted(
            entries,
            key=lambda governed: (
                governed.usage.last_used,
                governed.usage.hits,
                _negate_id_sort(governed.id),
            ),
            reverse=True,
        )

    def govern(
        self,
        entries: Iterable[GovernedEntry],
        policy: EvictionPolicy,
        now: datetime,
    ) -> EvictionResult:
        """Apply the cap and evict least-recently-used evictable entries.

        Eviction rules (ADR-0004 §2-3):

        - With no ``max_entries`` cap, nothing is evicted.
        - ``DEFAULT`` entries are never evicted and never count against the cap's
          eviction pressure beyond occupying a slot.
        - An entry inside its grace window (``now - last_used < grace_window``) is
          never evicted, however stale its recency rank.
        - Otherwise, the least-recently-used *evictable, out-of-grace* entries are
          dropped until the total is within the cap.

        Args:
            entries: The governed entries for one vocabulary kind.
            policy: The cap and grace window for that kind.
            now: The current time, used to evaluate the grace window.

        Returns:
            An :class:`EvictionResult` with the kept entries (ranking order) and the
            evicted entries.
        """
        ranked = self.rank(entries)
        if policy.max_entries is None or len(ranked) <= policy.max_entries:
            return EvictionResult(kept=tuple(ranked), evicted=())

        overflow = len(ranked) - policy.max_entries
        evicted: list[GovernedEntry] = []

        # Walk least-recently-used first (ranked is most-useful-first), evicting only
        # entries that are both evictable and outside the grace window.
        for governed in reversed(ranked):
            if overflow <= 0:
                break
            if not governed.is_evictable:
                continue
            if self._in_grace(governed, policy, now):
                continue
            evicted.append(governed)
            overflow -= 1

        evicted_ids = {governed.id for governed in evicted}
        kept = tuple(governed for governed in ranked if governed.id not in evicted_ids)
        return EvictionResult(kept=kept, evicted=tuple(evicted))

    def attribute_tier1(
        self,
        matched_tokens: Iterable[str],
        edit_output_tokens: Mapping[str, Sequence[str]],
    ) -> tuple[str, ...]:
        """Credit the entries whose edits survived into the matched text (Tier 1).

        Token provenance, per ADR-0004: each reconciliation step records, for every
        edit it applied, the tokens that edit produced (``edit_id -> output tokens``).
        An edit is credited iff at least one of its output tokens appears in the final
        matched utterance — a deterministic, single-pass, oracle-free *but-for* proxy.

        Comparison is case-insensitive on whitespace-stripped tokens, matching how the
        reconciliation pipeline normalizes surface forms.

        Args:
            matched_tokens: The tokens of the final matched text (the sent command that
                VoiceAttack accepted).
            edit_output_tokens: For each contributing edit's id, the tokens that edit
                produced earlier in the pipeline.

        Returns:
            The ids of the credited edits, in the iteration order of
            ``edit_output_tokens`` (deterministic for an ordered mapping), de-duplicated.
        """
        surviving = {_norm(token) for token in matched_tokens}
        surviving.discard("")
        credited: list[str] = []
        for edit_id, output_tokens in edit_output_tokens.items():
            if any(_norm(token) in surviving for token in output_tokens):
                credited.append(edit_id)
        return tuple(credited)

    @staticmethod
    def _in_grace(governed: GovernedEntry, policy: EvictionPolicy, now: datetime) -> bool:
        """Whether ``governed`` is still inside the policy's grace window."""
        if policy.grace_window is None:
            return False
        return (now - governed.usage.last_used) < policy.grace_window


def _norm(token: str) -> str:
    """Normalize a token for provenance comparison (strip + casefold)."""
    return token.strip().casefold()


def _negate_id_sort(entry_id: str) -> tuple[int, ...]:
    """Map an id to a key that sorts ascending under the outer ``reverse=True``.

    The outer ``sorted`` runs with ``reverse=True`` so recency/frequency sort
    descending; the id tie-break must still sort *ascending*. Negating each code point
    inverts the order, cancelling the outer reversal so equal-recency entries come out
    in plain ascending id order.
    """
    return tuple(-ord(char) for char in entry_id)
