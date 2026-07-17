"""EVB communication quality monitor — entry point."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _relaunch_in_project_venv_if_needed() -> None:
    root = Path(__file__).resolve().parent
    venv_python = root / ".venv" / "Scripts" / "python.exe"
    main_script = root / "main.py"
    if not venv_python.is_file():
        return
    try:
        venv_python.resolve().stat()
    except OSError:
        return
    try:
        if Path(sys.executable).resolve() == venv_python.resolve():
            return
    except OSError:
        return
    raise SystemExit(
        subprocess.call(
            [str(venv_python), str(main_script), *sys.argv[1:]],
            cwd=str(root),
        )
    )


_relaunch_in_project_venv_if_needed()

from ui.main_window import run_app

if __name__ == "__main__":
    run_app()
