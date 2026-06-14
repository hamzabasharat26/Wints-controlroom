"""Metrics panel — system-wide real-time metrics display.

Shows aggregate statistics across all 10 targets:
    - Online/offline/fault counts
    - Average RSSI and worst RSSI
    - Average battery SOC and lowest SOC
    - Total solar power generation
    - System uptime
    - Sim time clock

Updates every second from SystemModel.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from control_room.models.system_model import SystemModel


class MetricRow(QWidget):
    """Single metric row with label and value.

    Args:
        label: Metric name.
        parent: Parent widget.

    Example:
        >>> row = MetricRow("Online Targets")
        >>> row.set_value("8/10")
    """

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)

        self._label = QLabel(label)
        self._label.setFont(QFont("Segoe UI", 8))
        self._label.setStyleSheet("color: #6c7086;")
        layout.addWidget(self._label)

        self._value = QLabel("—")
        self._value.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        self._value.setStyleSheet("color: #cdd6f4;")
        layout.addWidget(self._value)

    def set_value(self, text: str, color: str = "#cdd6f4") -> None:
        """Update the displayed value.

        Args:
            text: Value text to display.
            color: CSS colour for the value text.

        Example:
            >>> row = MetricRow("Test")
            >>> row.set_value("42", "#a6e3a1")
        """
        self._value.setText(text)
        self._value.setStyleSheet(f"color: {color};")


class MetricsPanel(QWidget):
    """System-wide metrics panel with real-time updates.

    Args:
        system_model: The SystemModel to read aggregate data from.
        parent: Parent widget.

    Example:
        >>> model = SystemModel()
        >>> panel = MetricsPanel(model)
    """

    def __init__(
        self,
        system_model: SystemModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = system_model
        self._start_time = time.monotonic()
        self.setMinimumWidth(220)
        self.setMaximumWidth(280)

        self._setup_ui()
        self._start_timer()

    def _setup_ui(self) -> None:
        """Build the metrics panel layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)

        # Title
        title = QLabel("SYSTEM METRICS")
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        title.setStyleSheet("color: #89b4fa;")
        layout.addWidget(title)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #313244;")
        layout.addWidget(sep)

        # Metrics
        self._online_metric = MetricRow("TARGETS ONLINE")
        layout.addWidget(self._online_metric)

        self._fault_metric = MetricRow("FAULTED")
        layout.addWidget(self._fault_metric)

        self._avg_soc_metric = MetricRow("AVG BATTERY SOC")
        layout.addWidget(self._avg_soc_metric)

        self._worst_soc_metric = MetricRow("LOWEST SOC")
        layout.addWidget(self._worst_soc_metric)

        self._avg_rssi_metric = MetricRow("AVG RSSI")
        layout.addWidget(self._avg_rssi_metric)

        self._worst_rssi_metric = MetricRow("WORST RSSI")
        layout.addWidget(self._worst_rssi_metric)

        self._solar_metric = MetricRow("TOTAL SOLAR")
        layout.addWidget(self._solar_metric)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #313244;")
        layout.addWidget(sep2)

        self._sim_time_metric = MetricRow("SIM TIME")
        layout.addWidget(self._sim_time_metric)

        self._uptime_metric = MetricRow("SESSION UPTIME")
        layout.addWidget(self._uptime_metric)

        layout.addStretch()

    def _start_timer(self) -> None:
        """Start periodic update timer."""
        timer = QTimer(self)
        timer.timeout.connect(self._update_metrics)
        timer.start(1000)  # Every second

    def _update_metrics(self) -> None:
        """Pull data from SystemModel and update all metric rows."""
        targets = self._model.get_all_targets()

        online = sum(1 for t in targets.values() if t.online and not t.is_stale)
        faulted = sum(1 for t in targets.values() if t.fault and t.online)

        # Online count with colour
        if online == 10:
            self._online_metric.set_value(f"{online}/10", "#a6e3a1")
        elif online >= 5:
            self._online_metric.set_value(f"{online}/10", "#f9e2af")
        else:
            self._online_metric.set_value(f"{online}/10", "#f38ba8")

        # Faulted count
        if faulted == 0:
            self._fault_metric.set_value("0", "#a6e3a1")
        else:
            self._fault_metric.set_value(str(faulted), "#f38ba8")

        # Battery metrics
        socs = [t.battery_soc for t in targets.values() if t.online and t.battery_soc >= 0]
        if socs:
            avg_soc = sum(socs) / len(socs)
            min_soc = min(socs)
            soc_color = "#a6e3a1" if avg_soc > 50 else "#f9e2af" if avg_soc > 20 else "#f38ba8"
            self._avg_soc_metric.set_value(f"{avg_soc:.0f}%", soc_color)

            worst_color = "#a6e3a1" if min_soc > 50 else "#f9e2af" if min_soc > 20 else "#f38ba8"
            worst_target = min(
                (t for t in targets.values() if t.online and t.battery_soc >= 0),
                key=lambda t: t.battery_soc,
            )
            self._worst_soc_metric.set_value(
                f"{min_soc:.0f}% ({worst_target.target_id})", worst_color
            )
        else:
            self._avg_soc_metric.set_value("—")
            self._worst_soc_metric.set_value("—")

        # RSSI metrics
        rssis = [t.rssi_dbm for t in targets.values() if t.online and not t.is_stale]
        if rssis:
            avg_rssi = sum(rssis) / len(rssis)
            min_rssi = min(rssis)
            rssi_color = "#a6e3a1" if avg_rssi > -65 else "#f9e2af" if avg_rssi > -80 else "#f38ba8"
            self._avg_rssi_metric.set_value(f"{avg_rssi:.0f} dBm", rssi_color)

            worst_rssi_target = min(
                (t for t in targets.values() if t.online and not t.is_stale),
                key=lambda t: t.rssi_dbm,
            )
            self._worst_rssi_metric.set_value(
                f"{min_rssi} dBm ({worst_rssi_target.target_id})",
                "#f38ba8" if min_rssi < -80 else "#f9e2af",
            )
        else:
            self._avg_rssi_metric.set_value("—")
            self._worst_rssi_metric.set_value("—")

        # Solar total
        total_solar = sum(t.solar_w for t in targets.values() if t.online)
        self._solar_metric.set_value(f"{total_solar:.0f} W", "#f9e2af")

        # Sim time
        sim_times = [t.sim_time_h for t in targets.values() if t.online and t.sim_time_h > 0]
        if sim_times:
            avg_sim = sum(sim_times) / len(sim_times)
            hours = int(avg_sim) % 24
            minutes = int((avg_sim % 1) * 60)
            self._sim_time_metric.set_value(f"{hours:02d}:{minutes:02d} sim")

        # Session uptime
        elapsed = time.monotonic() - self._start_time
        mins = int(elapsed) // 60
        secs = int(elapsed) % 60
        self._uptime_metric.set_value(f"{mins:02d}:{secs:02d}")
