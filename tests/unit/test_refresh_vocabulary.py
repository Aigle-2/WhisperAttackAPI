"""Unit tests for the RefreshVocabulary use case (ADR-0005 trigger logic + status).

The generator is faked, so these pin the orchestration only: the staleness/force gate, the
hot-apply of the phrase index on success, and the user-facing status — independent of any
real VAICOM install (the adapter's own discovery/staleness lives in its test).
"""

from __future__ import annotations

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
