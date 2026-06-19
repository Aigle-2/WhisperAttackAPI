"""JSONL vocabulary repository: versioned source + hot usage sidecar (ADR-0004).

The :class:`~vaivox.application.ports.VocabularyRepository` adapter. It implements
ADR-0004 Option A by keeping two artifact types per vocabulary kind:

- **Source** (``<kind>.jsonl``): one structured :class:`VocabularyEntry` per line —
  versioned, diff-friendly, hand/UI-editable.
- **Usage sidecar** (``<kind>.usage.json``): a ``id -> {last_used, hits}`` map written
  hot, never committed to git.

Default source may ship beside the app, while user additions/overrides and usage live in
the per-user VAIVOX data directory. The adapter reads them at
:meth:`JsonlVocabularyRepository.load` time, overlays user source on defaults, and joins
usage on ``id``.
All disk access degrades gracefully (logged, never raised) so a missing or malformed
sidecar can never crash reconciliation — usage simply resets to "never used".

This adapter performs plain, immediate writes. The thread-safe in-memory source of
truth and the idle-gated atomic swap are ADR-0009 concerns layered on top later; this
file does not preclude them.
"""

from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from vaivox.domain.vocabulary.model import (
    GovernedEntry,
    UsageStats,
    VocabularyEntry,
    VocabularyKind,
    VocabularyOrigin,
)

_LOGGER = logging.getLogger(__name__)


