"""Open a file or directory with the platform's default file manager."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def open_path(path: Path | str) -> None:
    """Open an existing path using Explorer, Finder, or the Linux default opener.

    Raises FileNotFoundError when the target does not exist and propagates
    launcher errors so the GUI can present a useful message to the user.
    """
    target = Path(path).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"Path does not exist: {target}")

    if sys.platform == "win32":
        os.startfile(str(target))  # type: ignore[attr-defined]
        return

    if sys.platform == "darwin":
        command = ["open", str(target)]
    else:
        opener = shutil.which("xdg-open")
        if not opener:
            raise FileNotFoundError("xdg-open was not found on PATH")
        command = [opener, str(target)]

    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
