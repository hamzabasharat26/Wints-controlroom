"""Target card — custom QWidget displaying a single target's complete state.

Each card is a 240×320px widget in a responsive FlowLayout. It shows:
    - Target ID with status badge (green/amber/red animated colour)
    - Position indicator with motion animation
    - Battery bar with voltage tooltip
    - RSSI 5-bar widget with dBm tooltip
    - Raise/Stop/Lower buttons with pending spinners
    - Stale indicator when data is old (F-09 mitigation)

Cards are created once and reused — never deleted during runtime
(Pre-mortem F-10 mitigation).
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import (  # type: ignore[attr-defined]
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtProperty,
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPaintEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from control_room.models.system_model import SystemModel
from control_room.models.target_state import PositionLabel
from control_room.ui.video_widget import DualCameraDialog, VideoWidget

_RTSP_BASE = "rtsp://127.0.0.1:8554/wints"


class StatusBadge(QWidget):
    """Animated status badge with smooth colour transitions.

    Displays as a pill-shaped indicator that smoothly transitions
    between green (online), amber (fault), and red (offline).

    Args:
        parent: Parent widget.

    Example:
        >>> badge = StatusBadge()
        >>> badge.set_status("online")
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(80, 24)
        self._color = QColor(100, 100, 100)  # Grey = unknown
        self._label = "UNKNOWN"

        self._animation = QPropertyAnimation(self, b"badge_color")
        self._animation.setDuration(500)

    @pyqtProperty(QColor)
    def badge_color(self) -> QColor:
        """Current badge colour for animation.

        Returns:
            Current QColor.
        """
        return self._color

    @badge_color.setter  # type: ignore[no-redef]
    def badge_color(self, color: QColor) -> None:
        """Set badge colour and trigger repaint.

        Args:
            color: New colour value.
        """
        self._color = color
        self.update()

    def set_status(self, status: str) -> None:
        """Set the badge status with animated colour transition.

        Args:
            status: One of 'online', 'fault', 'offline', 'stale'.

        Example:
            >>> badge = StatusBadge()
            >>> badge.set_status("online")
        """
        colors = {
            "online": QColor(46, 204, 113),   # Emerald green
            "fault": QColor(243, 156, 18),     # Orange/amber
            "offline": QColor(231, 76, 60),    # Red
            "stale": QColor(149, 165, 166),    # Grey
        }
        labels = {
            "online": "ONLINE",
            "fault": "FAULT",
            "offline": "OFFLINE",
            "stale": "STALE",
        }

        target_color = colors.get(status, QColor(100, 100, 100))
        self._label = labels.get(status, "UNKNOWN")

        self._animation.stop()
        self._animation.setStartValue(self._color)
        self._animation.setEndValue(target_color)
        self._animation.start()

    def paintEvent(self, event: QPaintEvent | None) -> None:
        """Paint the pill-shaped badge with label.

        Args:
            event: Paint event.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw pill background
        painter.setBrush(self._color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 12, 12)

        # Draw label
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._label)
        painter.end()


class RSSIWidget(QWidget):
    """5-bar RSSI signal strength indicator.

    Custom-painted widget showing signal bars. Tooltip shows dBm and
    packet loss percentage.

    Args:
        parent: Parent widget.

    Example:
        >>> rssi = RSSIWidget()
        >>> rssi.set_rssi(-53)
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(40, 24)
        self._bars = 0
        self._rssi_dbm = -100

    def set_rssi(self, rssi_dbm: int, packet_loss_pct: float = 0.0) -> None:
        """Update RSSI display.

        Args:
            rssi_dbm: Signal strength in dBm.
            packet_loss_pct: Packet loss percentage for tooltip.

        Example:
            >>> w = RSSIWidget()
            >>> w.set_rssi(-53, 0.0)
        """
        self._rssi_dbm = rssi_dbm

        # Map RSSI to bars (5 bars max)
        if rssi_dbm > -55:
            self._bars = 5
        elif rssi_dbm > -65:
            self._bars = 4
        elif rssi_dbm > -72:
            self._bars = 3
        elif rssi_dbm > -80:
            self._bars = 2
        elif rssi_dbm > -90:
            self._bars = 1
        else:
            self._bars = 0

        self.setToolTip(f"RSSI: {rssi_dbm} dBm\nPacket loss: {packet_loss_pct:.1f}%")
        self.update()

    def paintEvent(self, event: QPaintEvent | None) -> None:
        """Paint signal bars.

        Args:
            event: Paint event.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bar_width = 5
        gap = 2
        base_height = 4
        max_bars = 5

        for i in range(max_bars):
            x = i * (bar_width + gap) + 2
            h = base_height + i * 3
            y = self.height() - h

            if i < self._bars:
                # Active bar colour based on signal strength
                if self._bars >= 4:
                    color = QColor(46, 204, 113)  # Green
                elif self._bars >= 2:
                    color = QColor(243, 156, 18)  # Amber
                else:
                    color = QColor(231, 76, 60)   # Red
            else:
                color = QColor(60, 60, 60)  # Inactive

            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(x, y, bar_width, h, 1, 1)

        painter.end()


class MastWidget(QWidget):
    """Vertical mast position indicator — shows antenna head position.

    Custom-painted widget showing a vertical rail with an antenna head
    that slides from bottom (DOWN=0%) to top (UP=100%). Animates smoothly.

    Args:
        parent: Parent widget.

    Example:
        >>> mast = MastWidget()
        >>> mast.set_position(75.0)  # 75% = near UP
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(36, 80)
        self._pct: float = 0.0
        self._target_pct: float = 0.0

        # Smooth animation timer (~30fps)
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._step_animation)
        self._anim_timer.setInterval(33)

    def set_position(self, pct: float) -> None:
        """Update target position percentage (animated).

        Args:
            pct: Position 0.0-100.0 (0=DOWN, 100=UP).
        """
        self._target_pct = max(0.0, min(100.0, pct))
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _step_animation(self) -> None:
        """EMA-style smooth interpolation step toward target."""
        diff = self._target_pct - self._pct
        if abs(diff) < 0.5:
            self._pct = self._target_pct
            self._anim_timer.stop()
        else:
            self._pct += diff * 0.15
        self.update()

    def paintEvent(self, event: Any) -> None:
        """Paint the mast rail and sliding antenna head.

        Args:
            event: Paint event.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx = w // 2
        rail_top = 14
        rail_bottom = h - 16
        rail_height = rail_bottom - rail_top

        # UP / DN labels
        painter.setPen(QColor(108, 112, 134))
        f = QFont("Segoe UI", 6)
        painter.setFont(f)
        painter.drawText(0, 0, w, 14, Qt.AlignmentFlag.AlignCenter, "UP")
        painter.drawText(0, h - 14, w, 14, Qt.AlignmentFlag.AlignCenter, "DN")

        # Mast rail
        painter.setPen(QColor(69, 71, 90))
        painter.drawLine(cx, rail_top, cx, rail_bottom)

        # Antenna head position
        head_y = int(rail_bottom - (self._pct / 100.0) * rail_height)

        # Colour: green=UP, blue=moving, grey=DOWN
        if self._pct > 90:
            head_color = QColor(166, 227, 161)
        elif self._pct > 10:
            head_color = QColor(137, 180, 250)
        else:
            head_color = QColor(108, 112, 134)

        # Antenna head (filled circle)
        painter.setBrush(head_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(cx - 6, head_y - 6, 12, 12)

        # Glow halo when fully UP
        if self._pct > 90:
            glow = QColor(166, 227, 161, 40)
            painter.setBrush(glow)
            painter.drawEllipse(cx - 10, head_y - 10, 20, 20)

        painter.end()


class TargetCard(QFrame):
    """Complete target card widget for the dashboard grid.

    Displays all target state information and provides control buttons.
    Connects to SystemModel signals for updates.

    Cards are created once and reused (F-10 mitigation).

    Args:
        target_id: Target identifier (e.g., 'T-01').
        system_model: The SystemModel to read state from and receive signals.
        parent: Parent widget.

    Example:
        >>> model = SystemModel()
        >>> card = TargetCard("T-01", model)
    """

    def __init__(
        self,
        target_id: str,
        system_model: SystemModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._target_id = target_id
        self._model = system_model
        self._command_pending = False

        self.setFixedSize(240, 400)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            TargetCard {
                background-color: #1e1e2e;
                border: 1px solid #313244;
                border-radius: 12px;
            }
            TargetCard:hover {
                border: 1px solid #89b4fa;
            }
        """)

        self._setup_ui()
        self._connect_signals()

        # Initial state pull from model (F-10: pull on creation)
        self._update_from_model()

    def _setup_ui(self) -> None:
        """Build the card layout with all sub-widgets."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # === Header: Target ID + Status Badge ===
        header = QHBoxLayout()
        self._id_label = QLabel(self._target_id)
        self._id_label.setFont(QFont("Consolas", 16, QFont.Weight.Bold))
        self._id_label.setStyleSheet("color: #cdd6f4;")
        header.addWidget(self._id_label)
        header.addStretch()
        self._status_badge = StatusBadge()
        header.addWidget(self._status_badge)
        layout.addLayout(header)

        # === Position Display — Mast widget + text label ===
        pos_row = QHBoxLayout()
        pos_row.setSpacing(6)

        # Vertical mast indicator
        self._mast_widget = MastWidget()
        pos_row.addWidget(self._mast_widget)

        # Text label (position + percentage)
        pos_text_col = QVBoxLayout()
        pos_text_col.setSpacing(2)
        self._position_label = QLabel("DOWN")
        self._position_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._position_label.setStyleSheet("color: #a6adc8;")
        pos_text_col.addWidget(self._position_label)

        self._position_pct_label = QLabel("0%")
        self._position_pct_label.setFont(QFont("Consolas", 9))
        self._position_pct_label.setStyleSheet("color: #6c7086;")
        pos_text_col.addWidget(self._position_pct_label)
        pos_text_col.addStretch()

        pos_row.addLayout(pos_text_col)
        pos_row.addStretch()
        layout.addLayout(pos_row)

        # === Battery + RSSI Row ===
        metrics_row = QHBoxLayout()

        # Battery
        batt_col = QVBoxLayout()
        batt_label = QLabel("BATTERY")
        batt_label.setFont(QFont("Segoe UI", 7))
        batt_label.setStyleSheet("color: #6c7086;")
        batt_col.addWidget(batt_label)

        self._battery_bar = QProgressBar()
        self._battery_bar.setRange(0, 100)
        self._battery_bar.setValue(0)
        self._battery_bar.setFixedHeight(12)
        self._battery_bar.setFixedWidth(120)
        self._battery_bar.setStyleSheet("""
            QProgressBar {
                background-color: #313244;
                border: none;
                border-radius: 3px;
                text-align: center;
                font-size: 8px;
                color: #cdd6f4;
            }
            QProgressBar::chunk {
                background-color: #a6e3a1;
                border-radius: 3px;
            }
        """)
        batt_col.addWidget(self._battery_bar)
        metrics_row.addLayout(batt_col)

        metrics_row.addStretch()

        # RSSI
        rssi_col = QVBoxLayout()
        rssi_label = QLabel("SIGNAL")
        rssi_label.setFont(QFont("Segoe UI", 7))
        rssi_label.setStyleSheet("color: #6c7086;")
        rssi_col.addWidget(rssi_label, alignment=Qt.AlignmentFlag.AlignRight)
        self._rssi_widget = RSSIWidget()
        rssi_col.addWidget(self._rssi_widget, alignment=Qt.AlignmentFlag.AlignRight)
        metrics_row.addLayout(rssi_col)

        layout.addLayout(metrics_row)

        # === Fault Chip ===
        self._fault_label = QLabel("")
        self._fault_label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self._fault_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fault_label.setStyleSheet("""
            color: #f38ba8;
            background-color: #45273a;
            border-radius: 4px;
            padding: 2px 8px;
        """)
        self._fault_label.hide()
        layout.addWidget(self._fault_label)

        # === Motor Current ===
        self._current_label = QLabel("Motor: 0.0 A")
        self._current_label.setFont(QFont("Segoe UI", 8))
        self._current_label.setStyleSheet("color: #6c7086;")
        layout.addWidget(self._current_label)

        # === Solar Power ===
        self._solar_label = QLabel("Solar: 0.0 W")
        self._solar_label.setFont(QFont("Segoe UI", 8))
        self._solar_label.setStyleSheet("color: #6c7086;")
        layout.addWidget(self._solar_label)

        layout.addStretch()

        # === Video Feed (front camera, compact inline view) ===
        front_url = f"{_RTSP_BASE}/{self._target_id}/front"
        self._video_widget = VideoWidget(
            target_id=self._target_id,
            cam_label="FRONT",
            rtsp_url=front_url,
            parent=self,
        )
        self._video_widget.setFixedHeight(90)
        self._video_widget.setMinimumWidth(180)
        layout.addWidget(self._video_widget)

        # === Control Buttons ===
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        self._raise_btn = QPushButton("▲ RAISE")
        self._stop_btn = QPushButton("■ STOP")
        self._lower_btn = QPushButton("▼ LOWER")

        for btn in [self._raise_btn, self._stop_btn, self._lower_btn]:
            btn.setFixedHeight(32)
            btn.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._raise_btn.setStyleSheet("""
            QPushButton {
                background-color: #313244;
                color: #a6e3a1;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 0 8px;
            }
            QPushButton:hover { background-color: #45475a; }
            QPushButton:disabled { color: #585b70; border-color: #313244; }
        """)
        self._stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #313244;
                color: #f9e2af;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 0 8px;
            }
            QPushButton:hover { background-color: #45475a; }
            QPushButton:disabled { color: #585b70; border-color: #313244; }
        """)
        self._lower_btn.setStyleSheet("""
            QPushButton {
                background-color: #313244;
                color: #89b4fa;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 0 8px;
            }
            QPushButton:hover { background-color: #45475a; }
            QPushButton:disabled { color: #585b70; border-color: #313244; }
        """)

        btn_layout.addWidget(self._raise_btn)
        btn_layout.addWidget(self._stop_btn)
        btn_layout.addWidget(self._lower_btn)
        layout.addLayout(btn_layout)

        # === Stale Indicator ===
        self._stale_label = QLabel("⚠ STALE")
        self._stale_label.setFont(QFont("Segoe UI", 7))
        self._stale_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stale_label.setStyleSheet("color: #9399b2; background: transparent;")
        self._stale_label.hide()
        layout.addWidget(self._stale_label)

    def _connect_signals(self) -> None:
        """Connect to SystemModel signals and button clicks."""
        self._model.target_updated.connect(self._on_target_updated)

    def mouseDoubleClickEvent(self, event: Any) -> None:
        """Open dual-camera video dialog on double-click.

        Args:
            event: Mouse event.
        """
        target_num = self._target_id.split("-")[1]
        front_url = f"{_RTSP_BASE}/{self._target_id}/front"
        rear_url = f"{_RTSP_BASE}/{self._target_id}/rear"
        dialog = DualCameraDialog(self._target_id, front_url, rear_url, self)
        dialog.exec()

    def _on_target_updated(self, target_id: str) -> None:
        """Handle target update signal from SystemModel.

        Args:
            target_id: Updated target identifier.
        """
        if target_id != self._target_id:
            return
        self._update_from_model()

    def _update_from_model(self) -> None:
        """Pull current state from SystemModel and update all widgets."""
        target = self._model.get_target(self._target_id)

        # Status badge
        if not target.online or target.is_stale:
            if target.is_stale and target.online:
                self._status_badge.set_status("stale")
            else:
                self._status_badge.set_status("offline")
        elif target.fault:
            self._status_badge.set_status("fault")
        else:
            self._status_badge.set_status("online")

        # Position — update mast widget and text labels
        pct = max(0.0, min(100.0, target.position_pct))
        self._position_label.setText(target.position.value)
        self._position_pct_label.setText(f"{pct:.0f}%")
        self._mast_widget.set_position(pct)

        # Battery
        soc = max(0, min(100, target.battery_soc))
        self._battery_bar.setValue(int(soc))
        self._battery_bar.setFormat(f"{soc:.0f}%")

        # Battery colour based on SOC
        if soc > 50:
            chunk_color = "#a6e3a1"  # Green
        elif soc > 20:
            chunk_color = "#f9e2af"  # Amber
        else:
            chunk_color = "#f38ba8"  # Red
        self._battery_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: #313244;
                border: none;
                border-radius: 3px;
                text-align: center;
                font-size: 8px;
                color: #cdd6f4;
            }}
            QProgressBar::chunk {{
                background-color: {chunk_color};
                border-radius: 3px;
            }}
        """)
        self._battery_bar.setToolTip(
            f"SOC: {target.battery_soc:.1f}%\n"
            f"Voltage: {target.battery_voltage:.2f} V"
        )

        # RSSI
        self._rssi_widget.set_rssi(target.rssi_dbm, target.packet_loss_pct)

        # Fault chip
        if target.fault and target.fault_code:
            self._fault_label.setText(f"⚠ {target.fault_code.value}")
            self._fault_label.show()
        else:
            self._fault_label.hide()

        # Motor current & solar
        self._current_label.setText(f"Motor: {target.motor_current_a:.1f} A")
        self._solar_label.setText(f"Solar: {target.solar_w:.0f} W")

        # Button states
        is_online = target.online and not target.is_stale and not target.fault
        self._raise_btn.setEnabled(
            is_online and target.position != PositionLabel.UP and not self._command_pending
        )
        self._lower_btn.setEnabled(
            is_online and target.position != PositionLabel.DOWN and not self._command_pending
        )
        self._stop_btn.setEnabled(
            target.online and not target.is_stale and not self._command_pending
        )

        # Stale indicator (F-09 mitigation)
        if target.is_stale and target.last_update_ts > 0:
            self._stale_label.show()
        else:
            self._stale_label.hide()

    def set_command_pending(self, pending: bool) -> None:
        """Set the command pending state (shows/hides spinner on buttons).

        Args:
            pending: Whether a command is pending.

        Example:
            >>> card = TargetCard("T-01", SystemModel())
            >>> card.set_command_pending(True)
        """
        self._command_pending = pending
        if pending:
            self._raise_btn.setEnabled(False)
            self._lower_btn.setEnabled(False)
            self._stop_btn.setEnabled(False)
            self._raise_btn.setText("PENDING...")
            self._stop_btn.setText("PENDING...")
            self._lower_btn.setText("PENDING...")
        else:
            self._raise_btn.setText("▲ RAISE")
            self._stop_btn.setText("■ STOP")
            self._lower_btn.setText("▼ LOWER")
            self._update_from_model()  # Re-evaluate button states

    def clear_pending(self) -> None:
        """Unconditionally restore button labels and re-enable appropriately.

        Called by the broadcast safety timer and any other path that needs
        to force-clear PENDING state regardless of ack tracking.

        Example:
            >>> card = TargetCard("T-01", SystemModel())
            >>> card.clear_pending()
        """
        self.set_command_pending(False)

    def start_video(self) -> None:
        """Start the inline front-camera RTSP stream.

        Called after the dashboard finishes constructing all cards so that
        the semaphore (max 2 concurrent streams) is not hit during init.
        Only starts if MediaMTX is reachable — the VideoWidget handles the
        'Cannot open' case gracefully by showing STREAM UNAVAILABLE.

        Example:
            >>> card = TargetCard("T-01", SystemModel())
            >>> card.start_video()
        """
        self._video_widget.start_stream()

    def stop_video(self) -> None:
        """Stop the inline video stream (called on window close).

        Example:
            >>> card = TargetCard("T-01", SystemModel())
            >>> card.stop_video()
        """
        self._video_widget.stop_stream()

    @property
    def target_id(self) -> str:
        """Target identifier.

        Returns:
            Target ID string.
        """
        return self._target_id

    @property
    def raise_button(self) -> QPushButton:
        """The raise command button.

        Returns:
            QPushButton for raising the target.
        """
        return self._raise_btn

    @property
    def stop_button(self) -> QPushButton:
        """The stop command button.

        Returns:
            QPushButton for stopping the target.
        """
        return self._stop_btn

    @property
    def lower_button(self) -> QPushButton:
        """The lower command button.

        Returns:
            QPushButton for lowering the target.
        """
        return self._lower_btn
