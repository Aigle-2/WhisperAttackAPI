"""One-shot CLI: migrate the legacy flat vocabulary into the JSONL source (ADR-0004).

Reads the effective merged ``fuzzy_words.txt`` / ``word_mappings.txt`` (shipped defaults +
per-user overrides) via the app configuration and seeds the structured
``%LOCALAPPDATA%\\VAIVOX\\<kind>.jsonl`` source through the repository. Idempotent: re-running
skips entries whose id is already present.

    python tools/migrate_vocabulary.py
"""

import os
import sys
from datetime import datetime
from pathlib import Path


def _ensure_src_on_path() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


def main() -> None:
    _ensure_src_on_path()

    from vaivox.infrastructure.config.identity import VAIVOX
    from vaivox.infrastructure.config.settings import VaivoxConfiguration
    from vaivox.infrastructure.vocabulary.jsonl_repository import JsonlVocabularyRepository
    from vaivox.infrastructure.vocabulary.migration import migrate_legacy_vocabulary

    app_path = str(Path(__file__).resolve().parents[1])
    local_appdata = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    app_data_dir = os.path.join(local_appdata, VAIVOX.data_dir_name)
    os.makedirs(app_data_dir, exist_ok=True)

    config = VaivoxConfiguration(app_path, app_data_dir)
    repository = JsonlVocabularyRepository(app_data_dir)
    report = migrate_legacy_vocabulary(
        config.get_word_mappings(),
        config.get_fuzzy_words(),
        repository,
        datetime.now(),
    )

    print(
        f"Migrated {report.fuzzy_words} fuzzy words + {report.word_mappings} word mappings "
        f"({report.total} entries) into {app_data_dir}"
    )


if __name__ == "__main__":
    main()
