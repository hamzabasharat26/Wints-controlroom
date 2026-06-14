"""Unit tests for the solar panel physics simulator.

Tests the solar model against irradiance physics:
    - Zero irradiance at night
    - Peak irradiance at solar noon
    - Irradiance clamped to non-negative (F-16 mitigation)
    - Charge current limited to max_charge_current
    - Power = η × A × G × η_mppt
"""

from __future__ import annotations

import pytest

from target_simulator.physics.solar import SolarConstants, SolarSimulator


class TestSolarIrradiance:
    """Test solar irradiance model."""

    def test_zero_irradiance_at_night(self) -> None:
        """Irradiance is 0 before sunrise and after sunset."""
        solar = SolarSimulator()
        assert solar.get_irradiance(3.0) == 0.0   # 03:00 — night
        assert solar.get_irradiance(22.0) == 0.0   # 22:00 — night

    def test_peak_irradiance_at_noon(self) -> None:
        """Irradiance peaks near solar noon (12:00).

        With sunrise=6, sunset=18, peak is at 12:00.
        """
        solar = SolarSimulator(constants=SolarConstants(cloud_noise_std_w_m2=0))
        g_noon = solar.get_irradiance(12.0)
        g_morning = solar.get_irradiance(8.0)
        assert g_noon > g_morning, "Noon irradiance should exceed morning"
        assert g_noon == pytest.approx(1000.0, abs=50)  # Near peak

    def test_irradiance_never_negative_f16(self) -> None:
        """Pre-mortem F-16: Irradiance is clamped to >= 0.

        Even with cloud noise, irradiance never goes negative.
        """
        solar = SolarSimulator(constants=SolarConstants(cloud_noise_std_w_m2=200))
        for hour in range(0, 24):
            for _ in range(100):
                g = solar.get_irradiance(float(hour))
                assert g >= 0.0, f"Negative irradiance at hour {hour}"


class TestSolarPower:
    """Test solar power output."""

    def test_power_formula(self) -> None:
        """Power = η × A × G × η_mppt.

        At STC (1000 W/m²): P = 0.22 × 1.0 × 1000 × 0.95 = 209 W
        """
        solar = SolarSimulator(constants=SolarConstants(cloud_noise_std_w_m2=0))
        p = solar.get_power_w(12.0)  # Noon
        assert 180.0 < p < 220.0, f"Expected ~209W at STC, got {p:.1f}W"

    def test_zero_power_at_night(self) -> None:
        """Power is 0 at night."""
        solar = SolarSimulator()
        assert solar.get_power_w(3.0) == 0.0


class TestSolarChargeCurrent:
    """Test charge current calculation."""

    def test_charge_current_limited(self) -> None:
        """Charge current is capped at max_charge_current_a."""
        solar = SolarSimulator(constants=SolarConstants(
            cloud_noise_std_w_m2=0,
            max_charge_current_a=5.0,  # Low limit for test
        ))
        current = solar.get_charge_current(12.0, 13.2)
        assert current <= 5.0

    def test_zero_current_at_night(self) -> None:
        """Charge current is 0 at night."""
        solar = SolarSimulator()
        assert solar.get_charge_current(3.0, 13.2) == 0.0

    def test_zero_current_with_zero_voltage(self) -> None:
        """Charge current is 0 when battery voltage is 0 (guard against division by zero)."""
        solar = SolarSimulator()
        assert solar.get_charge_current(12.0, 0.0) == 0.0


class TestSolarStateDict:
    """Test solar state export for telemetry."""

    def test_state_dict_has_all_fields(self) -> None:
        """State dict includes all required telemetry fields."""
        solar = SolarSimulator()
        d = solar.get_state_dict(12.0)
        required_keys = {"irradiance_w_m2", "power_w", "sim_time_h", "is_daytime"}
        assert required_keys.issubset(d.keys())

    def test_is_daytime_correct(self) -> None:
        """is_daytime flag matches time of day."""
        solar = SolarSimulator()
        assert solar.get_state_dict(12.0)["is_daytime"] is True
        assert solar.get_state_dict(3.0)["is_daytime"] is False
