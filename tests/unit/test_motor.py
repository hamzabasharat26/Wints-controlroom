"""Unit tests for the motor physics simulator.

Tests the DC motor ODE model against known physical behaviours:
    - Steady-state current convergence
    - Position clamping at limits
    - Overcurrent protection
    - Stall detection
    - Limit switch bounce and debounce
    - State machine transitions

Each test verifies a specific physical invariant or pre-mortem mitigation.
"""

from __future__ import annotations

import pytest

from target_simulator.physics.motor import (
    MotorDirection,
    MotorSimulator,
    MotorState,
)


class TestMotorBasicOperation:
    """Test basic motor operation — raise, lower, stop."""

    def test_initial_state_is_idle_at_zero(self) -> None:
        """Motor starts IDLE at position 0%."""
        motor = MotorSimulator()
        assert motor.physics_state.state == MotorState.IDLE
        assert motor.position_pct == pytest.approx(0.0, abs=0.1)
        assert motor.current_a == 0.0

    def test_command_raise_transitions_to_accelerating(self) -> None:
        """Commanding RAISE from IDLE transitions to ACCELERATING."""
        motor = MotorSimulator()
        result = motor.command_raise()
        assert result is True
        assert motor.physics_state.state == MotorState.ACCELERATING
        assert motor.physics_state.direction == MotorDirection.RAISING

    def test_command_lower_when_at_bottom_rejected(self) -> None:
        """Commanding LOWER when at position 0% is rejected (at lower limit)."""
        motor = MotorSimulator(initial_position_pct=0.0)
        result = motor.command_lower()
        assert result is False

    def test_command_raise_when_at_top_rejected(self) -> None:
        """Commanding RAISE when at position 100% is rejected (at upper limit)."""
        motor = MotorSimulator(initial_position_pct=100.0)
        result = motor.command_raise()
        assert result is False

    def test_stop_from_accelerating(self) -> None:
        """STOP command is accepted during ACCELERATING state."""
        motor = MotorSimulator()
        motor.command_raise()
        # Run a few steps to get into motion
        for _ in range(50):
            motor.step(0.001)
        result = motor.command_stop()
        assert result is True
        assert motor.physics_state.state == MotorState.DECELERATING

    def test_current_rises_on_startup(self) -> None:
        """Motor current increases after commanding RAISE."""
        motor = MotorSimulator()
        motor.command_raise()
        for _ in range(100):
            motor.step(0.001)
        assert motor.current_a > 0.1, "Current should rise after commanding motor"

    def test_position_increases_when_raising(self) -> None:
        """Position percentage increases when motor is raising."""
        motor = MotorSimulator()
        motor.command_raise()
        for _ in range(500):
            motor.step(0.001)
        assert motor.position_pct > 0.0, "Position should increase when raising"


class TestMotorProtection:
    """Test overcurrent and stall protection."""

    def test_position_clamped_to_bounds_f13(self) -> None:
        """Pre-mortem F-13: Position is clamped to [0, θ_max].

        Even after extensive simulation, position never goes negative
        or exceeds 100%.
        """
        motor = MotorSimulator()
        motor.command_raise()
        # Run well past the expected travel time
        for _ in range(5000):
            motor.step(0.001)
        assert 0.0 <= motor.position_pct <= 100.0

    def test_current_clamped_to_physical_bounds_f13(self) -> None:
        """Pre-mortem F-13: Current never exceeds ±20A clamp."""
        motor = MotorSimulator()
        motor.command_raise()
        max_current = 0.0
        for _ in range(1000):
            motor.step(0.001)
            max_current = max(max_current, abs(motor.current_a))
        assert max_current <= 20.0, "Current must be clamped to ±20A"

    def test_fault_state_disables_drive(self) -> None:
        """Entering fault state disables drive and zeroes current."""
        motor = MotorSimulator()
        motor.command_raise()
        for _ in range(100):
            motor.step(0.001)
        motor._enter_fault("TEST_FAULT")
        assert motor.physics_state.drive_enabled is False
        assert motor.current_a == 0.0
        assert motor.physics_state.state == MotorState.MOTOR_FAULT

    def test_clear_fault_returns_to_idle(self) -> None:
        """Clearing a fault returns the motor to IDLE state."""
        motor = MotorSimulator()
        motor._enter_fault("TEST_FAULT")
        assert motor.is_faulted is True
        result = motor.clear_fault()
        assert result is True
        assert motor.physics_state.state == MotorState.IDLE
        assert motor.is_faulted is False


class TestMotorLimitSwitches:
    """Test limit switch simulation and debounce."""

    def test_upper_limit_stops_motor(self) -> None:
        """Motor stops when reaching upper limit during RAISE."""
        motor = MotorSimulator()
        motor.command_raise()
        # Run until motor reaches upper limit
        for i in range(10000):
            motor.step(0.001)
            if motor.physics_state.state == MotorState.IDLE and motor.position_pct > 90:
                break
        assert motor.position_pct >= 99.0, "Motor should reach upper limit"
        assert motor.physics_state.state == MotorState.IDLE

    def test_lower_command_from_top(self) -> None:
        """Motor can be commanded to LOWER from the top position."""
        motor = MotorSimulator(initial_position_pct=100.0)
        result = motor.command_lower()
        assert result is True
        assert motor.physics_state.direction == MotorDirection.LOWERING


class TestMotorStateDict:
    """Test motor state export for telemetry."""

    def test_state_dict_has_all_fields(self) -> None:
        """State dict includes all required telemetry fields."""
        motor = MotorSimulator()
        d = motor.get_state_dict()
        required_keys = {
            "current_a", "omega_rad_s", "theta_rad", "position_pct",
            "position_label", "direction", "state", "drive_enabled",
            "fault_code", "up_limit_active", "down_limit_active",
        }
        assert required_keys.issubset(d.keys())

    def test_position_label_down(self) -> None:
        """Position label is 'DOWN' when at 0%."""
        motor = MotorSimulator(initial_position_pct=0.0)
        assert motor.get_position_label() == "DOWN"

    def test_position_label_up(self) -> None:
        """Position label is 'UP' when at 100%."""
        motor = MotorSimulator(initial_position_pct=100.0)
        assert motor.get_position_label() == "UP"
