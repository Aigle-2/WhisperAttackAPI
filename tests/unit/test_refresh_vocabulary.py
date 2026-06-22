"""Unit tests for the RefreshVocabulary use case (ADR-0005 trigger logic + status).

The generator is faked, so these pin the orchestration only: the staleness/force gate, the
hot-apply of the phrase index on success, and the user-facing status — independent of any
real VAICOM install (the adapter's own discovery/staleness lives in its test).
"""

from __future__ import annotations

import threading

from vaivox.application.ports import StatusLevel, VocabularyGenerationResult
from vaivox.application.refresh_vocabulary import (
    RefreshVocabulary,
    ReloadVocabulary,
)


class FakeGenerator:
    def __init__(self, stale, result):
        self._stale = stale
        self._result = result
        self.generate_calls = 0

    def is_stale(self):
        return self._stale

    def generate(self):
        self.generate_calls += 1
        return self._result


class FakeReporter:
    def __init__(self):
        self.lines = []

    def report(self, message, level=StatusLevel.INFO):
        self.lines.append((message, level))

    def messages(self):
        return [message for message, _level in self.lines]


def _make(stale, result):
    generator = FakeGenerator(stale, result)
    reporter = FakeReporter()
    applied: list[bool] = []
    use_case = RefreshVocabulary(generator, reporter, lambda: applied.append(True))
    return use_case, generator, reporter, applied


def test_skips_generation_when_up_to_date():
    use_case, generator, reporter, applied = _make(
        stale=False, result=VocabularyGenerationResult(generated=True, reason="unused")
    )

    result = use_case.execute()

    assert result.generated is False
    assert result.reason == "up to date"
    assert generator.generate_calls == 0  # never touched the generator
    assert applied == []
    assert reporter.messages() == []  # quiet on the common, already-fresh path


def test_generates_and_hot_applies_when_stale():
    gen_result = VocabularyGenerationResult(
        generated=True, reason="generated", keyterm_count=42, phrase_count=100, source="C:/VAICOM"
    )
    use_case, generator, reporter, applied = _make(stale=True, result=gen_result)

    result = use_case.execute()

    assert result is gen_result
    assert generator.generate_calls == 1
    assert applied == [True]  # the regenerated phrase index was hot-applied (ADR-0009)
    assert any(
        level is StatusLevel.SUCCESS and "100 phrases" in message and "42 keyterms" in message
        for message, level in reporter.lines
    )


def test_reports_and_does_not_apply_when_no_install_found():
    gen_result = VocabularyGenerationResult(generated=False, reason="no VAICOM install found")
    use_case, generator, reporter, applied = _make(stale=True, result=gen_result)

    result = use_case.execute()

    assert result.generated is False
    assert generator.generate_calls == 1
    assert applied == []  # nothing generated -> nothing to apply
    assert any("no VAICOM install found" in message for message in reporter.messages())


def test_force_bypasses_the_staleness_check():
    gen_result = VocabularyGenerationResult(generated=True, reason="generated", phrase_count=3)
    use_case, generator, _reporter, applied = _make(stale=False, result=gen_result)

    use_case.execute(force=True)  # not stale, but forced (the UI "Refresh" action)

    assert generator.generate_calls == 1
    assert applied == [True]


def test_concurrent_executions_are_serialized():
    # A generator that flips itself "fresh" the moment it generates and asserts no two
    # generations overlap. The second concurrent caller must wait for the first, then -
    # because force=False and the first just generated - re-evaluate is_stale() to False
    # and no-op "up to date" (one generation total).
    class SerializingGenerator:
        def __init__(self) -> None:
            self._stale = True
            self.generate_calls = 0
            self._inside = False
            self.overlap_detected = False
            self._barrier = threading.Event()

        def is_stale(self) -> bool:
            return self._stale

        def generate(self) -> VocabularyGenerationResult:
            if self._inside:
                self.overlap_detected = True
            self._inside = True
            # Hold inside generate long enough that a truly-concurrent second caller would
            # overlap if the lock were absent.
            self._barrier.wait(timeout=1.0)
            self.generate_calls += 1
            self._stale = False  # the install is now fresh
            self._inside = False
            return VocabularyGenerationResult(generated=True, reason="generated", phrase_count=7)

    generator = SerializingGenerator()
    reporter = FakeReporter()
    use_case = RefreshVocabulary(generator, reporter, lambda: 0)

    results: list[VocabularyGenerationResult] = []

    def run() -> None:
        results.append(use_case.execute())

    first = threading.Thread(target=run)
    second = threading.Thread(target=run)
    first.start()
    second.start()
    # Release the first generation so it can complete; the second is blocked on the lock.
    generator._barrier.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    assert generator.overlap_detected is False  # the lock prevented concurrent generation
    assert generator.generate_calls == 1  # the second caller re-checked staleness and no-op'd
    reasons = sorted(result.reason for result in results)
    assert reasons == ["generated", "up to date"]


def test_reload_vocabulary_applies_from_disk_and_reports_count():
    reporter = FakeReporter()
    applied: list[bool] = []

    def apply() -> int:
        applied.append(True)
        return 42

    result = ReloadVocabulary(apply, reporter).execute()

    assert result.reloaded is True
    assert result.phrases == 42  # the live count is surfaced
    assert applied == [True]  # re-read + hot-applied (no generation)
    assert any("Reloading vocabulary" in message for message in reporter.messages())
