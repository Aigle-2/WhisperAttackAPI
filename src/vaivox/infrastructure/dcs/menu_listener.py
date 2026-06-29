"""Receive fresh DCS F10 menu snapshots from the VAIVOX panel hook (ADR-0012).

``ActionIndex`` values are process- and menu-generation-specific. This listener therefore
starts empty on every VAIVOX run and exposes a dispatchable map only after a protocol-v2
snapshot arrives from the currently running DCS process. A disk mirror is retained for
diagnostics, never restored for dispatch.

The hook sends a cumulative entry list after every menu mutation and periodically re-sends
the settled snapshot at the same revision. The heartbeat lets a VAIVOX process started after
DCS establish a fresh live handshake; an already-synchronized listener ignores the duplicate
revision without invalidating its handles. The listener debounces changed snapshots and
commits only the settled menu. Duplicate labels on distinct menu paths are omitted from the
label-only dispatch map so speech resolution fails closed rather than choosing arbitrarily.
"""

from __future__ import annotations

import contextlib
import json
import logging
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from vaivox.domain.commands.model import MissionMenuEntry

_LOGGER = logging.getLogger(__name__)

#: VAIVOX-owned port the DCS hook broadcasts the live F10 menu to. Distinct from VAICOM's
#: 33491/33492 so VAIVOX never contends for a VAICOM-bound socket.
DEFAULT_MENU_PORT = 33493

#: Current hook/listener wire protocol. Older, unstamped snapshots are unsafe for dispatch.
MENU_PROTOCOL_VERSION = 2

#: Message type tag the hook stamps, so an unrelated datagram on the port is ignored.
_MESSAGE_TYPE = "vaivox.f10menu"

_RECV_BUFFER_BYTES = 64 * 1024
_MENU_FILE = "f10_menu.json"


@dataclass(frozen=True)
class MissionMenuHealth:
    """Observable listener and live-snapshot state for diagnostics."""

    listener_bound: bool
    runtime_confirmed: bool
    session_id: str | None
    revision: int | None
    current_aircraft: str | None
    command_count: int
    ambiguous_labels: tuple[str, ...]
    last_update_unix: float | None
    error: str | None


@dataclass(frozen=True)
class _MenuSnapshot:
    """One validated, path-aware hook snapshot ready for debounce/commit."""

    session_id: str
    revision: int
    phase: str
    current_aircraft: str | None
    entries: tuple[MissionMenuEntry, ...]
    ambiguous_labels: tuple[str, ...]

    @property
    def menu(self) -> dict[str, int]:
        """Compatibility label map, excluding path-ambiguous labels."""
        ambiguous = {label.casefold() for label in self.ambiguous_labels}
        return {
            entry.label: entry.action_index
            for entry in self.entries
            if entry.label.casefold() not in ambiguous
        }


