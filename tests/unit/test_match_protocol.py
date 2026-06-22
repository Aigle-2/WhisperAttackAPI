"""Layer-1 unit tests for the VoiceAttack return-channel wire protocol (ADR-0006, M1).

Drives :mod:`vaivox.infrastructure.voiceattack.protocol` from the shared golden
vectors in ``tests/contract/match_protocol_vectors.json`` — the single source of
truth the C# plugin is also tested against (AC1). No socket is involved: this is pure
serialization/parsing, so it runs in CI Linux with no VoiceAttack, no Windows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from vaivox.domain.telemetry.model import MatchOutcome
from vaivox.infrastructure.voiceattack.protocol import (
    MATCH_PROTOCOL_VERSION,
    build_reply,
    parse_match_outcome,
)

_VECTORS_PATH = Path(__file__).resolve().parents[1] / "contract" / "match_protocol_vectors.json"


def _load_vectors() -> dict[str, Any]:
    return json.loads(_VECTORS_PATH.read_text(encoding="utf-8"))


_VECTORS = _load_vectors()
_ROUND_TRIP = _VECTORS["round_trip"]
_PARSE_ONLY = _VECTORS["parse_only"]


def test_vectors_declare_the_frozen_protocol_version() -> None:
    assert _VECTORS["protocol_version"] == MATCH_PROTOCOL_VERSION == 1


@pytest.mark.parametrize("vector", _ROUND_TRIP, ids=lambda v: v["name"])
def test_build_reply_matches_golden_bytes(vector: dict[str, Any]) -> None:
    """build_reply emits the exact bytes the C# plugin must reproduce."""
    expected = vector["reply_bytes"].encode("utf-8")
    assert build_reply(vector["matched"], vector["resolved_command"]) == expected


@pytest.mark.parametrize("vector", _ROUND_TRIP, ids=lambda v: v["name"])
def test_round_trip_vectors_parse_back_to_their_inputs(vector: dict[str, Any]) -> None:
    """Each round-trip vector parses back into the MatchOutcome it was built from."""
    outcome = parse_match_outcome(vector["reply_bytes"].encode("utf-8"))
    assert outcome == MatchOutcome(
        matched=vector["matched"], resolved_command=vector["resolved_command"]
    )


@pytest.mark.parametrize("vector", _PARSE_ONLY, ids=lambda v: v["name"])
def test_parse_only_vectors_yield_the_expected_outcome(vector: dict[str, Any]) -> None:
    """Degraded / forward-compat replies parse to the documented outcome (or None)."""
    outcome = parse_match_outcome(vector["reply_bytes"].encode("utf-8"))

    if vector["expected_matched"] is None:
        assert outcome is None
    else:
        assert outcome is not None
        assert outcome.matched == vector["expected_matched"]
        assert outcome.resolved_command == vector["expected_resolved"]


def test_build_reply_round_trips_through_parse() -> None:
    """A property check independent of the vectors file."""
    for matched, resolved in [(True, "Tower, taxi"), (True, None), (False, None)]:
        outcome = parse_match_outcome(build_reply(matched, resolved))
        assert outcome == MatchOutcome(matched=matched, resolved_command=resolved)


def test_parse_returns_none_on_invalid_utf8() -> None:
    """Non-UTF-8 bytes are treated as unknown, never raised."""
    assert parse_match_outcome(b"\xff\xfe\x00") is None
