"""LiFePO4 battery physics model — coulomb counting, OCV-SOC, BMS protection.

Simulates a 4S 100Ah LiFePO4 battery pack with:
    - State of Charge (SOC) by coulomb counting
    - Terminal voltage from OCV-SOC curve minus I·R_internal
    - Temperature-dependent internal resistance
    - BMS protection (under-voltage cutoff at SOC < 10%)
    - Charging from solar panel input

Source: EVE Energy LF100LA datasheet for OCV-SOC curve and R_internal data.
Simulator equivalent of: firmware/battery.c

The SOC is always clamped to [0, 100] (Pre-mortem F-14 mitigation).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

import numpy as np


class BatteryState(enum.Enum):
    """Battery manager state machine states.

    Matches the state diagram in docs/01_design.md §2.3.

    Example:
        >>> state = BatteryState.DISCHARGING
        >>> state.value
        'DISCHARGING'
    """

    CHARGING = "CHARGING"
    FLOAT = "FLOAT"
    DISCHARGING = "DISCHARGING"
    LOW_SOC = "LOW_SOC"
    CRITICAL = "CRITICAL"
    BMS_CUTOFF = "BMS_CUTOFF"


@dataclass
class BatteryConstants:
    """Physical constants for the LiFePO4 battery model.

    All values sourced from config/wints.yaml. OCV-SOC data from
    EVE Energy LF100LA datasheet (0.2C discharge curve).

    Args:
        capacity_ah: Nominal capacity (Ah).
        series_cells: Number of cells in series (4S pack).
        coulombic_efficiency: Round-trip coulombic efficiency.
        r_internal_base_ohm: Per-cell internal resistance at 25°C (Ω).
        bms_cutoff_soc_pct: SOC percentage at which BMS disconnects load.
        overcharge_voltage_per_cell_v: Maximum cell voltage (V).
        undervoltage_per_cell_v: Minimum cell voltage (V).
        over_temperature_c: Temperature limit for charge rate reduction (°C).
        quiescent_load_w: Always-on electronics power draw (W).
        camera_streaming_load_w: Camera streaming power draw (W).
        ocv_soc_table: List of [SOC%, OCV_per_cell_V] pairs.
        r_internal_temp_table: List of [temperature_C, multiplier] pairs.

    Example:
        >>> bc = BatteryConstants()
        >>> bc.capacity_ah
        100
    """

    capacity_ah: int = 100
    series_cells: int = 4
    coulombic_efficiency: float = 0.995
    r_internal_base_ohm: float = 0.005
    bms_cutoff_soc_pct: float = 10.0
    overcharge_voltage_per_cell_v: float = 3.70
    undervoltage_per_cell_v: float = 2.50
    over_temperature_c: float = 60.0
    quiescent_load_w: float = 7.0
    camera_streaming_load_w: float = 15.0
    ocv_soc_table: list[list[float]] | None = None
    r_internal_temp_table: list[list[float]] | None = None

    def __post_init__(self) -> None:
        """Initialize default OCV-SOC and R_internal tables if not provided."""
        if self.ocv_soc_table is None:
            # EVE Energy LF100LA datasheet, 0.2C discharge curve
            self.ocv_soc_table = [
                [0, 2.50], [5, 3.00], [10, 3.20], [15, 3.23],
                [20, 3.25], [30, 3.27], [40, 3.28], [50, 3.30],
                [60, 3.31], [70, 3.33], [80, 3.35], [90, 3.40],
                [95, 3.50], [100, 3.65],
            ]
        if self.r_internal_temp_table is None:
            self.r_internal_temp_table = [
                [-20, 2.00], [-10, 1.60], [0, 1.30], [10, 1.10],
                [25, 1.00], [40, 0.90], [55, 0.95],
            ]


class BatterySimulator:
    """Physics-accurate LiFePO4 battery simulator.

    Models SOC by coulomb counting, terminal voltage from OCV-SOC curve,
    temperature-dependent R_internal, and BMS protection logic.

    SOC is always clamped to [0, 100] after every integration step
    (Pre-mortem F-14 mitigation).

    Args:
        constants: Battery physical constants.
        initial_soc: Starting state of charge (0-100%).
        initial_temperature_c: Starting temperature (°C).

    Example:
        >>> battery = BatterySimulator(initial_soc=80.0)
        >>> battery.soc
        80.0
        >>> battery.terminal_voltage > 12.0
        True
    """

    def __init__(
        self,
        constants: BatteryConstants | None = None,
        initial_soc: float = 80.0,
        initial_temperature_c: float = 25.0,
    ) -> None:
        self._c = constants or BatteryConstants()
        self._soc = max(0.0, min(100.0, initial_soc))
        self._temperature_c = initial_temperature_c
        self._state = BatteryState.DISCHARGING
        self._load_disconnected = False

        # Prepare interpolation arrays from OCV-SOC table
        table = self._c.ocv_soc_table or []
        self._soc_points = np.array([row[0] for row in table])
        self._ocv_points = np.array([row[1] for row in table])

        # Prepare R_internal temperature derating table
        temp_table = self._c.r_internal_temp_table or []
        self._temp_points = np.array([row[0] for row in temp_table])
        self._r_mult_points = np.array([row[1] for row in temp_table])

    @property
    def soc(self) -> float:
        """Current state of charge (0-100%).

        Returns:
            SOC percentage, always in [0, 100].

        Example:
            >>> battery = BatterySimulator(initial_soc=50.0)
            >>> 0.0 <= battery.soc <= 100.0
            True
        """
        return self._soc

    @property
    def state(self) -> BatteryState:
        """Current battery manager state.

        Returns:
            Current BatteryState enum value.

        Example:
            >>> battery = BatterySimulator(initial_soc=80.0)
            >>> battery.state
            <BatteryState.DISCHARGING: 'DISCHARGING'>
        """
        return self._state

    @property
    def is_load_disconnected(self) -> bool:
        """Whether the BMS has disconnected the motor load.

        Returns:
            True if BMS cutoff is active.

        Example:
            >>> battery = BatterySimulator(initial_soc=80.0)
            >>> battery.is_load_disconnected
            False
        """
        return self._load_disconnected

    @property
    def temperature_c(self) -> float:
        """Current battery temperature in Celsius.

        Returns:
            Temperature in °C.

        Example:
            >>> battery = BatterySimulator()
            >>> battery.temperature_c
            25.0
        """
        return self._temperature_c

    def _interpolate_ocv(self, soc: float) -> float:
        """Get per-cell OCV from SOC using linear interpolation.

        Args:
            soc: State of charge (0-100%).

        Returns:
            Per-cell open circuit voltage (V).

        Example:
            >>> battery = BatterySimulator()
            >>> 2.5 <= battery._interpolate_ocv(50.0) <= 3.65
            True
        """
        return float(np.interp(soc, self._soc_points, self._ocv_points))

    def _get_r_internal_multiplier(self, temp_c: float) -> float:
        """Get R_internal temperature derating multiplier.

        Args:
            temp_c: Battery temperature (°C).

        Returns:
            Multiplier for base R_internal.

        Example:
            >>> battery = BatterySimulator()
            >>> battery._get_r_internal_multiplier(25.0)
            1.0
        """
        return float(np.interp(temp_c, self._temp_points, self._r_mult_points))

    @property
    def r_internal(self) -> float:
        """Total pack internal resistance at current temperature (Ω).

        Returns:
            Pack internal resistance in ohms.

        Example:
            >>> battery = BatterySimulator()
            >>> battery.r_internal > 0
            True
        """
        r_cell = self._c.r_internal_base_ohm * self._get_r_internal_multiplier(self._temperature_c)
        return r_cell * self._c.series_cells

    @property
    def ocv(self) -> float:
        """Pack open-circuit voltage at current SOC (V).

        Returns:
            Pack OCV in volts (N_series × per-cell OCV).

        Example:
            >>> battery = BatterySimulator(initial_soc=50.0)
            >>> battery.ocv > 12.0
            True
        """
        return self._interpolate_ocv(self._soc) * self._c.series_cells

    @property
    def terminal_voltage(self) -> float:
        """Pack terminal voltage under current load (V).

        For no-load condition, returns OCV. Under load, V = OCV - I·R_internal.
        Currently returns OCV as instantaneous load is not tracked here;
        the caller (target.py) passes current through the step() method.

        Returns:
            Terminal voltage in volts.

        Example:
            >>> battery = BatterySimulator(initial_soc=50.0)
            >>> battery.terminal_voltage > 0
            True
        """
        return self.ocv

    def get_terminal_voltage_under_load(self, current_a: float) -> float:
        """Calculate terminal voltage under a specific load current.

        V_terminal = OCV(SOC) - I × R_internal(T)

        Args:
            current_a: Load current in amps (positive = discharging).

        Returns:
            Terminal voltage under load (V).

        Example:
            >>> battery = BatterySimulator(initial_soc=50.0)
            >>> v_load = battery.get_terminal_voltage_under_load(5.0)
            >>> v_noload = battery.get_terminal_voltage_under_load(0.0)
            >>> v_load < v_noload  # Voltage sag under load
            True
        """
        return self.ocv - current_a * self.r_internal

    def step(
        self,
        dt_sim_s: float,
        motor_current_a: float = 0.0,
        solar_charge_current_a: float = 0.0,
    ) -> None:
        """Advance the battery simulation by one timestep.

        Updates SOC by coulomb counting, manages BMS state machine,
        and clamps SOC to [0, 100].

        Args:
            dt_sim_s: Timestep in simulated seconds.
            motor_current_a: Motor load current (A, positive = discharge).
            solar_charge_current_a: Solar charge current (A, positive = charge).

        Example:
            >>> battery = BatterySimulator(initial_soc=50.0)
            >>> battery.step(1.0, motor_current_a=5.0)
            >>> battery.soc < 50.0  # SOC decreased under load
            True
        """
        c = self._c

        # Calculate quiescent load current from the bus voltage
        v_bus = self.ocv
        if v_bus > 0:
            quiescent_current = c.quiescent_load_w / v_bus
        else:
            quiescent_current = 0.0

        # Net current: positive = discharging
        if self._load_disconnected:
            # BMS has cut off motor, but electronics still draw
            net_current = quiescent_current - solar_charge_current_a
        else:
            net_current = motor_current_a + quiescent_current - solar_charge_current_a

        # Coulomb counting: dSOC/dt = -I_net / (C_nominal × η × 3600)
        # Negative net_current = charging (SOC increases)
        dsoc = -(net_current / (c.capacity_ah * c.coulombic_efficiency * 3600.0)) * dt_sim_s * 100.0

        self._soc += dsoc

        # === SOC CLAMPING (Pre-mortem F-14 mitigation) ===
        self._soc = max(0.0, min(100.0, self._soc))

        # === BMS STATE MACHINE ===
        self._update_state_machine(solar_charge_current_a, net_current)

    def _update_state_machine(
        self, solar_current_a: float, net_current_a: float
    ) -> None:
        """Update battery manager state machine based on current SOC and currents.

        Args:
            solar_current_a: Solar charge current (A).
            net_current_a: Net current (positive = discharge).

        Example:
            >>> battery = BatterySimulator(initial_soc=80.0)
            >>> battery._update_state_machine(0.0, 5.0)
        """
        c = self._c

        # Check for BMS cutoff
        if self._soc <= c.bms_cutoff_soc_pct and self._state != BatteryState.BMS_CUTOFF:
            self._state = BatteryState.BMS_CUTOFF
            self._load_disconnected = True
            return

        # State transitions
        if self._state == BatteryState.BMS_CUTOFF:
            # Only exit BMS cutoff when SOC recovers above cutoff + hysteresis
            if self._soc > c.bms_cutoff_soc_pct + 5 and solar_current_a > 0:
                self._state = BatteryState.CHARGING
                self._load_disconnected = False

        elif self._state == BatteryState.DISCHARGING:
            if self._soc < 20.0:
                self._state = BatteryState.LOW_SOC
            elif net_current_a < 0:  # Charging
                self._state = BatteryState.CHARGING

        elif self._state == BatteryState.LOW_SOC:
            if self._soc < 12.0:
                self._state = BatteryState.CRITICAL
            elif net_current_a < 0 and self._soc > 20.0:
                self._state = BatteryState.CHARGING
            elif self._soc > 20.0:
                self._state = BatteryState.DISCHARGING

        elif self._state == BatteryState.CRITICAL:
            if self._soc <= c.bms_cutoff_soc_pct:
                self._state = BatteryState.BMS_CUTOFF
                self._load_disconnected = True
            elif net_current_a < 0 and self._soc > 12.0:
                self._state = BatteryState.LOW_SOC

        elif self._state == BatteryState.CHARGING:
            if self._soc >= 98.0:
                ocv_cell = self._interpolate_ocv(self._soc)
                if ocv_cell >= 3.6:
                    self._state = BatteryState.FLOAT
            elif net_current_a > 0:
                self._state = BatteryState.DISCHARGING

        elif self._state == BatteryState.FLOAT:
            if net_current_a > 0 and self._soc < 95.0:
                self._state = BatteryState.DISCHARGING
            elif self._soc < 95.0:
                self._state = BatteryState.CHARGING

    def get_state_dict(self) -> dict[str, Any]:
        """Export current battery state for telemetry/persistence.

        Returns:
            Dictionary with all battery state fields.

        Example:
            >>> battery = BatterySimulator(initial_soc=75.0)
            >>> d = battery.get_state_dict()
            >>> 'soc' in d
            True
        """
        return {
            "soc": round(self._soc, 2),
            "ocv_v": round(self.ocv, 3),
            "terminal_voltage_v": round(self.terminal_voltage, 3),
            "r_internal_ohm": round(self.r_internal, 5),
            "temperature_c": round(self._temperature_c, 1),
            "state": self._state.value,
            "load_disconnected": self._load_disconnected,
        }