class MissionMenuListener:
    """Keep the latest current-session F10 label-to-``ActionIndex`` map."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_MENU_PORT,
        persist_path: Path | None = None,
        on_update: Callable[[int], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        debounce_seconds: float = 0.4,
    ) -> None:
        """Configure the receiver without restoring any stale dispatch state.

        Args:
            host: Loopback host to bind.
            port: UDP port the DCS hook broadcasts to.
            persist_path: Optional diagnostic mirror of the last live snapshot. It is never
                restored because ``ActionIndex`` values cannot cross DCS sessions safely.
            on_update: Optional callback invoked with the settled, unambiguous command count.
            on_error: Optional callback invoked when the listener cannot bind.
            debounce_seconds: Quiet window before a cumulative snapshot becomes authoritative.
        """
        self._host = host
        self._port = port
        self._persist_path = persist_path
        self._on_update = on_update
        self._on_error = on_error
        self._debounce_seconds = debounce_seconds
        self._menu: dict[str, int] = {}
        self._entries: tuple[MissionMenuEntry, ...] = ()
        self._ambiguous_labels: tuple[str, ...] = ()
        self._session_id: str | None = None
        self._revision: int | None = None
        self._current_aircraft: str | None = None
        self._last_update_unix: float | None = None
        self._listener_bound = False
        self._error: str | None = None
        self._pending: _MenuSnapshot | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._commit_timer: threading.Timer | None = None
        self._running = False

    def get_menu(self) -> dict[str, int]:
        """Return the settled current-session map, excluding ambiguous labels."""
        with self._lock:
            return dict(self._menu)

    def get_entries(self) -> tuple[MissionMenuEntry, ...]:
        """Return every settled path-aware entry, including duplicate labels."""
        with self._lock:
            return self._entries

    def get_health(self) -> MissionMenuHealth:
        """Return an immutable snapshot of listener and runtime-handshake state."""
        with self._lock:
            return MissionMenuHealth(
                listener_bound=self._listener_bound,
                runtime_confirmed=self._session_id is not None,
                session_id=self._session_id,
                revision=self._revision,
                current_aircraft=self._current_aircraft,
                command_count=len(self._entries),
                ambiguous_labels=self._ambiguous_labels,
                last_update_unix=self._last_update_unix,
                error=self._error,
            )

    def start(self) -> None:
        """Start the background receive loop on a daemon thread (idempotent)."""
        if self._thread is not None:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._serve, name="vaivox-f10-menu-listener", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the receive loop, cancel a pending commit, and release the socket."""
        self._running = False
        if self._commit_timer is not None:
            self._commit_timer.cancel()
        if self._socket is not None:
            with contextlib.suppress(OSError):
                self._socket.close()

    def _serve(self) -> None:
        """Bind the UDP port and dispatch each datagram; degrade cleanly on failure."""
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.bind((self._host, self._port))
        except OSError as error:
            message = f"F10 menu listener could not bind {self._host}:{self._port} ({error})"
            with self._lock:
                self._error = message
                self._listener_bound = False
            _LOGGER.warning("%s; live index disabled.", message)
            self._emit_error(message)
            return
        with self._lock:
            self._listener_bound = True
            self._error = None
        _LOGGER.info("F10 menu listener bound %s:%s", self._host, self._port)
        while self._running:
            try:
                data, _addr = self._socket.recvfrom(_RECV_BUFFER_BYTES)
            except OSError:
                break
            self._handle_datagram(data)
        with self._lock:
            self._listener_bound = False

    def _handle_datagram(self, data: bytes) -> None:
        """Invalidate stale handles, then stage or immediately commit a snapshot."""
        snapshot = _parse_snapshot(data)
        if snapshot is None:
            return
        immediate = snapshot.phase in {"loaded", "reset"}
        with self._lock:
            session_changed = snapshot.session_id != self._session_id
            current_revision = self._revision if snapshot.session_id == self._session_id else None
            pending_revision = (
                self._pending.revision
                if self._pending is not None and self._pending.session_id == snapshot.session_id
                else None
            )
            newest = max(
                revision
                for revision in (current_revision, pending_revision, -1)
                if revision is not None
            )
            if snapshot.revision <= newest:
                return
            # Any menu mutation invalidates the previously committed handles immediately.
            # The cumulative replacement becomes dispatchable only after its build settles.
            self._menu = {}
            self._entries = ()
            self._ambiguous_labels = ()
            if session_changed:
                self._revision = None
                self._current_aircraft = None
            self._session_id = snapshot.session_id
            if immediate:
                self._pending = None
                self._entries = snapshot.entries
                self._menu = snapshot.menu
                self._revision = snapshot.revision
                self._current_aircraft = snapshot.current_aircraft
                self._last_update_unix = time.time()
                received_at = self._last_update_unix
            else:
                self._pending = snapshot
                received_at = None
        if immediate:
            if self._commit_timer is not None:
                self._commit_timer.cancel()
            assert received_at is not None
            self._persist(snapshot, received_at)
            self._emit_notify(len(snapshot.entries))
            return
        self._schedule_commit(snapshot.session_id, snapshot.revision)

    def _schedule_commit(self, session_id: str, revision: int) -> None:
        """Commit only after the hook's per-item datagrams have gone quiet."""
        if self._commit_timer is not None:
            self._commit_timer.cancel()
        if self._debounce_seconds <= 0:
            self._commit_pending(session_id, revision)
            return
        self._commit_timer = threading.Timer(
            self._debounce_seconds,
            self._commit_pending,
            (session_id, revision),
        )
        self._commit_timer.daemon = True
        self._commit_timer.start()

    def _commit_pending(
        self,
        expected_session: str | None = None,
        expected_revision: int | None = None,
    ) -> None:
        """Atomically expose and persist the latest settled snapshot."""
        with self._lock:
            snapshot = self._pending
            if snapshot is None:
                return
            if expected_session is not None and snapshot.session_id != expected_session:
                return
            if expected_revision is not None and snapshot.revision != expected_revision:
                return
            self._pending = None
            self._entries = snapshot.entries
            self._menu = dict(snapshot.menu)
            self._ambiguous_labels = snapshot.ambiguous_labels
            self._session_id = snapshot.session_id
            self._revision = snapshot.revision
            self._current_aircraft = snapshot.current_aircraft
            self._last_update_unix = time.time()
            received_at = self._last_update_unix
        self._persist(snapshot, received_at)
        self._emit_notify(len(snapshot.entries))

    def _emit_notify(self, count: int) -> None:
        """Invoke the update callback, guarding against a faulty consumer."""
        if self._on_update is None:
            return
        try:
            self._on_update(count)
        except Exception as error:  # a UI callback fault must not kill the listener
            _LOGGER.debug("F10 menu on_update callback failed: %s", error)

    def _emit_error(self, message: str) -> None:
        """Invoke the bind-error callback without letting UI code kill the listener."""
        if self._on_error is None:
            return
        try:
            self._on_error(message)
        except Exception as error:
            _LOGGER.debug("F10 menu on_error callback failed: %s", error)

    def _persist(self, snapshot: _MenuSnapshot, received_at: float) -> None:
        """Mirror live state for diagnostics; the file is deliberately never restored."""
        if self._persist_path is None:
            return
        record = {
            "protocol": MENU_PROTOCOL_VERSION,
            "session": snapshot.session_id,
            "revision": snapshot.revision,
            "phase": snapshot.phase,
            "aircraft": snapshot.current_aircraft,
            "received_at": received_at,
            "menu": snapshot.menu,
            "entries": [
                {
                    "label": entry.label,
                    "action_index": entry.action_index,
                    "path": list(entry.path),
                }
                for entry in snapshot.entries
            ],
            "ambiguous_labels": list(snapshot.ambiguous_labels),
        }
        try:
            self._persist_path.write_text(json.dumps(record), encoding="utf-8")
        except OSError as error:
            _LOGGER.debug(
                "Could not persist F10 menu diagnostics to %s: %s",
                self._persist_path,
                error,
            )


