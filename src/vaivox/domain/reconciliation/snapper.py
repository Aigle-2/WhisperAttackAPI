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

An **exact match short-circuits the bands**: when the normalized utterance equals a known
command verbatim, it snaps to that command's stored form regardless of the runner-up
margin. A different command scoring close by is irrelevant when the input *is* one of them
— without this, a perfect hit whose runner-up merely falls within ``MARGIN`` would be
misreported as an abstain near-miss. Otherwise three bands share **one scorer** (ADR-0006),
so near-miss reporting is just the abstain-band output of the same function at a different
cut-off:

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

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from rapidfuzz import fuzz

#: Connector punctuation (hyphens, dashes, slashes, …) folded to a space before matching,
#: so a transcript like "Air-to-Air" scores against the stored "Air to Air" as one phrase.
_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)

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
    phrase with a conservative composite scorer: ``token_sort_ratio`` for word-order
    variation, plus a compact no-space ratio for phrases where VoiceAttack stores a
    spoken compound as one token. Whatever the scoring, the runner-up margin guard is
    mandatory for fuzzy matches — an exact (verbatim) match short-circuits it, since an
    utterance that *is* a known command is unambiguous (see :meth:`snap`).

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
        # Exact-match lookup: normalized phrase -> its position. The dedup above guarantees
        # each normalized key maps to exactly one phrase, so an utterance that *is* a known
        # command resolves to a single, unambiguous phrase (see :meth:`snap`).
        self._exact: dict[str, int] = {
            normalized: position for position, normalized in enumerate(self._normalized)
        }
        self._high = high
        self._low = low
        self._margin = margin

    @property
    def phrase_index(self) -> tuple[str, ...]:
        """The frozen phrase index, in load order (original casing)."""
        return self._index

    def snap(self, text: str) -> SnapResult:
        """Score ``text`` against the phrase index and apply the three bands.

        An exact (verbatim, after normalization) match short-circuits the bands and snaps
        regardless of the runner-up margin: when the utterance *is* a known command, a
        different command scoring close by is not a real ambiguity.

        Args:
            text: The reconciled command text to consider snapping.

        Returns:
            A :class:`SnapResult` carrying the decision, the text to route onward, the
            best candidate and score, and (when abstaining) the near-miss list.
        """
        query = _normalize(text)
        if not self._index or not query:
            return SnapResult(decision=SnapDecision.RAW, text=text)

        # Exact-match short-circuit (ADR-0011): the normalized utterance *is* a known
        # command, so the user said exactly that phrase. The runner-up margin guards
        # against ambiguity between two close phrases, but there is none here — a different
        # command scoring nearby is irrelevant when the input matches one verbatim. Snap
        # regardless of margin (and emit the canonical stored form, which also fixes the
        # input back to canonical casing/punctuation). The dedup in __init__ guarantees at
        # most one phrase matches exactly; an exact normalized match always scores 100.
        exact_position = self._exact.get(query)
        if exact_position is not None:
            exact_phrase = self._index[exact_position]
            return SnapResult(
                decision=SnapDecision.SNAPPED,
                text=exact_phrase,
                candidate=exact_phrase,
                score=100.0,
            )

        scored = _top_scores(query, self._normalized, limit=_NEAR_MISS_LIMIT)
        best_phrase = self._index[scored[0][1]]
        best_score = scored[0][0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0

        if best_score >= self._high and (best_score - runner_up) >= self._margin:
            return SnapResult(
                decision=SnapDecision.SNAPPED,
                text=best_phrase,
                candidate=best_phrase,
                score=best_score,
            )

        if best_score >= self._low:
            near_misses = tuple(
                NearMiss(phrase=self._index[position], score=score) for score, position in scored
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
    """Normalize a phrase for matching (lowercase, fold punctuation to spaces, collapse).

    Connector punctuation is treated as a word boundary: a transcript like
    ``"TACAN Air-to-Air"`` must score against the canonical ``"TACAN Air to Air"`` as the
    *same* phrase, not lose points for the hyphen splitting one token off from three.

    This intentionally diverges from the eval oracle's ``normalize``, which models
    VoiceAttack's punctuation-*sensitive* ``Command.Exists``. The snapper's job is to
    recognize the equivalence and snap to the canonical phrase — which VoiceAttack then
    accepts — so it normalizes more aggressively than the acceptance test it feeds.

    Args:
        text: The phrase to normalize.

    Returns:
        The lowercased, punctuation-folded, whitespace-collapsed phrase.
    """
    return " ".join(_PUNCTUATION.sub(" ", text.lower()).split())


def _score(query: str, choice: str) -> float:
    """Score two normalized phrases with the snapper's shared scorer.

    ``token_sort_ratio`` handles word order, while the compact ratio handles spoken
    compounds that VoiceAttack stores as a single token, such as "wheel chocks" vs.
    "wheelchocks".
    """
    score = fuzz.token_sort_ratio(query, choice)
    if _has_compound_split(query, choice):
        score = max(score, fuzz.ratio(query.replace(" ", ""), choice.replace(" ", "")))
    return score


def _has_compound_split(left: str, right: str) -> bool:
    """Whether one phrase joins adjacent tokens that the other phrase splits."""
    left_tokens = left.split()
    right_tokens = right.split()
    return _has_joined_token(left_tokens, right_tokens) or _has_joined_token(
        right_tokens, left_tokens
    )


def _has_joined_token(tokens: Sequence[str], other_tokens: Sequence[str]) -> bool:
    """Return true when any token equals two or more adjacent tokens joined."""
    for token in tokens:
        if len(token) < 4:
            continue
        for start in range(len(other_tokens)):
            combined = ""
            for end in range(start, len(other_tokens)):
                combined += other_tokens[end]
                if len(combined) > len(token):
                    break
                if not token.startswith(combined):
                    break
                if end > start and combined == token:
                    return True
    return False


def _top_scores(query: str, choices: Sequence[str], limit: int) -> tuple[tuple[float, int], ...]:
    """Return ``(score, index)`` pairs sorted by score descending."""
    scored = ((_score(query, choice), index) for index, choice in enumerate(choices))
    return tuple(sorted(scored, key=lambda item: item[0], reverse=True)[:limit])


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
