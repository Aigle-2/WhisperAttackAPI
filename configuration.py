"""Legacy import shim: configuration now lives in the infrastructure layer.

Retained so the legacy entry point and the ported tests keep importing
``configuration`` while the migration completes. New code imports from
:mod:`vaivox.infrastructure.config.settings` directly.
"""

from vaivox.infrastructure.config.settings import (
    ConfigurationError,
    WhisperAttackConfiguration,
)

__all__ = ["ConfigurationError", "WhisperAttackConfiguration"]
