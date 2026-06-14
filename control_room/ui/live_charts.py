"""Live charts panel — rolling time-series plots using pyqtgraph.

Displays 4 charts updated every second from SystemModel:
    1. Avg Battery SOC (%) — rolling 120s window
    2. Avg RSSI (dBm) — rolling 120s window
    3. Online target count — rolling 120s window
    4. Total solar power (W) — rolling 120s window

Uses pyqtgraph (0.13.7) for GPU-accelerated real-time plotting.
Background colour matches the Catppuccin-Mocha dashboard theme.
"""

from __future__ import annotations

from collections import deque

import pyqtgraph as pg
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from control_room.models.system_model import SystemModel

# Chart window — 120 data points = 120 seconds of history
_WINDOW = 120

# Catppuccin Mocha colours
_BG = "#11111b"
_PLOT_BG = "#1e1e2e"
_GRID = "#313244"


def _configure_plot(plot: pg.PlotItem, title: str, ylabel: str, yrange: tuple[float, float], pen_color: str) -> pg.PlotDataItem:
    """Configure a pyqtgraph PlotItem with dark theme and return its curve."""
    plot.setTitle(title, color="#cdd6f4", size="9pt")
    plot.setLabel("left", ylabel, color="#6c7086")
    plot.getAxis("left").setTextPen(pg.mkPen(color="#6c7086"))
    plot.getAxis("bottom").setTextPen(pg.mkPen(color="#6c7086"))
    plot.getAxis("left").setPen(pg.mkPen(color="#313244"))
    plot.getAxis("bottom").setPen(pg.mkPen(color="#313244"))
    plot.setYRange(*yrange, padding=0.05)
    plot.showGrid(x=True, y=True, alpha=0.15)
    plot.setMouseEnabled(x=False, y=False)

    curve = plot.plot(
        pen=pg.mkPen(color=pen_color, width=2),
        fillLevel=yrange[0],
        brush=pg.mkBrush(color=pen_color + "22"),  # 13% opacity fill
    )
    return curve


class LiveChartsPanel(QWidget):
    """Real-time charts panel showing 4 system-wide metrics.

    Args:
        system_model: The SystemModel to read data from.
        parent: Parent widget.

    Example:
        >>> model = SystemModel()
        >>> panel = LiveChartsPanel(model)
    """

    def __init__(
        self,
        system_model: SystemModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = system_model
        self._t = 0

        # Rolling deques — x = time index, y = metric value
        self._xs: deque[int] = deque(maxlen=_WINDOW)
        self._soc_ys: deque[float] = deque(maxlen=_WINDOW)
        self._rssi_ys: deque[float] = deque(maxlen=_WINDOW)
        self._online_ys: deque[float] = deque(maxlen=_WINDOW)
        self._solar_ys: deque[float] = deque(maxlen=_WINDOW)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._setup_ui()
        self._start_timer()

    def _setup_ui(self) -> None:
        """Build the 4-chart vertical stack (full-width, no truncation)."""
        # Configure pyqtgraph global settings
        pg.setConfigOption("background", _PLOT_BG)
        pg.setConfigOption("foreground", "#cdd6f4")
        pg.setConfigOption("antialias", True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # GraphicsLayoutWidget holds all 4 plots efficiently in one GL surface
        self._gl = pg.GraphicsLayoutWidget()
        self._gl.setBackground(_BG)
        layout.addWidget(self._gl)

        # Vertical stack — all 4 plots in column 0, full panel width
        self._soc_plot = self._gl.addPlot(row=0, col=0)
        self._rssi_plot = self._gl.addPlot(row=1, col=0)
        self._online_plot = self._gl.addPlot(row=2, col=0)
        self._solar_plot = self._gl.addPlot(row=3, col=0)

        # Configure each plot — shorter titles to fit narrow panel
        self._soc_curve = _configure_plot(
            self._soc_plot, "Battery SOC", "%", (0, 100), "#a6e3a1"
        )
        self._rssi_curve = _configure_plot(
            self._rssi_plot, "RSSI (dBm)", "dBm", (-100, -40), "#89b4fa"
        )
        self._online_curve = _configure_plot(
            self._online_plot, "Online (#)", "#", (0, 10), "#cba6f7"
        )
        self._solar_curve = _configure_plot(
            self._solar_plot, "Solar (W)", "W", (0, 2200), "#f9e2af"
        )

        # Add threshold lines using PyQt6 Qt directly
        from PyQt6.QtCore import Qt as _Qt
        dash = _Qt.PenStyle.DashLine
        self._soc_plot.addLine(y=20, pen=pg.mkPen(color="#f38ba8", width=1, style=dash))
        self._soc_plot.addLine(y=50, pen=pg.mkPen(color="#f9e2af", width=1, style=dash))
        self._rssi_plot.addLine(y=-80, pen=pg.mkPen(color="#f38ba8", width=1, style=dash))


    def _start_timer(self) -> None:
        """Start 1-second update timer."""
        timer = QTimer(self)
        timer.timeout.connect(self._update)
        timer.start(1000)

    def _update(self) -> None:
        """Sample SystemModel and push data to all 4 charts."""
        targets = self._model.get_all_targets()
        online_targets = [t for t in targets.values() if t.online and not t.is_stale]

        # Compute aggregates
        socs = [t.battery_soc for t in online_targets if t.battery_soc >= 0]
        rssis = [t.rssi_dbm for t in online_targets]
        solar = sum(t.solar_w for t in targets.values() if t.online)

        avg_soc = sum(socs) / len(socs) if socs else 0.0
        avg_rssi = sum(rssis) / len(rssis) if rssis else -100.0
        n_online = float(len(online_targets))

        # Append to rolling buffers
        self._xs.append(self._t)
        self._soc_ys.append(avg_soc)
        self._rssi_ys.append(avg_rssi)
        self._online_ys.append(n_online)
        self._solar_ys.append(solar)
        self._t += 1

        xs = list(self._xs)

        # Update curves
        self._soc_curve.setData(x=xs, y=list(self._soc_ys))
        self._rssi_curve.setData(x=xs, y=list(self._rssi_ys))
        self._online_curve.setData(x=xs, y=list(self._online_ys))
        self._solar_curve.setData(x=xs, y=list(self._solar_ys))

        # Auto-scroll x-axis — keep only the last WINDOW points in view
        if len(xs) > 1:
            self._soc_plot.setXRange(xs[0], xs[-1], padding=0.02)
            self._rssi_plot.setXRange(xs[0], xs[-1], padding=0.02)
            self._online_plot.setXRange(xs[0], xs[-1], padding=0.02)
            self._solar_plot.setXRange(xs[0], xs[-1], padding=0.02)
