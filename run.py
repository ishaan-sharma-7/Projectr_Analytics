import subprocess
import sys
import os
import signal
import time
import platform


BACKEND_PORT = 8000
FRONTEND_PORT = 5173
PORT_FREE_TIMEOUT = 5


def find_pids_on_port(port):
    """Return list of PIDs using the given port, or None."""
    try:
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}"],
                capture_output=True, text=True,
            )
        else:
            result = subprocess.run(
                ["fuser", f"{port}/tcp"],
                capture_output=True, text=True,
            )
        pids = result.stdout.strip().split()
        return [int(p) for p in pids if p.isdigit()] or None
    except Exception:
        return None


def wait_for_port_free(port, timeout=PORT_FREE_TIMEOUT):
    """Block until the port is free or timeout is reached."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not find_pids_on_port(port):
            return True
        time.sleep(0.3)
    return False


def free_port(port, name):
    """If port is occupied, prompt the user to kill the process."""
    pids = find_pids_on_port(port)
    if not pids:
        return
    pid_list = ", ".join(str(p) for p in pids)
    answer = input(f"Port {port} ({name}) is in use by PID {pid_list}. Kill it? [y/N] ")
    if answer.strip().lower() != "y":
        print(f"Skipping {name} — port {port} still occupied.")
        sys.exit(1)

    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
            print(f"  Killed PID {pid}")
        except ProcessLookupError:
            pass

    print(f"  Waiting for port {port} to be released…")
    if not wait_for_port_free(port):
        print(f"  ERROR: port {port} is still in use after {PORT_FREE_TIMEOUT}s. Exiting.")
        sys.exit(1)
    print(f"  Port {port} is free.")


free_port(BACKEND_PORT, "backend")
free_port(FRONTEND_PORT, "frontend")

backend = subprocess.Popen(["uvicorn", "backend.main:app", "--reload"])
frontend = subprocess.Popen(["npm", "run", "dev"], cwd="frontend")

try:
    backend.wait()
    frontend.wait()
except KeyboardInterrupt:
    backend.terminate()
    frontend.terminate()
    sys.exit(0)
