"""Unit tests for the UDP VAICOM F10 ``doAction`` sink (ADR-0012).

The socket is monkeypatched so no real datagram leaves the test — we assert on exactly what
*would* be sent (type, actionsequence, address).
"""

from __future__ import annotations

import json

import pytest

from vaivox.domain.commands.model import DispatchTargetKind, MissionMenuEntry, VaicomF10Action
from vaivox.infrastructure.voiceattack.vaicom_f10_sink import (
    DEFAULT_VAICOM_F10_PORT,
    UdpVaicomF10ActionSink,
)

_SOCKET_TARGET = "vaivox.infrastructure.voiceattack.vaicom_f10_sink.socket.socket"


@pytest.fixture
def sent_datagrams(monkeypatch: pytest.MonkeyPatch) -> list[tuple[bytes, tuple[str, int]]]:
    """Patch the UDP socket and capture every ``(datagram, address)`` that would be sent."""
    sent: list[tuple[bytes, tuple[str, int]]] = []

    class _FakeUdpSocket:
        def __enter__(self) -> _FakeUdpSocket:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def sendto(self, data: bytes, address: tuple[str, int]) -> None:
            sent.append((data, address))

    monkeypatch.setattr(_SOCKET_TARGET, lambda *args, **kwargs: _FakeUdpSocket())
    return sent


def _action(action_index: int | None) -> VaicomF10Action:
    return VaicomF10Action(
        identifier="Action FLEX NORTH",
        label="FLEX NORTH",
        command_id=20086,
        action_index=action_index,
    )


def test_dispatch_sends_actionsequence_datagram(
    sent_datagrams: list[tuple[bytes, tuple[str, int]]],
) -> None:
    sink = UdpVaicomF10ActionSink(
        "127.0.0.1",
        33491,
        live_index=lambda: {"FLEX NORTH": 0},
    )
    outcome = sink.dispatch(_action(99))

    assert len(sent_datagrams) == 1
    data, address = sent_datagrams[0]
    assert address == ("127.0.0.1", 33491)
    assert json.loads(data.decode("utf-8")) == {
        "type": "mission.player.actionsequence",
        "actionsequence": [0],
    }
    assert outcome.accepted is True
    assert outcome.target_kind == DispatchTargetKind.VAICOM_F10_ACTION.value
    assert outcome.resolved_target == "Action FLEX NORTH"
    assert "actionIndex 0" in (outcome.detail or "")


def test_dispatch_without_current_live_label_does_not_send(
    sent_datagrams: list[tuple[bytes, tuple[str, int]]],
) -> None:
    outcome = UdpVaicomF10ActionSink(live_index=lambda: {}).dispatch(_action(7))

    assert sent_datagrams == []  # no datagram constructed
    assert outcome.accepted is False
    assert "ActionIndex" in (outcome.detail or "")


def test_default_port_is_vaicom_client_send_port() -> None:
    assert DEFAULT_VAICOM_F10_PORT == 33491


def test_socket_error_is_reported_as_not_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise OSError("network down")

    monkeypatch.setattr(_SOCKET_TARGET, boom)

    outcome = UdpVaicomF10ActionSink(live_index=lambda: {"FLEX NORTH": 5}).dispatch(_action(5))

    assert outcome.accepted is False
    assert "UDP send failed" in (outcome.detail or "")


def test_dispatch_rechecks_case_insensitive_live_index_at_send_time(
    sent_datagrams: list[tuple[bytes, tuple[str, int]]],
) -> None:
    current = {"flex north": 4}
    sink = UdpVaicomF10ActionSink(live_index=lambda: current)

    first = sink.dispatch(_action(1))
    current.clear()
    second = sink.dispatch(_action(1))

    assert first.accepted is True
    assert json.loads(sent_datagrams[0][0])["actionsequence"] == [4]
    assert second.accepted is False
    assert len(sent_datagrams) == 1


def test_live_index_provider_error_fails_closed(
    sent_datagrams: list[tuple[bytes, tuple[str, int]]],
) -> None:
    def unavailable() -> dict[str, int]:
        raise OSError("listener stopped")

    outcome = UdpVaicomF10ActionSink(live_index=unavailable).dispatch(_action(3))

    assert outcome.accepted is False
    assert sent_datagrams == []


def test_dispatch_rechecks_exact_path_when_labels_are_duplicated(
    sent_datagrams: list[tuple[bytes, tuple[str, int]]],
) -> None:
    entries = (
        MissionMenuEntry("CHECK IN", 2, ("ATC",)),
        MissionMenuEntry("CHECK IN", 9, ("Support",)),
    )
    action = VaicomF10Action(
        identifier="Action CHECK IN",
        label="CHECK IN",
        action_index=2,
        menu_path=("ATC",),
    )

    outcome = UdpVaicomF10ActionSink(live_entries=lambda: entries).dispatch(action)

    assert outcome.accepted is True
    assert json.loads(sent_datagrams[0][0])["actionsequence"] == [2]
