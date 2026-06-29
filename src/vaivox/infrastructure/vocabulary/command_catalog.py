"""Load generated command metadata for the UI command browser.

The snapper intentionally consumes ``phrase_index.txt`` as a flat list of phrases. The UI
needs a little more context, though: VAICOM's keyword export knows which commands are
module-specific (for example ``F-4E AI WSO | Ground Crew``). This module reads the optional
``command_catalog.json`` sidecar generated next to the phrase index and degrades to flat,
unscoped entries when the sidecar is absent.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

COMMAND_CATALOG_FILE = "command_catalog.json"
COMMAND_CATALOG_VERSION = 1


@dataclass(frozen=True)
class CommandCatalogEntry:
    """One speakable command phrase plus optional scope metadata.

    Attributes:
        phrase: The phrase shown in the Commands window and present in the snap index.
        groups: Human-readable VAICOM groups/categories that contributed this phrase.
        aircraft: Extracted aircraft/module tags such as ``F-4E`` or ``AH-64D``.
        sources: Source files that contributed the phrase, for diagnostics.
    """

    phrase: str
    groups: tuple[str, ...] = ()
    aircraft: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


def load_command_catalog(
    data_dir: str | None,
    fallback_phrases: Iterable[str] = (),
) -> tuple[CommandCatalogEntry, ...]:
    """Load command entries from the generated sidecar, or build flat fallback entries.

    Args:
        data_dir: The per-user VAIVOX data directory the generator writes into.
        fallback_phrases: Flat phrases to expose when the metadata sidecar is absent or
            unreadable. This keeps older generated installs usable until the next refresh.

    Returns:
        De-duplicated command catalog entries sorted case-insensitively by phrase.
    """
    path = Path(data_dir) / COMMAND_CATALOG_FILE if data_dir else None
    if path is not None and path.is_file():
        try:
            loaded = _entries_from_payload(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as error:
            _LOGGER.warning("Failed to load command catalog '%s': %s", path, error)
        else:
            if loaded:
                return loaded

    return _dedupe_entries(CommandCatalogEntry(phrase.strip()) for phrase in fallback_phrases)


def entry_matches_aircraft(entry: CommandCatalogEntry, current_aircraft: str | None) -> bool:
    """Return whether ``entry`` is tagged for ``current_aircraft``.

    DCS module names are not perfectly stable across APIs (``F-4E-45MC`` vs ``F-4E``), so
    matching is deliberately prefix/containment based after punctuation is stripped.
    """
    current = _aircraft_key(current_aircraft)
    if not current:
        return False
    return any(_tags_match(_aircraft_key(tag), current) for tag in entry.aircraft)


def _entries_from_payload(payload: object) -> tuple[CommandCatalogEntry, ...]:
    if not isinstance(payload, dict) or payload.get("version") != COMMAND_CATALOG_VERSION:
        return ()
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        return ()
    entries: list[CommandCatalogEntry] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        phrase = raw.get("phrase")
        if not isinstance(phrase, str) or not phrase.strip():
            continue
        entries.append(
            CommandCatalogEntry(
                phrase=phrase.strip(),
                groups=_string_tuple(raw.get("groups")),
                aircraft=_string_tuple(raw.get("aircraft")),
                sources=_string_tuple(raw.get("sources")),
            )
        )
    return _dedupe_entries(entries)


def _dedupe_entries(entries: Iterable[CommandCatalogEntry]) -> tuple[CommandCatalogEntry, ...]:
    merged: dict[str, CommandCatalogEntry] = {}
    order: list[str] = []
    for entry in entries:
        phrase = entry.phrase.strip()
        if not phrase:
            continue
        key = phrase.casefold()
        if key not in merged:
            order.append(key)
            merged[key] = CommandCatalogEntry(
                phrase=phrase,
                groups=_unique(entry.groups),
                aircraft=_unique(entry.aircraft),
                sources=_unique(entry.sources),
            )
            continue
        previous = merged[key]
        merged[key] = CommandCatalogEntry(
            phrase=previous.phrase,
            groups=_unique((*previous.groups, *entry.groups)),
            aircraft=_unique((*previous.aircraft, *entry.aircraft)),
            sources=_unique((*previous.sources, *entry.sources)),
        )
    return tuple(sorted((merged[key] for key in order), key=lambda entry: entry.phrase.lower()))


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return _unique(item.strip() for item in value if isinstance(item, str) and item.strip())


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return tuple(unique)


def _tags_match(tag: str, current: str) -> bool:
    if not tag or not current:
        return False
    return tag == current or current.startswith(tag) or tag.startswith(current)


def _aircraft_key(value: str | None) -> str:
    if value is None:
        return ""
    return "".join(character for character in value.casefold() if character.isalnum())


__all__ = [
    "COMMAND_CATALOG_FILE",
    "COMMAND_CATALOG_VERSION",
    "CommandCatalogEntry",
    "entry_matches_aircraft",
    "load_command_catalog",
]
