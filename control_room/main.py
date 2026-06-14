"""WINTS Control Room — main entry point.

Initializes the Qt application, creates the SystemModel, MQTT client,
and main window, then enters the Qt event loop.

Usage:
    python -m control_room.main
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import structlog
import yaml
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from control_room.models.system_model import SystemModel
from control_room.mqtt.client import DashboardMQTTClient
from control_room.ui.main_window import MainWindow

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _setup_logging() -> None:
    """Configure structlog for the dashboard process.

    Example:
        >>> _setup_logging()
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _load_config() -> dict[str, Any]:
    """Load configuration from config/wints.yaml.

    Returns:
        Configuration dictionary.
    """
    config_path = PROJECT_ROOT / "config" / "wints.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


def main() -> None:
    """Dashboard application entry point.

    Creates QApplication, SystemModel, MQTT client, and MainWindow,
    then starts the Qt event loop.

    Example:
        >>> # main()  # Blocks until window is closed
    """
    _setup_logging()
    logger = structlog.get_logger("dashboard")

    app = QApplication(sys.argv)
    app.setApplicationName("WINTS Control Room")
    app.setApplicationVersion("1.0.0")

    # Set default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Load config
    try:
        config = _load_config()
    except FileNotFoundError:
        logger.error("config_not_found", path=str(PROJECT_ROOT / "config" / "wints.yaml"))
        sys.exit(1)

    broker_cfg = config.get("broker", {})

    # Create core objects
    model = SystemModel()
    mqtt_client = DashboardMQTTClient(
        system_model=model,
        broker_host=broker_cfg.get("host", "localhost"),
        broker_port=broker_cfg.get("port", 1883),
    )

    # Create main window
    window = MainWindow(model, mqtt_client)
    window.show()

    # Connect to broker
    logger.info("connecting_to_broker", host=broker_cfg.get("host"), port=broker_cfg.get("port"))
    mqtt_client.connect_to_broker()

    # Run Qt event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
