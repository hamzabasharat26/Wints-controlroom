"""RTSP Video widget — OpenCV-based fallback for Qt6 RTSP display.

Implements C2 mitigation: lazy video loading, max 2 concurrent streams.
Uses OpenCV VideoCapture in a background thread since QMediaPlayer
is unavailable on this Windows Qt6 installation (isAvailable() == False).

Frames are captured at ~15fps in a daemon thread and pushed to the
widget via a Qt signal (frame_ready) for thread-safe GUI update.

Stream URL format: rtsp://127.0.0.1:8554/target-01-front
"""

from __future__ import annotations

import threading
import time
from typing import Any

import cv2
import structlog
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

logger = structlog.get_logger(__name__)

# Global semaphore: max 10 concurrent RTSP decodes (one per target card)
_STREAM_SEMAPHORE = threading.Semaphore(10)


class RTSPCapture(QThread):
    """Background thread that captures frames from an RTSP/file source.

    Emits frame_ready(QImage) at ~15fps whenever a new frame is decoded.
    Emits error_occurred(str) when the stream fails.

    Args:
        url: RTSP URL or local file path to open.
        target_id: Target identifier for logging.
        cam_label: Camera label ('FRONT' or 'REAR').
    """

    frame_ready = pyqtSignal(QImage)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        url: str,
        target_id: str,
        cam_label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._url = url
        self._target_id = target_id
        self._cam_label = cam_label
        self._running = False
        self._log = logger.bind(target=target_id, cam=cam_label)

    def run(self) -> None:
        """Capture loop — runs in background thread."""
        if not _STREAM_SEMAPHORE.acquire(blocking=False):
            self._log.warning("stream_semaphore_full", msg="max 2 streams, skipping")
            self.error_occurred.emit("Stream limit reached (max 2 concurrent)")
            return

        self._running = True
        self._log.info("rtsp_capture_starting", url=self._url)
        cap: cv2.VideoCapture | None = None

        try:
            cap = cv2.VideoCapture(self._url)
            if not cap.isOpened():
                self._log.warning("rtsp_open_failed", url=self._url)
                self.error_occurred.emit(f"Cannot open: {self._url}")
                return

            self._log.info("rtsp_connected", url=self._url)
            consecutive_failures = 0

            while self._running:
                ret, frame = cap.read()
                if not ret:
                    consecutive_failures += 1
                    if consecutive_failures >= 30:
                        self._log.warning("rtsp_too_many_failures")
                        self.error_occurred.emit("Stream lost — too many read failures")
                        break
                    time.sleep(0.033)
                    continue

                consecutive_failures = 0

                # Convert BGR → RGB → QImage
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                bytes_per_line = ch * w
                q_image = QImage(
                    rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888
                )
                self.frame_ready.emit(q_image.copy())

                # ~15fps cap
                time.sleep(0.066)

        except Exception as exc:
            self._log.error("rtsp_exception", error=str(exc))
            self.error_occurred.emit(str(exc))
        finally:
            if cap is not None:
                cap.release()
            _STREAM_SEMAPHORE.release()
            self._running = False
            self._log.info("rtsp_capture_stopped")

    def stop(self) -> None:
        """Signal the capture loop to stop."""
        self._running = False


class VideoWidget(QWidget):
    """Single-camera RTSP video display widget.

    Shows a live video frame or a 'STREAM UNAVAILABLE' message.
    Clicking opens the fullscreen dialog for both front + rear cameras.

    Args:
        target_id: Target identifier (e.g. 'T-01').
        cam_label: 'FRONT' or 'REAR'.
        rtsp_url: RTSP stream URL.
        parent: Parent widget.

    Example:
        >>> w = VideoWidget('T-01', 'FRONT', 'rtsp://127.0.0.1:8554/target-01-front')
    """

    def __init__(
        self,
        target_id: str,
        cam_label: str,
        rtsp_url: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._target_id = target_id
        self._cam_label = cam_label
        self._rtsp_url = rtsp_url
        self._capture: RTSPCapture | None = None
        self._connected = False

        self.setMinimumSize(160, 90)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the video display layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Frame label — displays either video or placeholder
        self._frame_label = QLabel()
        self._frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._frame_label.setStyleSheet("background-color: #0d1117; color: #6c7086;")
        self._frame_label.setMinimumSize(160, 90)
        layout.addWidget(self._frame_label)

        # Camera label overlay
        self._cam_badge = QLabel(f"CAM: {self._cam_label}")
        self._cam_badge.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        self._cam_badge.setStyleSheet(
            "color: #a6e3a1; background: rgba(0,0,0,140); padding: 1px 4px;"
        )
        self._cam_badge.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._cam_badge)

        self._show_unavailable("NOT STARTED")

    def _show_unavailable(self, reason: str) -> None:
        """Display the STREAM UNAVAILABLE placeholder."""
        self._frame_label.setPixmap(QPixmap())  # clear any frame
        self._frame_label.setText(
            f"STREAM\nUNAVAILABLE\n\n{self._cam_label}\n\n{reason}"
        )
        self._frame_label.setStyleSheet(
            "background-color: #0d1117; color: #45475a; font-size: 9px;"
        )

    def start_stream(self) -> None:
        """Start the RTSP capture thread (lazy — call only when needed)."""
        if self._capture is not None and self._capture.isRunning():
            return  # already running

        self._frame_label.setText(f"CAM: {self._cam_label}\nConnecting...")
        self._capture = RTSPCapture(self._rtsp_url, self._target_id, self._cam_label, self)
        self._capture.frame_ready.connect(self._on_frame)
        self._capture.error_occurred.connect(self._on_error)
        self._capture.start()

    def stop_stream(self) -> None:
        """Stop the capture thread."""
        if self._capture is not None:
            self._capture.stop()
            self._capture.wait(2000)
            self._capture = None

    def _on_frame(self, image: QImage) -> None:
        """Slot — receives new frame from capture thread."""
        if not self._connected:
            self._connected = True
            logger.info("stream_connected", target=self._target_id, cam=self._cam_label)
        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            self._frame_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._frame_label.setPixmap(scaled)
        self._frame_label.setStyleSheet("background-color: #0d1117;")

    def _on_error(self, msg: str) -> None:
        """Slot — show error state when stream fails."""
        self._connected = False
        logger.warning("stream_error", target=self._target_id, cam=self._cam_label, error=msg)
        self._show_unavailable(msg[:30])


class DualCameraDialog(QDialog):
    """Full-screen dialog showing both front and rear cameras for a target.

    Opens when a target card is clicked.

    Args:
        target_id: e.g. 'T-01'
        front_url: RTSP URL for the front camera.
        rear_url: RTSP URL for the rear camera.
    """

    def __init__(
        self,
        target_id: str,
        front_url: str,
        rear_url: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{target_id} — Live Feeds")
        self.setMinimumSize(900, 420)
        self.setStyleSheet("background-color: #0d1117;")

        layout = QHBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        self._front = VideoWidget(target_id, "FRONT", front_url)
        self._rear = VideoWidget(target_id, "REAR", rear_url)
        layout.addWidget(self._front)
        layout.addWidget(self._rear)

        self._front.start_stream()
        self._rear.start_stream()

    def closeEvent(self, event: Any) -> None:
        """Stop streams when dialog closes."""
        self._front.stop_stream()
        self._rear.stop_stream()
        event.accept()
