"""Offline reconciliation eval runner + metrics (ADR-0008).

Runs each dataset item's raw STT through the reconciliation pipeline against a frozen
vocab snapshot, then applies the conservative phrase snapper (Axis B, ADR-0011) before
asking the VAICOM mock whether the resulting command exists and whether it is the
*expected* one. Reports match / wrong-match / not-found / abstain rates (overall and
per failure-mode tag) plus near-miss recoverability.

The pipeline is **reconcile -> snap -> oracle**: the frozen command set IS the snapper's
phrase index (`PhraseSnapper(load_commands())`), so a high-confidence near-miss the
per-token step left just shy of an exact command is snapped to that command, while
mid-confidence inputs land in the `abstain` band (the snapper holds the text and emits a
near-miss). `abstain` was reserved for this in earlier phases (ADR-0006) and starts being
populated here. Pure + deterministic — no I/O beyond reading the committed fixtures.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from tests.eval.vaicom_mock import VaicomMock, normalize
from vaivox.domain.reconciliation.pipeline import reconcile
from vaivox.domain.reconciliation.snapper import PhraseSnapper, SnapDecision

_FIXTURES = Path(__file__).parent / "fixtures"

MATCH = "match"
WRONG_MATCH = "wrong_match"
NOT_FOUND = "not_found"
ABSTAIN = "abstain"

_NEAR_MISS_LIMIT = 3


@dataclass(frozen=True)
class EvalItem:
    """One labelled dataset row."""

    raw_stt: str
    expected_command: str
    tags: list[str]


@dataclass
class EvalMetrics:
    """Aggregate eval outcome (and its serializable summary)."""

    total: int = 0
    match: int = 0
    wrong_match: int = 0
    not_found: int = 0
    abstain: int = 0
    near_miss_recoverable: int = 0
    per_tag: dict[str, dict[str, int]] = field(default_factory=dict)

    def rate(self, count: int) -> float:
        return count / self.total if self.total else 0.0

    def summary(self) -> dict[str, object]:
        return {
            "total": self.total,
            "match": self.match,
            "wrong_match": self.wrong_match,
            "not_found": self.not_found,
            "abstain": self.abstain,
            "near_miss_recoverable": self.near_miss_recoverable,
            "match_rate": round(self.rate(self.match), 4),
            "wrong_match_rate": round(self.rate(self.wrong_match), 4),
            "not_found_rate": round(self.rate(self.not_found), 4),
            "per_tag": self.per_tag,
        }


def load_commands() -> list[str]:
    lines = (_FIXTURES / "commands.txt").read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def load_vocab() -> dict[str, object]:
    return json.loads((_FIXTURES / "vocab.json").read_text(encoding="utf-8"))


def load_dataset() -> list[EvalItem]:
    items: list[EvalItem] = []
    for line in (_FIXTURES / "golden.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        row = json.loads(line)
        items.append(
            EvalItem(
                raw_stt=row["raw_stt"],
                expected_command=row["expected_command"],
                tags=list(row.get("tags", [])),
            )
        )
    return items


def load_baseline() -> dict[str, object]:
    return json.loads((_FIXTURES / "baseline.json").read_text(encoding="utf-8"))


def _classify(command: str, expected: str, oracle: VaicomMock) -> str:
    if not oracle.exists(command):
        return NOT_FOUND
    if normalize(command) == normalize(expected):
        return MATCH
    return WRONG_MATCH


def run_eval() -> EvalMetrics:
    """Run the full eval over the committed fixtures and return the metrics.

    The pipeline is reconcile -> snap -> oracle (ADR-0011): the frozen command set is the
    snapper's phrase index, so the eval exercises the snapper end to end. A *snapped*
    command is classified by the oracle exactly like any other; an *abstained* command is
    counted in the ``abstain`` band (the snapper held the text and emitted a near-miss),
    distinct from a plain ``not_found``.
    """
    vocab = load_vocab()
    word_mappings = vocab["word_mappings"]
    fuzzy_words = vocab["fuzzy_words"]
    phonetic_alphabet = vocab["phonetic_alphabet"]
    commands = load_commands()
    oracle = VaicomMock(commands)
    snapper = PhraseSnapper(commands)

    metrics = EvalMetrics()
    per_tag: dict[str, dict[str, int]] = defaultdict(
        lambda: {MATCH: 0, WRONG_MATCH: 0, NOT_FOUND: 0, ABSTAIN: 0}
    )

    for item in load_dataset():
        result = reconcile(item.raw_stt, word_mappings, fuzzy_words, phonetic_alphabet)
        snap = snapper.snap(result.command_text)
        command = snap.text
        outcome = _classify(command, item.expected_command, oracle)

        # An abstained, still-not-found utterance is its own band: the snapper saw a
        # mid-confidence near-miss but conservatively declined to snap (ADR-0011). It is
        # tracked separately from a plain miss so threshold loosening is observable.
        if outcome == NOT_FOUND and snap.decision is SnapDecision.ABSTAINED:
            outcome = ABSTAIN

        metrics.total += 1
        setattr(metrics, outcome, getattr(metrics, outcome) + 1)
        for tag in item.tags:
            per_tag[tag][outcome] += 1

        if outcome in (NOT_FOUND, ABSTAIN) and item.expected_command in oracle.nearest(
            command, _NEAR_MISS_LIMIT
        ):
            metrics.near_miss_recoverable += 1

    metrics.per_tag = {tag: dict(counts) for tag, counts in sorted(per_tag.items())}
    return metrics
