"""Start the VeriPantry demo with one command (Windows, macOS, Linux).

    python run_demo.py            # first run installs everything, then starts the demo
    python run_demo.py --reset    # same, but clears earlier demo orders and the audit log first

Needs Python 3.11+ and Node.js 20.19+ (or 22.12+). No API key: the demo runs on
recorded Valio Aimo stock and price data, so every run behaves the same.
Starts three local services and opens http://localhost:5173/stage.
Press Ctrl+C to stop them all.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND, AGENT, FRONTEND = ROOT / "backend", ROOT / "agent", ROOT / "frontend"
VENV = BACKEND / ".venv"
LOGS = BACKEND / "var" / "logs"
WINDOWS = os.name == "nt"
VENV_PY = VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")
START_URL = "http://localhost:5173/stage"

SERVICES = [  # name, port, health URL
    ("gateway", 8000, "http://127.0.0.1:8000/health"),
    ("agent", 8100, "http://127.0.0.1:8100/agent/scenarios"),
    ("web app", 5173, "http://localhost:5173"),
]


def step(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"\nERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], cwd: Path) -> None:
    if subprocess.run(cmd, cwd=cwd).returncode != 0:
        fail(f"command failed: {' '.join(cmd)}")


def check_tools() -> str:
    if sys.version_info < (3, 11):
        fail(f"Python 3.11 or newer is needed (this is {sys.version.split()[0]}).")
    npm = shutil.which("npm")
    node = shutil.which("node")
    if not npm or not node:
        fail("Node.js is needed: https://nodejs.org (version 20.19+ or 22.12+).")
    version = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
    major, minor = (int(x) for x in version.split(".")[:2])
    if (major, minor) < (20, 19) or (major == 21) or (major == 22 and minor < 12):
        fail(f"Node.js 20.19+ or 22.12+ is needed (this is {version}).")
    return npm


def fingerprint(*files: Path) -> str:
    return hashlib.sha256(b"".join(f.read_bytes() for f in files)).hexdigest()


def install_python() -> None:
    reqs = [BACKEND / "requirements.txt", AGENT / "requirements.txt"]
    stamp = VENV / ".veripantry-installed"
    if stamp.exists() and stamp.read_text() == fingerprint(*reqs):
        return
    step("Installing Python packages (first run only, about a minute)")
    if not VENV_PY.exists():
        venv.EnvBuilder(with_pip=True).create(VENV)
    run([str(VENV_PY), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", str(reqs[0]), "-r", str(reqs[1])], ROOT)
    stamp.write_text(fingerprint(*reqs))


def install_node(npm: str) -> None:
    lock = FRONTEND / "package-lock.json"
    stamp = FRONTEND / "node_modules" / ".veripantry-installed"
    if stamp.exists() and stamp.read_text() == fingerprint(lock):
        return
    step("Installing web app packages (first run only, about a minute)")
    run([npm, "ci", "--no-audit", "--no-fund", "--loglevel=error"], FRONTEND)
    stamp.write_text(fingerprint(lock))


def prepare_demo_data(reset: bool) -> None:
    if not (BACKEND / "var" / "registry.json").exists() or not (BACKEND / "var" / "dev" / "mandate.jwt").exists():
        step("Creating demo identities, keys and the agent's mandate")
        run([str(VENV_PY), "-m", "scripts.dev_setup"], BACKEND)
    if reset:
        step("Clearing earlier demo orders and the audit log")
        run([str(VENV_PY), "-m", "scripts.dev_setup", "--reset-demo"], BACKEND)


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_until_up(url: str, proc: subprocess.Popen, name: str, timeout: float = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            fail(f"the {name} stopped while starting. See {LOGS / (name.replace(' ', '-') + '.log')}")
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except Exception:
            time.sleep(0.5)
    fail(f"the {name} did not start within {int(timeout)} s. See {LOGS / (name.replace(' ', '-') + '.log')}")


def start_services() -> list[subprocess.Popen]:
    busy = [f"{name} port {port}" for name, port, _ in SERVICES if port_in_use(port)]
    if busy:
        fail("these ports are already in use: " + ", ".join(busy) + ". Is the demo already running? Stop it first.")
    LOGS.mkdir(parents=True, exist_ok=True)
    py = str(VENV_PY)
    commands = {
        "gateway": ([py, "-m", "uvicorn", "app.demo:app", "--port", "8000"], BACKEND),
        "agent": ([py, "-m", "uvicorn", "stub_agent.app:app", "--port", "8100"], AGENT),
        "web app": (["node", str(FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"), "--port", "5173", "--strictPort"], FRONTEND),
    }
    procs: list[subprocess.Popen] = []
    for name, _, url in SERVICES:
        step(f"Starting the {name}")
        cmd, cwd = commands[name]
        log = open(LOGS / f"{name.replace(' ', '-')}.log", "w", encoding="utf-8")
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
        procs.append(proc)
        try:
            wait_until_up(url, proc, name)
        except SystemExit:
            stop(procs)
            raise
    return procs


def stop(procs: list[subprocess.Popen]) -> None:
    for p in procs:
        if p.poll() is None:
            p.terminate()
    for p in procs:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the VeriPantry demo.")
    parser.add_argument("--reset", action="store_true", help="clear earlier demo orders and the audit log first")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args()

    npm = check_tools()
    install_python()
    install_node(npm)
    prepare_demo_data(args.reset)
    procs = start_services()

    print(f"""
------------------------------------------------------------
 VeriPantry demo is running.

   Demo (buyer + Head Chef's phone):  {START_URL}
   Sign in as another person:         http://localhost:5173/sign-in
   Audit (as Valio Auditor):          http://localhost:5173/audit

 Guide: JUDGES.md    Logs: {LOGS}
 Press Ctrl+C to stop.
------------------------------------------------------------""", flush=True)
    if not args.no_browser:
        webbrowser.open(START_URL)
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        print("\nA service stopped unexpectedly; see the logs above. Shutting down.", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        stop(procs)


if __name__ == "__main__":
    main()
