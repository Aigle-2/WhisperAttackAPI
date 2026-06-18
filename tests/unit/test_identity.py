"""Unit tests for the centralized product identity (ADR-0002, ADR-0003)."""

from __future__ import annotations

from vaivox import __version__
from vaivox.infrastructure.config.identity import VAIVOX, ProductIdentity

_UPSTREAM_GUID = "{1AD02372-145E-4143-BBBE-AC7575595C24}"


def test_identity_is_vaivox() -> None:
    assert isinstance(VAIVOX, ProductIdentity)
    assert VAIVOX.name == "VAIVOX"
    assert VAIVOX.window_title == "VAIVOX"
    assert VAIVOX.version == __version__


def test_separation_from_upstream() -> None:
    # Clean separation: a fresh GUID and a VAIVOX-specific data dir / log / lock so a
    # parallel upstream WhisperAttack install is never clobbered (ADR-0002).
    assert VAIVOX.plugin_guid != _UPSTREAM_GUID
    assert VAIVOX.data_dir_name == "VAIVOX"
    assert VAIVOX.log_file_name == "VAIVOX.log"
    assert VAIVOX.instance_lock_name == "vaivox"
    assert "whisper" not in VAIVOX.instance_lock_name.lower()


def test_ports_are_localhost_ints() -> None:
    assert VAIVOX.control_host == "127.0.0.1"
    assert VAIVOX.voiceattack_host == "127.0.0.1"
    assert VAIVOX.api_host == "127.0.0.1"
    for port in (VAIVOX.control_port, VAIVOX.voiceattack_port, VAIVOX.api_port):
        assert isinstance(port, int)
        assert 1 <= port <= 65535
