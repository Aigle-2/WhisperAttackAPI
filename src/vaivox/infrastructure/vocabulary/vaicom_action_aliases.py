"""Read VAICOM's locally exported action-to-spoken-alias catalog.

VAICOM-derived phrases are intentionally never shipped by VAIVOX (ADR-0005). This
adapter reads ``Export/keywords.html`` from the user's own VAICOM installation and
returns a conservative exact action mapping for mission-F10 enrichment.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from html.parser import HTMLParser
from pathlib import Path

from vaivox.infrastructure.vocabulary import vaicom_generator_core as generator

_LOGGER = logging.getLogger(__name__)


class VaicomActionAliasCatalog:
    """Load and mtime-cache VAICOM action aliases from ``keywords.html``."""

    def __init__(self, discover: Callable[[], Path | None] | None = None) -> None:
        """Wire optional VAICOM-root discovery (overridable for tests)."""
        self._discover = discover
        self._signature: tuple[str, int, int] | None = None
        self._aliases: dict[str, tuple[str, ...]] = {}
        self._warned: str | None = None

    def load(self) -> Mapping[str, tuple[str, ...]]:
        """Return normalized action identifiers mapped to their spoken aliases."""
        path = self._resolve_path()
        if path is None or not path.is_file():
            self._warn_once("VAICOM Export/keywords.html not found; using F10 labels only")
            self._signature = None
            self._aliases = {}
            return {}
        try:
            stat = path.stat()
            signature = (str(path), stat.st_mtime_ns, stat.st_size)
        except OSError as error:
            self._warn_once(f"Cannot inspect VAICOM aliases: {error}")
            return {}
        if signature == self._signature:
            return dict(self._aliases)
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            aliases = parse_action_aliases(text)
        except OSError as error:
            self._warn_once(f"Cannot read VAICOM aliases: {error}")
            return {}
        self._signature = signature
        self._aliases = aliases
        self._warned = None
        return dict(aliases)

    def _resolve_path(self) -> Path | None:
        root = self._discover() if self._discover is not None else generator.discover_vaicom_root()
        return None if root is None else root / "Export" / "keywords.html"

    def _warn_once(self, message: str) -> None:
        if message == self._warned:
            return
        self._warned = message
        _LOGGER.warning(message)


class _KeywordsHtmlParser(HTMLParser):
    """Small tolerant parser for VAICOM's generated keyword table rows."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, tuple[str, ...]]] = []
        self._in_row = False
        self._cell: str | None = None
        self._action_parts: list[str] = []
        self._alias_parts: list[str] | None = None
        self._aliases: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "tr":
            self._in_row = True
            self._action_parts = []
            self._aliases = []
        elif self._in_row and tag == "td":
            if "action" in classes:
                self._cell = "action"
            elif "aliases" in classes:
                self._cell = "aliases"
        elif self._cell == "aliases" and tag == "span" and "alias-item" in classes:
            self._alias_parts = []

    def handle_data(self, data: str) -> None:
        if self._cell == "action":
            self._action_parts.append(data)
        elif self._cell == "aliases" and self._alias_parts is not None:
            self._alias_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._alias_parts is not None:
            alias = _clean("".join(self._alias_parts))
            if alias:
                self._aliases.append(alias)
            self._alias_parts = None
        elif tag == "td":
            self._cell = None
            self._alias_parts = None
        elif tag == "tr" and self._in_row:
            action = _clean("".join(self._action_parts))
            if action:
                self.rows.append((action, tuple(self._aliases)))
            self._in_row = False
            self._cell = None


def parse_action_aliases(html: str) -> dict[str, tuple[str, ...]]:
    """Parse exact action identifiers and ordered aliases from VAICOM HTML."""
    parser = _KeywordsHtmlParser()
    parser.feed(html)
    collected: dict[str, list[str]] = {}
    for action, aliases in parser.rows:
        key = _normalize(action)
        if not key:
            continue
        bucket = collected.setdefault(key, [])
        seen = {_normalize(alias) for alias in bucket}
        for alias in aliases:
            normalized = _normalize(alias)
            if normalized and normalized not in seen:
                seen.add(normalized)
                bucket.append(alias)
    return {key: tuple(aliases) for key, aliases in collected.items()}


def _clean(value: str) -> str:
    return " ".join(value.split())


def _normalize(value: str) -> str:
    return _clean(value).casefold()


__all__ = ["VaicomActionAliasCatalog", "parse_action_aliases"]
