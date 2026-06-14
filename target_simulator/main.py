"""WINTS Target Simulator — main entry point.

Spawns 10 asyncio tasks, one per simulated target. Each target runs
independently with its own physics engine, MQTT client, and fault
injection API.

Usage:
    python -m target_simulator.main
    python -m target_simulator.main --fault T-07 --offline T-09

Target positions, initial SOCs, and RF distances are loaded from
config/wints.yaml.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Any

import structlog
import yaml

from target_simulator.target import TargetSimulator

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _setup_logging() -> None:
    """Configure structlog with JSON rendering for production logging.

    Uses structlog's JSONRenderer for machine-readable output and
    ConsoleRenderer for human-readable development output.

    Example:
        >>> _setup_logging()
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _load_config() -> dict[str, Any]:
    """Load simulation configuration from config/wints.yaml.

    Returns:
        Configuration dictionary.

    Raises:
        FileNotFoundError: If config file is missing.

    Example:
        >>> config = _load_config()
        >>> 'targets' in config
        True
    """
    config_path = PROJECT_ROOT / "config" / "wints.yaml"
    if not config_path.exists():
        msg = f"Config file not found: {config_path}"
        raise FileNotFoundError(msg)

    with open(config_path) as f:
        config: dict[str, Any] = yaml.safe_load(f)
    return config


async def run_all_targets(
    config: dict[str, Any],
    fault_target: str | None = None,
    offline_target: str | None = None,
) -> None:
    """Spawn and run all 10 target simulator tasks.

    Args:
        config: Configuration dictionary from wints.yaml.
        fault_target: Target ID to start in FAULT state (e.g., 'T-07').
        offline_target: Target ID to start OFFLINE (e.g., 'T-09').

    Example:
        >>> # asyncio.run(run_all_targets(config))
    """
    logger = structlog.get_logger("simulator")
    logger.info("starting_simulator", target_count=len(config.get("targets", {})))

    broker_cfg = config.get("broker", {})
    sim_cfg = config.get("simulation", {})
    port_cfg = config.get("ports", {})

    targets: list[TargetSimulator] = []
    tasks: list[asyncio.Task[None]] = []

    target_configs = config.get("targets", {})

    for i, (target_id, target_cfg) in enumerate(sorted(target_configs.items()), start=1):
        target = TargetSimulator(
            target_id=target_id,
            broker_host=broker_cfg.get("host", "localhost"),
            broker_port=broker_cfg.get("port", 1883),
            distance_m=target_cfg.get("distance_m", 1000),
            bearing_deg=target_cfg.get("bearing_deg", 0),
            initial_soc=target_cfg.get("initial_soc", 80),
            initial_position_pct=0.0,
            time_accel=sim_cfg.get("time_acceleration_factor", 60),
            fault_injector_port=port_cfg.get("fault_injector_base", 9301) + i - 1,
            start_offline=(target_id == offline_target),
            start_faulted=(target_id == fault_target),
        )
        targets.append(target)
        task = asyncio.create_task(target.run(), name=f"target-{target_id}")
        tasks.append(task)

    logger.info(
        "all_targets_spawned",
        count=len(tasks),
        fault=fault_target,
        offline=offline_target,
    )

    # Wait for all tasks (they run until cancelled)
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("simulator_cancelled")
        for target in targets:
            target.stop()


def main() -> None:
    """CLI entry point for the target simulator.

    Parses command-line arguments and runs the asyncio event loop.

    Example:
        >>> # main()  # Blocks until Ctrl+C
    """
    import argparse

    parser = argparse.ArgumentParser(description="WINTS Target Simulator")
    parser.add_argument("--fault", type=str, default=None, help="Target to start faulted")
    parser.add_argument("--offline", type=str, default=None, help="Target to start offline")
    args = parser.parse_args()

    _setup_logging()
    logger = structlog.get_logger("main")

    try:
        config = _load_config()
    except FileNotFoundError as exc:
        logger.error("config_not_found", error=str(exc))
        sys.exit(1)

    logger.info("wints_simulator_starting")

    # Handle graceful shutdown
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    main_task = loop.create_task(
        run_all_targets(config, fault_target=args.fault, offline_target=args.offline)
    )

    # Handle Ctrl+C
    def _shutdown(sig: int) -> None:
        logger.info("shutdown_signal_received", signal=sig)
        main_task.cancel()

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _shutdown, sig)

    try:
        loop.run_until_complete(main_task)
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt")
        main_task.cancel()
        try:
            loop.run_until_complete(main_task)
        except asyncio.CancelledError:
            pass
    finally:
        loop.close()
        logger.info("simulator_stopped")


if __name__ == "__main__":
    main()
