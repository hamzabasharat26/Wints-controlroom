"""Pydantic models for MQTT payloads — dashboard side.

Re-exports the shared models from target_simulator.models to maintain
a single source of truth. Dashboard code imports from here.
"""

from __future__ import annotations

# Re-export from shared models — single source of truth
from target_simulator.models import (
    CommandPayload,
    CommandType,
    FaultCode,
    FaultInjectionRequest,
    PositionLabel,
    StatusPayload,
    TelemetryPayload,
)

__all__ = [
    "CommandPayload",
    "CommandType",
    "FaultCode",
    "FaultInjectionRequest",
    "PositionLabel",
    "StatusPayload",
    "TelemetryPayload",
]
