"""RF link propagation model — FSPL, shadowing, and packet error rate.

Simulates a 5 GHz 802.11n wireless link between each target and the
control room, using:
    - Free-space path loss (Friis equation)
    - Log-normal shadowing with configurable σ
    - Periodic fading events (σ doubles for 30 sim-seconds per hour)
    - Packet error rate (PER) derived from RSSI
    - Simulated packet drops for QoS 0 telemetry

Source: Ubiquiti NanoBeam 5AC Gen2 datasheet for antenna gains and
typical link budgets. Standard RF propagation models from
Rappaport, "Wireless Communications: Principles and Practice."

Simulator equivalent of: firmware/network.c (RF link quality section)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

# Speed of light (m/s)
_SPEED_OF_LIGHT: float = 2.998e8


@dataclass
class RFLinkConstants:
    """Physical constants for the RF link model.

    All values sourced from config/wints.yaml. Antenna gains from
    Ubiquiti airMAX product specifications.

    Args:
        frequency_hz: Carrier frequency (Hz).
        tx_power_dbm: Transmit power (dBm).
        tx_antenna_gain_dbi: Transmit antenna gain (dBi).
        rx_antenna_gain_dbi: Receive antenna gain (dBi).
        misc_losses_db: Cable, connector, and fade margin losses (dB).
        shadow_std_db: Log-normal shadowing standard deviation (dB).
        shadow_fade_duration_sim_s: Duration of fading events (sim seconds).
        shadow_fade_multiplier: Factor by which σ increases during fading.
        per_good_rssi_dbm: RSSI above which PER = 0.
        per_marginal_rssi_dbm: RSSI at which PER reaches 0.3.
        per_bad_rssi_dbm: RSSI at which PER reaches 1.0.

    Example:
        >>> rfc = RFLinkConstants()
        >>> rfc.frequency_hz
        5000000000.0
    """

    frequency_hz: float = 5.0e9
    tx_power_dbm: float = 23.0
    tx_antenna_gain_dbi: float = 16.0
    rx_antenna_gain_dbi: float = 23.0
    misc_losses_db: float = 3.0
    shadow_std_db: float = 6.0
    shadow_fade_duration_sim_s: float = 30.0
    shadow_fade_multiplier: float = 2.0
    per_good_rssi_dbm: float = -65.0
    per_marginal_rssi_dbm: float = -80.0
    per_bad_rssi_dbm: float = -95.0


class RFLinkSimulator:
    """RF link propagation simulator.

    Computes RSSI from distance and link budget, applies log-normal
    shadowing with periodic fading events, and derives packet error
    rate from the resulting RSSI.

    Args:
        constants: RF link physical constants.
        distance_m: Distance between target and control room (m).
        bearing_deg: Bearing from control room (degrees, unused in model
                     but stored for position display).

    Example:
        >>> rf = RFLinkSimulator(distance_m=500)
        >>> rssi = rf.get_rssi(sim_time_h=12.0)
        >>> rssi < 0  # RSSI is always negative in dBm
        True
    """

    def __init__(
        self,
        constants: RFLinkConstants | None = None,
        distance_m: float = 1000.0,
        bearing_deg: float = 0.0,
    ) -> None:
        self._c = constants or RFLinkConstants()
        self._distance_m = max(1.0, distance_m)  # Minimum 1m to avoid log(0)
        self._bearing_deg = bearing_deg
        self._rng = random.Random()

        # Pre-compute free-space path loss (constant for a fixed distance)
        self._fspl_db = self._compute_fspl(self._distance_m)

        # Nominal RSSI without shadowing
        self._nominal_rssi = (
            self._c.tx_power_dbm
            + self._c.tx_antenna_gain_dbi
            + self._c.rx_antenna_gain_dbi
            - self._fspl_db
            - self._c.misc_losses_db
        )

        # Fading event tracking
        self._fade_active = False
        self._fade_end_time_h: float = 0.0
        self._last_fade_hour: int = -1

        # Cache last computed values
        self._last_rssi: float = self._nominal_rssi
        self._last_per: float = 0.0

    def _compute_fspl(self, distance_m: float) -> float:
        """Compute free-space path loss in dB using Friis equation.

        FSPL(dB) = 20·log10(d) + 20·log10(f) + 20·log10(4π/c)

        Args:
            distance_m: Distance in meters (must be > 0).

        Returns:
            Free-space path loss in dB.

        Example:
            >>> rf = RFLinkSimulator()
            >>> fspl = rf._compute_fspl(1000.0)
            >>> fspl > 100  # Significant at 5 GHz / 1 km
            True
        """
        f = self._c.frequency_hz
        return (
            20.0 * math.log10(distance_m)
            + 20.0 * math.log10(f)
            + 20.0 * math.log10(4.0 * math.pi / _SPEED_OF_LIGHT)
        )

    def _get_shadowing_db(self, sim_time_h: float) -> float:
        """Generate log-normal shadowing value with periodic fading.

        Once per simulated hour, a fading event may occur, doubling the
        shadowing σ for 30 simulated seconds.

        Args:
            sim_time_h: Current simulated time in hours.

        Returns:
            Shadowing loss in dB (always positive — it's a loss).

        Example:
            >>> rf = RFLinkSimulator()
            >>> s = rf._get_shadowing_db(12.0)
            >>> s >= 0  # Shadowing is a loss
            False  # Actually it can be negative (gain from multipath)
        """
        current_hour = int(sim_time_h)

        # Check for fading event trigger (once per sim hour)
        if current_hour != self._last_fade_hour:
            self._last_fade_hour = current_hour
            # Random chance of fading event
            if self._rng.random() < 0.3:  # 30% chance per hour
                self._fade_active = True
                self._fade_end_time_h = sim_time_h + (
                    self._c.shadow_fade_duration_sim_s / 3600.0
                )

        # Check if fading has ended
        if self._fade_active and sim_time_h >= self._fade_end_time_h:
            self._fade_active = False

        # Determine current σ
        sigma = self._c.shadow_std_db
        if self._fade_active:
            sigma *= self._c.shadow_fade_multiplier

        return self._rng.gauss(0, sigma)

    def get_rssi(self, sim_time_h: float = 0.0) -> float:
        """Compute current RSSI in dBm.

        RSSI = P_tx + G_tx + G_rx - FSPL - L_shadow - L_misc

        Args:
            sim_time_h: Current simulated time in hours (for fading events).

        Returns:
            RSSI in dBm (negative value).

        Example:
            >>> rf = RFLinkSimulator(distance_m=500)
            >>> rssi = rf.get_rssi()
            >>> -100 < rssi < 0
            True
        """
        shadowing = self._get_shadowing_db(sim_time_h)
        self._last_rssi = self._nominal_rssi - shadowing
        self._last_per = self._compute_per(self._last_rssi)
        return self._last_rssi

    def _compute_per(self, rssi_dbm: float) -> float:
        """Compute packet error rate from RSSI.

        PER model:
            RSSI > -65 dBm:  PER = 0.0
            -80 to -65 dBm:  PER linearly 0 → 0.3
            -95 to -80 dBm:  PER linearly 0.3 → 1.0
            RSSI < -95 dBm:  PER = 1.0

        Args:
            rssi_dbm: Received signal strength in dBm.

        Returns:
            Packet error rate (0.0 to 1.0).

        Example:
            >>> rf = RFLinkSimulator()
            >>> rf._compute_per(-50.0)
            0.0
            >>> rf._compute_per(-72.5)  # Midpoint of -65 to -80
            0.15
            >>> rf._compute_per(-100.0)
            1.0
        """
        c = self._c
        if rssi_dbm > c.per_good_rssi_dbm:
            return 0.0
        elif rssi_dbm >= c.per_marginal_rssi_dbm:
            # Linear from 0 to 0.3
            fraction = (c.per_good_rssi_dbm - rssi_dbm) / (
                c.per_good_rssi_dbm - c.per_marginal_rssi_dbm
            )
            return 0.3 * fraction
        elif rssi_dbm >= c.per_bad_rssi_dbm:
            # Linear from 0.3 to 1.0
            fraction = (c.per_marginal_rssi_dbm - rssi_dbm) / (
                c.per_marginal_rssi_dbm - c.per_bad_rssi_dbm
            )
            return 0.3 + 0.7 * fraction
        else:
            return 1.0

    @property
    def packet_error_rate(self) -> float:
        """Last computed packet error rate.

        Returns:
            PER from 0.0 to 1.0.

        Example:
            >>> rf = RFLinkSimulator(distance_m=500)
            >>> _ = rf.get_rssi()
            >>> 0.0 <= rf.packet_error_rate <= 1.0
            True
        """
        return self._last_per

    def should_drop_packet(self, qos: int = 0) -> bool:
        """Determine if a packet should be dropped based on RF model.

        QoS 1 packets are NEVER dropped (F-08 mitigation): MQTT QoS 1
        retransmits until acknowledged, so packet loss manifests as
        latency, not as loss. Only QoS 0 (best-effort) telemetry
        packets are subject to RF-modelled drops.

        Args:
            qos: MQTT QoS level (0 or 1).

        Returns:
            True if the packet should be dropped.

        Example:
            >>> rf = RFLinkSimulator(distance_m=500)
            >>> _ = rf.get_rssi()
            >>> rf.should_drop_packet(qos=1)  # QoS 1 never dropped
            False
        """
        # F-08 mitigation: QoS 1 is never dropped by the RF model
        if qos >= 1:
            return False

        return self._rng.random() < self._last_per

    @property
    def nominal_rssi(self) -> float:
        """Nominal RSSI without shadowing effects (for display).

        Returns:
            Nominal RSSI in dBm.

        Example:
            >>> rf = RFLinkSimulator(distance_m=500)
            >>> rf.nominal_rssi < 0
            True
        """
        return self._nominal_rssi

    @property
    def distance_m(self) -> float:
        """Distance from control room in meters.

        Returns:
            Distance in meters.

        Example:
            >>> rf = RFLinkSimulator(distance_m=1500)
            >>> rf.distance_m
            1500.0
        """
        return self._distance_m

    def get_state_dict(self) -> dict[str, Any]:
        """Export current RF state for telemetry.

        Returns:
            Dictionary with RF link state fields.

        Example:
            >>> rf = RFLinkSimulator(distance_m=500)
            >>> _ = rf.get_rssi()
            >>> d = rf.get_state_dict()
            >>> 'rssi_dbm' in d
            True
        """
        return {
            "rssi_dbm": round(self._last_rssi, 1),
            "nominal_rssi_dbm": round(self._nominal_rssi, 1),
            "packet_error_rate": round(self._last_per, 4),
            "packet_loss_pct": round(self._last_per * 100, 2),
            "distance_m": self._distance_m,
            "bearing_deg": self._bearing_deg,
            "fspl_db": round(self._fspl_db, 1),
            "fade_active": self._fade_active,
        }
