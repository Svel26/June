from pathlib import Path
import subprocess
from typing import Optional

PROJECT_ROOT = Path("c:/projects/June-Extension")


def run_command(command: str, background: bool = False) -> str:
    """
    Run a shell command in the project root directory.

    - If background is False, runs subprocess.run with a 60s timeout and returns combined stdout+stderr.
    - If background is True, starts subprocess.Popen and returns an immediate confirmation with the PID.
    """
    if not command:
        return ""

    if background:
        try:
            p = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(PROJECT_ROOT),
            )
            return f"Started background process, pid={p.pid}"
        except Exception as e:
            return f"Failed to start background process: {e}"
    else:
        try:
            completed = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
                timeout=60,
            )
            out = completed.stdout or ""
            err = completed.stderr or ""
            return out + err
        except subprocess.TimeoutExpired as e:
            partial = e.stdout or ""
            partial_err = e.stderr or ""
            return f"Command timed out after 60 seconds.\n{partial}{partial_err}"
        except Exception as e:
            return f"Command failed: {e}"