"""Legacy shim: spelled-code compaction now lives in the reconciliation domain.

Retained so existing imports keep working during the migration. New code should
import from :mod:`vaivox.domain.reconciliation.spelled_codes` directly.
"""

from vaivox.domain.reconciliation.spelled_codes import compact_spelled_codes

__all__ = ["compact_spelled_codes"]
