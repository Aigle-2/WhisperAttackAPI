r"""The VoiceAttack return-channel wire protocol (ADR-0006, frozen in M1).

The return channel reuses the existing **65433** socket and connection: the request
is unchanged (the command text, UTF-8), and the plugin replies with the match
outcome. This module is the single Python source of truth for that reply's
serialization (:func:`build_reply`) and parsing (:func:`parse_match_outcome`); the
C# plugin must emit byte-identical replies, verified against the shared golden
vectors in ``tests/contract/match_protocol_vectors.json``.

Wire protocol (frozen):

* **Reply** — one ``\n``-terminated UTF-8 JSON object on a single line::

      {"v":1,"matched":true,"resolved_command":"..."}

  ``resolved_command`` may be ``null``. The reference serialization is compact (no
  inter-token whitespace) with a stable key order (``v``, ``matched``,
  ``resolved_command``) so both languages produce the same bytes.
* **Framing** — read **until the ``\n``**; never assume a single ``recv`` holds the
  whole line (TCP may split or coalesce).
* **Versioning** — the ``"v"`` integer is the protocol version
  (:data:`MATCH_PROTOCOL_VERSION`). Unknown fields are ignored so the plugin can add
  fields without breaking older readers (forward-compatible).
* **Best-effort** — parsing is defensive: empty data, invalid JSON, a non-object
  payload, or a missing/non-boolean ``matched`` field all yield ``None`` ("unknown"),
  which telemetry records without stamping vocabulary usage. The reader never raises
  on a malformed reply.

This module is infrastructure (pure transport, no learning logic). It imports the
domain :class:`~vaivox.domain.telemetry.model.MatchOutcome`, never the reverse.
"""

from __future__ import annotations

import json
from typing import Any

from vaivox.domain.telemetry.model import MatchOutcome

MATCH_PROTOCOL_VERSION = 1
"""The wire-protocol version emitted in the ``"v"`` field of every reply."""


def build_reply(matched: bool, resolved_command: str | None) -> bytes:
    r"""Serialize a match outcome to the reference reply bytes.

    This is the canonical serialization the plugin must reproduce byte-for-byte: a
    compact, single-line UTF-8 JSON object with a stable key order, terminated by a
    single ``\n``. Round-trips exactly through :func:`parse_match_outcome`.

    Args:
        matched: Whether VoiceAttack found and dispatched a command for the text.
        resolved_command: The command VoiceAttack resolved to, or ``None`` when not
            matched (or when the plugin does not report the resolved command).

    Returns:
        The ``\n``-terminated UTF-8 reply line, e.g.
        ``b'{"v":1,"matched":true,"resolved_command":"Tower, request taxi"}\n'``.
    """
    payload: dict[str, Any] = {
        "v": MATCH_PROTOCOL_VERSION,
        "matched": matched,
        "resolved_command": resolved_command,
    }
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return line.encode("utf-8") + b"\n"


def parse_match_outcome(data: bytes) -> MatchOutcome | None:
    r"""Parse a plugin reply into a :class:`MatchOutcome`, best-effort.

    Framing, whitespace, and forward-compatibility are all handled here: a trailing
    ``\n`` and surrounding whitespace are tolerated, and unknown fields are ignored
    so a newer plugin can add fields without breaking this reader.

    Args:
        data: The raw reply bytes read from the socket (with or without the trailing
            newline).

    Returns:
        The parsed :class:`MatchOutcome`, or ``None`` ("unknown") when the reply is
        empty, not valid UTF-8 JSON, not a JSON object, or is missing a boolean
        ``matched`` field. The caller treats ``None`` as an unknown outcome:
        telemetry records it, nothing is stamped.
    """
    if not data:
        return None

    try:
        text = data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None

    if not text:
        return None

    try:
        payload = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    matched = payload.get("matched")
    if not isinstance(matched, bool):
        return None

    resolved = payload.get("resolved_command")
    if resolved is not None and not isinstance(resolved, str):
        resolved = None

    return MatchOutcome(matched=matched, resolved_command=resolved)
