"""Start the FastAPI backend and Next.js frontend for local development."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List


ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
PLACEHOLDER_MARKERS = ("your_", "your-", "placeholder", "replace_me", "changeme")


def configured_deepseek_key() -> bool:
    value = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    env_file = BACKEND_DIR / ".env"
    if not value and env_file.is_file():
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, candidate = line.split("=", 1)
            if name.strip() == "DEEPSEEK_API_KEY":
                value = candidate.strip().strip("\"'")
                break
    lowered = value.casefold()
    return bool(value) and not any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def backend_python() -> Path:
    candidates = (
        BACKEND_DIR / ".venv" / "Scripts" / "python.exe",
        BACKEND_DIR / ".venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "Backend virtual environment not found. Follow the first-time setup in README.md "
        "and create backend/.venv before running this command."
    )


def frontend_command() -> List[str]:
    node = shutil.which("node.exe" if os.name == "nt" else "node")
    if not node:
        raise SystemExit("Node.js was not found. Install Node.js and run npm install in frontend/.")
    if not (FRONTEND_DIR / "node_modules").is_dir():
        raise SystemExit("Frontend dependencies not found. Run npm install in frontend/ first.")
    next_cli = FRONTEND_DIR / "node_modules" / "next" / "dist" / "bin" / "next"
    if not next_cli.is_file():
        raise SystemExit("Next.js was not found. Run npm install in frontend/ first.")
    return [node, str(next_cli), "dev", "--hostname", "localhost", "--port", "3000"]


def start_process(command: List[str], cwd: Path) -> subprocess.Popen:
    options = {"cwd": str(cwd)}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    return subprocess.Popen(command, **options)


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> int:
    if not configured_deepseek_key():
        raise SystemExit(
            "DEEPSEEK_API_KEY is not configured. Copy backend/.env.example to "
            "backend/.env and replace the placeholder with your own DeepSeek API key."
        )

    python = backend_python()
    frontend = frontend_command()
    commands = (
        (
            "backend",
            [
                str(python),
                "-m",
                "uvicorn",
                "app.main:app",
                "--reload",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            BACKEND_DIR,
        ),
        (
            "frontend",
            frontend,
            FRONTEND_DIR,
        ),
    )
    processes = []
    try:
        for name, command, cwd in commands:
            processes.append((name, start_process(command, cwd)))
        print("Backend:  http://127.0.0.1:8000")
        print("Frontend: http://localhost:3000")
        print("Press Ctrl+C to stop both services.")
        while True:
            for name, process in processes:
                code = process.poll()
                if code is not None:
                    print("{} exited with code {}.".format(name.capitalize(), code))
                    return code or 1
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nStopping backend and frontend...")
        return 0
    finally:
        for _, process in reversed(processes):
            stop_process(process)


if __name__ == "__main__":
    sys.exit(main())
