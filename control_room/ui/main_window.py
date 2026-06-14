"""Main dashboard window — assembles target cards, event log, and metrics panel.

Implements a dark-themed responsive layout with:
    - 10 target cards in a FlowLayout (reflows on window resize)
    - Collapsible event log panel at the bottom
    - Collapsible metrics panel on the right
    - Connection status bar
    - Command flow: button click → CommandTracker → MQTT publish → ack/timeout
"""

from __future__ import annotations

from typing import Any

import structlog
from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
    QDockWidget,
    QGridLayout,
    QLabel,
    QMainWindow,
    QScrollArea,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from control_room.models.system_model import SystemModel
from control_room.models.target_state import CommandType
from control_room.mqtt.client import DashboardMQTTClient
from control_room.services.command_tracker import CommandTracker
from control_room.ui.event_log import EventLogWidget
from control_room.ui.live_charts import LiveChartsPanel
from control_room.ui.metrics_panel import MetricsPanel
from control_room.ui.target_card import TargetCard

logger = structlog.get_logger(__name__)


class FlowLayout(QVBoxLayout):
    """Simple flow layout that wraps widgets into rows.

    This is a simplified flow layout that arranges fixed-size widgets
    in a grid-like pattern that reflows when the container is resized.

    For a proper FlowLayout, Qt doesn't provide one by default. We use
    a grid-based approach that recalculates on resize.
    """

    pass


