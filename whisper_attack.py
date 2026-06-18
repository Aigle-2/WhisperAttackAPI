"""Legacy launcher shim — the application entry point now lives in ``vaivox.main``.

Kept so ``python whisper_attack.py`` and the existing PyInstaller target keep working
during the migration. The single entry-point implementation is :func:`vaivox.main.main`.
"""

import os
import sys

# Make the in-repo ``src/vaivox`` package importable when launching from source.
_VAIVOX_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if os.path.isdir(_VAIVOX_SRC) and _VAIVOX_SRC not in sys.path:
    sys.path.insert(0, _VAIVOX_SRC)

from vaivox.main import main

if __name__ == "__main__":
    main()
