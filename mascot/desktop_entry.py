"""Freedesktop ``.desktop`` entry writer (Linux).

Shared by the app-launcher shortcuts (:mod:`mascot.shortcuts`) and run-at-login
(:mod:`mascot.autostart`). A ``.desktop`` file is the Linux equivalent of a
Windows ``.lnk`` — it makes the app show up in the application menu / on the
desktop and launches it with the right interpreter and working directory.
"""
from __future__ import annotations

from pathlib import Path


def build(name: str, exec_cmd: str, *, comment: str = "", icon: str = "",
          path: str = "", categories: str = "Utility;") -> str:
    """Render a minimal, spec-compliant Desktop Entry."""
    lines = ["[Desktop Entry]", "Version=1.0", "Type=Application", f"Name={name}"]
    if comment:
        lines.append(f"Comment={comment}")
    lines.append(f"Exec={exec_cmd}")
    if path:
        lines.append(f"Path={path}")
    if icon:
        lines.append(f"Icon={icon}")
    lines += ["Terminal=false", f"Categories={categories}", ""]
    return "\n".join(lines)


def write(path: Path, **kwargs) -> bool:
    """Write a ``.desktop`` file (marked executable) and report success."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(**kwargs), encoding="utf-8")
    try:
        path.chmod(0o755)  # GNOME/KDE expect launchers to be executable
    except OSError:
        pass
    return path.exists()
