"""Mission-scoped F10 vocabulary discovery from VAICOM's live logs.

VAICOM imports DCS F10 menu actions as command phrases prefixed with ``Action`` and logs
them in ``Logs/VAICOMPRO.log``. These phrases are mission/server scoped: they should help
the live STT request and phrase snapper, but they must not be folded into the permanent
VAIVOX vocabulary source.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path

from vaivox.application.ports import MissionVocabularySnapshot
from vaivox.infrastructure.vocabulary import vaicom_generator_core as generator

_LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_MISSION_F10_PHRASES = 500

_MISSION_MARKER_RE = re.compile(
    r"Mission title:\s*(?P<title>.*?),\s*Menu name:\s*(?P<menu>.*)",
    re.IGNORECASE,
)
_CURRENT_F10_RE = re.compile(
    r"\bSet menu F10 item:\s*(?P<phrase>Action\s+.*?),\s*ActionIndex:",
    re.IGNORECASE,
)
_LEGACY_F10_RE = re.compile(
    r"\bSetting menu F10 item\s+(?P<phrase>Action\s+.*?)\s+with\s+actionIndex\b",
    re.IGNORECASE,
)


class VaicomF10MissionVocabulary:
    """Read the current mission's imported F10 commands from VAICOM's log.

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
        """Return mission-only F10 command phrases currently visible in VAICOM's log."""
        path = self._resolve_log_path()
        if path is None:
            return MissionVocabularySnapshot((), reason="no VAICOM install found")
        if not path.is_file():
            return MissionVocabularySnapshot(
                (), source=str(path), reason="VAICOM F10 log not found"
            )

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as error:
            _LOGGER.warning("Failed to read VAICOM F10 log '%s': %s", path, error)
            return MissionVocabularySnapshot(
                (), source=str(path), reason="VAICOM F10 log unreadable"
            )

        phrases = parse_f10_phrases(text, max_phrases=self._max_phrases)
        return MissionVocabularySnapshot(
            tuple(phrases),
            source=str(path),
            reason="loaded" if phrases else "no F10 commands found",
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
    """Extract VAICOM-style ``Action ...`` F10 phrases from a log snapshot.

    When mission markers are present, only blocks for the latest mission title are used.
    This keeps the overlay scoped to the current mission even if ``VAICOMPRO.log`` still
    contains older imports from the same VoiceAttack session.
    """
    scoped_text = _latest_mission_text(text)
    phrases: list[str] = []
    for regex in (_CURRENT_F10_RE, _LEGACY_F10_RE):
        phrases.extend(match.group("phrase") for match in regex.finditer(scoped_text))
    return _dedupe_phrases(phrases, max_phrases=max_phrases)


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


def _dedupe_phrases(phrases: list[str], max_phrases: int) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for phrase in phrases:
        normalized = _normalize_f10_phrase(phrase)
        if normalized is None:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
        if len(deduped) >= max_phrases:
            break
    return deduped


def _normalize_f10_phrase(value: str) -> str | None:
    phrase = generator.clean_term(value)
    if not phrase:
        return None
    if phrase.lower().startswith("action "):
        phrase = f"Action {phrase[7:].strip()}"
    else:
        phrase = f"Action {phrase}"

    words = phrase.split()
    if len(words) < 2 or len(words) > 16 or len(phrase) > 120:
        return None
    return phrase


__all__ = [
    "DEFAULT_MAX_MISSION_F10_PHRASES",
    "VaicomF10MissionVocabulary",
    "parse_f10_phrases",
]
