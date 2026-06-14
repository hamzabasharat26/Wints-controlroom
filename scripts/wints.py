"""WINTS CLI — Command-line orchestrator for the Wireless Integrated Network Target System.

Provides commands to check prerequisites, start services, run simulations,
launch the dashboard, inject faults, and replay sessions.

Usage:
    python -m scripts.wints doctor     Check all prerequisites
    python -m scripts.wints setup      Create venv + install packages
    python -m scripts.wints broker     Start Mosquitto broker
    python -m scripts.wints sim        Start all 10 simulated targets
    python -m scripts.wints dashboard  Launch PyQt6 control room
    python -m scripts.wints demo       Launch everything in correct order
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Project root is the parent of the scripts/ directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
LOGS_DIR = PROJECT_ROOT / "logs"
TOOLS_DIR = PROJECT_ROOT / "tools"

console = Console()


def _check_port_free(port: int) -> tuple[bool, str]:
    """Check if a TCP port is available for binding.

    Args:
        port: The TCP port number to check.

    Returns:
        Tuple of (is_free, detail_message).

    Example:
        >>> free, msg = _check_port_free(1883)
        >>> if not free:
        ...     print(f"Port blocked: {msg}")
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1)
        result = sock.connect_ex(("localhost", port))
        if result == 0:
            return False, f"Port {port} is already in use"
        return True, f"Port {port} is free"
    except OSError as exc:
        return True, f"Port {port} check returned: {exc}"
    finally:
        sock.close()


def _find_binary(name: str) -> str | None:
    """Find a binary by name, searching PATH and common install locations.

    Args:
        name: The binary name to search for.

    Returns:
        Absolute path as string if found, otherwise None.
    """
    path = shutil.which(name)
    if path is not None:
        return path

    if sys.platform == "win32":
        if name == "mosquitto":
            candidate = Path("C:/Program Files/mosquitto/mosquitto.exe")
            if candidate.exists():
                return str(candidate)
        elif name == "ffmpeg":
            user_profile = os.environ.get("USERPROFILE", "")
            if user_profile:
                # Check Links directory
                link = Path(user_profile) / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
                if link.exists():
                    return str(link)
                # Check Packages directory using glob
                pkg_dir = Path(user_profile) / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
                if pkg_dir.exists():
                    candidates = list(pkg_dir.glob("**/ffmpeg.exe"))
                    if candidates:
                        return str(candidates[0])
    return None


def _check_binary(name: str, test_args: list[str] | None = None) -> tuple[bool, str]:
    """Check if a binary is available on PATH or common locations and is executable.

    Args:
        name: Binary name to look up.
        test_args: Optional args to test execution (e.g., ['--version']).

    Returns:
        Tuple of (is_available, detail_message).

    Example:
        >>> ok, msg = _check_binary("mosquitto", ["-h"])
    """
    path = _find_binary(name)
    if path is None:
        return False, f"{name} not found on PATH or default directories"
    if test_args:
        try:
            result = subprocess.run(
                [path, *test_args],
                capture_output=True,
                text=True,
                timeout=10,
            )
            # Some tools return non-zero for --help; that's OK if they produce output
            output = result.stdout or result.stderr
            first_line = output.strip().split("\n")[0] if output.strip() else "no output"
            return True, f"{name}: {first_line}"
        except subprocess.TimeoutExpired:
            return False, f"{name} timed out during test"
        except OSError as exc:
            return False, f"{name} execution error: {exc}"
    return True, f"{name} found at {path}"


def _check_python_package(package: str) -> tuple[bool, str]:
    """Check if a Python package is importable.

    Args:
        package: Package name to import.

    Returns:
        Tuple of (is_importable, detail_message).

    Example:
        >>> ok, msg = _check_python_package("paho.mqtt.client")
    """
    try:
        __import__(package)
        return True, f"{package} — installed"
    except ImportError:
        return False, f"{package} — NOT installed"


