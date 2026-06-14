"""Solar panel physics model — irradiance, MPPT, and charge current calculation.

Simulates a 200W monocrystalline solar panel with:
    - Sinusoidal irradiance model with cloud noise
    - MPPT tracking at 95% efficiency
    - Charge current output to the battery model

Irradiance is always clamped to >= 0 (Pre-mortem F-16 mitigation).

Simulator equivalent of: firmware/battery.c (solar input section)
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class SolarConstants:
    """Physical constants for the solar panel model.

    All values sourced from config/wints.yaml.

    Args:
        panel_efficiency: Panel conversion efficiency (0-1).
        panel_area_m2: Physical panel area (m²).
        mppt_efficiency: MPPT tracking efficiency (0-1).
        peak_irradiance_w_m2: Standard test conditions irradiance (W/m²).
        sunrise_h: Simulated sunrise hour.
        sunset_h: Simulated sunset hour.
        cloud_noise_std_w_m2: Standard deviation of cloud noise (W/m²).
        max_charge_current_a: Maximum safe charge current (A).

    Example:
        >>> sc = SolarConstants()
        >>> sc.panel_efficiency
        0.22
    """

    panel_efficiency: float = 0.22
    panel_area_m2: float = 1.0
    mppt_efficiency: float = 0.95
    peak_irradiance_w_m2: float = 1000.0
    sunrise_h: float = 6.0
    sunset_h: float = 18.0
    cloud_noise_std_w_m2: float = 50.0
    max_charge_current_a: float = 20.0


class SolarSimulator:
    """Solar panel simulator with irradiance model and MPPT.

    Generates solar irradiance based on simulated time of day, adds
    Gaussian cloud noise, and calculates panel electrical output
    through an MPPT controller.

    Args:
        constants: Solar panel physical constants.

    Example:
        >>> solar = SolarSimulator()
        >>> power = solar.get_power_w(sim_time_h=12.0)  # Noon
        >>> power > 100.0  # Near peak at noon
        True
        >>> power_night = solar.get_power_w(sim_time_h=2.0)  # Night
        >>> power_night == 0.0
        True
    """

    def __init__(self, constants: SolarConstants | None = None) -> None:
        self._c = constants or SolarConstants()
        self._rng = random.Random()

    def get_irradiance(self, sim_time_h: float) -> float:
        """Calculate solar irradiance at a given simulated time.

        G(t) = G_peak × max(0, sin(π × (t - t_sunrise) / (t_sunset - t_sunrise)))
               + N(0, σ_cloud²)

        Result is clamped to [0, G_peak] (Pre-mortem F-16 mitigation).

        Args:
            sim_time_h: Simulated time in hours (0-24).

        Returns:
            Irradiance in W/m², always >= 0.

        Example:
            >>> solar = SolarSimulator()
            >>> g = solar.get_irradiance(12.0)  # Noon
            >>> g > 0
            True
            >>> g_night = solar.get_irradiance(3.0)
            >>> g_night == 0.0
            True
        """
        c = self._c
        t = sim_time_h % 24.0

        # Check if daytime
        if t < c.sunrise_h or t > c.sunset_h:
            return 0.0

        # Sinusoidal base irradiance
        day_fraction = (t - c.sunrise_h) / (c.sunset_h - c.sunrise_h)
        g_base = c.peak_irradiance_w_m2 * np.sin(np.pi * day_fraction)

        # Add cloud noise
        noise = self._rng.gauss(0, c.cloud_noise_std_w_m2)
        g_total = g_base + noise

        # F-16 mitigation: clamp to non-negative
        return max(0.0, min(float(g_total), c.peak_irradiance_w_m2))

    def get_power_w(self, sim_time_h: float) -> float:
        """Calculate electrical power output from the panel.

        P_solar = η_panel × A_panel × G(t) × η_mppt

        Args:
            sim_time_h: Simulated time in hours (0-24).

        Returns:
            Electrical power output in watts, always >= 0.

        Example:
            >>> solar = SolarSimulator()
            >>> p = solar.get_power_w(12.0)
            >>> p >= 0
            True
        """
        c = self._c
        irradiance = self.get_irradiance(sim_time_h)
        return c.panel_efficiency * c.panel_area_m2 * irradiance * c.mppt_efficiency

    def get_charge_current(
        self, sim_time_h: float, battery_voltage_v: float
    ) -> float:
        """Calculate charge current to the battery.

        I_charge = min(P_solar / V_battery, I_max)

        Args:
            sim_time_h: Simulated time in hours (0-24).
            battery_voltage_v: Current battery terminal voltage (V).

        Returns:
            Charge current in amps, clamped to [0, max_charge_current].

        Example:
            >>> solar = SolarSimulator()
            >>> i = solar.get_charge_current(12.0, 13.2)
            >>> 0 <= i <= 20.0
            True
        """
        c = self._c
        power_w = self.get_power_w(sim_time_h)

        if battery_voltage_v <= 0 or power_w <= 0:
            return 0.0

        current = power_w / battery_voltage_v
        return min(current, c.max_charge_current_a)

    def get_state_dict(self, sim_time_h: float) -> dict[str, Any]:
        """Export current solar state for telemetry.

        Args:
            sim_time_h: Current simulated time in hours.

        Returns:
            Dictionary with solar state fields.

        Example:
            >>> solar = SolarSimulator()
            >>> d = solar.get_state_dict(12.0)
            >>> 'irradiance_w_m2' in d
            True
        """
        irradiance = self.get_irradiance(sim_time_h)
        power = self.get_power_w(sim_time_h)
        return {
            "irradiance_w_m2": round(irradiance, 1),
            "power_w": round(power, 2),
            "sim_time_h": round(sim_time_h, 2),
            "is_daytime": self._c.sunrise_h <= (sim_time_h % 24) <= self._c.sunset_h,
        }
