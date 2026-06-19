"""Mission-scoped F10 vocabulary discovery from VAICOM's live logs.

VAICOM imports DCS F10 menu actions under identifiers prefixed with ``Action`` and logs
them in ``Logs/VAICOMPRO.log``. These entries are mission/server scoped: their human
labels should help the live STT request and command browser, but they must not be folded
into the permanent VAIVOX vocabulary source.

The overlay is scoped to the **current mission**: the log accumulates F10 imports across
missions and sessions, so :func:`parse_f10_phrases` keeps only the blocks for the latest
``Mission title:`` marker (see :func:`_latest_mission_text`). A new mission therefore
replaces the previous mission's command surfaces, while the current mission's labels are
shown even when they were imported before VAIVOX started.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _F10Item:
    """One live VAICOM F10 menu item extracted from the mission log."""

    identifier: str
    label: str
    action_index: int | None
    command_id: int | None


class VaicomF10MissionVocabulary:
    """Read the current mission's imported F10 command surfaces from VAICOM's log.

    The log accumulates F10 imports across missions; :func:`parse_f10_phrases` keeps only
    the latest mission's blocks, so a new mission replaces the previous overlay while the
    current mission's commands remain visible across a VAIVOX restart.

    Args:
        log_path: Optional explicit ``VAICOMPRO.log`` path. When omitted, the adapter
            auto-discovers the VAICOM root and reads ``Logs/VAICOMPRO.log``.
        discover: Optional VAICOM-root discovery override for tests.
        max_phrases: Safety cap for large dynamic menus.
    """

    def __init__(
        self,
        log_path: str | None = None,
        discover: Callable[[], Path | None] | None = None,
        max_phrases: int = DEFAULT_MAX_MISSION_F10_PHRASES,
    ) -> None:
        """Wire the optional log override, discovery hook, and phrase cap."""
        self._log_path = Path(log_path) if log_path else None
        self._discover = discover
        self._max_phrases = max_phrases

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

        items = parse_f10_items(text, max_phrases=self._max_phrases)
        phrases = [item.label for item in items]
        return MissionVocabularySnapshot(
            tuple(phrases),
            surfaces=tuple(_surface_from_item(item) for item in items),
            source=str(path),
            reason="loaded" if phrases else "no F10 commands found",
            diagnostics=_build_diagnostics(path, text, phrases),
        )

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

    When mission markers are present, only blocks for the latest mission title are used.
    This keeps the overlay scoped to the current mission even if ``VAICOMPRO.log`` still
    contains older imports from the same VoiceAttack session. If that scoped view holds no
    F10 items (VAICOM also logs menu markers, so the latest marker need not bracket the F10
    import block) the whole log is used as a fallback, so the commands still surface.
    """
    return [item.label for item in parse_f10_items(text, max_phrases=max_phrases)]


def parse_f10_surfaces(
    text: str,
    max_phrases: int = DEFAULT_MAX_MISSION_F10_PHRASES,
) -> list[CommandSurface]:
    """Extract typed mission F10 command surfaces from a log snapshot."""
    return [_surface_from_item(item) for item in parse_f10_items(text, max_phrases=max_phrases)]


def parse_f10_items(
    text: str,
    max_phrases: int = DEFAULT_MAX_MISSION_F10_PHRASES,
) -> list[_F10Item]:
    """Extract scoped, de-duplicated VAICOM F10 items from a log snapshot."""
    items = _extract_f10_items(_latest_mission_text(text))
    if not items:
        items = _extract_f10_items(text)
    return _dedupe_items(items, max_phrases=max_phrases)


def _extract_f10_items(text: str) -> list[_F10Item]:
    """Return the raw VAICOM F10 items matched by either log format."""
    items: list[_F10Item] = []
    for regex in (_CURRENT_F10_RE, _LEGACY_F10_RE):
        for match in regex.finditer(text):
            identifier = generator.clean_term(match.group("identifier"))
            label = _label_from_identifier(identifier)
            if label is None:
                continue
            items.append(
                _F10Item(
                    identifier=identifier,
                    label=label,
                    action_index=_to_int(match.group("action_index")),
                    command_id=_to_int(match.group("command_id")),
                )
            )
    return items


def _build_diagnostics(path: Path, text: str, phrases: list[str]) -> MissionVocabularyDiagnostics:
    """Capture verbose pull detail for the diagnostic log (cheap; F10 logs are small)."""
    markers = list(_MISSION_MARKER_RE.finditer(text))
    latest = markers[-1].group("title").strip() if markers else None
    scoped = _extract_f10_items(_latest_mission_text(text))
    whole = _extract_f10_items(text)
    try:
        file_bytes = path.stat().st_size
    except OSError:
        file_bytes = len(text.encode("utf-8", errors="ignore"))
    return MissionVocabularyDiagnostics(
        log_path=str(path),
        file_bytes=file_bytes,
        mission_markers=len(markers),
        latest_mission=latest,
        scoped_matches=len(scoped),
        whole_log_matches=len(whole),
        fallback_used=not scoped and bool(whole),
        deduped_phrases=len(phrases),
    )


def _latest_mission_text(text: str) -> str:
    markers = list(_MISSION_MARKER_RE.finditer(text))
    if not markers:
        return text

    latest_title = markers[-1].group("title").strip()
    blocks: list[str] = []
    for index, marker in enumerate(markers):
        start = marker.start()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        if marker.group("title").strip() == latest_title:
            blocks.append(text[start:end])
    return "\n".join(blocks)


def _dedupe_items(items: list[_F10Item], max_phrases: int) -> list[_F10Item]:
    seen: set[str] = set()
    deduped: list[_F10Item] = []
    for item in items:
        key = item.label.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= max_phrases:
            break
    return deduped


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


def _surface_from_item(item: _F10Item) -> CommandSurface:
    return CommandSurface(
        id=f"mission_f10:{_surface_key(item.identifier)}",
        label=item.label,
        aliases=_f10_aliases(item.label, item.identifier),
        source="mission_f10",
        scope="mission",
        dispatch_target=VaicomF10Action(
            identifier=item.identifier,
            label=item.label,
            command_id=item.command_id,
            action_index=item.action_index,
        ),
    )


def _f10_aliases(label: str, identifier: str) -> tuple[str, ...]:
    aliases = [identifier]
    if not label.casefold().startswith("request "):
        aliases.extend((f"Request {label}", f"Request a {label}"))
        if not label.casefold().endswith("transition"):
            aliases.append(f"Request {label} Transition")
    return tuple(aliases)


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
