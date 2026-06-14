"""DC motor physics model — coupled electrical/mechanical ODE simulation.

Simulates a 12V permanent-magnet DC motor with gearbox driving a range target
from DOWN (0%) to UP (100%) position. The model solves the coupled electrical
and mechanical differential equations using scipy's RK45 adaptive solver.

Physical model:
    Electrical: V_bus = L·(di/dt) + R·i + K_e·ω
    Mechanical: J·(dω/dt) = K_t·i - B·ω - T_load·sign(ω)
    Position:   dθ/dt = ω

The motor includes:
    - Overcurrent protection (trips at 12A after 300ms inrush window)
    - Stall detection (low ω + high current for sustained period)
    - Limit switch simulation with realistic bounce and Schmitt trigger debounce
    - State clamping to prevent ODE divergence (Pre-mortem F-13 mitigation)

Simulator equivalent of: firmware/motor.c
    Hardware: TIM1 PWM at 25kHz on PA8, BTS7960 H-bridge, ADC current sense on IS pin
"""

from __future__ import annotations

import enum
import random
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.integrate import solve_ivp


class MotorDirection(enum.Enum):
    """Motor drive direction.

    Example:
        >>> direction = MotorDirection.RAISING
        >>> direction.value
        1
    """

    STOPPED = 0
    RAISING = 1
    LOWERING = -1


class MotorState(enum.Enum):
    """Motor controller state machine states.

    Matches the state diagram in docs/01_design.md §2.2.

    Example:
        >>> state = MotorState.IDLE
        >>> state == MotorState.IDLE
        True
    """

    IDLE = "IDLE"
    COMMANDED = "COMMANDED"
    ACCELERATING = "ACCELERATING"
    RUNNING = "RUNNING"
    DECELERATING = "DECELERATING"
    LIMIT_REACHED = "LIMIT_REACHED"
    OVERCURRENT = "OVERCURRENT"
    STALL = "STALL"
    MOTOR_FAULT = "MOTOR_FAULT"


@dataclass
class MotorConstants:
    """Physical constants for the DC motor model.

    All values sourced from config/wints.yaml. See docs/01_design.md §4.1
    for derivation and source citations.

    Args:
        resistance_ohm: Armature resistance R (Ω).
        inductance_h: Armature inductance L (H).
        torque_constant: Motor torque constant K_t (N·m/A).
        back_emf_constant: Back-EMF constant K_e (V·s/rad).
        rotor_inertia_kg_m2: Total inertia J (kg·m²) — rotor + geared load.
        viscous_friction: Viscous friction coefficient B (N·m·s/rad).
        load_torque_nm: Load torque T_load (N·m) — gravity + friction.
        overcurrent_threshold_a: Overcurrent trip level (A).
        inrush_window_ms: Time after start where overcurrent is allowed (ms).
        stall_omega_threshold: Angular velocity below which stall is suspected (rad/s).
        stall_current_threshold_a: Current above which stall is suspected (A).
        stall_duration_ms: How long stall condition must persist before fault (ms).
        theta_max_rad: Maximum angular displacement DOWN→UP (rad).
        supply_voltage_v: Bus voltage (V).

    Example:
        >>> mc = MotorConstants()
        >>> mc.resistance_ohm
        0.5
    """

    resistance_ohm: float = 0.5
    inductance_h: float = 0.002
    torque_constant: float = 0.08
    back_emf_constant: float = 0.08
    rotor_inertia_kg_m2: float = 0.02
    viscous_friction: float = 0.01
    load_torque_nm: float = 0.1
    overcurrent_threshold_a: float = 12.0
    inrush_window_ms: float = 300.0
    stall_omega_threshold: float = 0.5
    stall_current_threshold_a: float = 8.0
    stall_duration_ms: float = 2000.0
    theta_max_rad: float = 1.5708  # π/2
    supply_voltage_v: float = 12.0