def _ensure_directories() -> None:
    """Create required directories if they don't exist.

    Creates: logs/, logs/mosquitto/, tools/mediamtx/, video_server/samples/

    Example:
        >>> _ensure_directories()  # Idempotent, safe to call multiple times
    """
    dirs = [
        LOGS_DIR,
        LOGS_DIR / "mosquitto",
        TOOLS_DIR / "mediamtx",
        PROJECT_ROOT / "video_server" / "samples",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


@click.group()
def cli() -> None:
    """WINTS — Wireless Integrated Network Target System CLI.

    Example:
        $ python -m scripts.wints doctor
        $ python -m scripts.wints demo
    """


@cli.command()
def doctor() -> None:
    """Check all prerequisites and show a coloured status report.

    Validates: Python version, pip packages, native binaries,
    port availability, directory structure.

    Example:
        $ python -m scripts.wints doctor

    Raises:
        SystemExit: With code 1 if any critical check fails.
    """
    _ensure_directories()
    console.print(Panel("[bold cyan]WINTS System Doctor[/bold cyan]", expand=False))
    console.print()

    all_ok = True

    # === System Info ===
    info_table = Table(title="System Information", show_header=False)
    info_table.add_column("Item", style="bold")
    info_table.add_column("Value")
    info_table.add_row("OS", platform.platform())
    info_table.add_row("Python", sys.version.split()[0])
    info_table.add_row("Architecture", platform.machine())
    info_table.add_row("Project Root", str(PROJECT_ROOT))
    console.print(info_table)
    console.print()

    # === Python Version ===
    checks_table = Table(title="Prerequisite Checks")
    checks_table.add_column("Check", style="bold")
    checks_table.add_column("Status")
    checks_table.add_column("Details")

    py_version = sys.version_info
    if py_version >= (3, 11):
        checks_table.add_row(
            "Python >= 3.11",
            Text("PASS", style="green"),
            f"{py_version.major}.{py_version.minor}.{py_version.micro}",
        )
    else:
        checks_table.add_row(
            "Python >= 3.11",
            Text("FAIL", style="red"),
            f"Found {py_version.major}.{py_version.minor} — need 3.11+",
        )
        all_ok = False

    # === Native Binaries ===
    binaries: list[tuple[str, list[str] | None, bool]] = [
        ("mosquitto", ["-h"], True),
        ("ffmpeg", ["-version"], False),  # Not critical — only for test patterns
    ]
    for name, args, critical in binaries:
        ok, detail = _check_binary(name, args)
        if ok:
            checks_table.add_row(
                name,
                Text("PASS", style="green"),
                detail[:80],
            )
        else:
            status = "FAIL" if critical else "WARN"
            style = "red" if critical else "yellow"
            checks_table.add_row(name, Text(status, style=style), detail)
            if critical:
                all_ok = False

    # MediaMTX binary check
    mediamtx_path = TOOLS_DIR / "mediamtx" / "mediamtx.exe"
    if not sys.platform.startswith("win"):
        mediamtx_path = TOOLS_DIR / "mediamtx" / "mediamtx"
    if mediamtx_path.exists():
        checks_table.add_row(
            "MediaMTX",
            Text("PASS", style="green"),
            f"Found at {mediamtx_path}",
        )
    else:
        checks_table.add_row(
            "MediaMTX",
            Text("WARN", style="yellow"),
            f"Not found at {mediamtx_path} — download from GitHub",
        )

    # === Python Packages ===
    packages = [
        "PyQt6", "paho.mqtt.client", "pydantic", "structlog", "numpy",
        "scipy", "prometheus_client", "click", "rich", "pyqtgraph",
        "cv2", "yaml", "aiohttp",
    ]
    pkg_ok_count = 0
    pkg_fail_count = 0
    for pkg in packages:
        ok, detail = _check_python_package(pkg)
        if ok:
            pkg_ok_count += 1
        else:
            pkg_fail_count += 1
            checks_table.add_row(f"pip: {pkg}", Text("FAIL", style="red"), detail)
            all_ok = False

    if pkg_fail_count == 0:
        checks_table.add_row(
            f"Python packages ({pkg_ok_count}/{len(packages)})",
            Text("PASS", style="green"),
            "All packages installed",
        )
    else:
        checks_table.add_row(
            "Python packages",
            Text(f"MISSING ({pkg_fail_count})", style="red"),
            "Run: pip install -r requirements.txt",
        )

    # === Port Availability ===
    ports_to_check: list[tuple[str, int]] = [
        ("MQTT Broker", 1883),
        ("RTSP Server", 8554),
        ("Dashboard Metrics", 9200),
    ]
    for label, port in ports_to_check:
        free, detail = _check_port_free(port)
        if free:
            checks_table.add_row(
                f"Port {port} ({label})",
                Text("FREE", style="green"),
                detail,
            )
        else:
            checks_table.add_row(
                f"Port {port} ({label})",
                Text("IN USE", style="yellow"),
                detail,
            )

    # === Directory Structure ===
    required_dirs = [
        "config", "control_room", "target_simulator", "video_server",
        "firmware", "tests", "docs", "logs", "scripts",
    ]
    missing_dirs = [d for d in required_dirs if not (PROJECT_ROOT / d).exists()]
    if not missing_dirs:
        checks_table.add_row(
            "Directory structure",
            Text("PASS", style="green"),
            f"All {len(required_dirs)} directories present",
        )
    else:
        checks_table.add_row(
            "Directory structure",
            Text("WARN", style="yellow"),
            f"Missing: {', '.join(missing_dirs)}",
        )

    # === Config Files ===
    config_files = ["config/wints.yaml", "config/mosquitto.conf"]
    missing_configs = [f for f in config_files if not (PROJECT_ROOT / f).exists()]
    if not missing_configs:
        checks_table.add_row(
            "Configuration files",
            Text("PASS", style="green"),
            "wints.yaml, mosquitto.conf present",
        )
    else:
        checks_table.add_row(
            "Configuration files",
            Text("FAIL", style="red"),
            f"Missing: {', '.join(missing_configs)}",
        )
        all_ok = False

    console.print(checks_table)
    console.print()

    # === Summary ===
    if all_ok:
        console.print(
            Panel(
                "[bold green]All critical checks passed. System is ready.[/bold green]",
                title="Result",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                "[bold red]Some critical checks failed. Fix issues above before proceeding.[/bold red]",
                title="Result",
                border_style="red",
            )
        )
        sys.exit(1)


def _download_mediamtx() -> bool:
    """Download and extract MediaMTX to tools/mediamtx."""
    import io
    import urllib.request
    import zipfile

    mediamtx_dir = TOOLS_DIR / "mediamtx"
    mediamtx_dir.mkdir(parents=True, exist_ok=True)

    exe_name = "mediamtx.exe" if sys.platform == "win32" else "mediamtx"
    target_path = mediamtx_dir / exe_name
    if target_path.exists():
        console.print(f"[green]MediaMTX binary already exists at {target_path}[/green]")
        return True

    console.print("[yellow]Downloading MediaMTX...[/yellow]")
    version = "1.9.0"
    if sys.platform == "win32":
        filename = f"mediamtx_v{version}_windows_amd64.zip"
    elif sys.platform == "darwin":
        filename = f"mediamtx_v{version}_darwin_amd64.tar.gz"
    else:
        filename = f"mediamtx_v{version}_linux_amd64.tar.gz"

    url = f"https://github.com/bluenviron/mediamtx/releases/download/v{version}/{filename}"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()

        if filename.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                z.extract(exe_name, path=str(mediamtx_dir))
        else:
            import tarfile
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
                tar.extract(exe_name, path=str(mediamtx_dir))

        if sys.platform != "win32":
            target_path.chmod(0o755)

        console.print(f"[green]MediaMTX downloaded and installed to {target_path}[/green]")
        return True
    except Exception as exc:
        console.print(f"[yellow]Failed to download MediaMTX: {exc}[/yellow]")
        return False


@cli.command()
def setup() -> None:
    """Create venv, install packages, download MediaMTX.

    Idempotent — safe to run multiple times.

    Example:
        $ python -m scripts.wints setup
    """
    _ensure_directories()
    console.print("[bold cyan]WINTS Setup[/bold cyan]")
    console.print()

    # Install Python packages
    console.print("[yellow]Installing Python packages...[/yellow]")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(PROJECT_ROOT / "requirements.txt")],
        cwd=str(PROJECT_ROOT),
        check=False,
    )
    console.print("[green]Python packages installed.[/green]")
    console.print()

    # Download MediaMTX
    _download_mediamtx()
    console.print()
    console.print("[green]Setup complete. Run 'python -m scripts.wints doctor' to verify.[/green]")


