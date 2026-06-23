"""Use case: learn vocabulary from a dispatch's match outcome (ADR-0006).

This is the learning half of the return-channel loop. After a command is dispatched and
VoiceAttack reports back through the :class:`~vaivox.application.ports.CommandSink` port,
this use case turns a **near-miss** — VoiceAttack did not match, or the phrase snapper
abstained — into a *proposal* to map the spoken surface form onto the nearest valid command.

It is driven entirely by ports (``VocabularyRepository`` + ``Clock``) and a pure domain
function (:func:`~vaivox.domain.vocabulary.learning.propose_from_near_miss`), so the whole
loop is provable in memory with no socket and no VoiceAttack (ADR-0006 AC2). The adapter
contributes nothing but the scripted :class:`~vaivox.domain.telemetry.model.MatchOutcome`.

**Apply policy (human-in-the-loop by default).** ADR-0006 keeps a human in the loop: the
default policy is :attr:`ApplyPolicy.PROPOSE_ONLY` — the proposal is returned and logged,
**nothing is written**. :attr:`ApplyPolicy.AUTO_APPLY` writes the proposal as a ``LEARNED``
entry through the repository (governance then governs/evicts it like any learned entry). The
policy is a constructor flag wired from config (``vocab_auto_learn``, default off); tests
flip it to exercise the write path.

**Match semantics.** Three outcomes from the sink mean three things here:

- ``MatchOutcome(matched=True)`` — matched; **no learning** (nothing to correct).
- ``MatchOutcome(matched=False)`` — not matched; a learnable near-miss (if the snap gave
  candidates).
- ``None`` — unknown (best-effort: no/garbled reply); **no learning** (no signal).

A snap *abstain* is also a learnable near-miss on its own (the snapper already found
close-but-not-confident candidates), so learning fires when the outcome is ``matched=False``
**or** the snap abstained — provided there are candidate phrases to learn toward.
"""

from __future__ import annotations

import logging
from enum import Enum

from vaivox.application.ports import Clock, VocabularyRepository
from vaivox.domain.reconciliation.model import ReconciliationResult
from vaivox.domain.reconciliation.snapper import SnapDecision, SnapResult
from vaivox.domain.telemetry.model import MatchOutcome
from vaivox.domain.vocabulary.learning import LearnedProposal, propose_from_near_miss
from vaivox.domain.vocabulary.model import VocabularyKind

_LOGGER = logging.getLogger(__name__)


class ApplyPolicy(Enum):
    """Whether a learning proposal is only recorded or actually written (ADR-0006).

    Attributes:
        PROPOSE_ONLY: Human-in-the-loop (the default). The proposal is returned and logged;
            nothing is written to the repository.
        AUTO_APPLY: Write the proposal as a ``LEARNED`` entry via the repository.
    """

    PROPOSE_ONLY = "propose_only"
    AUTO_APPLY = "auto_apply"


class LearnFromOutcome:
    """Derive (and optionally apply) a learned vocabulary entry from a dispatch outcome.

    Called on the shared routing path (VoiceAttack branch only) after the command is sent
    and its :class:`MatchOutcome` is known. It is best-effort and never fatal to dispatch:
    any failure is logged and swallowed (mirroring :class:`~vaivox.application.usage_stamping.\
UsageStamper`), so a learning hiccup can never break a command.
    """

    def __init__(
        self,
        repository: VocabularyRepository,
        clock: Clock,
        *,
        policy: ApplyPolicy = ApplyPolicy.PROPOSE_ONLY,
    ) -> None:
        """Wire the repository, the clock, and the apply policy.

        Args:
            repository: The vocabulary repository a ``LEARNED`` entry is written through on
                auto-apply (and read for id-collision avoidance).
            clock: The clock supplying the new entry's seed ``last_used`` (grace window).
            policy: Propose-only (default, human-in-the-loop) or auto-apply.
        """
        self._repository = repository
        self._clock = clock
        self._policy = policy

    def execute(
        self,
        result: ReconciliationResult,
        snap: SnapResult | None,
        match: MatchOutcome | None,
    ) -> LearnedProposal | None:
        """Learn from one dispatch outcome, returning the proposal (or ``None``).

        Args:
            result: The reconciliation result that was dispatched (its ``command_text`` is the
                spoken surface form learned as an alias).
            snap: The phrase-snap result for the dispatched command, or ``None`` (no snapper /
                kneeboard path). Its near-misses are the candidate valid phrases.
            match: The VoiceAttack match outcome from the sink, or ``None`` (unknown).

        Returns:
            The :class:`LearnedProposal` derived from the near-miss (whether or not it was
            applied), or ``None`` when there is nothing to learn (matched, unknown, no snap
            candidates, or no usable proposal).
        """
        try:
            return self._learn(result, snap, match)
        except Exception as error:  # never fatal to dispatch (parity with the stamper)
            _LOGGER.warning("Vocabulary learning failed (dispatch unaffected): %s", error)
            return None

    def _learn(
        self,
        result: ReconciliationResult,
        snap: SnapResult | None,
        match: MatchOutcome | None,
    ) -> LearnedProposal | None:
        """Do the proposal derivation + optional apply (guarded by :meth:`execute`)."""
        if not self._is_near_miss(snap, match):
            return None
        candidates = _candidate_phrases(snap)
        if not candidates:
            # No candidate valid phrases to learn toward (e.g. an empty phrase index).
            return None

        existing_ids = frozenset(
            governed.id for governed in self._repository.load(VocabularyKind.WORD_MAPPING)
        )
        proposal = propose_from_near_miss(
            result.command_text, candidates, existing_ids=existing_ids
        )
        if proposal is None:
            return None

        if self._policy is ApplyPolicy.AUTO_APPLY:
            self._repository.add(proposal.entry, self._clock.now())
            _LOGGER.info(
                "Learned mapping '%s' -> '%s' (auto-apply, score %.1f).",
                proposal.utterance,
                proposal.nearest_phrase,
                proposal.score,
            )
        else:
            _LOGGER.info(
                "Vocabulary proposal (propose-only): '%s' -> '%s' (score %.1f).",
                proposal.utterance,
                proposal.nearest_phrase,
                proposal.score,
            )
        return proposal

    @staticmethod
    def _is_near_miss(snap: SnapResult | None, match: MatchOutcome | None) -> bool:
        """Whether this outcome is a learnable near-miss.

        A near-miss is a confirmed *not matched* (``matched is False``) — distinct from an
        unknown ``None`` — or a snap *abstain* (the snapper found close candidates but was not
        confident). A confirmed match never learns.
        """
        if match is not None and match.matched:
            return False
        if match is not None and not match.matched:
            return True
        return snap is not None and snap.decision is SnapDecision.ABSTAINED


def _candidate_phrases(snap: SnapResult | None) -> list[tuple[str, float]]:
    """Extract the valid phrases to learn toward from a snap result, best first.

    Prefers the abstain-band ``near_misses`` (the rich top-N list); when the snapper instead
    *snapped* or returned a single best candidate (no near-miss list), falls back to that one
    ``candidate``. Returns an empty list when there is nothing to learn toward — an empty
    phrase index, or a kneeboard route (``snap is None``).
    """
    if snap is None:
        return []
    if snap.near_misses:
        return [(near.phrase, near.score) for near in snap.near_misses]
    if snap.candidate is not None:
        return [(snap.candidate, snap.score)]
    return []
