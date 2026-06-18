"""Conservative whole-utterance phrase snap (Axis B, ADR-0011).

Per-token reconciliation (:mod:`vaivox.domain.reconciliation.pipeline`) cleans a
transcript word-by-word, but VoiceAttack's ``Command.Exists`` is effectively an exact
match: an utterance that is *close to* a valid VAICOM command but not exact still fails
(a leading filler word, a word split, a callsign just below the per-token fuzzy
threshold). Those mismatches live at the **whole-utterance** level, so the per-token
step cannot fix them.

:class:`PhraseSnapper` runs **after** reconciliation. It scores the reconciled command
against a frozen **phrase index** of valid command phrases (``rapidfuzz``) and snaps to
the best match only when confidence is high; otherwise it abstains (emitting a near-miss)
or leaves the text untouched. The decisive constraint is the eval's ``wrong_match == 0``
guard (ADR-0008): in a combat sim, firing the *wrong* command is far worse than missing
one the user simply repeats — so the snapper biases hard toward abstaining.

Three bands share **one scorer** (ADR-0006), so near-miss reporting is just the
abstain-band output of the same function at a different cut-off:

- ``best >= HIGH`` **and** ``(best - runner_up) >= MARGIN`` -> **snapped** to the best
  phrase. The runner-up margin is mandatory: never snap when two phrases are similarly
  close, because ambiguity is exactly where a wrong snap fires the wrong command.
- ``LOW <= best < HIGH`` (or the margin is too small) -> **abstained**: the reconciled
  text is sent unchanged and a near-miss (top-N candidates + scores) is recorded.
- ``best < LOW`` -> **raw**: the reconciled text is sent unchanged with no near-miss.

The snapper is pure (no I/O) and deterministic. It imports only ``rapidfuzz`` (the same
dependency the per-token fuzzy step already uses) so the domain stays free of any
infrastructure concern. An empty index makes :meth:`PhraseSnapper.snap` a no-op (always
``raw``), which preserves behaviour when no generated index file is present.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from rapidfuzz import fuzz, process

#: Minimum best score (0-100) to consider snapping to the best phrase.
DEFAULT_HIGH = 90.0

#: Minimum best score (0-100) to record a near-miss instead of sending raw text.
DEFAULT_LOW = 60.0

#: Minimum gap between the best and runner-up scores required to snap.
DEFAULT_MARGIN = 15.0

#: How many near-miss candidates to record in the abstain band.
_NEAR_MISS_LIMIT = 3


class SnapDecision(StrEnum):
    """Which band the candidate fell into (ADR-0011).

    Attributes:
        SNAPPED: High confidence and an unambiguous winner; the text was replaced.
        ABSTAINED: Mid confidence (or an ambiguous winner); the text was kept and a
            near-miss recorded.
        RAW: Low confidence (or an empty index); the text was kept untouched.
    """

    SNAPPED = "snapped"
    ABSTAINED = "abstained"
    RAW = "raw"


@dataclass(frozen=True)
class NearMiss:
    """One scored candidate phrase from the shared scorer.

    Attributes:
        phrase: The candidate command phrase from the index.
        score: Its similarity to the input (0-100, rapidfuzz ``token_sort_ratio``).
    """

    phrase: str
    score: float


@dataclass(frozen=True)
class SnapResult:
    """The outcome of one snap attempt (ADR-0011).

    Attributes:
        decision: Which band the candidate fell into.
        text: The text to route onward — the snapped phrase when ``SNAPPED``, otherwise
            the input text unchanged.
        candidate: The best-scoring phrase considered, or ``None`` for an empty index.
        score: The best candidate's score (0-100), or ``0.0`` for an empty index.
        near_misses: The top-N scored candidates, populated only when ``ABSTAINED`` (the
            abstain-band output that doubles as the near-miss report, ADR-0006).
    """

    decision: SnapDecision
    text: str
    candidate: str | None = None
    score: float = 0.0
    near_misses: tuple[NearMiss, ...] = field(default_factory=tuple)


class PhraseSnapper:
    """Snap a reconciled command to a valid phrase, conservatively (ADR-0011).

    Constructed with the frozen phrase index (the set of valid command phrases) and the
    three thresholds. The thresholds default to conservative, eval-calibrated values
    (:data:`DEFAULT_HIGH` / :data:`DEFAULT_LOW` / :data:`DEFAULT_MARGIN`); they are tuned
    against the offline eval (ADR-0008) and real telemetry (ADR-0006) — start strict,
    loosen only with evidence, and the eval gate keeps ``wrong_match == 0`` as they move.

    Recipient segmentation (ADR-0011) is a documented follow-up: v1 scores the whole
    phrase with ``token_sort_ratio`` (the same scorer the eval's near-miss helper uses,
    ADR-0006), which is order-insensitive and already recovers the eval's recoverable
    misses. Whatever the scoring, the runner-up margin guard is mandatory.

    Args:
        phrase_index: The valid command phrases to snap to. An empty index makes
            :meth:`snap` a no-op (every input is returned ``RAW``).
        high: Minimum best score (0-100) to consider snapping.
        low: Minimum best score (0-100) to record a near-miss instead of raw text.
        margin: Minimum gap between the best and runner-up scores required to snap.
    """

    def __init__(
        self,
        phrase_index: Iterable[str],
        high: float = DEFAULT_HIGH,
        low: float = DEFAULT_LOW,
        margin: float = DEFAULT_MARGIN,
    ) -> None:
        """Freeze the phrase index and thresholds (see the class docstring)."""
        # Preserve the original casing for output while matching case-insensitively, and
        # de-duplicate normalized phrases so the runner-up margin reflects distinct
        # commands rather than casing variants of the same phrase.
        index: list[str] = []
        seen: set[str] = set()
        for phrase in phrase_index:
            stripped = phrase.strip()
            key = _normalize(stripped)
            if key and key not in seen:
                seen.add(key)
                index.append(stripped)
        self._index: tuple[str, ...] = tuple(index)
        self._normalized: tuple[str, ...] = tuple(_normalize(phrase) for phrase in self._index)
        self._high = high
        self._low = low
        self._margin = margin

    @property
    def phrase_index(self) -> tuple[str, ...]:
        """The frozen phrase index, in load order (original casing)."""
        return self._index

    def snap(self, text: str) -> SnapResult:
        """Score ``text`` against the phrase index and apply the three bands.

        Args:
            text: The reconciled command text to consider snapping.

        Returns:
            A :class:`SnapResult` carrying the decision, the text to route onward, the
            best candidate and score, and (when abstaining) the near-miss list.
        """
        query = _normalize(text)
        if not self._index or not query:
            return SnapResult(decision=SnapDecision.RAW, text=text)

        scored = process.extract(
            query,
            self._normalized,
            scorer=fuzz.token_sort_ratio,
            limit=_NEAR_MISS_LIMIT,
        )
        # ``process.extract`` returns ``(choice, score, position)`` triples sorted best
        # first; ``position`` indexes back into the original-casing phrase list.
        best_phrase = self._index[scored[0][2]]
        best_score = scored[0][1]
        runner_up = scored[1][1] if len(scored) > 1 else 0.0

        if best_score >= self._high and (best_score - runner_up) >= self._margin:
            return SnapResult(
                decision=SnapDecision.SNAPPED,
                text=best_phrase,
                candidate=best_phrase,
                score=best_score,
            )

        if best_score >= self._low:
            near_misses = tuple(
                NearMiss(phrase=self._index[position], score=score)
                for _choice, score, position in scored
            )
            return SnapResult(
                decision=SnapDecision.ABSTAINED,
                text=text,
                candidate=best_phrase,
                score=best_score,
                near_misses=near_misses,
            )

        return SnapResult(
            decision=SnapDecision.RAW,
            text=text,
            candidate=best_phrase,
            score=best_score,
        )


def _normalize(text: str) -> str:
    """Normalize a phrase for matching (lowercase, collapse whitespace).

    Mirrors the eval oracle's ``normalize`` so the snapper and the match oracle agree on
    what counts as the same phrase.

    Args:
        text: The phrase to normalize.

    Returns:
        The lowercased, whitespace-collapsed phrase.
    """
    return " ".join(text.lower().split())


def build_snapper(phrase_index: Sequence[str]) -> PhraseSnapper:
    """Construct a :class:`PhraseSnapper` with the conservative default thresholds.

    A thin convenience for the composition root and the eval, both of which want the
    eval-calibrated defaults rather than spelling out the three thresholds.

    Args:
        phrase_index: The valid command phrases to snap to.

    Returns:
        A :class:`PhraseSnapper` over ``phrase_index`` with the default thresholds.
    """
    return PhraseSnapper(phrase_index)