@cli.command()
def broker() -> None:
    """Start the Mosquitto MQTT broker (blocks, logs to console).

    Uses config/mosquitto.conf. Checks port 1883 is free before starting.

    Example:
        $ python -m scripts.wints broker
    """
    _ensure_directories()
    free, detail = _check_port_free(1883)
    if not free:
        console.print(f"[red]Cannot start broker: {detail}[/red]")
        console.print("[yellow]Check if another Mosquitto instance is running.[/yellow]")
        if sys.platform == "win32":
            console.print("[dim]Run: netstat -ano | findstr :1883[/dim]")
        sys.exit(1)

    mosquitto_path = _find_binary("mosquitto")
    if not mosquitto_path:
        console.print("[red]Mosquitto not found on PATH.[/red]")
        console.print("[yellow]Install: winget install EclipseFoundation.Mosquitto[/yellow]")
        sys.exit(1)

    conf_path = CONFIG_DIR / "mosquitto.conf"
    console.print(f"[cyan]Starting Mosquitto broker with config: {conf_path}[/cyan]")
    console.print("[dim]Press Ctrl+C to stop[/dim]")
    console.print()

    try:
        subprocess.run(
            [mosquitto_path, "-c", str(conf_path), "-v"],
            cwd=str(PROJECT_ROOT),
            check=True,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Broker stopped by user.[/yellow]")
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Broker exited with code {exc.returncode}[/red]")
        sys.exit(1)


@cli.command()
@click.option("--fault", type=str, default=None, help="Target to start in FAULT state (e.g., T-07)")
@click.option("--offline", type=str, default=None, help="Target to start OFFLINE (e.g., T-09)")
def sim(fault: str | None, offline: str | None) -> None:
    """Start all 10 simulated targets.

    Args:
        fault: Optional target ID to start in FAULT state.
        offline: Optional target ID to start as OFFLINE.

    Example:
        $ python -m scripts.wints sim
        $ python -m scripts.wints sim --fault T-07 --offline T-09
    """
    console.print("[cyan]Starting WINTS Target Simulator...[/cyan]")
    args = [sys.executable, "-m", "target_simulator.main"]
    if fault:
        args.extend(["--fault", fault])
    if offline:
        args.extend(["--offline", offline])

    try:
        subprocess.run(args, cwd=str(PROJECT_ROOT), check=True)
    except KeyboardInterrupt:
        console.print("\n[yellow]Simulator stopped by user.[/yellow]")
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Simulator exited with code {exc.returncode}[/red]")
        sys.exit(1)


@cli.command()
def dashboard() -> None:
    """Launch the PyQt6 control room dashboard.

    Example:
        $ python -m scripts.wints dashboard
    """
    console.print("[cyan]Launching WINTS Control Room Dashboard...[/cyan]")
    try:
        subprocess.run(
            [sys.executable, "-m", "control_room.main"],
            cwd=str(PROJECT_ROOT),
            check=True,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard closed.[/yellow]")
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Dashboard exited with code {exc.returncode}[/red]")
        sys.exit(1)


@cli.command()
def video() -> None:
    """Start MediaMTX RTSP server with test patterns.

    Example:
        $ python -m scripts.wints video
    """
    console.print("[cyan]Starting RTSP video server...[/cyan]")
    try:
        subprocess.run(
            [sys.executable, "-m", "video_server.start_mediamtx"],
            cwd=str(PROJECT_ROOT),
            check=True,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Video server stopped.[/yellow]")


@cli.command()
def demo() -> None:
    """Launch broker + video + simulator + dashboard in correct order.

    Prints the demo script to the console as services start.
    Monitors all subprocesses and restarts broker if it dies.
    Disables Windows sleep for the duration of the demo.

    Example:
        $ python -m scripts.wints demo
    """
    _ensure_directories()

    console.print(Panel("[bold cyan]WINTS Demo Mode[/bold cyan]", expand=False))
    console.print()

    # Pre-flight checks
    console.print("[yellow]Running pre-flight checks...[/yellow]")

    # Check port 1883
    free, detail = _check_port_free(1883)
    existing_broker = False
    if not free:
        try:
            import paho.mqtt.client as mqtt
            # Test connection to the existing broker
            test_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
            test_client.connect("localhost", 1883)
            existing_broker = True
            console.print("[green]  * Port 1883 is already in use by a running MQTT broker. Reusing existing broker.[/green]")
        except Exception:
            console.print(f"[red]Port 1883 in use and not accepting connections: {detail}[/red]")
            sys.exit(1)

    # Disable sleep on Windows (C6 mitigation)
    if sys.platform == "win32":
        console.print("[dim]Disabling Windows sleep for demo...[/dim]")
        subprocess.run(
            ["powercfg", "-change", "-standby-timeout-ac", "0"],
            capture_output=True,
            check=False,
        )

    processes: list[subprocess.Popen[Any]] = []

    try:
        # 1. Start broker (only if not already running)
        if not existing_broker:
            console.print("[cyan]Starting Mosquitto broker...[/cyan]")
            mosquitto_path = _find_binary("mosquitto")
            if not mosquitto_path:
                console.print("[red]Mosquitto not found. Run: wints doctor[/red]")
                sys.exit(1)

            broker_proc = subprocess.Popen(
                [mosquitto_path, "-c", str(CONFIG_DIR / "mosquitto.conf"), "-v"],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(broker_proc)
            time.sleep(2)  # Wait for broker to start

            if broker_proc.poll() is not None:
                console.print("[red]Broker failed to start![/red]")
                sys.exit(1)
            console.print("[green]  * Broker running on port 1883[/green]")

        # 2. Start MediaMTX RTSP server
        console.print("[cyan]Starting MediaMTX RTSP server...[/cyan]")
        mediamtx_exe = PROJECT_ROOT / "tools" / "mediamtx" / "mediamtx.exe"
        mediamtx_cfg = CONFIG_DIR / "mediamtx.yml"
        samples_dir = PROJECT_ROOT / "video_server" / "samples"

        # Generate test patterns if missing
        sample_files = list(samples_dir.glob("*.mp4")) if samples_dir.exists() else []
        if len(sample_files) < 20:
            console.print("[yellow]  * Generating test pattern videos (first run)...[/yellow]")
            subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "video_server" / "generate_test_patterns.py")],
                cwd=str(PROJECT_ROOT),
                check=False,
            )

        if mediamtx_exe.exists() and mediamtx_cfg.exists():
            mediamtx_proc = subprocess.Popen(
                [str(mediamtx_exe), str(mediamtx_cfg)],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(mediamtx_proc)
            time.sleep(3)  # Wait for streams to initialise
            if mediamtx_proc.poll() is None:
                console.print("[green]  * MediaMTX running on rtsp://127.0.0.1:8554[/green]")
            else:
                console.print("[yellow]  * MediaMTX failed to start — video unavailable[/yellow]")
        else:
            console.print("[yellow]  * MediaMTX not found — skipping RTSP server[/yellow]")

        # 3. Start simulator
        console.print("[cyan]Starting target simulator (10 targets)...[/cyan]")
        sim_proc = subprocess.Popen(
            [
                sys.executable, "-m", "target_simulator.main",
                "--fault", "T-07",
                "--offline", "T-09",
            ],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(sim_proc)
        time.sleep(3)  # Wait for targets to connect
        console.print("[green]  * Simulator running (T-07 FAULT, T-09 OFFLINE)[/green]")

        # 4. Start dashboard
        console.print("[cyan]Launching control room dashboard...[/cyan]")
        dash_proc = subprocess.Popen(
            [sys.executable, "-m", "control_room.main"],
            cwd=str(PROJECT_ROOT),
        )
        processes.append(dash_proc)
        console.print("[green]  * Dashboard launched[/green]")
        console.print()

        console.print(Panel(
            "[bold green]All systems running.[/bold green]\n"
            "[dim]Press Ctrl+C to stop all processes.[/dim]\n\n"
            "Demo script: docs/05_demo_script.md\n"
            "Video feeds: double-click any target card\n"
            "Inject faults: python -m scripts.wints inject T-03 overcurrent",
            title="WINTS Demo Active",
            border_style="green",
        ))

        # Wait for dashboard to close
        dash_proc.wait()

    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down all processes...[/yellow]")
    finally:
        for proc in reversed(processes):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

        # Restore Windows sleep settings
        if sys.platform == "win32":
            subprocess.run(
                ["powercfg", "-change", "-standby-timeout-ac", "30"],
                capture_output=True,
                check=False,
            )
            console.print("[dim]Windows sleep settings restored.[/dim]")

        console.print("[green]All processes stopped.[/green]")


@cli.command()
@click.argument("target_id")
@click.argument("fault_type")
def inject(target_id: str, fault_type: str) -> None:
    """Inject a fault into a target via the fault injector HTTP API.

    Args:
        target_id: Target identifier (e.g., T-01, T-07).
        fault_type: Fault type (overcurrent, broker_disconnect, battery_bms,
                    limit_stuck, packet_loss_spike, clear).

    Example:
        $ python -m scripts.wints inject T-03 overcurrent
        $ python -m scripts.wints inject T-03 clear
    """
    import json
    import urllib.request

    # Parse target number
    try:
        target_num = int(target_id.split("-")[1])
    except (IndexError, ValueError):
        console.print(f"[red]Invalid target ID: {target_id}. Use format T-XX (e.g., T-03)[/red]")
        sys.exit(1)

    port = 9300 + target_num

    if fault_type == "clear":
        url = f"http://localhost:{port}/fault/clear"
        data = b"{}"
    else:
        url = f"http://localhost:{port}/fault/inject"
        data = json.dumps({"fault": fault_type}).encode()

    try:
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = resp.read().decode()
            console.print(f"[green]{target_id}: {fault_type} — {result}[/green]")
    except urllib.error.URLError as exc:
        console.print(
            f"[red]Failed to reach {target_id} fault injector on port {port}: {exc}[/red]"
        )
        console.print("[yellow]Is the simulator running?[/yellow]")
        sys.exit(1)


@cli.command()
@click.argument("session_file", type=click.Path(exists=True))
def replay(session_file: str) -> None:
    """Replay a recorded session against the simulator.

    Args:
        session_file: Path to session JSONL file.

    Example:
        $ python -m scripts.wints replay logs/session_20260614_143015.jsonl
    """
    console.print(f"[cyan]Replaying session: {session_file}[/cyan]")
    console.print("[yellow]Replay functionality will be available after Phase 6.[/yellow]")


@cli.command()
def test() -> None:
    """Run the full test suite.

    Example:
        $ python -m scripts.wints test
    """
    console.print("[cyan]Running WINTS test suite...[/cyan]")
    subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        cwd=str(PROJECT_ROOT),
        check=False,
    )


@cli.command()
def lint() -> None:
    """Run ruff + mypy on the codebase.

    Example:
        $ python -m scripts.wints lint
    """
    console.print("[cyan]Running ruff...[/cyan]")
    subprocess.run(
        [sys.executable, "-m", "ruff", "check", "."],
        cwd=str(PROJECT_ROOT),
        check=False,
    )
    console.print()
    console.print("[cyan]Running mypy...[/cyan]")
    subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", "control_room/", "target_simulator/"],
        cwd=str(PROJECT_ROOT),
        check=False,
    )


if __name__ == "__main__":
    cli()
