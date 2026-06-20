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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from vaivox.application.ports import MissionVocabularyDiagnostics, MissionVocabularySnapshot
from vaivox.domain.commands.model import CommandSurface, MissionMenuEntry, VaicomF10Action
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
        live_entries: Callable[[], Sequence[MissionMenuEntry]] | None = None,
        action_aliases: Callable[[], Mapping[str, tuple[str, ...]]] | None = None,
    ) -> None:
        """Wire the optional log override, discovery hook, phrase cap, and live index."""
        self._log_path = Path(log_path) if log_path else None
        self._discover = discover
        self._max_phrases = max_phrases
        self._live_index = live_index
        self._live_entries = live_entries
        self._action_aliases = action_aliases

    def load(self) -> MissionVocabularySnapshot:
        """Return the current mission's F10 labels and command surfaces."""
        path = self._resolve_log_path()
        if path is None:
            return self._snapshot(
                (),
                reason="no VAICOM install found",
                diagnostics=MissionVocabularyDiagnostics(),
            )
        if not path.is_file():
            return self._snapshot(
                (),
                source=str(path),
                reason="VAICOM F10 log not found",
                diagnostics=MissionVocabularyDiagnostics(log_path=str(path)),
            )

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as error:
            _LOGGER.warning("Failed to read VAICOM F10 log '%s': %s", path, error)
            return self._snapshot(
                (),
                source=str(path),
                reason="VAICOM F10 log unreadable",
                diagnostics=MissionVocabularyDiagnostics(log_path=str(path)),
            )

        items = parse_f10_items(text, max_phrases=self._max_phrases)
        return self._snapshot(
            items,
            source=str(path),
            reason="no live F10 handshake",
            diagnostics=_build_diagnostics(path, text, [item.label for item in items]),
        )

    def _snapshot(
        self,
        items: Sequence[_F10Item],
        *,
        source: str | None = None,
        reason: str,
        diagnostics: MissionVocabularyDiagnostics,
    ) -> MissionVocabularySnapshot:
        """Build active and unavailable surfaces around the live menu authority."""
        aliases = self._load_aliases()
        surfaces = self._build_surfaces(items, aliases)
        active = [surface for surface in surfaces if surface.available]
        phrases = _recognition_phrases(active)
        return MissionVocabularySnapshot(
            tuple(phrases),
            surfaces=tuple(surfaces),
            source=source,
            reason="loaded" if active else reason,
            diagnostics=diagnostics,
            display_phrases=_display_phrases(surfaces),
        )

    def _load_aliases(self) -> Mapping[str, tuple[str, ...]]:
        if self._action_aliases is None:
            return {}
        try:
            return self._action_aliases()
        except Exception as error:
            _LOGGER.warning("VAICOM action aliases unavailable: %s", error)
            return {}

    def _build_surfaces(
        self,
        items: Sequence[_F10Item],
        aliases: Mapping[str, tuple[str, ...]],
    ) -> list[CommandSurface]:
        """Join diagnostic log metadata to the authoritative path-aware live menu."""
        by_label: dict[str, _F10Item] = {item.label.casefold(): item for item in items}
        live = self._read_live_entries()
        surfaces: list[CommandSurface] = []
        active_labels: set[str] = set()
        for entry in live[: self._max_phrases]:
            item = by_label.get(entry.label.casefold()) or _F10Item(
                identifier=f"Action {entry.label}",
                label=entry.label,
                action_index=None,
                command_id=None,
            )
            active_labels.add(entry.label.casefold())
            surfaces.append(
                _surface_from_item(
                    item,
                    dispatch_index=entry.action_index,
                    menu_path=entry.path,
                    semantic_aliases=_semantic_aliases(item.identifier, aliases),
                )
            )
        for item in items:
            if item.label.casefold() in active_labels:
                continue
            surfaces.append(
                _surface_from_item(
                    item,
                    semantic_aliases=_semantic_aliases(item.identifier, aliases),
                    available=False,
                    unavailable_reason="not present in the settled live DCS F10 menu",
                )
            )
        return surfaces

    def _read_live_entries(self) -> tuple[MissionMenuEntry, ...]:
        try:
            if self._live_entries is not None:
                return tuple(self._live_entries())
            if self._live_index is not None:
                return tuple(
                    MissionMenuEntry(label=label, action_index=index)
                    for label, index in self._live_index().items()
                )
        except Exception as error:
            _LOGGER.debug("Live F10 menu unavailable: %s", error)
        return ()

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
    menu_path: tuple[str, ...] = (),
    semantic_aliases: tuple[str, ...] = (),
    available: bool = True,
    unavailable_reason: str | None = None,
) -> CommandSurface:
    """Build a surface, copying only an explicitly supplied live dispatch index."""
    return CommandSurface(
        id=f"mission_f10:{_surface_key(item.identifier)}:{_surface_key('/'.join(menu_path))}",
        label=item.label,
        aliases=_f10_aliases(item.identifier),
        source="mission_f10",
        scope="mission",
        dispatch_target=VaicomF10Action(
            identifier=item.identifier,
            label=item.label,
            command_id=item.command_id,
            action_index=dispatch_index,
            menu_path=menu_path,
        ),
        semantic_aliases=semantic_aliases,
        available=available,
        unavailable_reason=unavailable_reason,
    )


def _f10_aliases(identifier: str) -> tuple[str, ...]:
    return (identifier,)


def _semantic_aliases(
    identifier: str,
    aliases: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """Return only aliases joined by exact normalized VAICOM action identifier."""
    return tuple(aliases.get(" ".join(identifier.split()).casefold(), ()))


def _recognition_phrases(surfaces: Sequence[CommandSurface]) -> list[str]:
    phrases: list[str] = []
    seen: set[str] = set()
    for surface in surfaces:
        for phrase in (surface.label, *surface.semantic_aliases):
            key = " ".join(phrase.split()).casefold()
            if key and key not in seen:
                seen.add(key)
                phrases.append(phrase)
    return phrases


def _display_phrases(surfaces: Sequence[CommandSurface]) -> tuple[str, ...]:
    rows: list[str] = []
    for surface in surfaces:
        target = surface.dispatch_target
        assert isinstance(target, VaicomF10Action)
        if surface.available:
            path = " / ".join(target.menu_path)
            suffix = f" — live ({path})" if path else " — live"
        else:
            suffix = " — unavailable"
        rows.append(f"{surface.label}{suffix}")
        rows.extend(f"  Say: {alias}" for alias in surface.semantic_aliases)
    return tuple(rows)


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
