"""CI-gated offline reconciliation eval (ADR-0008).

Runs the full pipeline over the curated golden dataset against the mocked VAICOM and
asserts no regression below the committed baseline. The decisive guard is
``wrong_match == 0``: VAIVOX must never fire the *wrong* command. Deterministic, so the
metrics are exact.
"""

from __future__ import annotations

from tests.eval.harness import load_baseline, run_eval


def test_no_wrong_matches() -> None:
    # The dangerous failure mode: a reconciled utterance that matches a *different*
    # command and fires it. Must stay zero.
    assert run_eval().wrong_match == 0


def test_outcomes_partition_the_dataset() -> None:
    metrics = run_eval()
    assert metrics.total > 0
    assert (
        metrics.match + metrics.wrong_match + metrics.not_found + metrics.abstain == metrics.total
    )


def test_no_regression_vs_baseline() -> None:
    metrics = run_eval()
    baseline = load_baseline()

    assert metrics.total == baseline["total"], "dataset size changed; refresh the baseline"
    # No regression: at least as many correct matches, no more wrong matches or misses.
    assert metrics.match >= baseline["match"]
    assert metrics.wrong_match <= baseline["wrong_match"]
    assert metrics.not_found <= baseline["not_found"]


def test_misses_are_recoverable() -> None:
    # Every not-found expected command is within the near-miss top-N — i.e. the misses
    # are the recoverable kind Axis A governance / Axis B snap target, not noise.
    # The AI_ATC long-prompt F10 example is the typed-resolver exception.
    metrics = run_eval()
    missish = metrics.not_found + metrics.abstain
    long_prompt_not_found = metrics.per_tag.get("long_prompt", {}).get("not_found", 0)
    assert metrics.near_miss_recoverable + long_prompt_not_found == missish
