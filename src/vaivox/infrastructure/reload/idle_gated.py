"""Idle-gated atomic reference swap for hot-reloadable runtime state (ADR-0009).

ADR-0009 splits live changes by latency tolerance. The *hot atomic swap at idle* class —
a regenerated VAICOM vocabulary / phrase index (ADR-0005) or an LRU maintenance pass —
must take effect without a restart, yet **never mid-utterance**: swapping the matching
state while a command is in flight could change behaviour unpredictably (Option C,
rejected). This primitive captures exactly that contract, free of any concern for *what*
is being swapped.

:class:`IdleGatedSwap` holds one live value and accepts a *staged* replacement. The
replacement is applied atomically only at an **idle checkpoint** — when an injected
predicate reports idle (in production, "not recording") — either immediately on request
when already idle, or lazily at the next read once idle is reached. Consumers read the
live value through :meth:`current`, which hands back the reference under a lock; an
in-flight consumer keeps the reference it captured, so a concurrent swap can never alter
the value a call is already using. A swap that applies fires an optional observer callback
(ADR-0009 surfaces "vocabulary refreshed" in the UI).

The primitive is generic and pure infrastructure (a lock plus a predicate); it carries no
domain knowledge, so the same mechanism serves the phrase index today and the vocabulary
repository when it migrates to the in-memory source-of-truth model (ADR-0009).
"""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock


class IdleGatedSwap[T]:
    """A thread-safe holder whose value swaps atomically only at an idle checkpoint.

    Args:
        initial: The value live until the first swap is applied.
        is_idle: Predicate returning whether it is safe to swap now (not mid-utterance).
            Evaluated under the internal lock at each checkpoint, so keep it cheap and
            non-reentrant (a plain flag read such as ``lambda: not recorder.is_recording``).
        on_swap: Optional observer invoked with the newly-applied value each time a staged
            swap takes effect, called outside the lock (ADR-0009 UI signalling).
    """

    def __init__(
        self,
        initial: T,
        is_idle: Callable[[], bool],
        on_swap: Callable[[T], None] | None = None,
    ) -> None:
        """Seed the live value and the idle/observer callbacks (see the class docstring)."""
        self._lock = Lock()
        self._current = initial
        self._pending: T | None = None
        self._pending_announce = True
        self._is_idle = is_idle
        self._on_swap = on_swap

    def current(self) -> T:
        """Apply any staged value if idle, then return the live reference.

        Reading is the lazy checkpoint: a value staged while busy is applied here once
        idle is reached. The reference is captured under the lock and returned, so the
        caller is unaffected by any swap requested afterwards.

        Returns:
            The live value (the just-applied staged value when a deferred swap landed here).
        """
        with self._lock:
            applied, announce = self._apply_pending_if_idle_locked()
            value = self._current
        if applied and announce:
            self._announce(value)
        return value

    def request_swap(self, value: T, announce: bool = True) -> bool:
        """Stage ``value`` and apply it immediately if idle, else defer to the next read.

        The latest staged value wins: requesting again before an apply replaces the
        pending value, so an older regeneration never clobbers a newer one.

        Args:
            value: The replacement to make live at the next idle checkpoint.
            announce: Whether the observer should be notified when this swap applies.

        Returns:
            ``True`` if the swap was applied now (idle), ``False`` if it was staged for the
            next idle checkpoint.
        """
        with self._lock:
            self._pending = value
            self._pending_announce = announce
            applied, should_announce = self._apply_pending_if_idle_locked()
            current = self._current
        if applied and should_announce:
            self._announce(current)
        return applied

    def _apply_pending_if_idle_locked(self) -> tuple[bool, bool]:
        """Promote the pending value to live when idle. The caller must hold the lock.

        Returns:
            A pair of ``(applied, announce)`` flags for the pending value.
        """
        pending = self._pending
        if pending is not None and self._is_idle():
            self._current = pending
            self._pending = None
            return True, self._pending_announce
        return False, False

    def _announce(self, value: T) -> None:
        """Fire the observer for a freshly-applied swap (called outside the lock)."""
        if self._on_swap is not None:
            self._on_swap(value)
