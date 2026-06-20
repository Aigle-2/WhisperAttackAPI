"""Mission-scoped F10 vocabulary discovery from VAICOM's live logs.

VAICOM imports DCS F10 menu actions under identifiers prefixed with ``Action`` and logs
them in ``Logs/VAICOMPRO.log``. These entries are mission/server scoped: their human
labels should help the live STT request and command browser, but they must not be folded
into the permanent VAIVOX vocabulary source.

The overlay is scoped to the **current menu snapshot**: when mission markers exist,
:func:`parse_f10_phrases` reads only the block beginning at the final ``Mission title:``
marker. VAICOM logs ``Adding new`` / ``Updating existing`` lines on every scan, so those
lines are authoritative for live labels even when the older ``Set menu F10 item`` line is
not repeated. Numeric ids from ``Set`` lines remain diagnostic metadata only.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from vaivox.application.ports import MissionVocabularyDiagnostics, MissionVocabularySnapshot
from vaivox.domain.commands.model import CommandSurface, VaicomF10Action
from vaivox.infrastructure.vocabulary import vaicom_generator_core as generator

_LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_MISSION_F10_PHRASES = 500

_MISSION_MARKER_RE = re.compile(
    r"Mission title:\s*(?P<title>.*?),\s*Menu name:\s*(?P<menu>.*)",
    re.IGNORECASE,
)
_CURRENT_F10_RE = re.compile(
    r"\bSet menu F10 item:\s*(?P<identifier>Action\s+.*?),\s*"
    r"ActionIndex:\s*(?P<action_index>-?\d+),\s*Command ID:\s*(?P<command_id>-?\d+)",
    re.IGNORECASE,
)
_LEGACY_F10_RE = re.compile(
    r"\bSetting menu F10 item\s+(?P<identifier>Action\s+.*?)\s+with\s+"
    r"actionIndex\s+(?P<action_index>-?\d+)\s+as\s+command\s+(?P<command_id>-?\d+)",
    re.IGNORECASE,
)
_F10_ACTIVITY_RE = re.compile(
    r"\b(?:Adding new|Updating existing) menu item:\s*"
    r"(?P<identifier>Action\s+[^\r\n]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _F10Item:
    """One live VAICOM F10 menu item extracted from the mission log."""

    identifier: str
    label: str
    action_index: int | None
    command_id: int | None


class VaicomF10MissionVocabulary:
    """Read the current mission's imported F10 command surfaces from VAICOM's log.

    The log accumulates F10 imports across missions; :func:`parse_f10_phrases` uses the
    final mission scan block, so a later snapshot replaces the previous overlay.

    Args:
        log_path: Optional explicit ``VAICOMPRO.log`` path. When omitted, the adapter
            auto-discovers the VAICOM root and reads ``Logs/VAICOMPRO.log``.
        discover: Optional VAICOM-root discovery override for tests.
        max_phrases: Safety cap for large dynamic menus.
        live_index: Optional callable returning the settled current-session
            ``{label: ActionIndex}`` map from the DCS hook
            (:mod:`~vaivox.infrastructure.dcs.menu_listener`). It is the **only** source of
            executable indices. Historical log values remain diagnostic metadata and are
            always cleared from runtime targets before this map is applied (ADR-0012).
    """

    def __init__(
        self,
        log_path: str | None = None,
        discover: Callable[[], Path | None] | None = None,
        max_phrases: int = DEFAULT_MAX_MISSION_F10_PHRASES,
        live_index: Callable[[], Mapping[str, int]] | None = None,
    ) -> None:
        """Wire the optional log override, discovery hook, phrase cap, and live index."""
        self._log_path = Path(log_path) if log_path else None
        self._discover = discover
        self._max_phrases = max_phrases
        self._live_index = live_index

    def load(self) -> MissionVocabularySnapshot:
        """Return the current mission's F10 labels and command surfaces."""
        path = self._resolve_log_path()
        if path is None:
            return MissionVocabularySnapshot(
                (),
                reason="no VAICOM install found",
                diagnostics=MissionVocabularyDiagnostics(),
            )
        if not path.is_file():
            return MissionVocabularySnapshot(
                (),
                source=str(path),
                reason="VAICOM F10 log not found",
                diagnostics=MissionVocabularyDiagnostics(log_path=str(path)),
            )

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as error:
            _LOGGER.warning("Failed to read VAICOM F10 log '%s': %s", path, error)
            return MissionVocabularySnapshot(
                (),
                source=str(path),
                reason="VAICOM F10 log unreadable",
                diagnostics=MissionVocabularyDiagnostics(log_path=str(path)),
            )

        items = self._with_live_index(parse_f10_items(text, max_phrases=self._max_phrases))
        phrases = [item.label for item in items]
        return MissionVocabularySnapshot(
            tuple(phrases),
            surfaces=tuple(
                _surface_from_item(item, dispatch_index=item.action_index) for item in items
            ),
            source=str(path),
            reason="loaded" if phrases else "no F10 commands found",
            diagnostics=_build_diagnostics(path, text, phrases),
        )

    def _with_live_index(self, items: list[_F10Item]) -> list[_F10Item]:
        """Apply only current-session live indices, clearing historical fallbacks.

        A missing listener, listener fault, empty handshake, or label absent from the live
        map leaves that item visible but non-dispatchable. This is deliberately fail-closed:
        a stale ``ActionIndex`` can execute a different F10 action.
        """
        safe_items = [replace(item, action_index=None) for item in items]
        if self._live_index is None:
            return safe_items
        try:
            live = self._live_index()
        except Exception as error:  # never let a live-source fault break the overlay
            _LOGGER.debug("Live F10 index unavailable: %s", error)
            return safe_items
        if not live:
            return safe_items
        lookup = {label.casefold(): index for label, index in live.items()}
        return [_override_action_index(item, lookup) for item in safe_items]

    def _resolve_log_path(self) -> Path | None:
        if self._log_path is not None:
            return self._log_path

        root = self._discover_root()
        if root is None:
            return None
        return root / "Logs" / "VAICOMPRO.log"

    def _discover_root(self) -> Path | None:
        if self._discover is not None:
            return self._discover()
        return generator.discover_vaicom_root()


