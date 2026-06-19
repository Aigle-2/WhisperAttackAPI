"""Adapter that regenerates the VAICOM vocabulary into the data dir (ADR-0005).

VAICOM-derived data is never shipped; it is generated locally from the user's own
install. This adapter wraps the packaged generator in
:mod:`vaivox.infrastructure.vocabulary.vaicom_generator_core` and exposes it behind the
:class:`~vaivox.application.ports.VocabularyGenerator` port. The historical ``tools/``
script remains as a CLI wrapper, while frozen builds now carry the implementation inside
the ``vaivox`` package.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from vaivox.application.ports import VocabularyGenerationResult
from vaivox.infrastructure.vocabulary import vaicom_generator_core as generator

#: Output file names mirror the packaged generator and the loaders
#: (:mod:`vaivox.infrastructure.vocabulary.vaicom_keyterms` / ``.phrase_index``).
KEYTERMS_FILE = generator.KEYTERMS_FILE
PHRASE_INDEX_FILE = generator.PHRASE_INDEX_FILE

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
        """Whether the generated vocabulary is missing or older than install sources.

        Returns:
            ``True`` when either output file is absent, or a discoverable install has a
            source file newer than the outputs; ``False`` when up to date or when no
            install can be found to regenerate against.
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
            A :class:`~vaivox.application.ports.VocabularyGenerationResult`; generation is
            reported as skipped when no VAICOM install can be found, so startup can fall
            back to the generic seed.
        """
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
        root: Path | None = generator.discover_vaicom_root()
        return root


def _newest_source_mtime(root: Path, saved_games: Path) -> float | None:
    """Return the newest mtime among the VAICOM source files the generator reads.

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