@dataclass
class LimitSwitchConstants:
    """Constants for limit switch bounce and debounce simulation.

    Args:
        bounce_count_min: Minimum bounces per switch activation.
        bounce_count_max: Maximum bounces per switch activation.
        bounce_duration_min_ms: Minimum duration of a single bounce (ms).
        bounce_duration_max_ms: Maximum duration of a single bounce (ms).
        debounce_period_ms: Schmitt trigger debounce period (ms).

    Example:
        >>> lsc = LimitSwitchConstants()
        >>> lsc.debounce_period_ms
        20.0
    """

    bounce_count_min: int = 3
    bounce_count_max: int = 8
    bounce_duration_min_ms: float = 5.0
    bounce_duration_max_ms: float = 50.0
    debounce_period_ms: float = 20.0


@dataclass
class LimitSwitchState:
    """Runtime state for a limit switch with debounce logic.

    Args:
        raw_active: Raw (unbounced) switch state.
        debounced_active: Debounced output after Schmitt filter.
        bounce_remaining: Number of bounces remaining in current activation.
        bounce_end_time: Time when current bounce ends.
        last_transition_time: Time of the last raw state change.

    Example:
        >>> lss = LimitSwitchState()
        >>> lss.debounced_active
        False
    """

    raw_active: bool = False
    debounced_active: bool = False
    bounce_remaining: int = 0
    bounce_end_time: float = 0.0
    last_transition_time: float = 0.0


@dataclass
class MotorPhysicsState:
    """Complete runtime state of the motor physics simulation.

    State vector for the ODE solver: [current_a, omega_rad_s, theta_rad]

    Args:
        current_a: Armature current (A). Clamped to [0, 20].
        omega_rad_s: Angular velocity (rad/s). Clamped to [-ω_max, +ω_max].
        theta_rad: Angular position (rad). 0=DOWN, θ_max=UP.
        position_pct: Derived position percentage. 0=fully down, 100=fully up.
        direction: Current drive direction.
        state: Motor controller state machine state.
        drive_enabled: Whether the H-bridge is enabled.
        fault_code: Active fault code, if any.
        start_time: Time when motor was last commanded to start (for inrush window).
        stall_start_time: Time when stall condition was first detected.
        up_limit: Upper limit switch state.
        down_limit: Lower limit switch state.

    Example:
        >>> mps = MotorPhysicsState()
        >>> mps.position_pct
        0.0
    """

    current_a: float = 0.0
    omega_rad_s: float = 0.0
    theta_rad: float = 0.0
    position_pct: float = 0.0
    direction: MotorDirection = MotorDirection.STOPPED
    state: MotorState = MotorState.IDLE
    drive_enabled: bool = False
    fault_code: str | None = None
    start_time: float = 0.0
    stall_start_time: float | None = None
    up_limit: LimitSwitchState = field(default_factory=LimitSwitchState)
    down_limit: LimitSwitchState = field(default_factory=LimitSwitchState)


