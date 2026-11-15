"""Locate a usable FFmpeg executable for Red Spindle.

The preferred order is an explicit Red Spindle override, a complete system
FFmpeg installation, then the FFmpeg binary shipped by imageio-ffmpeg. The
system installation is preferred because it normally includes ffprobe too.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _is_usable_ffmpeg(executable: str) -> bool:
    """Return True only when the candidate file can actually execute FFmpeg."""
    if not executable or not Path(executable).is_file():
        return False

    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "timeout": 10,
        "check": False,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    try:
        result = subprocess.run([executable, "-version"], **kwargs)
    except (OSError, subprocess.SubprocessError):
        return False

    output = result.stdout or ""
    return result.returncode == 0 and "ffmpeg version" in output.lower()


def _windows_candidates() -> list[str]:
    """Return common Windows install paths used by WinGet and manual installs."""
    if sys.platform != "win32":
        return []

    candidates: list[str] = []
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        roots = [
            Path(local_app) / "Microsoft" / "WinGet" / "Packages",
            Path(local_app) / "Programs",
        ]
        for root in roots:
            if root.exists():
                try:
                    candidates.extend(str(path) for path in root.glob("**/ffmpeg.exe"))
                except OSError:
                    pass

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    if program_files.exists():
        try:
            candidates.extend(str(path) for path in program_files.glob("**/ffmpeg.exe"))
        except OSError:
            pass
    return candidates


def get_ffmpeg_executable(required_encoder: Optional[str] = None) -> Optional[str]:
    """Find and validate FFmpeg, including the bundled imageio-ffmpeg fallback.

    Set ``REDSPINDLE_FFMPEG`` to an explicit executable path to override normal
    discovery. A system FFmpeg on PATH is preferred over the packaged fallback.
    """
    candidates: list[str] = []

    override = os.environ.get("REDSPINDLE_FFMPEG")
    if override:
        candidates.append(override.strip().strip('"'))

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        candidates.append(system_ffmpeg)

    # imageio-ffmpeg wheels contain a platform-specific FFmpeg executable.
    # Import lazily so development environments can still import Red Spindle
    # and show a useful error if the optional wheel was not installed.
    try:
        import imageio_ffmpeg  # type: ignore

        bundled_ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled_ffmpeg:
            candidates.append(str(bundled_ffmpeg))
    except (ImportError, RuntimeError, OSError):
        pass

    candidates.extend(_windows_candidates())

    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(os.path.expanduser(candidate)))
        if normalized in seen:
            continue
        seen.add(normalized)
        if not _is_usable_ffmpeg(normalized):
            continue
        if required_encoder and not ffmpeg_has_encoder(normalized, required_encoder):
            continue
        return normalized

    return None


def ffmpeg_has_encoder(executable: str, encoder_name: str) -> bool:
    """Check whether the selected FFmpeg build exposes a named encoder."""
    if not executable or not encoder_name:
        return False
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "timeout": 15,
        "check": False,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        result = subprocess.run([executable, "-hide_banner", "-encoders"], **kwargs)
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    return re.search(
        rf"(?m)^\s*[A-Z.]{{6}}\s+{re.escape(encoder_name)}\s",
        result.stdout or "",
    ) is not None
