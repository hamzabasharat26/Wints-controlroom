"""Command tracker — tracks issued commands from button click to ack/timeout.

Each command gets a UUID (trace_id), is placed in a pending queue, and
the tracker waits for a status echo with the matching trace_id. If no
echo arrives within 500ms, the command is marked as timed out.

No optimistic UI: the target card only updates when the simulator
responds, not when the button is clicked.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


@dataclass
class PendingCommand:
    """A command that has been issued but not yet acknowledged.

    Args:
        target_id: Target the command was sent to.
        trace_id: Unique command identifier.
        cmd: Command type string.
        issued_at: Unix timestamp when the command was issued.
        timeout_ms: Timeout in milliseconds.

    Example:
        >>> pc = PendingCommand("T-01", "abc-123", "raise", time.time())
        >>> pc.is_timed_out()
        False
    """

    target_id: str
    trace_id: str
    cmd: str
    issued_at: float
    timeout_ms: float = 2000.0

    def is_timed_out(self) -> bool:
        """Check if this command has exceeded its timeout.

        Returns:
            True if the command has timed out.

        Example:
            >>> pc = PendingCommand("T-01", "abc", "raise", time.time() - 1.0)
            >>> pc.is_timed_out()
            True
        """
        elapsed_ms = (time.time() - self.issued_at) * 1000.0
        return elapsed_ms > self.timeout_ms


class CommandTracker(QObject):
    """Tracks command lifecycle: issued → pending → acked/timed_out.

    Signals:
        command_acked(str, str): target_id, trace_id — command was acknowledged.
        command_timed_out(str, str): target_id, trace_id — command timed out.

    Example:
        >>> tracker = CommandTracker()
        >>> trace_id = "abc-123"
        >>> tracker.issue("T-01", trace_id, "raise")
        >>> tracker.is_pending("T-01")
        True
    """

    command_acked = pyqtSignal(str, str)  # target_id, trace_id
    command_timed_out = pyqtSignal(str, str)  # target_id, trace_id

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        # Pending commands: target_id → PendingCommand
        self._pending: dict[str, PendingCommand] = {}

        # Timeout check timer (every 100ms)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check_timeouts)
        self._timer.start(100)

    def issue(self, target_id: str, trace_id: str, cmd: str) -> None:
        """Record a new pending command.

        Only one pending command per target at a time (F-23 mitigation:
        button debouncing). If a command is already pending for this target,
        it's replaced.

        Args:
            target_id: Target identifier.
            trace_id: Command trace_id.
            cmd: Command type string.

        Example:
            >>> tracker = CommandTracker()
            >>> tracker.issue("T-01", "abc-123", "raise")
            >>> tracker.is_pending("T-01")
            True
        """
        self._pending[target_id] = PendingCommand(
            target_id=target_id,
            trace_id=trace_id,
            cmd=cmd,
            issued_at=time.time(),
        )

    def acknowledge(self, target_id: str, trace_id: str) -> bool:
        """Acknowledge a pending command.

        Args:
            target_id: Target identifier.
            trace_id: Command trace_id from the status echo.

        Returns:
            True if a matching pending command was found and acked.

        Example:
            >>> tracker = CommandTracker()
            >>> tracker.issue("T-01", "abc-123", "raise")
            >>> tracker.acknowledge("T-01", "abc-123")
            True
        """
        pending = self._pending.get(target_id)
        if pending and pending.trace_id == trace_id:
            del self._pending[target_id]
            self.command_acked.emit(target_id, trace_id)
            return True
        return False

    def is_pending(self, target_id: str) -> bool:
        """Check if a command is pending for a target.

        Args:
            target_id: Target identifier.

        Returns:
            True if a command is pending (not yet acked or timed out).

        Example:
            >>> tracker = CommandTracker()
            >>> tracker.is_pending("T-01")
            False
        """
        return target_id in self._pending

    def _check_timeouts(self) -> None:
        """Periodic timeout check for all pending commands."""
        timed_out = [
            (tid, cmd) for tid, cmd in self._pending.items()
            if cmd.is_timed_out()
        ]
        for target_id, cmd in timed_out:
            del self._pending[target_id]
            self.command_timed_out.emit(target_id, cmd.trace_id)