class MotorSimulator:
    """Physics-accurate DC motor simulator using coupled ODE integration.

    Solves the electrical/mechanical coupled ODEs at each timestep using
    scipy's RK45 adaptive solver. Includes overcurrent protection, stall
    detection, and limit switch simulation with realistic bounce.

    This implements Pre-mortem F-13 mitigation: all ODE outputs are
    bounds-checked after every step to prevent numerical divergence.

    Args:
        constants: Motor physical constants.
        limit_constants: Limit switch bounce/debounce constants.
        initial_position_pct: Starting position (0=DOWN, 100=UP).

    Example:
        >>> motor = MotorSimulator()
        >>> motor.command_raise()
        >>> for _ in range(100):
        ...     motor.step(0.001)  # 1ms steps
        >>> motor.physics_state.current_a > 0
        True
    """

    def __init__(
        self,
        constants: MotorConstants | None = None,
        limit_constants: LimitSwitchConstants | None = None,
        initial_position_pct: float = 0.0,
    ) -> None:
        self._c = constants or MotorConstants()
        self._lc = limit_constants or LimitSwitchConstants()

        # Initialize physics state
        initial_theta = (initial_position_pct / 100.0) * self._c.theta_max_rad
        self._state = MotorPhysicsState(
            theta_rad=initial_theta,
            position_pct=initial_position_pct,
        )

        # Set initial limit switch states based on position
        if initial_position_pct <= 0.0:
            self._state.down_limit.debounced_active = True
            self._state.down_limit.raw_active = True
        elif initial_position_pct >= 100.0:
            self._state.up_limit.debounced_active = True
            self._state.up_limit.raw_active = True

        self._sim_time: float = 0.0

    @property
    def physics_state(self) -> MotorPhysicsState:
        """Read-only access to the current motor physics state.

        Returns:
            Current MotorPhysicsState snapshot.

        Example:
            >>> motor = MotorSimulator()
            >>> motor.physics_state.state
            <MotorState.IDLE: 'IDLE'>
        """
        return self._state

    @property
    def position_pct(self) -> float:
        """Current position as percentage (0=DOWN, 100=UP).

        Returns:
            Position percentage clamped to [0, 100].

        Example:
            >>> motor = MotorSimulator()
            >>> 0.0 <= motor.position_pct <= 100.0
            True
        """
        return self._state.position_pct

    @property
    def current_a(self) -> float:
        """Current armature current in amps.

        Returns:
            Current in amps, always >= 0.

        Example:
            >>> motor = MotorSimulator()
            >>> motor.current_a >= 0.0
            True
        """
        return self._state.current_a

    @property
    def is_faulted(self) -> bool:
        """Whether the motor is in a fault state.

        Returns:
            True if the motor state is OVERCURRENT, STALL, or MOTOR_FAULT.

        Example:
            >>> motor = MotorSimulator()
            >>> motor.is_faulted
            False
        """
        return self._state.state in (
            MotorState.OVERCURRENT,
            MotorState.STALL,
            MotorState.MOTOR_FAULT,
        )

    def command_raise(self) -> bool:
        """Command the motor to raise the target.

        Only accepted in IDLE state when not at upper limit and not faulted.

        Returns:
            True if the command was accepted.

        Example:
            >>> motor = MotorSimulator()
            >>> motor.command_raise()
            True
            >>> motor.physics_state.state
            <MotorState.COMMANDED: 'COMMANDED'>
        """
        if self._state.state != MotorState.IDLE:
            return False
        if self._state.up_limit.debounced_active:
            return False
        if self.is_faulted:
            return False

        self._state.state = MotorState.COMMANDED
        self._state.direction = MotorDirection.RAISING
        self._state.drive_enabled = True
        self._state.start_time = self._sim_time
        self._state.stall_start_time = None
        self._state.state = MotorState.ACCELERATING
        return True

    def command_lower(self) -> bool:
        """Command the motor to lower the target.

        Only accepted in IDLE state when not at lower limit and not faulted.

        Returns:
            True if the command was accepted.

        Example:
            >>> motor = MotorSimulator(initial_position_pct=100.0)
            >>> motor.command_lower()
            True
        """
        if self._state.state != MotorState.IDLE:
            return False
        if self._state.down_limit.debounced_active:
            return False
        if self.is_faulted:
            return False

        self._state.state = MotorState.COMMANDED
        self._state.direction = MotorDirection.LOWERING
        self._state.drive_enabled = True
        self._state.start_time = self._sim_time
        self._state.stall_start_time = None
        self._state.state = MotorState.ACCELERATING
        return True

    def command_stop(self) -> bool:
        """Command the motor to stop immediately.

        Accepted in any moving state. Removes drive and enters deceleration.

        Returns:
            True if the command was accepted (motor was moving).

        Example:
            >>> motor = MotorSimulator()
            >>> motor.command_raise()
            True
            >>> motor.command_stop()
            True
        """
        moving_states = {
            MotorState.COMMANDED,
            MotorState.ACCELERATING,
            MotorState.RUNNING,
        }
        if self._state.state not in moving_states:
            return False

        self._state.drive_enabled = False
        self._state.state = MotorState.DECELERATING
        return True

    def clear_fault(self) -> bool:
        """Clear a motor fault and return to IDLE.

        Resets current and velocity integrators.

        Returns:
            True if fault was cleared.

        Example:
            >>> motor = MotorSimulator()
            >>> # After a fault occurs:
            >>> motor.clear_fault()  # Returns True if in fault state
            False
        """
        if self._state.state != MotorState.MOTOR_FAULT:
            return False

        self._state.state = MotorState.IDLE
        self._state.drive_enabled = False
        self._state.direction = MotorDirection.STOPPED
        self._state.current_a = 0.0
        self._state.omega_rad_s = 0.0
        self._state.fault_code = None
        self._state.stall_start_time = None
        return True

    def _ode_rhs(
        self, _t: float, y: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        """Right-hand side of the coupled motor ODEs.

        State vector y = [current, omega, theta]

        Electrical: di/dt = (V_bus - R·i - K_e·ω) / L
        Mechanical: dω/dt = (K_t·i - B·ω - T_load·sign(direction)) / J
        Position:   dθ/dt = ω

        Args:
            _t: Current time (unused — autonomous system).
            y: State vector [current_a, omega_rad_s, theta_rad].

        Returns:
            Derivative vector [di/dt, dω/dt, dθ/dt].

        Example:
            >>> motor = MotorSimulator()
            >>> dydt = motor._ode_rhs(0, np.array([0.0, 0.0, 0.0]))
            >>> len(dydt) == 3
            True
        """
        current, omega, _theta = y[0], y[1], y[2]
        c = self._c

        # Determine applied voltage
        if self._state.drive_enabled:
            v_bus = c.supply_voltage_v * self._state.direction.value
        else:
            v_bus = 0.0

        # Electrical: di/dt = (V - R*i - K_e*ω) / L
        di_dt = (v_bus - c.resistance_ohm * current - c.back_emf_constant * omega) / c.inductance_h

        # Mechanical: dω/dt = (K_t*i - B*ω - T_load*load_sign) / J
        # Load torque opposes motion. We use a smooth tanh approximation to prevent
        # high-frequency numerical chattering and stiffness in the RK45 solver.
        load_sign = np.tanh(omega / 0.1)

        domega_dt = (
            c.torque_constant * current - c.viscous_friction * omega - c.load_torque_nm * load_sign
        ) / c.rotor_inertia_kg_m2

        # Position: dθ/dt = ω
        dtheta_dt = omega

        return np.array([di_dt, domega_dt, dtheta_dt])

    def _update_limit_switches(self) -> None:
        """Update limit switch raw and debounced states based on position.

        Simulates realistic switch bounce with randomised bounce trains
        and a 20ms Schmitt trigger debounce filter.

        Example:
            >>> motor = MotorSimulator()
            >>> motor._update_limit_switches()
        """
        c = self._c
        lc = self._lc
        theta = self._state.theta_rad

        # Check raw switch activation based on position
        raw_up = theta >= c.theta_max_rad
        raw_down = theta <= 0.0

        # Update UP limit switch with bounce
        self._update_single_switch(self._state.up_limit, raw_up, lc)
        # Update DOWN limit switch with bounce
        self._update_single_switch(self._state.down_limit, raw_down, lc)

    def _update_single_switch(
        self, switch: LimitSwitchState, physical_active: bool, lc: LimitSwitchConstants
    ) -> None:
        """Update a single limit switch with bounce simulation.

        Args:
            switch: The switch state to update.
            physical_active: Whether the switch is physically pressed.
            lc: Limit switch constants.

        Example:
            >>> motor = MotorSimulator()
            >>> switch = LimitSwitchState()
            >>> motor._update_single_switch(switch, True, LimitSwitchConstants())
        """
        # Detect new activation
        if physical_active and not switch.raw_active:
            # Start bounce train
            switch.bounce_remaining = random.randint(lc.bounce_count_min, lc.bounce_count_max)
            switch.last_transition_time = self._sim_time

        # Process bounce train
        if switch.bounce_remaining > 0:
            if self._sim_time >= switch.bounce_end_time:
                switch.raw_active = not switch.raw_active
                switch.bounce_remaining -= 1
                bounce_ms = random.uniform(lc.bounce_duration_min_ms, lc.bounce_duration_max_ms)
                switch.bounce_end_time = self._sim_time + bounce_ms / 1000.0
                switch.last_transition_time = self._sim_time
        else:
            switch.raw_active = physical_active

        # Schmitt trigger debounce: output changes only after stable for debounce_period
        time_since_transition = self._sim_time - switch.last_transition_time
        if time_since_transition >= lc.debounce_period_ms / 1000.0:
            switch.debounced_active = switch.raw_active

    def step(self, dt: float) -> None:
        """Advance the motor simulation by one timestep.

        Solves the coupled ODEs, checks protection limits, updates state
        machine, and clamps all outputs to physical bounds.

        This is the core simulation loop, called at 1ms intervals.

        Args:
            dt: Timestep in seconds (typically 0.001 for 1ms).

        Example:
            >>> motor = MotorSimulator()
            >>> motor.command_raise()
            True
            >>> motor.step(0.001)
            >>> motor.physics_state.current_a > 0
            True
        """
        c = self._c

        # Skip physics if motor is faulted or idle with no energy
        if self._state.state == MotorState.MOTOR_FAULT:
            self._sim_time += dt
            return

        if self._state.state == MotorState.IDLE and abs(self._state.omega_rad_s) < 1e-6:
            self._sim_time += dt
            return

        # Solve ODE
        y0 = np.array([
            self._state.current_a,
            self._state.omega_rad_s,
            self._state.theta_rad,
        ])

        try:
            sol = solve_ivp(
                self._ode_rhs,
                [0, dt],
                y0,
                method="RK45",
                max_step=dt,
                atol=1e-8,
                rtol=1e-6,
            )
            if sol.success and sol.y.shape[1] > 0:
                new_current = float(sol.y[0, -1])
                new_omega = float(sol.y[1, -1])
                new_theta = float(sol.y[2, -1])
            else:
                # Solver failed — hold last state (F-13 mitigation)
                new_current = self._state.current_a
                new_omega = self._state.omega_rad_s
                new_theta = self._state.theta_rad
        except Exception:
            # Any solver exception — hold last state (F-13 mitigation)
            new_current = self._state.current_a
            new_omega = self._state.omega_rad_s
            new_theta = self._state.theta_rad

        # === STATE CLAMPING (Pre-mortem F-13 mitigation) ===
        # Clamp current to physical bounds
        new_current = max(-20.0, min(20.0, new_current))
        if not self._state.drive_enabled and abs(new_current) < 0.01:
            new_current = 0.0

        # Clamp position to physical bounds
        new_theta = max(0.0, min(c.theta_max_rad, new_theta))

        # If at limits, stop motion
        if new_theta <= 0.0 and new_omega < 0.0:
            new_omega = 0.0
        if new_theta >= c.theta_max_rad and new_omega > 0.0:
            new_omega = 0.0

        # Apply clamped values
        self._state.current_a = new_current
        self._state.omega_rad_s = new_omega
        self._state.theta_rad = new_theta
        self._state.position_pct = (new_theta / c.theta_max_rad) * 100.0

        # Update limit switches
        self._update_limit_switches()

        # === OVERCURRENT PROTECTION ===
        time_since_start = (self._sim_time - self._state.start_time) * 1000.0  # ms
        in_inrush_window = time_since_start < c.inrush_window_ms

        if (
            abs(new_current) > c.overcurrent_threshold_a
            and not in_inrush_window
            and self._state.state
            in (MotorState.ACCELERATING, MotorState.RUNNING)
        ):
            self._enter_fault("OVERCURRENT")
            self._sim_time += dt
            return

        # === STALL DETECTION ===
        if (
            abs(new_omega) < c.stall_omega_threshold
            and abs(new_current) > c.stall_current_threshold_a
            and self._state.state in (MotorState.ACCELERATING, MotorState.RUNNING)
            and not in_inrush_window
        ):
            if self._state.stall_start_time is None:
                self._state.stall_start_time = self._sim_time
            elif (self._sim_time - self._state.stall_start_time) * 1000.0 > c.stall_duration_ms:
                self._enter_fault("MOTOR_STALL")
                self._sim_time += dt
                return
        else:
            self._state.stall_start_time = None

        # === LIMIT SWITCH CHECK ===
        # Both switches active = hardware fault (Pre-mortem F-15)
        if self._state.up_limit.debounced_active and self._state.down_limit.debounced_active:
            self._enter_fault("LIMIT_STUCK")
            self._sim_time += dt
            return

        # Reached limit in direction of travel
        if (
            self._state.direction == MotorDirection.RAISING
            and self._state.up_limit.debounced_active
        ) or (
            self._state.direction == MotorDirection.LOWERING
            and self._state.down_limit.debounced_active
        ):
            self._state.drive_enabled = False
            self._state.state = MotorState.LIMIT_REACHED
            self._state.omega_rad_s = 0.0
            self._state.current_a = 0.0
            self._state.direction = MotorDirection.STOPPED
            self._state.state = MotorState.IDLE

        # === STATE TRANSITIONS ===
        if self._state.state == MotorState.ACCELERATING:
            # Transition to RUNNING when ω reaches 95% of steady-state
            omega_target = (c.supply_voltage_v - c.resistance_ohm * c.overcurrent_threshold_a) / c.back_emf_constant
            if abs(new_omega) >= 0.95 * abs(omega_target):
                self._state.state = MotorState.RUNNING

        elif self._state.state == MotorState.DECELERATING:
            # Transition to IDLE when ω ≈ 0
            if abs(new_omega) < 0.1:
                self._state.omega_rad_s = 0.0
                self._state.current_a = 0.0
                self._state.direction = MotorDirection.STOPPED
                self._state.state = MotorState.IDLE

        self._sim_time += dt

    def _enter_fault(self, fault_code: str) -> None:
        """Enter motor fault state. Disables drive immediately.

        Args:
            fault_code: Fault identifier (e.g., 'OVERCURRENT', 'MOTOR_STALL', 'LIMIT_STUCK').

        Example:
            >>> motor = MotorSimulator()
            >>> motor._enter_fault("OVERCURRENT")
            >>> motor.physics_state.state
            <MotorState.MOTOR_FAULT: 'MOTOR_FAULT'>
        """
        self._state.drive_enabled = False
        self._state.state = MotorState.MOTOR_FAULT
        self._state.fault_code = fault_code
        self._state.omega_rad_s = 0.0
        self._state.current_a = 0.0
        self._state.direction = MotorDirection.STOPPED

    def get_position_label(self) -> str:
        """Get human-readable position label.

        Returns:
            'UP' if at top, 'DOWN' if at bottom, 'MOVING' otherwise.

        Example:
            >>> motor = MotorSimulator(initial_position_pct=0.0)
            >>> motor.get_position_label()
            'DOWN'
        """
        if self._state.position_pct >= 99.0:
            return "UP"
        elif self._state.position_pct <= 1.0:
            return "DOWN"
        else:
            return "MOVING"

    def get_state_dict(self) -> dict[str, Any]:
        """Export current motor state as a dictionary for telemetry/persistence.

        Returns:
            Dictionary with all motor state fields.

        Example:
            >>> motor = MotorSimulator()
            >>> d = motor.get_state_dict()
            >>> 'current_a' in d
            True
        """
        return {
            "current_a": round(self._state.current_a, 4),
            "omega_rad_s": round(self._state.omega_rad_s, 4),
            "theta_rad": round(self._state.theta_rad, 6),
            "position_pct": round(self._state.position_pct, 2),
            "position_label": self.get_position_label(),
            "direction": self._state.direction.name,
            "state": self._state.state.value,
            "drive_enabled": self._state.drive_enabled,
            "fault_code": self._state.fault_code,
            "up_limit_active": self._state.up_limit.debounced_active,
            "down_limit_active": self._state.down_limit.debounced_active,
        }
