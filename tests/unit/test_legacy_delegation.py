"""Guard that the legacy shims still delegate to the extracted domain.

These pin the Phase 2 wiring: if a future change re-implements logic in the legacy
modules instead of delegating, these identity checks fail.
"""

from __future__ import annotations


def test_transcription_postprocess_delegates_to_domain() -> None:
    import transcription_postprocess

    from vaivox.domain.reconciliation.spelled_codes import compact_spelled_codes

    assert transcription_postprocess.compact_spelled_codes is compact_spelled_codes


def test_stt_keyterms_reexport_domain_vocabulary() -> None:
    import stt_backends.keyterms as legacy

    from vaivox.domain.vocabulary import keyterms as domain

    assert legacy.apply_keyterm_budget is domain.apply_keyterm_budget
    assert legacy.KeytermBudget is domain.KeytermBudget
    assert legacy.PHONETIC_ALPHABET is domain.PHONETIC_ALPHABET
    assert callable(legacy.load_vaicom_keyterms)
