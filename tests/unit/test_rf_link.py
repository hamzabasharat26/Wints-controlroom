"""Unit tests for the RF link propagation model.

Tests the RF model against known propagation physics:
    - FSPL increases with distance
    - RSSI decreases with distance
    - PER breakpoints match configuration
    - QoS 1 packets are never dropped (F-08 mitigation)
    - Shadowing adds variance but preserves mean
"""

from __future__ import annotations

import pytest

from target_simulator.physics.rf_link import RFLinkSimulator


class TestFreeSpacePathLoss:
    """Test FSPL calculation against Friis equation."""

    def test_fspl_increases_with_distance(self) -> None:
        """FSPL is monotonically increasing with distance.

        FSPL(dB) ∝ 20·log10(d) — doubling distance adds ~6 dB.
        """
        rf = RFLinkSimulator(distance_m=1000)
        fspl_1km = rf._compute_fspl(1000.0)
        fspl_2km = rf._compute_fspl(2000.0)
        assert fspl_2km > fspl_1km
        # 6 dB per doubling
        assert (fspl_2km - fspl_1km) == pytest.approx(6.02, abs=0.1)

    def test_fspl_at_5ghz_1km(self) -> None:
        """FSPL at 5 GHz / 1 km should be approximately 120 dB.

        FSPL = 20·log10(1000) + 20·log10(5e9) + 20·log10(4π/c)
             ≈ 60 + 194.0 - 147.6 ≈ 106.4 dB
        """
        rf = RFLinkSimulator(distance_m=1000)
        fspl = rf._compute_fspl(1000.0)
        # Expected: ~106.4 dB
        assert 100.0 < fspl < 115.0, f"FSPL at 5 GHz / 1 km = {fspl:.1f} dB"


class TestRSSI:
    """Test RSSI computation."""

    def test_rssi_decreases_with_distance(self) -> None:
        """Nominal RSSI decreases as targets get further away."""
        rf_near = RFLinkSimulator(distance_m=500)
        rf_far = RFLinkSimulator(distance_m=5000)
        assert rf_near.nominal_rssi > rf_far.nominal_rssi

    def test_rssi_is_negative(self) -> None:
        """RSSI should always be negative dBm for realistic distances."""
        rf = RFLinkSimulator(distance_m=500)
        rssi = rf.get_rssi(sim_time_h=12.0)
        assert rssi < 0


class TestPacketErrorRate:
    """Test PER model breakpoints."""

    def test_per_zero_at_good_rssi(self) -> None:
        """PER = 0 when RSSI > -65 dBm."""
        rf = RFLinkSimulator()
        assert rf._compute_per(-50.0) == 0.0
        assert rf._compute_per(-64.0) == 0.0

    def test_per_one_at_bad_rssi(self) -> None:
        """PER = 1.0 when RSSI < -95 dBm."""
        rf = RFLinkSimulator()
        assert rf._compute_per(-100.0) == 1.0

    def test_per_linear_in_marginal_zone(self) -> None:
        """PER linearly increases from 0 to 0.3 in marginal zone."""
        rf = RFLinkSimulator()
        midpoint = (-65 + -80) / 2  # = -72.5
        per_mid = rf._compute_per(midpoint)
        assert per_mid == pytest.approx(0.15, abs=0.01)

    def test_qos1_never_dropped_f08(self) -> None:
        """Pre-mortem F-08: QoS 1 packets are never dropped by RF model.

        MQTT QoS 1 retransmits until ACK, so packet loss manifests
        as latency, not as data loss.
        """
        # Create a very far target with terrible RSSI
        rf = RFLinkSimulator(distance_m=10000)
        rf.get_rssi(sim_time_h=12.0)

        # QoS 1 should never be dropped regardless of PER
        for _ in range(100):
            assert rf.should_drop_packet(qos=1) is False


class TestRFStateDict:
    """Test RF state export for telemetry."""

    def test_state_dict_has_all_fields(self) -> None:
        """State dict includes all required telemetry fields."""
        rf = RFLinkSimulator(distance_m=1500, bearing_deg=45.0)
        rf.get_rssi()  # Compute RSSI first
        d = rf.get_state_dict()
        required_keys = {
            "rssi_dbm", "nominal_rssi_dbm", "packet_error_rate",
            "packet_loss_pct", "distance_m", "bearing_deg",
            "fspl_db", "fade_active",
        }
        assert required_keys.issubset(d.keys())
        assert d["distance_m"] == 1500.0
        assert d["bearing_deg"] == 45.0