def parse_f10_phrases(
    text: str,
    max_phrases: int = DEFAULT_MAX_MISSION_F10_PHRASES,
) -> list[str]:
    """Extract human-facing F10 labels from a log snapshot.

    When mission markers are present, only the final marker block is authoritative. A
    whole-file fallback is retained solely for older log formats without mission markers.
    """
    return [item.label for item in parse_f10_items(text, max_phrases=max_phrases)]


def parse_f10_surfaces(
    text: str,
    max_phrases: int = DEFAULT_MAX_MISSION_F10_PHRASES,
) -> list[CommandSurface]:
    """Extract non-dispatchable mission F10 surfaces from a log snapshot.

    Log indices are intentionally not copied onto executable targets. Runtime dispatchable
    surfaces are built by :class:`VaicomF10MissionVocabulary` only after live-map overlay.
    """
    return [_surface_from_item(item) for item in parse_f10_items(text, max_phrases=max_phrases)]


def parse_f10_items(
    text: str,
    max_phrases: int = DEFAULT_MAX_MISSION_F10_PHRASES,
) -> list[_F10Item]:
    """Extract scoped, de-duplicated VAICOM F10 items from a log snapshot.

    The current-mission block is scanned for the live command **labels** (its
    ``Adding new`` / ``Updating existing`` lines), but those lines omit the executable
    ``ActionIndex`` (ADR-0012). The index is therefore sourced separately, from the latest
    ``Set menu F10 item`` line per identifier across the whole log (see
    :func:`_action_metadata_map`), and merged onto the scoped items.
    """
    scoped_text, _latest_title, _has_marker = _current_mission_text(text)
    metadata = _action_metadata_map(text)
    items = [_with_action_metadata(item, metadata) for item in _extract_f10_items(scoped_text)]
    return _dedupe_items(items, max_phrases=max_phrases)


def _action_metadata_map(text: str) -> dict[str, tuple[int | None, int | None]]:
    """Map each F10 identifier to its latest ``(ActionIndex, Command ID)`` from the log.

    VAICOM logs ``Set menu F10 item: …, ActionIndex: N, Command ID: M`` only when it first
    *registers* a command; later mission scans emit marker-free ``Adding/Updating`` lines
    that omit the index. So the executable ``ActionIndex`` lives in older log lines, not the
    current mission block. We take the most recent occurrence per identifier across the
    whole log.

    Limitation (ADR-0012): ``ActionIndex`` is assigned by DCS per mission load, so the most
    recent value is correct while a mission's menu build order is stable but can be stale
    across *different* missions. The robust source is the live ``menuaux`` feed (a later
    enhancement); until then a ``None`` index leaves the item visible but non-dispatchable.
    """
    positioned: list[tuple[int, str, int | None, int | None]] = []
    for regex in (_CURRENT_F10_RE, _LEGACY_F10_RE):
        for match in regex.finditer(text):
            identifier = generator.clean_term(match.group("identifier"))
            positioned.append(
                (
                    match.start(),
                    identifier.casefold(),
                    _to_int(match.group("action_index")),
                    _to_int(match.group("command_id")),
                )
            )

    metadata: dict[str, tuple[int | None, int | None]] = {}
    # Sort by position so the last (most recent) occurrence per identifier wins.
    for _position, key, action_index, command_id in sorted(positioned, key=lambda value: value[0]):
        metadata[key] = (action_index, command_id)
    return metadata


def _with_action_metadata(
    item: _F10Item,
    metadata: dict[str, tuple[int | None, int | None]],
) -> _F10Item:
    """Fill an item's ``ActionIndex`` / ``Command ID`` from the whole-log map when missing."""
    if item.action_index is not None:
        return item
    found = metadata.get(item.identifier.casefold())
    if found is None:
        return item
    action_index, command_id = found
    return replace(
        item,
        action_index=action_index,
        command_id=item.command_id if item.command_id is not None else command_id,
    )


