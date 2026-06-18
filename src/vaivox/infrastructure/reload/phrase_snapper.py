"""Hot-reloadable phrase snapper: swap the phrase index in at idle (ADR-0009).

The conservative :class:`~vaivox.domain.reconciliation.snapper.PhraseSnapper` is built
from a frozen phrase index. ADR-0011's index is regenerated from a VAICOM install
(ADR-0005), and ADR-0009 says a regenerated index should take effect **without a
restart** — but only when idle, never while a command is being reconciled.

:class:`ReloadablePhraseSnapper` is the infrastructure adapter that delivers that. It
satisfies the application's :class:`~vaivox.application.ports.PhraseMatcher` port (so
``StopAndReconcile`` depends only on the port, not on this adapter), delegating each
:meth:`snap` to the live domain snapper held in an
:class:`~vaivox.infrastructure.reload.idle_gated.IdleGatedSwap`. A new index supplied to
:meth:`reload` is swapped in atomically at the next idle checkpoint; an in-flight ``snap``
keeps the snapper it captured, so matching behaviour never changes mid-utterance.

The eval (ADR-0008) deliberately does **not** use this adapter — it constructs a plain
frozen ``PhraseSnapper`` — so hot-reload can never leak non-determinism into the metrics.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from vaivox.domain.reconciliation.snapper import PhraseSnapper, SnapResult, build_snapper
from vaivox.infrastructure.reload.idle_gated import IdleGatedSwap


class ReloadablePhraseSnapper:
    """A :class:`~vaivox.application.ports.PhraseMatcher` with an idle-hot-swappable index.

    Args:
        initial: The snapper live until the first successful reload.
        is_idle: Predicate reporting whether a swap is safe now (production wires this to
            "not currently recording"); see
            :class:`~vaivox.infrastructure.reload.idle_gated.IdleGatedSwap`.
        on_reload: Optional observer invoked with the new phrase count each time an index
            actually swaps in (ADR-0009 surfaces "vocabulary refreshed: N phrases").
    """

    def __init__(
        self,
        initial: PhraseSnapper,
        is_idle: Callable[[], bool],
        on_reload: Callable[[int], None] | None = None,
    ) -> None:
        """Wire the initial snapper and the idle/observer callbacks."""
        self._on_reload = on_reload
        self._swap: IdleGatedSwap[PhraseSnapper] = IdleGatedSwap(initial, is_idle, self._announce)

    def snap(self, text: str) -> SnapResult:
        """Snap ``text`` with the live index (applying a staged reload first if idle).

        Args:
            text: The reconciled command text to consider snapping.

        Returns:
            The live snapper's :class:`~vaivox.domain.reconciliation.snapper.SnapResult`.
        """
        return self._swap.current().snap(text)

    def reload(self, phrases: Sequence[str]) -> bool:
        """Stage a snapper built from ``phrases`` and apply it at the next idle checkpoint.

        Args:
            phrases: The regenerated valid command phrases (ADR-0005). An empty sequence
                installs a no-op snapper (every command is sent raw).

        Returns:
            ``True`` if the new index was applied immediately (idle), ``False`` if it was
            staged for the next idle checkpoint.
        """
        return self._swap.request_swap(build_snapper(phrases))

    @property
    def phrase_index(self) -> tuple[str, ...]:
        """The live phrase index (applies a staged reload first if idle)."""
        return self._swap.current().phrase_index

    def _announce(self, snapper: PhraseSnapper) -> None:
        """Report a freshly-applied index swap as a phrase count (ADR-0009 signalling)."""
        if self._on_reload is not None:
            self._on_reload(len(snapper.phrase_index))
