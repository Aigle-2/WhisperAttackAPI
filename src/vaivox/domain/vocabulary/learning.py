"""Pure proposal derivation for the vocabulary learning loop (ADR-0006).

When VoiceAttack does **not** match a dispatched command (or the phrase snapper abstained
on it), the utterance was *close to* a valid command but missed. That near-miss is the
learning signal: the spoken surface form should resolve to the nearest valid phrase. This
module turns one such observation into a structured *proposal* — a suggested word-mapping
alias whose replacement is the nearest valid phrase.

It is a **pure domain function** (ADR-0001): no I/O, no clock, no repository. It only shapes
a :class:`LearnedProposal`; deciding whether to *write* it (propose-only vs auto-apply) and
*when* (the clock) is the application's job — see
:class:`~vaivox.application.learn_from_outcome.LearnFromOutcome`. Keeping derivation pure is
what lets the whole learning loop be proven in memory, with no socket and no VoiceAttack.

The proposal models the near-miss as a ``WORD_MAPPING`` entry: ``term`` is the nearest valid
phrase (the canonical replacement) and ``aliases`` carries the spoken utterance, so a future
utterance of the same misheard surface form is corrected toward the valid command. Only
``LEARNED`` entries are ever proposed — they alone are evictable (the seed vocabulary is
never touched).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from vaivox.domain.vocabulary.model import (
    VocabularyEntry,
    VocabularyKind,
    VocabularyOrigin,
)


@dataclass(frozen=True)
class LearnedProposal:
    """A suggested vocabulary edit derived from one near-miss (ADR-0006).

    The output of :func:`propose_from_near_miss`. It is a plain value object: the
    application either records it for human review (propose-only, the default) or writes it
    as a ``LEARNED`` entry (auto-apply). It carries enough provenance to be logged and shown.

    Attributes:
        utterance: The spoken/reconciled text that failed to match — the proposed alias.
        nearest_phrase: The closest valid command phrase — the proposed replacement (``term``).
        score: The similarity (0-100) of ``utterance`` to ``nearest_phrase`` (the near-miss
            score that motivated the proposal), for ranking/observability.
        entry: The concrete ``LEARNED`` :class:`VocabularyEntry` to add on auto-apply.
    """

    utterance: str
    nearest_phrase: str
    score: float
    entry: VocabularyEntry


def propose_from_near_miss(
    utterance: str,
    candidates: Sequence[tuple[str, float]],
    *,
    existing_ids: frozenset[str] = frozenset(),
) -> LearnedProposal | None:
    """Derive a learned word-mapping proposal from a near-miss, or ``None`` (pure).

    The single deterministic rule: map the (normalized) ``utterance`` surface form to the
    best-scoring valid candidate phrase as a ``LEARNED`` ``WORD_MAPPING`` (``term`` =
    candidate, ``aliases`` = the utterance). No proposal is made when there is no signal to
    learn from — a blank utterance, no candidates, or an utterance that already *is* the best
    candidate (nothing to correct toward).

    The function is pure and total: same inputs, same output; it never touches disk, the
    clock, or a repository. ``existing_ids`` only steers the generated id away from a
    collision; it does not gate the proposal.

    Args:
        utterance: The reconciled command text that VoiceAttack did not match (or that the
            snapper abstained on).
        candidates: The nearest valid phrases as ``(phrase, score)`` pairs, best first (the
            snapper's near-misses, or any phrase index lookup). Only the best is used.
        existing_ids: Ids already present in the ``WORD_MAPPING`` store, so the proposal's id
            avoids a collision (a ``-N`` suffix is appended when needed).

    Returns:
        A :class:`LearnedProposal`, or ``None`` when there is nothing to learn (blank
        utterance, no candidates, or the utterance already equals the best candidate).
    """
    spoken = utterance.strip()
    if not spoken or not candidates:
        return None

    nearest_phrase, score = candidates[0]
    nearest_phrase = nearest_phrase.strip()
    if not nearest_phrase or _normalize(spoken) == _normalize(nearest_phrase):
        return None

    entry = VocabularyEntry(
        id=_unique_id(_slug(nearest_phrase), existing_ids),
        kind=VocabularyKind.WORD_MAPPING,
        term=nearest_phrase,
        aliases=(spoken,),
        origin=VocabularyOrigin.LEARNED,
    )
    return LearnedProposal(
        utterance=spoken,
        nearest_phrase=nearest_phrase,
        score=score,
        entry=entry,
    )


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace (mirrors the snapper/oracle normalization)."""
    return " ".join(text.lower().split())


def _slug(text: str) -> str:
    """Slugify ``text`` into a stable id fragment (matches the migration / AddWordMapping)."""
    slug = "".join(char if char.isalnum() else "-" for char in text.strip().lower())
    slug = "-".join(part for part in slug.split("-") if part)
    return f"learned-{slug}" if slug else "learned-entry"


def _unique_id(base: str, seen: frozenset[str]) -> str:
    """Return ``base`` (or a ``base-N`` suffix) not already in ``seen``."""
    candidate = base
    counter = 2
    while candidate in seen:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate
