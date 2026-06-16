"""Settings / control panel for Claude Familiar.

A small normal (titled) window to configure the mascot: pick the art style with
a live preview, toggle the transparent floating card, enable run-at-login, and
install/update the Claude Code hooks. Run with:

    python -m mascot.control_panel
"""
from __future__ import annotations

import json
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import autostart, icon, settings as settings_mod, sprite_pixel, sprite_smooth
from .tkinter_app import _accent, round_rect

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EMIT_PY = PROJECT_ROOT / "hooks" / "emit.py"
INSTALL_HOOKS = PROJECT_ROOT / "scripts" / "install_hooks.py"
RUN_SCRIPT = PROJECT_ROOT / "run_mascot.py"

PREVIEW_W, PREVIEW_H = 124, 140
BG = "#15161d"
FG = "#e8e8ef"
MUTED = "#9095a8"


def _hooks_installed() -> bool:
    """True if our emit.py is referenced by a hook command in settings.json."""
    path = Path.home() / ".claude" / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    needle = str(EMIT_PY)
    for entries in (data.get("hooks") or {}).values():
        for entry in entries if isinstance(entries, list) else []:
            for hook in entry.get("hooks", []):
                if needle in hook.get("command", ""):
                    return True
    return False


def _pythonw() -> Path:
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