def menu_file_path(data_dir: str) -> Path:
    """Return the diagnostic live-menu mirror path in the application data directory."""
    return Path(data_dir) / _MENU_FILE


def _parse_snapshot(data: bytes) -> _MenuSnapshot | None:
    """Parse one current protocol snapshot, rejecting unstamped legacy messages."""
    try:
        record = json.loads(bytes(data).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict) or record.get("type") != _MESSAGE_TYPE:
        return None
    if record.get("protocol") != MENU_PROTOCOL_VERSION:
        return None
    session_id = record.get("session")
    revision = record.get("revision")
    phase = record.get("phase")
    aircraft = record.get("aircraft")
    if not isinstance(session_id, str) or not session_id:
        return None
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        return None
    if not isinstance(phase, str):
        return None
    if aircraft is not None and not isinstance(aircraft, str):
        return None
    parsed = _coerce_entries(record.get("entries"))
    if parsed is None:
        return None
    entries, ambiguous = parsed
    return _MenuSnapshot(
        session_id,
        revision,
        phase,
        aircraft.strip() if isinstance(aircraft, str) and aircraft.strip() else None,
        entries,
        ambiguous,
    )


def _coerce_entries(
    raw: object,
) -> tuple[tuple[MissionMenuEntry, ...], tuple[str, ...]] | None:
    """Build path-aware entries while reporting duplicate labels as ambiguous."""
    # DCS's Lua JSON encoder may serialize an empty table as ``{}`` rather than ``[]``.
    if raw == {}:
        return (), ()
    if not isinstance(raw, list):
        return None
    grouped: dict[str, list[tuple[str, int, tuple[str, ...]]]] = {}
    for raw_entry in raw:
        if not isinstance(raw_entry, dict):
            continue
        label = raw_entry.get("label")
        index = raw_entry.get("action_index")
        if not isinstance(label, str) or not label.strip():
            continue
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            continue
        path = _coerce_path(raw_entry.get("path"))
        grouped.setdefault(label.casefold(), []).append((label, index, path))

    entries: list[MissionMenuEntry] = []
    ambiguous: list[str] = []
    for values in grouped.values():
        signatures = {(index, path) for _label, index, path in values}
        label = values[0][0]
        if len(signatures) > 1:
            ambiguous.append(label)
        for index, path in sorted(signatures, key=lambda value: (value[1], value[0])):
            entries.append(MissionMenuEntry(label=label, action_index=index, path=path))
    entries.sort(key=lambda entry: (entry.path, entry.label.casefold(), entry.action_index))
    return tuple(entries), tuple(sorted(ambiguous, key=str.casefold))


def _coerce_path(raw: object) -> tuple[str, ...]:
    """Normalize the hook's optional submenu path for collision detection."""
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list):
        return tuple(value for value in raw if isinstance(value, str))
    if raw == {}:
        return ()
    return (repr(raw),)


__all__ = [
    "DEFAULT_MENU_PORT",
    "MENU_PROTOCOL_VERSION",
    "MissionMenuEntry",
    "MissionMenuHealth",
    "MissionMenuListener",
    "menu_file_path",
]