class MainWindow(QMainWindow):
    """WINTS Control Room main window.

    Assembles all dashboard components:
        - Target card grid (10 cards in a responsive layout)
        - Event log (bottom dock)
        - Metrics panel (right dock)
        - Toolbar with broadcast commands
        - Status bar with connection indicator

    Args:
        system_model: The SystemModel instance.
        mqtt_client: The MQTT client for publishing commands.
        parent: Parent widget.

    Example:
        >>> model = SystemModel()
        >>> client = DashboardMQTTClient(model)
        >>> window = MainWindow(model, client)
        >>> window.show()
    """

    def __init__(
        self,
        system_model: SystemModel,
        mqtt_client: DashboardMQTTClient,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = system_model
        self._mqtt = mqtt_client
        self._tracker = CommandTracker(self)
        self._cards: dict[str, TargetCard] = {}

        self.setWindowTitle("WINTS — Control Room")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

        # Dark theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #11111b;
            }
            QWidget {
                background-color: #11111b;
                color: #cdd6f4;
            }
            QScrollArea {
                border: none;
                background-color: #11111b;
            }
            QDockWidget {
                color: #cdd6f4;
                titlebar-close-icon: none;
                titlebar-normal-icon: none;
            }
            QDockWidget::title {
                background-color: #181825;
                padding: 6px;
                font-weight: bold;
            }
            QToolBar {
                background-color: #181825;
                border-bottom: 1px solid #313244;
                spacing: 8px;
                padding: 4px 8px;
            }
            QStatusBar {
                background-color: #181825;
                border-top: 1px solid #313244;
                color: #a6adc8;
            }
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45475a;
            }
            QPushButton:disabled {
                color: #585b70;
                border-color: #313244;
            }
        """)

        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_event_log_dock()
        self._setup_metrics_dock()
        self._setup_charts_dock()
        self._setup_status_bar()
        self._connect_signals()

    def _setup_toolbar(self) -> None:
        """Create the toolbar with broadcast commands."""
        toolbar = QToolBar("Commands")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))

        # Title
        title = QLabel("  WINTS CONTROL ROOM  ")
        title.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #89b4fa; background: transparent;")
        toolbar.addWidget(title)

        toolbar.addSeparator()

        # Broadcast buttons
        raise_all_btn = QAction("▲ RAISE ALL", self)
        raise_all_btn.triggered.connect(lambda: self._broadcast_command(CommandType.RAISE))
        toolbar.addAction(raise_all_btn)

        stop_all_btn = QAction("■ STOP ALL", self)
        stop_all_btn.triggered.connect(lambda: self._broadcast_command(CommandType.STOP))
        toolbar.addAction(stop_all_btn)

        lower_all_btn = QAction("▼ LOWER ALL", self)
        lower_all_btn.triggered.connect(lambda: self._broadcast_command(CommandType.LOWER))
        toolbar.addAction(lower_all_btn)

        self.addToolBar(toolbar)

    def _setup_central_widget(self) -> None:
        """Create the scrollable target card grid."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(20, 20, 20, 20)
        grid.setSpacing(16)

        # Create 10 target cards in a 5×2 grid
        for i in range(10):
            target_id = f"T-{i + 1:02d}"
            card = TargetCard(target_id, self._model)
            row = i // 5
            col = i % 5
            grid.addWidget(card, row, col)
            self._cards[target_id] = card

            # Connect button clicks
            card.raise_button.clicked.connect(
                lambda checked, tid=target_id: self._send_command(tid, CommandType.RAISE)
            )
            card.stop_button.clicked.connect(
                lambda checked, tid=target_id: self._send_command(tid, CommandType.STOP)
            )
            card.lower_button.clicked.connect(
                lambda checked, tid=target_id: self._send_command(tid, CommandType.LOWER)
            )

        grid.setRowStretch(2, 1)
        scroll.setWidget(container)
        self.setCentralWidget(scroll)

        # Stagger video stream starts so they don't all hammer OpenCV at once.
        # 300 ms between each card = all 10 streams started within 3 seconds.
        for idx, (_tid, card) in enumerate(self._cards.items()):
            delay_ms = 500 + idx * 300  # first stream after 0.5s, last after ~3.5s
            QTimer.singleShot(delay_ms, card.start_video)

    def _setup_event_log_dock(self) -> None:
        """Create the event log dock widget at the bottom."""
        dock = QDockWidget("Event Log", self)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self._event_log = EventLogWidget()
        dock.setWidget(self._event_log)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

    def _setup_metrics_dock(self) -> None:
        """Create the metrics panel dock widget on the right."""
        dock = QDockWidget("Metrics", self)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self._metrics = MetricsPanel(self._model)
        dock.setWidget(self._metrics)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _setup_charts_dock(self) -> None:
        """Create the live charts dock widget on the right (below metrics)."""
        dock = QDockWidget("Live Charts", self)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        dock.setMinimumWidth(300)
        dock.setMinimumHeight(300)
        self._charts = LiveChartsPanel(self._model)
        dock.setWidget(self._charts)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _setup_status_bar(self) -> None:
        """Create the status bar with connection indicator."""
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        self._conn_indicator = QLabel("● Disconnected")
        self._conn_indicator.setStyleSheet("color: #f38ba8;")
        self._conn_indicator.setFont(QFont("Segoe UI", 9))
        self._status_bar.addWidget(self._conn_indicator)

        self._online_count = QLabel("Targets Online: 0/10")
        self._online_count.setFont(QFont("Segoe UI", 9))
        self._status_bar.addPermanentWidget(self._online_count)

        # Update online count periodically
        timer = QTimer(self)
        timer.timeout.connect(self._update_status_bar)
        timer.start(1000)

    def _connect_signals(self) -> None:
        """Connect all model and tracker signals."""
        self._model.connection_changed.connect(self._on_connection_changed)
        self._model.command_acked.connect(self._on_command_acked)
        self._tracker.command_acked.connect(self._on_tracker_ack)
        self._tracker.command_timed_out.connect(self._on_tracker_timeout)

    def _send_command(self, target_id: str, cmd: CommandType) -> None:
        """Send a command to a specific target.

        Implements F-23 mitigation: only one pending command per target.

        Args:
            target_id: Target identifier.
            cmd: Command type.
        """
        if self._tracker.is_pending(target_id):
            return  # F-23: debounce — ignore if already pending

        trace_id = self._mqtt.publish_command(target_id, cmd)
        self._tracker.issue(target_id, trace_id, cmd.value)

        # Show pending spinner on card
        card = self._cards.get(target_id)
        if card:
            card.set_command_pending(True)

        # Log the command
        self._event_log.log_command(target_id, cmd.value, trace_id)

    def _broadcast_command(self, cmd: CommandType) -> None:
        """Send a broadcast command to all targets.

        Registers each target in CommandTracker so the 500ms per-target
        timeout fires normally.  Also starts a 5-second safety timer that
        clears any card that the tracker missed (e.g. T-09 OFFLINE never
        replies, broadcast trace-id never echoed).

        Args:
            cmd: Command type to broadcast.
        """
        trace_id = self._mqtt.publish_command("broadcast", cmd)
        self._event_log.log_command("ALL", cmd.value, trace_id)

        # Register every target in the tracker so timeouts fire
        for target_id in self._cards:
            # Broadcast children use the same child trace_id the simulator echoes
            child_trace = f"{trace_id}.{target_id}"
            self._tracker.issue(target_id, child_trace, cmd.value)

        # Mark all cards as pending
        for card in self._cards.values():
            card.set_command_pending(True)

        # Safety net: after 5 s, force-clear any card still showing PENDING.
        # This handles OFFLINE targets and any ack that arrives with a
        # mismatched trace_id.
        safety = QTimer(self)
        safety.setSingleShot(True)
        safety.setInterval(5000)
        safety.timeout.connect(self._clear_all_pending)
        safety.start()
        # Keep a reference so the timer is not garbage-collected
        self._broadcast_safety_timer = safety

    def _clear_all_pending(self) -> None:
        """Force-clear PENDING state on every card (broadcast safety net)."""
        for card in self._cards.values():
            card.set_command_pending(False)

    def _on_connection_changed(self, connected: bool) -> None:
        """Handle broker connection state change.

        Args:
            connected: Whether the broker is connected.
        """
        if connected:
            self._conn_indicator.setText("● Connected")
            self._conn_indicator.setStyleSheet("color: #a6e3a1;")
            self._event_log.log_info("Broker connected")
        else:
            self._conn_indicator.setText("● Disconnected")
            self._conn_indicator.setStyleSheet("color: #f38ba8;")
            self._event_log.log_error("Broker disconnected — reconnecting...")

    def _on_command_acked(self, target_id: str, trace_id: str) -> None:
        """Handle command acknowledgement from SystemModel.

        Args:
            target_id: Target that acknowledged.
            trace_id: Command trace_id.
        """
        self._tracker.acknowledge(target_id, trace_id)

    def _on_tracker_ack(self, target_id: str, trace_id: str) -> None:
        """Handle tracker ack — clear pending state on card.

        Args:
            target_id: Target identifier.
            trace_id: Command trace_id.
        """
        card = self._cards.get(target_id)
        if card:
            card.set_command_pending(False)
        self._event_log.log_status(target_id, f"Command acked [{trace_id[:8]}]")

    def _on_tracker_timeout(self, target_id: str, trace_id: str) -> None:
        """Handle tracker timeout — show warning.

        Args:
            target_id: Target identifier.
            trace_id: Command trace_id.
        """
        card = self._cards.get(target_id)
        if card:
            card.set_command_pending(False)
        self._event_log.log_warning(
            f"{target_id}: Command timeout [{trace_id[:8]}]"
        )

    def _update_status_bar(self) -> None:
        """Periodic status bar update."""
        count = self._model.get_online_count()
        self._online_count.setText(f"Targets Online: {count}/10")

    def closeEvent(self, event: Any) -> None:
        """Handle window close — graceful shutdown.

        Args:
            event: Close event.
        """
        logger.info("dashboard_closing")
        # Stop all video streams before disconnecting MQTT
        for card in self._cards.values():
            card.stop_video()
        self._mqtt.disconnect()
        event.accept()
