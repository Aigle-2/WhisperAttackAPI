"""Unit tests for the current-session F10 menu listener (ADR-0012)."""

from __future__ import annotations

import json
from pathlib import Path

from vaivox.infrastructure.dcs.menu_listener import (
    MENU_PROTOCOL_VERSION,
    MissionMenuListener,
    menu_file_path,
)


def _entry(label: object, index: object, path: object = None) -> dict[str, object]:
    return {"label": label, "action_index": index, "path": path}


def _datagram(
    entries: list[dict[str, object]],
    *,
    session: str = "dcs-session-1",
    revision: int = 1,
    phase: str = "update",
) -> bytes:
    return json.dumps(
        {
            "type": "vaivox.f10menu",
            "protocol": MENU_PROTOCOL_VERSION,
            "session": session,
            "revision": revision,
            "phase": phase,
            "entries": entries,
        }
    ).encode("utf-8")


def test_handle_datagram_replaces_the_settled_snapshot() -> None:
    listener = MissionMenuListener(port=0, debounce_seconds=0)

    listener._handle_datagram(_datagram([_entry("FLEX NORTH", 0), _entry("FLEX WEST", 1)]))
    assert listener.get_menu() == {"FLEX NORTH": 0, "FLEX WEST": 1}

    listener._handle_datagram(_datagram([_entry("Repeat last transmission", 0)], revision=2))
    assert listener.get_menu() == {"Repeat last transmission": 0}


def test_snapshot_is_not_exposed_until_the_build_settles() -> None:
    listener = MissionMenuListener(port=0, debounce_seconds=60)

    listener._handle_datagram(_datagram([_entry("FLEX NORTH", 0)]))
    assert listener.get_menu() == {}

    listener._commit_pending()
    assert listener.get_menu() == {"FLEX NORTH": 0}
    listener.stop()


def test_new_menu_mutation_invalidates_committed_handles_immediately() -> None:
    listener = MissionMenuListener(port=0, debounce_seconds=60)
    listener._handle_datagram(_datagram([_entry("OLD", 0)]))
    listener._commit_pending()
    assert listener.get_menu() == {"OLD": 0}

    listener._handle_datagram(_datagram([_entry("NEW", 1)], revision=2))

    assert listener.get_menu() == {}
    listener._commit_pending()
    assert listener.get_menu() == {"NEW": 1}
    listener.stop()


def test_handle_datagram_drops_malformed_entries() -> None:
    listener = MissionMenuListener(port=0, debounce_seconds=0)

    listener._handle_datagram(
        _datagram(
            [
                _entry("good", 3),
                _entry("bad", "x"),
                _entry("truthy", True),
                _entry("negative", -1),
                _entry(7, 4),
            ]
        )
    )

    assert listener.get_menu() == {"good": 3}


def test_duplicate_labels_on_different_paths_are_non_dispatchable() -> None:
    listener = MissionMenuListener(port=0, debounce_seconds=0)

    listener._handle_datagram(
        _datagram(
            [
                _entry("CHECK IN", 2, ["ATC"]),
                _entry("check in", 9, ["Support"]),
            ]
        )
    )

    assert listener.get_menu() == {}
    assert listener.get_health().ambiguous_labels == ("CHECK IN",)


def test_identical_duplicate_entry_is_harmless() -> None:
    listener = MissionMenuListener(port=0, debounce_seconds=0)
    entry = _entry("CHECK IN", 2, ["ATC"])

    listener._handle_datagram(_datagram([entry, entry]))

    assert listener.get_menu() == {"CHECK IN": 2}
    assert listener.get_health().ambiguous_labels == ()


def test_older_revision_is_ignored_but_a_new_session_resets_revision() -> None:
    listener = MissionMenuListener(port=0, debounce_seconds=0)
    listener._handle_datagram(_datagram([_entry("NEW", 5)], revision=5))

    listener._handle_datagram(_datagram([_entry("OLD", 1)], revision=4))
    assert listener.get_menu() == {"NEW": 5}

    listener._handle_datagram(
        _datagram([_entry("NEXT SESSION", 0)], session="dcs-session-2", revision=1)
    )
    assert listener.get_menu() == {"NEXT SESSION": 0}


def test_new_session_can_accumulate_revisions_before_its_first_commit() -> None:
    listener = MissionMenuListener(port=0, debounce_seconds=60)
    listener._handle_datagram(_datagram([_entry("OLD", 0)], revision=50))
    listener._commit_pending()

    listener._handle_datagram(_datagram([_entry("FIRST", 1)], session="dcs-session-2", revision=1))
    listener._handle_datagram(_datagram([_entry("SECOND", 2)], session="dcs-session-2", revision=2))
    listener._commit_pending()

    assert listener.get_menu() == {"SECOND": 2}
    assert listener.get_health().revision == 2
    listener.stop()


def test_legacy_unstamped_and_foreign_messages_are_rejected() -> None:
    listener = MissionMenuListener(port=0, debounce_seconds=0)

    listener._handle_datagram(b"not json at all")
    listener._handle_datagram(json.dumps({"type": "something.else", "menu": {"x": 1}}).encode())
    listener._handle_datagram(json.dumps({"type": "vaivox.f10menu", "menu": {"stale": 7}}).encode())

    assert listener.get_menu() == {}
    assert listener.get_health().runtime_confirmed is False


def test_persisted_snapshot_is_diagnostic_only_and_never_restored(tmp_path: Path) -> None:
    path = tmp_path / "f10_menu.json"
    listener = MissionMenuListener(port=0, persist_path=path, debounce_seconds=0)

    listener._handle_datagram(_datagram([_entry("FLEX NORTH", 2)], revision=7))
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["protocol"] == MENU_PROTOCOL_VERSION
    assert record["session"] == "dcs-session-1"
    assert record["revision"] == 7
    assert record["menu"] == {"FLEX NORTH": 2}

    restored = MissionMenuListener(port=0, persist_path=path, debounce_seconds=0)
    assert restored.get_menu() == {}
    assert restored.get_health().runtime_confirmed is False


def test_empty_loaded_snapshot_confirms_the_runtime_without_commands() -> None:
    listener = MissionMenuListener(port=0, debounce_seconds=0)

    listener._handle_datagram(_datagram([], phase="loaded"))

    health = listener.get_health()
    assert health.runtime_confirmed is True
    assert health.session_id == "dcs-session-1"
    assert health.command_count == 0


def test_lua_empty_table_encoding_is_accepted_as_an_empty_entry_list() -> None:
    listener = MissionMenuListener(port=0, debounce_seconds=0)
    payload = json.loads(_datagram([]))
    payload["entries"] = {}

    listener._handle_datagram(json.dumps(payload).encode("utf-8"))

    assert listener.get_health().runtime_confirmed is True
    assert listener.get_menu() == {}


def test_menu_file_path_is_in_the_data_dir() -> None:
    assert menu_file_path("C:/data").name == "f10_menu.json"


def test_emit_callbacks_are_guarded() -> None:
    seen: list[int] = []
    errors: list[str] = []
    listener = MissionMenuListener(port=0, on_update=seen.append, on_error=errors.append)

    listener._emit_notify(12)
    listener._emit_error("bind failed")

    assert seen == [12]
    assert errors == ["bind failed"]


def test_emit_callbacks_swallow_consumer_errors() -> None:
    def boom(_value: object) -> None:
        raise RuntimeError("UI gone")

    listener = MissionMenuListener(port=0, on_update=boom, on_error=boom)

    listener._emit_notify(3)
    listener._emit_error("bind failed")
