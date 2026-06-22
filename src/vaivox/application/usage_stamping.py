"""Credit vocabulary usage after a VoiceAttack dispatch (ADR-0004 / ADR-0006).

When a reconciled command is dispatched to VoiceAttack, the entries whose surface form
survived into the sent text earned the credit for shaping that command. This collaborator
turns that observation into the two repository writes ADR-0004 governance runs on:

1. **Usage stamping** — Tier 1 token-provenance attribution
   (:meth:`~vaivox.domain.vocabulary.governor.VocabularyGovernor.attribute_tier1`) over the
   sent text picks the contributing entry ids, then
   :meth:`~vaivox.application.ports.VocabularyRepository.mark_used` refreshes their recency
   and increments their hit count.
2. **LRU maintenance** — an *optional, inert-by-default* governance pass
   (:meth:`~vaivox.domain.vocabulary.governor.VocabularyGovernor.govern` +
   :meth:`~vaivox.application.ports.VocabularyRepository.replace_entries`). With no
   ``max_entries`` cap (the default) nothing is ever evicted, and ``DEFAULT`` entries are
   protected regardless — so the seed vocabulary is never at risk. The pass only does work
   once ``LEARNED`` entries exist *and* a cap is configured.

**Known limitation — no real match signal.** Without the C# plugin return channel
(ADR-0006) VAIVOX cannot know whether VoiceAttack *actually matched* the dispatched
command; it only knows the command was *sent*. So this stamps on **dispatch** (a proxy),
not on a confirmed match. When the return channel lands, ``mark_used`` must be conditioned
on ``matched == True`` and the attribution refined (Tier 2 counterfactual replay). That is
the known blocking dependency — see ``TODO.md`` §1 and ``AGENTS.md`` Phase 5 Axis A.

The stamping is **best-effort and never fatal to routing**: every repository call is guarded
so a failed sidecar write degrades to a logged warning and the dispatch still succeeds (the
repository already degrades gracefully; this is belt-and-braces).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from vaivox.application.ports import Clock, VocabularyRepository
from vaivox.domain.vocabulary.governor import VocabularyGovernor
from vaivox.domain.vocabulary.model import (
    EvictionPolicy,
    GovernedEntry,
    VocabularyKind,
)

_LOGGER = logging.getLogger(__name__)


class UsageStamper:
    """Stamp vocabulary usage (and optionally evict) after a VoiceAttack dispatch.

    The collaborator the shared routing path
    (:func:`~vaivox.application.record_command.route_command`) calls on the VoiceAttack
    branch only — kneeboard notes are free text and never credit vocabulary. It owns the
    write-back side of ADR-0004 governance: usage stamping always, the LRU pass only when a
    cap makes it meaningful.
    """

    def __init__(
        self,
        repository: VocabularyRepository,
        governor: VocabularyGovernor,
        clock: Clock,
        *,
        eviction_policies: Mapping[VocabularyKind, EvictionPolicy] | None = None,
    ) -> None:
        """Wire the repository, the governance domain service, and the clock.

        Args:
            repository: The vocabulary repository (the JSONL source of truth) the usage
                stamps and any eviction are written back through.
            governor: The pure governance domain service that performs Tier 1 attribution
                and the LRU ranking/eviction.
            clock: The clock supplying the stamp time (``mark_used`` recency, grace window).
            eviction_policies: Optional per-kind LRU policy. When omitted (the default), the
                maintenance pass is **inert** — no cap means nothing is ever evicted, so the
                seed vocabulary is never at risk. Supply a policy with a ``max_entries`` cap
                to enable eviction of ``LEARNED`` entries (``DEFAULT`` stays protected).
        """
        self._repository = repository
        self._governor = governor
        self._clock = clock
        self._eviction_policies = dict(eviction_policies or {})

    def stamp(self, sent_text: str) -> None:
        """Credit the entries whose surface form survived into ``sent_text``.

        Builds Tier 1 attribution inputs from the live repository — ``matched_tokens`` from
        the dispatched text, ``edit_output_tokens`` as ``{id: tokens(term + aliases)}`` for
        every entry — credits the survivors via the governor, and stamps them through
        :meth:`~vaivox.application.ports.VocabularyRepository.mark_used`. Then runs the
        optional (inert-by-default) LRU pass per kind.

        All work is wrapped so a repository failure is logged and swallowed — usage
        stamping must never break command dispatch.

        Args:
            sent_text: The exact text dispatched to VoiceAttack (post-snap).
        """
        try:
            self._stamp(sent_text)
        except Exception as error:
            _LOGGER.warning("Usage stamping failed (dispatch unaffected): %s", error)

    def _stamp(self, sent_text: str) -> None:
        """Do the attribution + stamp + optional eviction (guarded by :meth:`stamp`)."""
        entries_by_kind = {kind: self._repository.load(kind) for kind in VocabularyKind}
        all_entries = [entry for entries in entries_by_kind.values() for entry in entries]
        if not all_entries:
            return

        matched_tokens = sent_text.split()
        edit_output_tokens = {governed.id: _surface_tokens(governed) for governed in all_entries}
        credited = self._governor.attribute_tier1(matched_tokens, edit_output_tokens)
        if credited:
            self._repository.mark_used(credited, self._clock.now())

        self._maybe_evict()

    def _maybe_evict(self) -> None:
        """Run the LRU pass per kind when a cap is configured (inert by default).

        Reloads the **freshly stamped** view per kind so the pass ranks on the just-updated
        recency, then evicts only when its policy actually caps. With no policy (the default)
        this is a no-op: nothing is reloaded and ``govern`` is never even consulted.
        """
        for kind, policy in self._eviction_policies.items():
            if policy.max_entries is None:
                continue  # no cap -> nothing to evict; skip the reload + write entirely
            current = self._repository.load(kind)
            result = self._governor.govern(current, policy, self._clock.now())
            if result.evicted:
                self._repository.replace_entries(kind, result.kept)
                _LOGGER.info(
                    "Evicted %d %s entries (LRU, over cap %d).",
                    len(result.evicted),
                    kind.value,
                    policy.max_entries,
                )


def _surface_tokens(governed: GovernedEntry) -> list[str]:
    """Return the whitespace tokens of an entry's surface forms (``term`` + ``aliases``).

    These are the tokens an entry can contribute to a matched command. A multi-word term or
    alias is split so a single surviving word still credits the entry, matching the
    token-level survival semantics of
    :meth:`~vaivox.domain.vocabulary.governor.VocabularyGovernor.attribute_tier1`.

    Args:
        governed: The repository entry whose surface forms supply the output tokens.

    Returns:
        Every whitespace-separated token of the term and each alias, blanks dropped.
    """
    tokens = governed.entry.term.split()
    for alias in governed.entry.aliases:
        tokens.extend(alias.split())
    return tokens
