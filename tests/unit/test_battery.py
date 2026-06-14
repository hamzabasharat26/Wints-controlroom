"""Unit tests for the battery physics simulator.

Tests the LiFePO4 battery model against electrochemical invariants:
    - SOC bounds [0, 100] (F-14 mitigation)
    - OCV-SOC curve monotonicity
    - Voltage sag under load (V = OCV - IR)
    - BMS cutoff at low SOC
    - Charging increases SOC
    - Temperature-dependent R_internal
"""

from __future__ import annotations

import pytest

from target_simulator.physics.battery import BatterySimulator, BatteryState


class TestBatteryBasicBehaviour:
    """Test basic battery charge/discharge behaviour."""

    def test_initial_soc(self) -> None:
        """Battery starts at specified SOC."""
        batt = BatterySimulator(initial_soc=75.0)
        assert batt.soc == pytest.approx(75.0, abs=0.01)

    def test_soc_decreases_under_load(self) -> None:
        """SOC decreases when motor draws current."""
        batt = BatterySimulator(initial_soc=50.0)
        initial_soc = batt.soc
        batt.step(dt_sim_s=60.0, motor_current_a=10.0)
        assert batt.soc < initial_soc

    def test_soc_increases_during_charge(self) -> None:
        """SOC increases when solar charges the battery."""
        batt = BatterySimulator(initial_soc=50.0)
        initial_soc = batt.soc
        batt.step(dt_sim_s=60.0, solar_charge_current_a=15.0)
        assert batt.soc > initial_soc

    def test_ocv_increases_with_soc(self) -> None:
        """OCV is monotonically increasing with SOC.

        This is a physical invariant for LiFePO4 cells.
        """
        batt = BatterySimulator()
        prev_ocv = 0.0
        for soc in range(0, 101, 5):
            ocv = batt._interpolate_ocv(float(soc)) * 4  # 4S pack
            assert ocv >= prev_ocv, f"OCV decreased at SOC={soc}%"
            prev_ocv = ocv

    def test_terminal_voltage_sags_under_load(self) -> None:
        """V_terminal < V_ocv under load (V = OCV - I·R)."""
        batt = BatterySimulator(initial_soc=80.0)
        v_noload = batt.get_terminal_voltage_under_load(0.0)
        v_loaded = batt.get_terminal_voltage_under_load(10.0)
        assert v_loaded < v_noload, "Voltage must sag under load"


class TestBatteryProtection:
    """Test BMS protection logic."""

    def test_soc_clamped_to_zero_f14(self) -> None:
        """Pre-mortem F-14: SOC never goes below 0%.

        Even with extreme discharge, SOC stays >= 0.
        """
        batt = BatterySimulator(initial_soc=1.0)
        for _ in range(1000):
            batt.step(dt_sim_s=60.0, motor_current_a=50.0)
        assert batt.soc >= 0.0

    def test_soc_clamped_to_hundred_f14(self) -> None:
        """Pre-mortem F-14: SOC never exceeds 100%.

        Even with extreme charging, SOC stays <= 100.
        """
        batt = BatterySimulator(initial_soc=99.0)
        for _ in range(1000):
            batt.step(dt_sim_s=60.0, solar_charge_current_a=50.0)
        assert batt.soc <= 100.0

    def test_bms_cutoff_at_low_soc(self) -> None:
        """BMS disconnects load when SOC drops below threshold."""
        batt = BatterySimulator(initial_soc=11.0)
        # Drain until BMS triggers
        for _ in range(500):
            batt.step(dt_sim_s=60.0, motor_current_a=20.0)
            if batt.is_load_disconnected:
                break
        assert batt.is_load_disconnected, "BMS should cut off load at low SOC"
        assert batt.state == BatteryState.BMS_CUTOFF

    def test_bms_recovery_with_solar(self) -> None:
        """BMS reconnects load when SOC recovers above threshold + hysteresis."""
        batt = BatterySimulator(initial_soc=5.0)
        # Force BMS cutoff
        batt.step(dt_sim_s=1.0, motor_current_a=10.0)
        assert batt.is_load_disconnected

        # Charge with solar until recovery
        for _ in range(2000):
            batt.step(dt_sim_s=60.0, solar_charge_current_a=20.0)
            if not batt.is_load_disconnected:
                break
        assert not batt.is_load_disconnected, "BMS should reconnect after recovery"


class TestBatteryTemperature:
    """Test temperature-dependent internal resistance."""

    def test_cold_battery_higher_resistance(self) -> None:
        """Internal resistance is higher at cold temperatures."""
        warm = BatterySimulator(initial_temperature_c=25.0)
        cold = BatterySimulator(initial_temperature_c=-20.0)
        assert cold.r_internal > warm.r_internal

    def test_voltage_sag_worse_when_cold(self) -> None:
        """Voltage sag under load is worse at cold temperatures."""
        warm = BatterySimulator(initial_soc=80.0, initial_temperature_c=25.0)
        cold = BatterySimulator(initial_soc=80.0, initial_temperature_c=-20.0)
        v_warm = warm.get_terminal_voltage_under_load(10.0)
        v_cold = cold.get_terminal_voltage_under_load(10.0)
        assert v_cold < v_warm, "Cold battery should have worse voltage sag"


class TestBatteryStateDict:
    """Test battery state export for telemetry."""

    def test_state_dict_has_all_fields(self) -> None:
        """State dict includes all required telemetry fields."""
        batt = BatterySimulator(initial_soc=75.0)
        d = batt.get_state_dict()
        required_keys = {
            "soc", "ocv_v", "terminal_voltage_v", "r_internal_ohm",
            "temperature_c", "state", "load_disconnected",
        }
        assert required_keys.issubset(d.keys())
