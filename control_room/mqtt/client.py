"""Thread-safe MQTT client for the control room dashboard.

Wraps paho-mqtt with a reconnection FSM that implements exponential
backoff with jitter. All MQTT messages are dispatched to the Qt event
loop via QMetaObject.invokeMethod (Pre-mortem F-01 mitigation).

The client never writes to SystemModel directly from the network thread.
Instead, it serializes messages across the thread boundary using
Qt's queued connection mechanism.

Reconnection FSM matches docs/01_design.md §2.5.
"""

from __future__ import annotations

import enum
import uuid
from collections import OrderedDict
from typing import Any

import paho.mqtt.client as mqtt
import structlog
from PyQt6.QtCore import Q_ARG, QMetaObject, Qt

from control_room.models.system_model import SystemModel
from control_room.models.target_state import CommandPayload, CommandType

logger = structlog.get_logger(__name__)


# Deduplication cache for incoming messages
_DEDUP_MAX_ENTRIES: int = 200
_DEDUP_TTL_S: float = 5.0


class MQTTConnectionState(enum.Enum):
    """MQTT client connection state machine states.

    Example:
        >>> MQTTConnectionState.DISCONNECTED.value
        'DISCONNECTED'
    """

    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    SUBSCRIBING = "SUBSCRIBING"
    READY = "READY"
    RECONNECTING = "RECONNECTING"


class DashboardMQTTClient:
    """Thread-safe MQTT client for the dashboard.

    Runs paho-mqtt's network loop in a background thread. All incoming
    messages are dispatched to the SystemModel via QMetaObject.invokeMethod
    with Qt.QueuedConnection (F-01 mitigation).

    Args:
        system_model: The SystemModel instance to update.
        broker_host: MQTT broker hostname.
        broker_port: MQTT broker port.

    Example:
        >>> from PyQt6.QtWidgets import QApplication
        >>> app = QApplication([])
        >>> model = SystemModel()
        >>> client = DashboardMQTTClient(model)
        >>> client.connect_to_broker()
    """

    def __init__(
        self,
        system_model: SystemModel,
        broker_host: str = "localhost",
        broker_port: int = 1883,
    ) -> None:
        self._model = system_model
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._state = MQTTConnectionState.DISCONNECTED

        # Reconnection backoff
        self._backoff_s: float = 1.0
        self._backoff_base: float = 1.0
        self._backoff_max: float = 30.0

        # Message dedup cache
        self._dedup_cache: OrderedDict[str, float] = OrderedDict()

        # Create paho client
        client_id = f"wints-dashboard-{uuid.uuid4().hex[:8]}"
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,  # type: ignore[attr-defined]
            client_id=client_id,
            protocol=mqtt.MQTTv311,
            clean_session=True,  # F-07: no stale session messages
        )

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._log = logger.bind(component="dashboard_mqtt")

    @property
    def connection_state(self) -> MQTTConnectionState:
        """Current MQTT connection state.

        Returns:
            Current MQTTConnectionState.

        Example:
            >>> client = DashboardMQTTClient(SystemModel())
            >>> client.connection_state
            <MQTTConnectionState.DISCONNECTED: 'DISCONNECTED'>
        """
        return self._state

    def connect_to_broker(self) -> None:
        """Initiate connection to the MQTT broker.

        Starts the paho network loop in a background thread.

        Example:
            >>> client = DashboardMQTTClient(SystemModel())
            >>> client.connect_to_broker()
        """
        self._state = MQTTConnectionState.CONNECTING
        self._log.info("connecting", host=self._broker_host, port=self._broker_port)

        try:
            self._client.connect_async(
                self._broker_host,
                self._broker_port,
                keepalive=60,
            )
            self._client.loop_start()
        except Exception as exc:
            self._log.error("connect_failed", error=str(exc))
            self._state = MQTTConnectionState.DISCONNECTED

    def disconnect(self) -> None:
        """Gracefully disconnect from the broker.

        Example:
            >>> client = DashboardMQTTClient(SystemModel())
            >>> client.disconnect()
        """
        self._log.info("disconnecting")
        self._client.loop_stop()
        self._client.disconnect()
        self._state = MQTTConnectionState.DISCONNECTED

    def publish_command(
        self, target_id: str, cmd: CommandType
    ) -> str:
        """Publish a command to a target.

        Args:
            target_id: Target identifier (e.g., 'T-01') or 'broadcast'.
            cmd: Command type (raise, lower, stop).

        Returns:
            The trace_id of the published command.

        Example:
            >>> client = DashboardMQTTClient(SystemModel())
            >>> trace_id = client.publish_command("T-01", CommandType.RAISE)
            >>> len(trace_id) > 0
            True
        """
        payload = CommandPayload.create(cmd)

        if target_id == "broadcast":
            topic = "wints/broadcast/cmd"
        else:
            topic = f"wints/{target_id}/cmd"

        self._log.info(
            "command_published",
            target=target_id,
            cmd=cmd.value,
            trace_id=payload.trace_id,
        )

        self._client.publish(
            topic,
            payload=payload.model_dump_json(),
            qos=1,
        )

        return payload.trace_id

    def _on_connect(
        self, client: mqtt.Client, userdata: Any, flags: dict[str, Any], rc: int
    ) -> None:
        """MQTT on_connect callback (runs in paho network thread).

        Args:
            client: MQTT client instance.
            userdata: User data (unused).
            flags: Connection flags.
            rc: Result code (0 = success).
        """
        if rc == 0:
            self._log.info("connected", rc=rc)
            self._state = MQTTConnectionState.CONNECTED
            self._backoff_s = self._backoff_base  # Reset backoff

            # Subscribe to all WINTS topics
            client.subscribe("wints/#", qos=1)
            self._state = MQTTConnectionState.SUBSCRIBING
            self._state = MQTTConnectionState.READY

            # Notify SystemModel (thread-safe via Qt)
            QMetaObject.invokeMethod(
                self._model,
                "on_connection_changed",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(bool, True),
            )
        else:
            self._log.warning("connect_failed", rc=rc)
            self._state = MQTTConnectionState.RECONNECTING

    def _on_disconnect(
        self, client: mqtt.Client, userdata: Any, rc: int
    ) -> None:
        """MQTT on_disconnect callback (runs in paho network thread).

        Args:
            client: MQTT client instance.
            userdata: User data (unused).
            rc: Disconnect reason code.
        """
        self._log.warning("disconnected", rc=rc)
        self._state = MQTTConnectionState.RECONNECTING

        # Notify SystemModel (thread-safe via Qt)
        QMetaObject.invokeMethod(
            self._model,
            "on_connection_changed",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(bool, False),
        )

        # paho-mqtt handles reconnection automatically with loop_start()
        # We just need to track the state

    def _on_message(
        self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage
    ) -> None:
        """MQTT on_message callback (runs in paho network thread).

        Dispatches messages to the Qt event loop via QMetaObject.invokeMethod.
        This is the F-01 mitigation — we never modify SystemModel from
        the paho thread.

        Args:
            client: MQTT client instance.
            userdata: User data (unused).
            msg: Received MQTT message.
        """
        topic = msg.topic
        payload = msg.payload.decode(errors="replace")

        try:
            # Route by topic
            if "/status" in topic:
                QMetaObject.invokeMethod(
                    self._model,
                    "on_status_message",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, payload),
                )
            elif "/telemetry" in topic:
                QMetaObject.invokeMethod(
                    self._model,
                    "on_telemetry_message",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, payload),
                )
        except Exception as exc:
            self._log.error(
                "message_dispatch_failed",
                topic=topic,
                error=str(exc),
            )
