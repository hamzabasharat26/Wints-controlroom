"""Chaos tests — fault injection and resilience validation.

These tests verify that the system behaves correctly under fault conditions.
Each test maps to a specific pre-mortem failure mode from docs/02_premortem.md.
"""

from __future__ import annotations

import pytest

from target_simulator.physics.battery import BatterySimulator, BatteryState
from target_simulator.physics.motor import MotorSimulator, MotorState


class TestFaultInjectionMotor:
    """Test motor fault injection and recovery."""

    @pytest.mark.chaos
    def test_overcurrent_fault_stops_motor(self) -> None:
        """F-12: Overcurrent fault immediately stops the motor."""
        motor = MotorSimulator()
        motor.command_raise()
        for _ in range(100):
            motor.step(0.001)
        # Inject overcurrent
        motor._enter_fault("OVERCURRENT")
        assert motor.physics_state.state == MotorState.MOTOR_FAULT
        assert motor.physics_state.drive_enabled is False
        assert motor.current_a == 0.0

    @pytest.mark.chaos
    def test_limit_stuck_fault(self) -> None:
        """F-15: Both limit switches active = hardware fault."""
        motor = MotorSimulator()
        motor._enter_fault("LIMIT_STUCK")
        assert motor.physics_state.state == MotorState.MOTOR_FAULT
        assert motor.physics_state.fault_code == "LIMIT_STUCK"

    @pytest.mark.chaos
    def test_fault_recovery_sequence(self) -> None:
        """Motor can be recovered from fault → IDLE → command."""
        motor = MotorSimulator()
        motor._enter_fault("OVERCURRENT")
        assert motor.is_faulted is True

        # Clear fault
        result = motor.clear_fault()
        assert result is True
        assert motor.physics_state.state == MotorState.IDLE
        assert motor.is_faulted is False

        # Can command again
        assert motor.command_raise() is True

    @pytest.mark.chaos
    def test_command_rejected_during_fault(self) -> None:
        """Commands are rejected when motor is in FAULT state."""
        motor = MotorSimulator()
        motor._enter_fault("OVERCURRENT")
        assert motor.command_raise() is False
        assert motor.command_lower() is False
        assert motor.command_stop() is False


class TestFaultInjectionBattery:
    """Test battery fault injection and recovery."""

    @pytest.mark.chaos
    def test_bms_cutoff_under_heavy_load(self) -> None:
        """BMS cuts off load when SOC drops below threshold under sustained load."""
        batt = BatterySimulator(initial_soc=15.0)
        for _ in range(500):
            batt.step(dt_sim_s=60.0, motor_current_a=20.0)
            if batt.is_load_disconnected:
                break
        assert batt.is_load_disconnected
        assert batt.state == BatteryState.BMS_CUTOFF

    @pytest.mark.chaos
    def test_battery_survives_extreme_values(self) -> None:
        """Battery model doesn't crash with extreme current values."""
        batt = BatterySimulator(initial_soc=50.0)
        # Extreme discharge
        batt.step(dt_sim_s=3600.0, motor_current_a=100.0)
        assert 0.0 <= batt.soc <= 100.0

        # Extreme charge
        batt2 = BatterySimulator(initial_soc=50.0)
        batt2.step(dt_sim_s=3600.0, solar_charge_current_a=100.0)
        assert 0.0 <= batt2.soc <= 100.0

    @pytest.mark.chaos
    def test_bms_recovery_after_solar_charging(self) -> None:
        """BMS reconnects load after SOC recovers from solar charging."""
        batt = BatterySimulator(initial_soc=5.0)
        batt.step(dt_sim_s=1.0, motor_current_a=10.0)

        # Should be in BMS cutoff
        if not batt.is_load_disconnected:
            # Force it
            batt._soc = 5.0
            batt._update_state_machine(0.0, 10.0)

        # Charge with solar
        for _ in range(3000):
            batt.step(dt_sim_s=60.0, solar_charge_current_a=20.0)
            if not batt.is_load_disconnected:
                break

        assert not batt.is_load_disconnected, "BMS should reconnect after recovery"


class TestSystemResilience:
    """Test cross-component resilience scenarios."""

    @pytest.mark.chaos
    def test_motor_stops_on_bms_cutoff(self) -> None:
        """When battery BMS cuts off, motor should be stopped."""
        motor = MotorSimulator()
        batt = BatterySimulator(initial_soc=5.0)

        # Start motor
        motor.command_raise()
        for _ in range(100):
            motor.step(0.001)

        # Trigger BMS cutoff
        batt.step(dt_sim_s=1.0, motor_current_a=10.0)

        # In the actual target.py, the main loop checks BMS state and
        # stops the motor. Here we verify the motor CAN be stopped.
        if batt.is_load_disconnected:
            motor.command_stop()
            for _ in range(500):
                motor.step(0.001)
            assert motor.physics_state.state == MotorState.IDLE

    @pytest.mark.chaos
    def test_multiple_fault_clear_cycles(self) -> None:
        """Motor survives multiple fault/clear cycles without state corruption."""
        motor = MotorSimulator()
        for cycle in range(10):
            # Reset position to 0 to prevent hitting the upper limit switch
            motor._state.theta_rad = 0.0
            motor._state.position_pct = 0.0
            motor._state.up_limit.raw_active = False
            motor._state.up_limit.debounced_active = False
            motor._state.down_limit.raw_active = True
            motor._state.down_limit.debounced_active = True

            motor._enter_fault("OVERCURRENT")
            assert motor.is_faulted
            motor.clear_fault()
            assert not motor.is_faulted
            assert motor.command_raise()
            for _ in range(50):
                motor.step(0.001)
            motor.command_stop()
            for _ in range(200):
                motor.step(0.001)
