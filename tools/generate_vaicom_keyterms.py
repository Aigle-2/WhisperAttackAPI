"""Compatibility CLI wrapper for the packaged VAICOM vocabulary generator."""

from __future__ import annotations

from vaivox.infrastructure.vocabulary.vaicom_generator_core import *  # noqa: F403
from vaivox.infrastructure.vocabulary.vaicom_generator_core import main


if __name__ == "__main__":
    main()
