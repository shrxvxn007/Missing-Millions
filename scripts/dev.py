#!/usr/bin/env python3
"""Start both local servers and stop their process groups on exit."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def environment() -> dict[str, str]:
    values = dict(os.environ)
    config = ROOT / ".env"
    if config.is_file():
        for line in config.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key in {"DATA_PACKAGE_PATH", "TASKS_DB_PATH"}:
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                    value = value[1:-1]
                if value:
                    values.setdefault(key, value)
    return values


def verify_setup(values: dict[str, str]):
    if not (ROOT / ".venv/bin/python").is_file() or not (ROOT / "apps/web/node_modules").is_dir():
        raise RuntimeError("Dependencies are missing. Run make setup first.")
    selected = values.get("DATA_PACKAGE_PATH")
    paths = [ROOT / selected] if selected else [ROOT / "data/processed/demo.json", ROOT / "data/processed/real.json"]
    if not any(path.is_file() for path in paths):
        raise RuntimeError("No selected data package exists. Run make prepare-demo explicitly for a synthetic fixture, or prepare real sources.")
    for port in (8000, 5173):
        with socket.socket() as listener:
            try:
                listener.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"Port {port} is already occupied. Stop the previous local server before make dev.") from exc


def stop(processes: list[subprocess.Popen]):
    for process in processes:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 5
    for process in processes:
        try:
            process.wait(timeout=max(.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check dependencies, selected data files and free ports without starting servers")
    args = parser.parse_args()
    values = environment()
    try:
        verify_setup(values)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.check:
        print("Local dependencies, data selection and server ports are ready.")
        return 0
    processes = []
    signal.signal(signal.SIGTERM, lambda _signum, _frame: sys.exit(143))
    try:
        commands = [
            [str(ROOT / ".venv/bin/python"), "-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"],
            ["npm", "--prefix", "apps/web", "run", "dev", "--", "--port", "5173", "--strictPort"],
        ]
        for command in commands:
            processes.append(subprocess.Popen(command, cwd=ROOT, env=values, start_new_session=True))
        print("\nThe Missing Millions: http://127.0.0.1:5173\nAPI reference: http://127.0.0.1:8000/docs\nPress Ctrl+C to stop both servers.\n", flush=True)
        while True:
            for process in processes:
                code = process.poll()
                if code is not None:
                    print(f"A development server exited ({code}); stopping its companion.", file=sys.stderr)
                    return code or 1
            time.sleep(.25)
    except KeyboardInterrupt:
        return 0
    finally:
        stop(processes)


if __name__ == "__main__":
    raise SystemExit(main())
