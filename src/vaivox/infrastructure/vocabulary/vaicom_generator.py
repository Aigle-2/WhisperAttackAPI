"""Adapter that (re)generates the VAICOM vocabulary into the data dir (ADR-0005).

VAICOM-derived data is never shipped (ADR-0005); it is generated locally from the user's
own install. This adapter wraps the gate-excluded ``tools/generate_vaicom_keyterms.py``
(auto-discovery + the parsing/cleaning logic that the migration plan keeps as a tool) and
exposes it behind the :class:`~vaivox.application.ports.VocabularyGenerator` port.

The generator module is imported **lazily and defensively**: this module imports cleanly
even where the generator is absent — e.g. a frozen PyInstaller build bundles only the
``vaivox`` package, not ``tools/`` — and an unavailable generator degrades to
``generated=False`` rather than raising into the background startup thread that drives it.
(Bundling/migrating the generator into the package for the frozen build is a follow-up,
tracked with the ADR-0005 "generator end-to-end" validation.)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from vaivox.application.ports import VocabularyGenerationResult

_LOGGER = logging.getLogger(__name__)

#: Output file names — mirror ``tools/generate_vaicom_keyterms.py`` and the loaders
#: (:mod:`vaivox.infrastructure.vocabulary.vaicom_keyterms` / ``.phrase_index``).
KEYTERMS_FILE = "vaicom_keyterms.txt"
PHRASE_INDEX_FILE = "phrase_index.txt"

_DEFAULT_SAVED_GAMES = Path.home() / "Saved Games" / "DCS"


class VaicomVocabularyGenerator:
    """Generate VAICOM keyterms + the snap phrase index into the per-user data dir.

    Args:
        data_dir: The per-user VAIVOX data directory to write the output files into.
        saved_games: The DCS ``Saved Games`` directory (for ICAO overrides); defaults to
            the standard ``~/Saved Games/DCS`` location.
        discover: Optional VAICOM-root discovery override (defaults to the generator's
            auto-discovery). Injected in tests to exercise staleness without a real install.
    """

    def __init__(
        self,
        data_dir: str,
        saved_games: Path | None = None,
        discover: Callable[[], Path | None] | None = None,
    ) -> None:
        """Wire the output directory, the Saved Games path, and the discovery override."""
        self._data_dir = Path(data_dir)
        self._saved_games = saved_games or _DEFAULT_SAVED_GAMES
        self._discover = discover

    @property
    def _keyterms_path(self) -> Path:
        return self._data_dir / KEYTERMS_FILE

    @property
    def _phrase_index_path(self) -> Path:
        return self._data_dir / PHRASE_INDEX_FILE

    def is_stale(self) -> bool:
        """Whether the generated vocabulary is missing or older than the install's sources.

        Returns:
            ``True`` when either output file is absent (first run), or a discoverable
            install has a source file newer than the outputs; ``False`` when up to date or
            when no install can be found to regenerate against.
        """
        if not self._keyterms_path.is_file() or not self._phrase_index_path.is_file():
            return True
        root = self._discover_root()
        if root is None:
            return False
        newest_source = _newest_source_mtime(root, self._saved_games)
        if newest_source is None:
            return False
        outputs_mtime = min(
            self._keyterms_path.stat().st_mtime, self._phrase_index_path.stat().st_mtime
        )
        return newest_source > outputs_mtime

    def generate(self) -> VocabularyGenerationResult:
        """Discover the VAICOM install and write the keyterms + phrase index.

        Returns:
            A :class:`~vaivox.application.ports.VocabularyGenerationResult`;
            ``generated=False`` (never raised) when the generator is unavailable or no
            install was found, so the background caller falls back to the generic seed.
        """
        try:
            from tools import generate_vaicom_keyterms as generator
        except Exception as error:  # ImportError in a frozen build without tools/
            _LOGGER.warning("VAICOM generator unavailable: %s", error)
            return VocabularyGenerationResult(generated=False, reason="generator unavailable")

        root = self._discover_root()
        if root is None:
            return VocabularyGenerationResult(generated=False, reason="no VAICOM install found")

        keyterms: list[str] = generator.generate_keyterms(root, self._saved_games)
        generator.write_keyterms(self._keyterms_path, keyterms, root, self._saved_games)
        phrases: list[str] = generator.generate_phrase_index(root, self._saved_games)
        generator.write_phrase_index(self._phrase_index_path, phrases, root, self._saved_games)

        return VocabularyGenerationResult(
            generated=True,
            reason="generated",
            keyterm_count=len(keyterms),
            phrase_count=len(phrases),
            source=str(root),
        )

    def _discover_root(self) -> Path | None:
        """Discover the VAICOM install root (the injected override, else auto-discovery)."""
        if self._discover is not None:
            return self._discover()
        try:
            from tools import generate_vaicom_keyterms as generator
        except Exception as error:  # ImportError in a frozen build without tools/
            _LOGGER.warning("VAICOM generator unavailable: %s", error)
            return None
        root: Path | None = generator.discover_vaicom_root()
        return root


def _newest_source_mtime(root: Path, saved_games: Path) -> float | None:
    """Return the newest mtime among the VAICOM source files the generator reads.

    If any source is newer than the generated outputs, the install changed since the last
    generation (so the vocabulary is stale).

    Args:
        root: The VAICOM install root.
        saved_games: The DCS Saved Games directory (for the ICAO overrides script).

    Returns:
        The newest source mtime, or ``None`` when no known source file is present.
    """
    sources: list[Path] = []
    keywords = root / "Export" / "keywords.txt"
    if keywords.is_file():
        sources.append(keywords)
    for subdir in ("Profiles", "Export"):
        sources.extend((root / subdir).glob("*.vap"))
    icao = saved_games / "Scripts" / "VAICOMPRO" / "ICAOOverrides.lua"
    if icao.is_file():
        sources.append(icao)

    mtimes = [path.stat().st_mtime for path in sources if path.is_file()]
    return max(mtimes) if mtimes else None
