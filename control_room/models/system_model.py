"""SystemModel — single source of truth for all target state in the dashboard.

This is a QObject that holds the complete state of all 10 targets.
It receives updates from the MQTT client thread via QMetaObject.invokeMethod
(Pre-mortem F-01 mitigation: thread-safe MQTT→Qt bridge).

No widget ever writes to SystemModel directly. Widgets connect to Qt signals
and react to updates. This enforces a strict Model-View separation.

The SystemModel also tracks stale state (F-09 mitigation): if a target's
last update is older than 6 seconds, it's marked as stale.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from control_room.models.target_state import (
    FaultCode,
    PositionLabel,
    StatusPayload,
    TelemetryPayload,
)


class TargetData:
    """Complete state data for a single target, as seen by the dashboard.

    Args:
        target_id: Target identifier (e.g., 'T-01').

    Example:
        >>> td = TargetData("T-01")
        >>> td.online
        False
    """

    def __init__(self, target_id: str) -> None:
        self.target_id = target_id
        self.online: bool = False
        self.position: PositionLabel = PositionLabel.UNKNOWN
        self.position_pct: float = 0.0
        self.battery_soc: float = -1.0
        self.battery_voltage: float = -1.0
        self.fault: bool = False
        self.fault_code: FaultCode | None = None
        self.rssi_dbm: int = -100
        self.packet_loss_pct: float = 100.0
        self.uptime_s: int = 0
        self.motor_current_a: float = 0.0
        self.solar_w: float = 0.0
        self.temperature_c: float = 25.0
        self.sim_time_h: float = 0.0
        self.last_trace_id: str | None = None
        self.last_update_ts: float = 0.0  # Unix timestamp
        self.is_stale: bool = True  # No data yet = stale

    def update_from_status(self, status: StatusPayload) -> None:
        """Update this target's state from a status payload.

        Args:
            status: Validated StatusPayload from MQTT.

        Example:
            >>> td = TargetData("T-01")
            >>> import time
            >>> from control_room.models.target_state import StatusPayload, PositionLabel
            >>> status = StatusPayload(
            ...     target_id="T-01", online=True, position=PositionLabel.DOWN,
            ...     position_pct=0.0, battery_soc=85.0, battery_voltage=13.4,
            ...     fault=False, fault_code=None, trace_id=None,
            ...     ts=int(time.time() * 1000),
            ... )
            >>> td.update_from_status(status)
            >>> td.online
            True
        """
        self.online = status.online
        self.position = status.position
        self.position_pct = status.position_pct
        self.battery_soc = status.battery_soc
        self.battery_voltage = status.battery_voltage
        self.fault = status.fault
        self.fault_code = status.fault_code
        self.last_trace_id = status.trace_id
        self.last_update_ts = time.time()
        self.is_stale = False

    def update_from_telemetry(self, telemetry: TelemetryPayload) -> None:
        """Update this target's telemetry data.

        Args:
            telemetry: Validated TelemetryPayload from MQTT.

        Example:
            >>> td = TargetData("T-01")
            >>> from control_room.models.target_state import TelemetryPayload
            >>> telem = TelemetryPayload(
            ...     target_id="T-01", rssi_dbm=-53, packet_loss_pct=0.0,
            ...     uptime_s=120, motor_current_a=0.0, solar_w=150.0,
            ...     temperature_c=25.0, sim_time_h=2.0,
            ...     ts=int(time.time() * 1000),
            ... )
            >>> td.update_from_telemetry(telem)
            >>> td.rssi_dbm
            -53
        """
        self.rssi_dbm = telemetry.rssi_dbm
        self.packet_loss_pct = telemetry.packet_loss_pct
        self.uptime_s = telemetry.uptime_s
        self.motor_current_a = telemetry.motor_current_a
        self.solar_w = telemetry.solar_w
        self.temperature_c = telemetry.temperature_c
        self.sim_time_h = telemetry.sim_time_h
        self.last_update_ts = time.time()
        self.is_stale = False

    def check_staleness(self, timeout_s: float = 6.0) -> bool:
        """Check if this target's data is stale.

        A target is stale if no update has been received within timeout_s.

        Args:
            timeout_s: Staleness timeout in seconds.

        Returns:
            True if the target's data is stale.

        Example:
            >>> td = TargetData("T-01")
            >>> td.check_staleness()  # No updates yet
            True
        """
        if self.last_update_ts == 0:
            self.is_stale = True
            return True
        elapsed = time.time() - self.last_update_ts
        self.is_stale = elapsed > timeout_s
        return self.is_stale


class SystemModel(QObject):
    """Singleton model holding all target state for the dashboard.

    Thread-safety: All updates come through @pyqtSlot methods, which are
    invoked from the MQTT thread via QMetaObject.invokeMethod with
    Qt.QueuedConnection. This ensures all state mutations happen on the
    Qt event loop thread (Pre-mortem F-01 mitigation).

    Signals:
        target_updated(str): Emitted when a target's state changes.
        connection_changed(bool): Emitted when broker connection status changes.
        command_acked(str, str): Emitted when a command is acknowledged (target_id, trace_id).
        command_timed_out(str, str): Emitted when a command times out (target_id, trace_id).
        telemetry_received(str): Emitted when new telemetry arrives (target_id).

    Example:
        >>> model = SystemModel()
        >>> model.get_target("T-01").target_id
        'T-01'
    """

    # Qt signals — widgets connect to these
    target_updated = pyqtSignal(str)  # target_id
    connection_changed = pyqtSignal(bool)  # connected
    command_acked = pyqtSignal(str, str)  # target_id, trace_id
    command_timed_out = pyqtSignal(str, str)  # target_id, trace_id
    telemetry_received = pyqtSignal(str)  # target_id

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        # Initialize all 10 targets
        self._targets: dict[str, TargetData] = {}
        for i in range(1, 11):
            target_id = f"T-{i:02d}"
            self._targets[target_id] = TargetData(target_id)

        self._broker_connected = False

        # Staleness check timer (runs every 2 seconds)
        self._stale_timer = QTimer(self)
        self._stale_timer.timeout.connect(self._check_all_staleness)
        self._stale_timer.start(2000)

    def get_target(self, target_id: str) -> TargetData:
        """Get the state data for a specific target.

        Args:
            target_id: Target identifier (e.g., 'T-01').

        Returns:
            TargetData for the requested target.

        Example:
            >>> model = SystemModel()
            >>> td = model.get_target("T-01")
            >>> td.target_id
            'T-01'
        """
        return self._targets[target_id]

    def get_all_targets(self) -> dict[str, TargetData]:
        """Get all target state data.

        Returns:
            Dictionary mapping target_id to TargetData.

        Example:
            >>> model = SystemModel()
            >>> len(model.get_all_targets())
            10
        """
        return self._targets

    @property
    def broker_connected(self) -> bool:
        """Whether the MQTT broker is connected.

        Returns:
            True if connected.

        Example:
            >>> model = SystemModel()
            >>> model.broker_connected
            False
        """
        return self._broker_connected

    @pyqtSlot(str)
    def on_status_message(self, payload_json: str) -> None:
        """Handle a status message from MQTT (called on Qt thread).

        This slot is invoked via QMetaObject.invokeMethod from the MQTT
        thread, ensuring thread-safe access to the model (F-01 mitigation).

        Args:
            payload_json: Raw JSON string from MQTT.

        Example:
            >>> model = SystemModel()
            >>> model.on_status_message('{"target_id": "T-01", ...}')
        """
        try:
            status = StatusPayload.model_validate_json(payload_json)
        except Exception:
            return  # Malformed — logged by dispatcher

        target_id = status.target_id
        if target_id not in self._targets:
            return

        target = self._targets[target_id]
        target.update_from_status(status)

        # Check for command acknowledgement
        if status.trace_id:
            self.command_acked.emit(target_id, status.trace_id)

        self.target_updated.emit(target_id)

    @pyqtSlot(str)
    def on_telemetry_message(self, payload_json: str) -> None:
        """Handle a telemetry message from MQTT (called on Qt thread).

        Args:
            payload_json: Raw JSON string from MQTT.

        Example:
            >>> model = SystemModel()
            >>> model.on_telemetry_message('{"target_id": "T-01", ...}')
        """
        try:
            telemetry = TelemetryPayload.model_validate_json(payload_json)
        except Exception:
            return  # Malformed — logged by dispatcher

        target_id = telemetry.target_id
        if target_id not in self._targets:
            return

        self._targets[target_id].update_from_telemetry(telemetry)
        self.telemetry_received.emit(target_id)

    @pyqtSlot(bool)
    def on_connection_changed(self, connected: bool) -> None:
        """Handle broker connection state change.

        Args:
            connected: Whether the broker is now connected.

        Example:
            >>> model = SystemModel()
            >>> model.on_connection_changed(True)
        """
        self._broker_connected = connected
        self.connection_changed.emit(connected)

    def _check_all_staleness(self) -> None:
        """Periodic check for stale targets (F-09 mitigation).

        Updates the is_stale flag on all targets and emits target_updated
        signal for any that changed staleness status.
        """
        for target_id, target in self._targets.items():
            was_stale = target.is_stale
            target.check_staleness()
            if target.is_stale != was_stale:
                self.target_updated.emit(target_id)

    def get_online_count(self) -> int:
        """Count the number of currently online targets.

        Returns:
            Number of targets with online=True and not stale.

        Example:
            >>> model = SystemModel()
            >>> model.get_online_count()
            0
        """
        return sum(
            1 for t in self._targets.values()
            if t.online and not t.is_stale
        )