class ControlPanel:
    def __init__(self) -> None:
        s = settings_mod.load_settings()
        self.root = tk.Tk()
        self.root.title("Claude Familiar — Settings")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        icon.apply(self.root)

        self.style_var = tk.StringVar(value=s["art_style"])
        self.size_var = tk.StringVar(value=s["widget_size"])
        self.transp_var = tk.BooleanVar(value=s["transparent_bg"])
        self.startup_var = tk.BooleanVar(value=autostart.is_enabled())
        self.status = tk.StringVar(value="")

        self._build()
        self._draw_preview()
        self._refresh_hooks()

    # --- layout -----------------------------------------------------------
    def _build(self) -> None:
        pad = {"padx": 12, "pady": 6}
        tk.Label(self.root, text="🐾  Claude Familiar", bg=BG, fg=FG,
                 font=("Segoe UI", 14, "bold")).pack(anchor="w", **pad)

        # Mascot style + live preview
        style_box = tk.LabelFrame(self.root, text="Mascot", bg=BG, fg=MUTED,
                                  font=("Segoe UI", 9))
        style_box.pack(fill="x", **pad)
        left = tk.Frame(style_box, bg=BG)
        left.pack(side="left", fill="y", padx=8, pady=8)
        for label, val in (("Pixel (Claude-style)", "pixel"), ("Smooth (blob)", "smooth")):
            tk.Radiobutton(left, text=label, value=val, variable=self.style_var,
                           bg=BG, fg=FG, selectcolor=BG, activebackground=BG,
                           activeforeground=FG, font=("Segoe UI", 9),
                           command=self._draw_preview).pack(anchor="w")
        self.preview = tk.Canvas(style_box, width=PREVIEW_W, height=PREVIEW_H,
                                 bg=BG, highlightthickness=0)
        self.preview.pack(side="right", padx=8, pady=8)

        # Size
        size_box = tk.LabelFrame(self.root, text="Widget size", bg=BG, fg=MUTED,
                                 font=("Segoe UI", 9))
        size_box.pack(fill="x", **pad)
        size_row = tk.Frame(size_box, bg=BG)
        size_row.pack(anchor="w", padx=8, pady=4)
        for label, val in (("Small", "small"), ("Medium", "medium"), ("Large", "large")):
            tk.Radiobutton(size_row, text=label, value=val, variable=self.size_var,
                           bg=BG, fg=FG, selectcolor=BG, activebackground=BG,
                           activeforeground=FG, font=("Segoe UI", 9)).pack(side="left", padx=(0, 12))

        # Appearance
        appearance = tk.LabelFrame(self.root, text="Appearance", bg=BG, fg=MUTED,
                                   font=("Segoe UI", 9))
        appearance.pack(fill="x", **pad)
        tk.Checkbutton(appearance, text="Transparent background (floating card)",
                       variable=self.transp_var, bg=BG, fg=FG, selectcolor=BG,
                       activebackground=BG, activeforeground=FG,
                       font=("Segoe UI", 9)).pack(anchor="w", padx=8, pady=4)

        # Startup
        startup = tk.LabelFrame(self.root, text="Startup", bg=BG, fg=MUTED,
                                font=("Segoe UI", 9))
        startup.pack(fill="x", **pad)
        tk.Checkbutton(startup, text="Run automatically when Windows starts",
                       variable=self.startup_var, bg=BG, fg=FG, selectcolor=BG,
                       activebackground=BG, activeforeground=FG,
                       font=("Segoe UI", 9)).pack(anchor="w", padx=8, pady=4)

        # Hooks
        hooks = tk.LabelFrame(self.root, text="Claude Code hooks", bg=BG, fg=MUTED,
                              font=("Segoe UI", 9))
        hooks.pack(fill="x", **pad)
        self.hooks_label = tk.Label(hooks, text="", bg=BG, fg=FG, font=("Segoe UI", 9))
        self.hooks_label.pack(side="left", padx=8, pady=6)
        ttk.Button(hooks, text="Install / update", command=self._install_hooks).pack(
            side="right", padx=8, pady=6)

        # Actions
        actions = tk.Frame(self.root, bg=BG)
        actions.pack(fill="x", **pad)
        ttk.Button(actions, text="Save & Apply", command=self._save).pack(side="left")
        ttk.Button(actions, text="Launch widget", command=self._launch).pack(side="left", padx=6)
        ttk.Button(actions, text="Close", command=self.root.destroy).pack(side="right")

        tk.Label(self.root, textvariable=self.status, bg=BG, fg=MUTED,
                 font=("Segoe UI", 8), wraplength=340, justify="left").pack(
            anchor="w", padx=12, pady=(0, 10))

    # --- preview ----------------------------------------------------------
    def _draw_preview(self) -> None:
        c = self.preview
        c.delete("all")
        accent = _accent("idle")
        m = 6
        round_rect(c, m, m, PREVIEW_W - m, PREVIEW_H - m, 16, fill="#1d1f29", outline="")
        round_rect(c, m, m, PREVIEW_W - m, PREVIEW_H - m, 16, fill="", outline=accent, width=2)
        module = sprite_pixel if self.style_var.get() == "pixel" else sprite_smooth
        module.draw_creature(c, PREVIEW_W // 2, PREVIEW_H // 2 - 8, "idle", accent)
        c.create_text(PREVIEW_W // 2, PREVIEW_H - 18, text="idle",
                      fill=accent, font=("Segoe UI", 8, "bold"))

    # --- actions ----------------------------------------------------------
    def _refresh_hooks(self) -> None:
        if _hooks_installed():
            self.hooks_label.config(text="Installed ✓", fg="#5fd08a")
        else:
            self.hooks_label.config(text="Not installed", fg="#ed8936")

    def _install_hooks(self) -> None:
        proc = subprocess.run([sys.executable, str(INSTALL_HOOKS)],
                              capture_output=True, text=True)
        self._refresh_hooks()
        ok = proc.returncode == 0
        self.status.set("Hooks installed." if ok else f"Hook install failed: {proc.stderr[:200]}")

    def _save(self) -> None:
        settings_mod.save_settings({
            "art_style": self.style_var.get(),
            "widget_size": self.size_var.get(),
            "transparent_bg": bool(self.transp_var.get()),
        })
        autostart.set_enabled(bool(self.startup_var.get()))
        self.startup_var.set(autostart.is_enabled())
        self.status.set("Saved. Restart the widget for art/size/transparency changes to take effect.")

    def _launch(self) -> None:
        try:
            subprocess.Popen([str(_pythonw()), str(RUN_SCRIPT)], cwd=str(PROJECT_ROOT))
            self.status.set("Widget launched.")
        except OSError as exc:
            self.status.set(f"Could not launch widget: {exc}")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    ControlPanel().run()


if __name__ == "__main__":
    main()
