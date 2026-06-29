"""Adapter that regenerates the VAICOM vocabulary into the data dir (ADR-0005).

VAICOM-derived data is never shipped; it is generated locally from the user's own
install. This adapter wraps the packaged generator in
:mod:`vaivox.infrastructure.vocabulary.vaicom_generator_core` and exposes it behind the
:class:`~vaivox.application.ports.VocabularyGenerator` port. The historical ``tools/``
script remains as a CLI wrapper, while frozen builds now carry the implementation inside
the ``vaivox`` package.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from vaivox.application.ports import VocabularyGenerationResult
from vaivox.infrastructure.vocabulary import vaicom_generator_core as generator

#: Output file names mirror the packaged generator and the loaders
#: (:mod:`vaivox.infrastructure.vocabulary.vaicom_keyterms` / ``.phrase_index``).
KEYTERMS_FILE = generator.KEYTERMS_FILE
PHRASE_INDEX_FILE = generator.PHRASE_INDEX_FILE

_DEFAULT_SAVED_GAMES_NAME = "DCS"
_DCS_SAVED_GAMES_ENV = "DCS_SAVED_GAMES"


class VaicomVocabularyGenerator:
    """Generate VAICOM keyterms + the snap phrase index into the per-user data dir.

    Args:
        data_dir: The per-user VAIVOX data directory to write the output files into.
        saved_games: The DCS ``Saved Games`` directory (for ICAO overrides); defaults to
            the most likely local DCS profile, preferring the active-looking profile and
            honoring ``DCS_SAVED_GAMES`` when set.
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
        self._saved_games = saved_games or _discover_saved_games()
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
    for filename in ("keywords.txt", "keywords.html"):
        keywords = root / "Export" / filename
        if keywords.is_file():
            sources.append(keywords)
    for subdir in ("Profiles", "Export"):
        sources.extend((root / subdir).glob("*.vap"))
    logs = root / "Logs"
    for filename in ("WSO_DIALOG_CACHE_RAW.json", "WSO_ACTION_CACHE_RAW.json"):
        cache = logs / filename
        if cache.is_file():
            sources.append(cache)
    icao = saved_games / "Scripts" / "VAICOMPRO" / "ICAOOverrides.lua"
    if icao.is_file():
        sources.append(icao)

    mtimes = [path.stat().st_mtime for path in sources if path.is_file()]
    return max(mtimes) if mtimes else None


def _discover_saved_games(home: Path | None = None) -> Path:
    """Return the most likely DCS Saved Games profile without creating folders.

    VAICOM can be configured as Steam/release while the actual DCS profile is
    ``DCS.openbeta``. For vocabulary generation we only read ICAO overrides, so prefer the
    profile that looks active on disk and let ``DCS_SAVED_GAMES`` override the heuristic.
    """
    env_override = os.getenv(_DCS_SAVED_GAMES_ENV)
    if env_override:
        return Path(env_override)

    saved_games_root = (home or Path.home()) / "Saved Games"
    default_profile = saved_games_root / _DEFAULT_SAVED_GAMES_NAME
    candidates = _dcs_saved_games_candidates(saved_games_root)
    if not candidates:
        return default_profile
    return max(candidates, key=_saved_games_score)


def _dcs_saved_games_candidates(saved_games_root: Path) -> list[Path]:
    """Return existing DCS profile folders in deterministic preference order."""
    preferred_names = ("DCS.openbeta", "DCS", "DCS.openbeta_server", "DCS.server")
    preferred = [saved_games_root / name for name in preferred_names]
    discovered = sorted(saved_games_root.glob("DCS*")) if saved_games_root.is_dir() else []
    seen: set[Path] = set()
    candidates: list[Path] = []
    for path in [*preferred, *discovered]:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen or not path.is_dir():
            continue
        seen.add(resolved)
        candidates.append(path)
    return candidates


def _saved_games_score(path: Path) -> tuple[int, float, int]:
    """Score a DCS profile by active files, recency, and OpenBeta preference."""
    weighted_files = [
        (path / "Logs" / "dcs.log", 4),
        (path / "Scripts" / "Export.lua", 2),
        (path / "Scripts" / "VAICOMPRO" / "ICAOOverrides.lua", 1),
    ]
    existing_files = [candidate for candidate, _ in weighted_files if candidate.is_file()]
    active_score = sum(weight for candidate, weight in weighted_files if candidate.is_file())
    newest = max((candidate.stat().st_mtime for candidate in existing_files), default=0.0)
    openbeta_bonus = 1 if path.name.lower().startswith("dcs.openbeta") else 0
    return active_score, newest, openbeta_bonus