def _override_action_index(item: _F10Item, lookup: Mapping[str, int]) -> _F10Item:
    """Replace an item's ``ActionIndex`` with the live DCS value when its label is present."""
    index = lookup.get(item.label.casefold())
    if index is None or index == item.action_index:
        return item
    return replace(item, action_index=index)


def _extract_f10_items(text: str) -> list[_F10Item]:
    """Return metadata and live-scan VAICOM F10 items in log order."""
    positioned: list[tuple[int, _F10Item]] = []
    for regex in (_CURRENT_F10_RE, _LEGACY_F10_RE):
        for match in regex.finditer(text):
            identifier = generator.clean_term(match.group("identifier"))
            label = _label_from_identifier(identifier)
            if label is None:
                continue
            positioned.append(
                (
                    match.start(),
                    _F10Item(
                        identifier=identifier,
                        label=label,
                        action_index=_to_int(match.group("action_index")),
                        command_id=_to_int(match.group("command_id")),
                    ),
                )
            )

    for match in _F10_ACTIVITY_RE.finditer(text):
        identifier = generator.clean_term(match.group("identifier"))
        label = _label_from_identifier(identifier)
        if label is None:
            continue
        positioned.append(
            (
                match.start(),
                _F10Item(
                    identifier=identifier,
                    label=label,
                    action_index=None,
                    command_id=None,
                ),
            )
        )

    return [item for _position, item in sorted(positioned, key=lambda value: value[0])]


def _build_diagnostics(path: Path, text: str, phrases: list[str]) -> MissionVocabularyDiagnostics:
    """Capture verbose pull detail without reparsing repeated activity across the log."""
    folded = text.casefold()
    marker_count = folded.count("mission title:")
    scoped_text, latest, has_marker = _current_mission_text(text)
    scoped = _extract_f10_items(scoped_text)
    # Live activity repeats on every VAICOM scan and can produce hundreds of thousands of
    # historical matches. Count only bounded Set-item markers without re-running the full
    # regular-expression parser over a potentially large log.
    whole_log_matches = folded.count("set menu f10 item:") + folded.count("setting menu f10 item ")
    try:
        file_bytes = path.stat().st_size
    except OSError:
        file_bytes = len(text.encode("utf-8", errors="ignore"))
    return MissionVocabularyDiagnostics(
        log_path=str(path),
        file_bytes=file_bytes,
        mission_markers=marker_count,
        latest_mission=latest,
        scoped_matches=len(scoped),
        whole_log_matches=whole_log_matches,
        fallback_used=not has_marker and bool(scoped),
        deduped_phrases=len(phrases),
    )


def _current_mission_text(text: str) -> tuple[str, str | None, bool]:
    """Return the final mission scan block, or the whole legacy log without markers."""
    marker_start = max(text.rfind("Mission title:"), text.rfind("mission title:"))
    if marker_start < 0:
        return text, None, False

    marker = _MISSION_MARKER_RE.match(text, marker_start)
    if marker is None:
        return text, None, False
    latest_title = marker.group("title").strip()
    return text[marker_start:], latest_title, True


def _dedupe_items(items: list[_F10Item], max_phrases: int) -> list[_F10Item]:
    """De-duplicate by label with the final log occurrence winning."""
    seen: set[str] = set()
    reversed_items: list[_F10Item] = []
    for item in reversed(items):
        key = item.label.lower()
        if key in seen:
            continue
        seen.add(key)
        reversed_items.append(item)
        if len(reversed_items) >= max_phrases:
            break
    return list(reversed(reversed_items))


def _label_from_identifier(identifier: str) -> str | None:
    label = generator.clean_term(identifier)
    # Keep the identifier on the typed target; strip only for the human label.
    if label.lower().startswith("action "):
        label = label[7:].strip()
    if not label:
        return None

    words = label.split()
    if len(words) > 16 or len(label) > 120:
        return None
    return label


def _surface_from_item(
    item: _F10Item,
    *,
    dispatch_index: int | None = None,
) -> CommandSurface:
    """Build a surface, copying only an explicitly supplied live dispatch index."""
    return CommandSurface(
        id=f"mission_f10:{_surface_key(item.identifier)}",
        label=item.label,
        aliases=_f10_aliases(item.identifier),
        source="mission_f10",
        scope="mission",
        dispatch_target=VaicomF10Action(
            identifier=item.identifier,
            label=item.label,
            command_id=item.command_id,
            action_index=dispatch_index,
        ),
    )


def _f10_aliases(identifier: str) -> tuple[str, ...]:
    return (identifier,)


def _surface_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return key or "unnamed"


def _to_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


__all__ = [
    "DEFAULT_MAX_MISSION_F10_PHRASES",
    "VaicomF10MissionVocabulary",
    "parse_f10_items",
    "parse_f10_phrases",
    "parse_f10_surfaces",
]
