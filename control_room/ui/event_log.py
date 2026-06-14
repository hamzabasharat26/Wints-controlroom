"""Event log widget — colour-coded, filterable, exportable log display.

Displays structured events in the dashboard:
    - Commands (blue)
    - Status updates (green)
    - Telemetry (grey)
    - Warnings (amber)
    - Errors (red)

Supports search/filter bar and export to timestamped text file.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class EventLogWidget(QWidget):
    """Colour-coded event log with search and export.

    Args:
        parent: Parent widget.
        max_lines: Maximum number of lines to keep in the log.

    Example:
        >>> log = EventLogWidget()
        >>> log.log_command("T-01", "raise", "abc-123")
        >>> log.log_error("Something went wrong")
    """

    def __init__(self, parent: QWidget | None = None, max_lines: int = 1000) -> None:
        super().__init__(parent)
        self._max_lines = max_lines
        self._all_entries: list[tuple[str, str, str]] = []  # (timestamp, level, message)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the event log UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Search bar
        search_row = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Filter events...")
        self._search_input.setStyleSheet("""
            QLineEdit {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 4px;
                padding: 4px 8px;
                font-family: Consolas;
                font-size: 11px;
            }
        """)
        self._search_input.textChanged.connect(self._apply_filter)
        search_row.addWidget(self._search_input)

        export_btn = QPushButton("Export")
        export_btn.setFixedWidth(70)
        export_btn.setStyleSheet("""
            QPushButton {
                background-color: #313244;
                color: #89b4fa;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #45475a; }
        """)
        export_btn.clicked.connect(self._export_log)
        search_row.addWidget(export_btn)

        layout.addLayout(search_row)

        # Log text area
        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setFont(QFont("Consolas", 10))
        self._text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #11111b;
                color: #a6adc8;
                border: 1px solid #313244;
                border-radius: 4px;
            }
        """)
        self._text_edit.setMinimumHeight(120)
        layout.addWidget(self._text_edit)

    def _timestamp(self) -> str:
        """Get current timestamp string.

        Returns:
            Formatted timestamp HH:MM:SS.mmm.
        """
        now = datetime.now()
        return now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"

    def _append_entry(self, level: str, message: str, color: str) -> None:
        """Append a coloured entry to the log.

        Args:
            level: Log level string (CMD, STATUS, TELEM, WARN, ERROR, INFO).
            message: Log message text.
            color: HTML colour for the entry.
        """
        ts = self._timestamp()
        self._all_entries.append((ts, level, message))

        # Trim old entries
        if len(self._all_entries) > self._max_lines:
            self._all_entries = self._all_entries[-self._max_lines:]

        # Check if filtered
        filter_text = self._search_input.text().lower()
        full_text = f"[{ts}] [{level}] {message}"
        if filter_text and filter_text not in full_text.lower():
            return

        # Append with colour
        html = f'<span style="color:{color}">[{ts}] [{level}] {message}</span>'
        self._text_edit.append(html)

        # Auto-scroll to bottom
        scrollbar = self._text_edit.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def log_command(self, target_id: str, cmd: str, trace_id: str) -> None:
        """Log a command event.

        Args:
            target_id: Target identifier.
            cmd: Command type.
            trace_id: Command trace_id.

        Example:
            >>> log = EventLogWidget()
            >>> log.log_command("T-01", "raise", "abc-123")
        """
        self._append_entry(
            "CMD",
            f"{target_id} → {cmd.upper()} [{trace_id[:8]}]",
            "#89b4fa",  # Blue
        )

    def log_status(self, target_id: str, message: str) -> None:
        """Log a status event.

        Args:
            target_id: Target identifier.
            message: Status message.

        Example:
            >>> log = EventLogWidget()
            >>> log.log_status("T-01", "Position: UP")
        """
        self._append_entry("STATUS", f"{target_id}: {message}", "#a6e3a1")  # Green

    def log_telemetry(self, target_id: str, message: str) -> None:
        """Log a telemetry event.

        Args:
            target_id: Target identifier.
            message: Telemetry message.
        """
        self._append_entry("TELEM", f"{target_id}: {message}", "#6c7086")  # Grey

    def log_warning(self, message: str) -> None:
        """Log a warning event.

        Args:
            message: Warning message.

        Example:
            >>> log = EventLogWidget()
            >>> log.log_warning("T-03: High packet loss")
        """
        self._append_entry("WARN", message, "#f9e2af")  # Amber

    def log_error(self, message: str) -> None:
        """Log an error event.

        Args:
            message: Error message.

        Example:
            >>> log = EventLogWidget()
            >>> log.log_error("Broker connection lost")
        """
        self._append_entry("ERROR", message, "#f38ba8")  # Red

    def log_info(self, message: str) -> None:
        """Log an informational event.

        Args:
            message: Info message.

        Example:
            >>> log = EventLogWidget()
            >>> log.log_info("System started")
        """
        self._append_entry("INFO", message, "#cdd6f4")  # White

    def _apply_filter(self, text: str) -> None:
        """Apply search filter to the log entries.

        Args:
            text: Filter text (case-insensitive substring match).
        """
        self._text_edit.clear()
        filter_lower = text.lower()

        colors = {
            "CMD": "#89b4fa",
            "STATUS": "#a6e3a1",
            "TELEM": "#6c7086",
            "WARN": "#f9e2af",
            "ERROR": "#f38ba8",
            "INFO": "#cdd6f4",
        }

        for ts, level, message in self._all_entries:
            full_text = f"[{ts}] [{level}] {message}"
            if not filter_lower or filter_lower in full_text.lower():
                color = colors.get(level, "#a6adc8")
                html = f'<span style="color:{color}">{full_text}</span>'
                self._text_edit.append(html)

    def _export_log(self) -> None:
        """Export visible log entries to a text file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"wints_log_{timestamp}.txt"

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export Event Log",
            default_name,
            "Text Files (*.txt)",
        )

        if filepath:
            with open(filepath, "w", encoding="utf-8") as f:
                for ts, level, message in self._all_entries:
                    f.write(f"[{ts}] [{level}] {message}\n")