class JsonlVocabularyRepository:
    """Read/write structured vocabulary as JSONL source plus a JSON usage sidecar.

    Args:
        data_dir: The per-user VAIVOX data directory the source and sidecar live in.
        default_source_dir: Optional application directory holding shipped default JSONL
            sources. User data entries override default entries with the same id.
    """

    def __init__(self, data_dir: str, default_source_dir: str | None = None) -> None:
        """Bind the repository paths (resolved lazily per call)."""
        self._data_dir = Path(data_dir)
        self._default_source_dir = Path(default_source_dir) if default_source_dir else None

    def load(self, kind: VocabularyKind) -> list[GovernedEntry]:
        """Return every entry of ``kind`` joined with its usage stats.

        Args:
            kind: The vocabulary to load.

        Returns:
            One :class:`GovernedEntry` per source record. An entry with no sidecar row
            (e.g. a hand-added source line) is treated as never used: ``hits == 0`` and
            ``last_used`` at the Unix epoch, so the grace window does not protect it.
        """
        entries = self._read_source(kind)
        usage = self._read_usage(kind)
        governed: list[GovernedEntry] = []
        for entry in entries:
            stats = usage.get(entry.id, UsageStats(last_used=_EPOCH, hits=0))
            governed.append(GovernedEntry(entry=entry, usage=stats))
        return governed

    def mark_used(self, ids: Sequence[str], when: datetime) -> None:
        """Stamp ``last_used`` / increment ``hits`` for the credited entry ``ids``.

        Stamping spans every kind: an ``id`` is matched against whichever kind's source
        contains it. Unknown ids are ignored.

        Args:
            ids: The contributing entry ids.
            when: The match time to stamp.
        """
        wanted = set(ids)
        if not wanted:
            return
        for kind in VocabularyKind:
            known = {entry.id for entry in self._read_source(kind)}
            relevant = wanted & known
            if not relevant:
                continue
            usage = self._read_usage(kind)
            for entry_id in relevant:
                current = usage.get(entry_id, UsageStats(last_used=when, hits=0))
                usage[entry_id] = current.stamped(when)
            self._write_usage(kind, usage)

    def add(self, entry: VocabularyEntry, when: datetime) -> None:
        """Append a new source ``entry`` and seed its usage at ``when``.

        Args:
            entry: The new source entry.
            when: The creation time, written as the seed ``last_used`` so the grace
                window protects the entry from immediate eviction.
        """
        existing = self._read_source(entry.kind)
        existing_index = next(
            (index for index, other in enumerate(existing) if other.id == entry.id), None
        )
        if existing_index is not None:
            merged = _merge_entries(existing[existing_index], entry)
            if merged != existing[existing_index]:
                existing[existing_index] = merged
                self._write_effective_source(entry.kind, existing)
                usage = self._read_usage(entry.kind)
                usage.setdefault(entry.id, UsageStats(last_used=when, hits=0))
                self._write_usage(entry.kind, usage)
                return
            _LOGGER.warning(
                "Vocabulary entry '%s' already exists in %s; not re-adding.",
                entry.id,
                entry.kind.value,
            )
            return
        user_entries = self._read_user_source(entry.kind)
        user_entries.append(entry)
        self._write_user_source(entry.kind, user_entries)

        usage = self._read_usage(entry.kind)
        usage[entry.id] = UsageStats(last_used=when, hits=0)
        self._write_usage(entry.kind, usage)

    def replace_entries(self, kind: VocabularyKind, kept: Sequence[GovernedEntry]) -> None:
        """Persist the post-eviction ``kept`` set for ``kind`` (drops everything else).

        Both the source and the sidecar are rewritten to exactly the kept ids, so an
        evicted entry leaves no orphan usage row behind.

        Args:
            kind: The vocabulary being trimmed.
            kept: The retained governed entries.
        """
        kept_list = list(kept)
        self._write_effective_source(kind, [governed.entry for governed in kept_list])
        self._write_usage(kind, {governed.id: governed.usage for governed in kept_list})

    # -- source (JSONL) ----------------------------------------------------------------

    def _source_path(self, kind: VocabularyKind) -> Path:
        return self._data_dir / f"{kind.value}.jsonl"

    def _default_source_path(self, kind: VocabularyKind) -> Path | None:
        if self._default_source_dir is None:
            return None
        return self._default_source_dir / f"{kind.value}.jsonl"

    def _read_source(self, kind: VocabularyKind) -> list[VocabularyEntry]:
        merged: dict[str, VocabularyEntry] = {}
        for entry in self._read_default_source(kind):
            merged[entry.id] = entry
        for entry in self._read_user_source(kind):
            merged[entry.id] = entry
        return list(merged.values())

    def _read_default_source(self, kind: VocabularyKind) -> list[VocabularyEntry]:
        path = self._default_source_path(kind)
        if path is None:
            return []
        return self._read_source_file(path, kind)

    def _read_user_source(self, kind: VocabularyKind) -> list[VocabularyEntry]:
        return self._read_source_file(self._source_path(kind), kind)

    def _read_source_file(self, path: Path, kind: VocabularyKind) -> list[VocabularyEntry]:
        if not path.is_file():
            return []
        entries: list[VocabularyEntry] = []
        try:
            with open(path, encoding="utf-8") as file:
                for line_number, raw_line in enumerate(file, start=1):
                    line = raw_line.strip()
                    if not line:
                        continue
                    entry = _entry_from_record(line, kind)
                    if entry is None:
                        _LOGGER.warning(
                            "Skipping malformed vocabulary record at %s:%d", path, line_number
                        )
                        continue
                    entries.append(entry)
        except OSError as error:
            _LOGGER.warning("Failed to read vocabulary source '%s': %s", path, error)
            return []
        return entries

    def _write_user_source(self, kind: VocabularyKind, entries: list[VocabularyEntry]) -> None:
        lines = [json.dumps(_record_from_entry(entry), ensure_ascii=False) for entry in entries]
        body = "\n".join(lines)
        if body:
            body += "\n"
        self._atomic_write(self._source_path(kind), body)

    def _write_effective_source(self, kind: VocabularyKind, entries: list[VocabularyEntry]) -> None:
        defaults = {entry.id: entry for entry in self._read_default_source(kind)}
        if not defaults:
            self._write_user_source(kind, entries)
            return

        user_entries = [
            entry for entry in entries if entry.id not in defaults or entry != defaults[entry.id]
        ]
        self._write_user_source(kind, user_entries)

    # -- usage sidecar (JSON) ----------------------------------------------------------

    def _usage_path(self, kind: VocabularyKind) -> Path:
        return self._data_dir / f"{kind.value}.usage.json"

    def _read_usage(self, kind: VocabularyKind) -> dict[str, UsageStats]:
        path = self._usage_path(kind)
        if not path.is_file():
            return {}
        try:
            with open(path, encoding="utf-8") as file:
                raw = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            _LOGGER.warning("Failed to read usage sidecar '%s': %s", path, error)
            return {}
        if not isinstance(raw, dict):
            _LOGGER.warning("Usage sidecar '%s' is not an object; ignoring.", path)
            return {}
        usage: dict[str, UsageStats] = {}
        for entry_id, record in raw.items():
            stats = _usage_from_record(record)
            if stats is not None:
                usage[str(entry_id)] = stats
        return usage

    def _write_usage(self, kind: VocabularyKind, usage: dict[str, UsageStats]) -> None:
        payload = {entry_id: _record_from_usage(stats) for entry_id, stats in usage.items()}
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        self._atomic_write(self._usage_path(kind), body)

    # -- shared write helper -----------------------------------------------------------

    def _atomic_write(self, path: Path, body: str) -> None:
        """Write ``body`` to ``path`` via a temp file + replace (never partial on read)."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp.write(body)
                tmp_path = Path(tmp.name)
            tmp_path.replace(path)
        except OSError as error:
            _LOGGER.warning("Failed to write '%s': %s", path, error)


_EPOCH = datetime.fromtimestamp(0)


def _record_from_entry(entry: VocabularyEntry) -> dict[str, object]:
    """Serialize a source entry to its JSONL record (usage is never included)."""
    return {
        "id": entry.id,
        "term": entry.term,
        "aliases": list(entry.aliases),
        "origin": entry.origin.value,
    }


def _entry_from_record(line: str, kind: VocabularyKind) -> VocabularyEntry | None:
    """Parse one JSONL line into a :class:`VocabularyEntry`, or ``None`` if malformed."""
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    entry_id = record.get("id")
    term = record.get("term")
    if not isinstance(entry_id, str) or not isinstance(term, str):
        return None
    raw_aliases = record.get("aliases", [])
    aliases = tuple(str(alias) for alias in raw_aliases) if isinstance(raw_aliases, list) else ()
    origin = _origin_from_value(record.get("origin"))
    return VocabularyEntry(id=entry_id, kind=kind, term=term, aliases=aliases, origin=origin)


def _merge_entries(existing: VocabularyEntry, incoming: VocabularyEntry) -> VocabularyEntry:
    """Merge compatible entries with the same id, preserving the existing term/origin."""
    if (
        existing.kind is not VocabularyKind.WORD_MAPPING
        or incoming.kind is not existing.kind
        or incoming.term.casefold() != existing.term.casefold()
    ):
        return existing
    aliases = tuple(sorted({*existing.aliases, *incoming.aliases}, key=str.casefold))
    return VocabularyEntry(
        id=existing.id,
        kind=existing.kind,
        term=existing.term,
        aliases=aliases,
        origin=existing.origin,
    )


def _origin_from_value(value: object) -> VocabularyOrigin:
    """Map a stored origin string to the enum, defaulting to ``DEFAULT`` if unknown."""
    if isinstance(value, str):
        try:
            return VocabularyOrigin(value)
        except ValueError:
            pass
    return VocabularyOrigin.DEFAULT


def _record_from_usage(stats: UsageStats) -> dict[str, object]:
    """Serialize usage stats to a sidecar record (ISO timestamp, hit count)."""
    return {"last_used": stats.last_used.isoformat(), "hits": stats.hits}


def _usage_from_record(record: object) -> UsageStats | None:
    """Parse one sidecar record into :class:`UsageStats`, or ``None`` if malformed."""
    if not isinstance(record, dict):
        return None
    raw_last_used = record.get("last_used")
    raw_hits = record.get("hits", 0)
    if not isinstance(raw_last_used, str):
        return None
    try:
        last_used = datetime.fromisoformat(raw_last_used)
    except ValueError:
        return None
    hits = raw_hits if isinstance(raw_hits, int) and not isinstance(raw_hits, bool) else 0
    return UsageStats(last_used=last_used, hits=hits)
