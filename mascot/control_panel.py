"""Settings / control panel for Claude Familiar.

A small titled window to configure the mascot: pick the art style with a live,
size-aware preview, tune the attention shake, manage install / startup / hooks,
and run a full uninstall. Built on a cohesive dark ``ttk`` theme and grouped into
tabs. Run with:

    python -m mascot.control_panel
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import (autostart, icon, osplatform, pet_store, settings as settings_mod,
               shortcuts, sprite_pixel, sprite_smooth)
from .tkinter_app import _accent, round_rect

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EMIT_PY = PROJECT_ROOT / "hooks" / "emit.py"
INSTALL_HOOKS = PROJECT_ROOT / "scripts" / "install_hooks.py"
RUN_SCRIPT = PROJECT_ROOT / "run_mascot.py"

PREVIEW_W, PREVIEW_H = 132, 150

# --- dark palette ---------------------------------------------------------
BG = "#15161d"          # window background
PANEL = "#1d1f29"       # raised card / tab body
PANEL_HI = "#262936"    # hover / active
PREVIEW_BG = "#161821"
BORDER = "#2f3242"
FG = "#e8e8ef"
MUTED = "#9095a8"
ACCENT = "#d9885a"      # warm Claude-ish accent (primary action, section titles)
ACCENT_HI = "#e7a079"
OK = "#5fd08a"
WARN = "#ed8936"
DANGER = "#e06c75"

# Per-widget-size preview scaling (mirrors the config.UI_SCALE buckets, clamped so
# the largest creature still fits the preview canvas).
_PREVIEW_PX = {"small": 4, "medium": 5, "large": 6}       # pixel art: per-cell px
_PREVIEW_R = {"small": 24.0, "medium": 30.0, "large": 36.0}  # smooth art: body radius


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


def _apply_theme(root: tk.Misc) -> ttk.Style:
    """Configure a cohesive dark ttk theme on the 'clam' base (the most
    restylable built-in theme; degrades gracefully if unavailable)."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=BG, foreground=FG, font=("Segoe UI", 9),
                    fieldbackground=PANEL, bordercolor=BORDER, focuscolor=BG,
                    troughcolor=BG, lightcolor=PANEL, darkcolor=PANEL)

    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=PANEL)

    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("Card.TLabel", background=PANEL, foreground=FG)
    style.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
    style.configure("MutedBG.TLabel", background=BG, foreground=MUTED)
    style.configure("Header.TLabel", background=BG, foreground=FG,
                    font=("Segoe UI", 15, "bold"))
    style.configure("Section.TLabel", background=PANEL, foreground=ACCENT,
                    font=("Segoe UI", 8, "bold"))

    # Buttons: flat dark, with an accented primary and a danger variant.
    style.configure("TButton", background=PANEL, foreground=FG, bordercolor=BORDER,
                    padding=(12, 6), relief="flat")
    style.map("TButton", background=[("active", PANEL_HI), ("pressed", PANEL_HI)],
              foreground=[("disabled", MUTED)])
    style.configure("Accent.TButton", background=ACCENT, foreground="#1a1206",
                    font=("Segoe UI", 9, "bold"))
    style.map("Accent.TButton", background=[("active", ACCENT_HI), ("pressed", ACCENT_HI)])
    style.configure("Danger.TButton", background=PANEL, foreground=DANGER)
    style.map("Danger.TButton", background=[("active", "#3a2a2e"), ("pressed", "#3a2a2e")])

    # Radio / check: dark body, accent indicator when selected.
    for s in ("TRadiobutton", "TCheckbutton"):
        style.configure(s, background=PANEL, foreground=FG, focuscolor=PANEL,
                        indicatorcolor=BG)
        style.map(s, background=[("active", PANEL)], foreground=[("active", FG)],
                  indicatorcolor=[("selected", ACCENT), ("pressed", ACCENT_HI)])

    style.configure("TNotebook", background=BG, bordercolor=BORDER, tabmargins=(2, 6, 2, 0))
    style.configure("TNotebook.Tab", background=BG, foreground=MUTED,
                    padding=(16, 8), bordercolor=BORDER)
    style.map("TNotebook.Tab", background=[("selected", PANEL)],
              foreground=[("selected", FG), ("active", FG)])

    style.configure("Horizontal.TScale", background=PANEL, troughcolor=BG)
    style.configure("TSeparator", background=BORDER)
    return style


class ControlPanel:
    def __init__(self) -> None:
        s = settings_mod.load_settings()
        self.root = tk.Tk()
        self.root.title("Claude Familiar — Settings")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.style = _apply_theme(self.root)
        icon.apply(self.root)

        self.style_var = tk.StringVar(value=s["art_style"])
        self.size_var = tk.StringVar(value=s["widget_size"])
        self.transp_var = tk.BooleanVar(value=s["transparent_bg"])
        self.startup_var = tk.BooleanVar(value=autostart.is_enabled())
        self.shake_after_var = tk.IntVar(value=int(s["shake_after_s"]))
        self.shake_amp_var = tk.IntVar(value=int(s["shake_max_amp_px"]))
        self.home_monitor_var = tk.IntVar(value=int(s["home_monitor"]))
        self._monitors = osplatform.enumerate_work_areas()
        self.status = tk.StringVar(value="")

        self._build()
        self._draw_preview()
        self._refresh_hooks()

    # --- layout -----------------------------------------------------------
    def _build(self) -> None:
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=16, pady=(12, 2))
        ttk.Label(header, text="🐾  Claude Familiar", style="Header.TLabel").pack(side="left")
        ttk.Label(header, text="settings", style="MutedBG.TLabel").pack(
            side="left", padx=(8, 0), pady=(7, 0))

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=14, pady=8)
        nb.add(self._tab_appearance(nb), text="  Appearance  ")
        nb.add(self._tab_behavior(nb), text="  Behavior  ")
        nb.add(self._tab_setup(nb), text="  Setup  ")

        footer = ttk.Frame(self.root)
        footer.pack(fill="x", padx=16, pady=(2, 4))
        ttk.Button(footer, text="Save & Apply", style="Accent.TButton",
                   command=self._save).pack(side="left")
        ttk.Button(footer, text="Launch widget", command=self._launch).pack(side="left", padx=6)
        ttk.Button(footer, text="🐾 Pet", command=self._open_pet).pack(side="left")
        ttk.Button(footer, text="Close", command=self.root.destroy).pack(side="right")

        ttk.Label(self.root, textvariable=self.status, style="MutedBG.TLabel",
                  wraplength=380, justify="left").pack(anchor="w", padx=16, pady=(0, 12))

    def _tab_appearance(self, parent: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(parent, style="Card.TFrame", padding=14)

        row = ttk.Frame(tab, style="Card.TFrame")
        row.pack(fill="x")

        left = ttk.Frame(row, style="Card.TFrame")
        left.pack(side="left", fill="y")
        ttk.Label(left, text="MASCOT ART", style="Section.TLabel").pack(anchor="w", pady=(0, 4))
        for label, val in (("Pixel (Claude-style)", "pixel"), ("Smooth (blob)", "smooth")):
            ttk.Radiobutton(left, text=label, value=val, variable=self.style_var,
                            command=self._draw_preview).pack(anchor="w", pady=1)
        ttk.Label(left, text="WIDGET SIZE", style="Section.TLabel").pack(anchor="w", pady=(14, 4))
        size_row = ttk.Frame(left, style="Card.TFrame")
        size_row.pack(anchor="w")
        for label, val in (("Small", "small"), ("Medium", "medium"), ("Large", "large")):
            ttk.Radiobutton(size_row, text=label, value=val, variable=self.size_var,
                            command=self._draw_preview).pack(side="left", padx=(0, 10))

        self.preview = tk.Canvas(row, width=PREVIEW_W, height=PREVIEW_H, bg=PANEL,
                                 highlightthickness=0, bd=0)
        self.preview.pack(side="right", padx=(8, 0))

        ttk.Separator(tab).pack(fill="x", pady=12)
        ttk.Label(tab, text="CARD", style="Section.TLabel").pack(anchor="w", pady=(0, 2))
        ttk.Checkbutton(tab, text="Transparent background — floating card (Windows only)",
                        variable=self.transp_var).pack(anchor="w")

        ttk.Separator(tab).pack(fill="x", pady=12)
        ttk.Label(tab, text="DISPLAY", style="Section.TLabel").pack(anchor="w", pady=(0, 2))
        ttk.Label(tab, text="Which monitor the cards spawn on (Windows).",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        mon_row = ttk.Frame(tab, style="Card.TFrame")
        mon_row.pack(anchor="w")
        ttk.Radiobutton(mon_row, text="Auto (primary)", value=-1,
                        variable=self.home_monitor_var).pack(side="left", padx=(0, 10))
        for i in range(len(self._monitors)):
            ttk.Radiobutton(mon_row, text=f"Monitor {i + 1}", value=i,
                            variable=self.home_monitor_var).pack(side="left", padx=(0, 10))
        return tab

    def _tab_behavior(self, parent: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(parent, style="Card.TFrame", padding=14)
        ttk.Label(tab, text="ATTENTION SHAKE", style="Section.TLabel").pack(anchor="w")
        ttk.Label(tab, text="When an unanswered prompt makes the card shake — and how hard "
                            "it gets the longer you ignore it.",
                  style="Muted.TLabel", wraplength=430, justify="left").pack(
            anchor="w", pady=(2, 12))

        delay = ttk.Frame(tab, style="Card.TFrame")
        delay.pack(fill="x", pady=4)
        ttk.Label(delay, text="Start shaking after", style="Card.TLabel").pack(side="left")
        self.shake_after_label = ttk.Label(delay, text="", style="Muted.TLabel",
                                            width=6, anchor="e")
        self.shake_after_label.pack(side="right")
        ttk.Scale(delay, from_=5, to=120, orient="horizontal", variable=self.shake_after_var,
                  command=lambda _v: self._refresh_shake_labels()).pack(
            side="right", fill="x", expand=True, padx=10)

        amp = ttk.Frame(tab, style="Card.TFrame")
        amp.pack(fill="x", pady=4)
        ttk.Label(amp, text="How violent", style="Card.TLabel").pack(side="left")
        self.shake_amp_label = ttk.Label(amp, text="", style="Muted.TLabel", width=8, anchor="e")
        self.shake_amp_label.pack(side="right")
        ttk.Scale(amp, from_=4, to=40, orient="horizontal", variable=self.shake_amp_var,
                  command=lambda _v: self._refresh_shake_labels()).pack(
            side="right", fill="x", expand=True, padx=10)
        self._refresh_shake_labels()
        return tab

    def _tab_setup(self, parent: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(parent, style="Card.TFrame", padding=14)

        ttk.Label(tab, text="INSTALL", style="Section.TLabel").pack(anchor="w")
        srow = ttk.Frame(tab, style="Card.TFrame")
        srow.pack(fill="x", pady=(2, 12))
        self.install_label = ttk.Label(srow, text="", style="Card.TLabel")
        self.install_label.pack(side="left")
        self.install_btn = ttk.Button(srow, text="", command=self._toggle_install)
        self.install_btn.pack(side="right")

        ttk.Checkbutton(tab, text="Run automatically when Windows starts",
                        variable=self.startup_var).pack(anchor="w", pady=(0, 12))

        ttk.Label(tab, text="CLAUDE CODE HOOKS", style="Section.TLabel").pack(anchor="w")
        hrow = ttk.Frame(tab, style="Card.TFrame")
        hrow.pack(fill="x", pady=(2, 12))
        self.hooks_label = ttk.Label(hrow, text="", style="Card.TLabel")
        self.hooks_label.pack(side="left")
        ttk.Button(hrow, text="Install / update", command=self._install_hooks).pack(side="right")

        ttk.Label(tab, text="PET", style="Section.TLabel").pack(anchor="w")
        prow = ttk.Frame(tab, style="Card.TFrame")
        prow.pack(fill="x", pady=(2, 12))
        ttk.Label(prow, text="Start over with a brand-new egg — clears coins, XP, level, "
                             "needs, name & items.", style="Muted.TLabel",
                  wraplength=300, justify="left").pack(side="left")
        ttk.Button(prow, text="Reset progress", style="Danger.TButton",
                   command=self._reset_pet).pack(side="right")

        ttk.Separator(tab).pack(fill="x", pady=6)
        ttk.Label(tab, text="DANGER ZONE", style="Section.TLabel",
                  foreground=DANGER).pack(anchor="w", pady=(0, 2))
        drow = ttk.Frame(tab, style="Card.TFrame")
        drow.pack(fill="x", pady=2)
        ttk.Label(drow, text="Remove hooks, shortcuts, settings & icon — reset to original.",
                  style="Muted.TLabel", wraplength=300, justify="left").pack(side="left")
        ttk.Button(drow, text="Uninstall", style="Danger.TButton",
                   command=self._uninstall).pack(side="right")

        self._refresh_install()
        return tab

    # --- preview ----------------------------------------------------------
    def _draw_preview(self) -> None:
        c = self.preview
        c.delete("all")
        accent = _accent("idle")
        size = self.size_var.get()
        m = 8
        round_rect(c, m, m, PREVIEW_W - m, PREVIEW_H - m, 16, fill=PREVIEW_BG, outline="")
        round_rect(c, m, m, PREVIEW_W - m, PREVIEW_H - m, 16, fill="", outline=accent, width=2)
        cx, cy = PREVIEW_W // 2, PREVIEW_H // 2 - 8
        if self.style_var.get() == "pixel":
            sprite_pixel.draw_creature(c, cx, cy, "idle", accent, _PREVIEW_PX.get(size, 5))
        else:
            sprite_smooth.draw_creature(c, cx, cy, "idle", accent, _PREVIEW_R.get(size, 30.0))
        c.create_text(PREVIEW_W // 2, PREVIEW_H - 16, text=f"idle · {size}",
                      fill=accent, font=("Segoe UI", 8, "bold"))

    # --- actions ----------------------------------------------------------
    def _refresh_hooks(self) -> None:
        if _hooks_installed():
            self.hooks_label.config(text="Installed ✓", foreground=OK)
        else:
            self.hooks_label.config(text="Not installed", foreground=WARN)

    def _refresh_install(self) -> None:
        if shortcuts.is_installed():
            self.install_label.config(text="Added to Start menu ✓", foreground=OK)
            self.install_btn.config(text="Remove")
        else:
            self.install_label.config(text="Not in Start menu", foreground=WARN)
            self.install_btn.config(text="Add to Start menu")

    def _toggle_install(self) -> None:
        if shortcuts.is_installed():
            shortcuts.uninstall_app_shortcuts()
            self.status.set("Removed Claude Familiar shortcuts.")
        else:
            created = shortcuts.install_app_shortcuts()
            self.status.set(f"Added {len(created)} shortcut(s). Find it in the Start menu / on your desktop.")
        self._refresh_install()

    def _install_hooks(self) -> None:
        proc = subprocess.run([sys.executable, str(INSTALL_HOOKS)],
                              capture_output=True, text=True)
        self._refresh_hooks()
        ok = proc.returncode == 0
        self.status.set("Hooks installed." if ok else f"Hook install failed: {proc.stderr[:200]}")

    def _refresh_shake_labels(self) -> None:
        """Keep the slider read-outs in sync (delay in seconds; a friendly word for
        how violent the shake gets at its peak)."""
        self.shake_after_label.config(text=f"{self.shake_after_var.get()}s")
        amp = self.shake_amp_var.get()
        word = ("gentle" if amp <= 8 else "medium" if amp <= 18
                else "rough" if amp <= 28 else "violent")
        self.shake_amp_label.config(text=word)

    def _save(self) -> None:
        settings_mod.save_settings({
            "art_style": self.style_var.get(),
            "widget_size": self.size_var.get(),
            "transparent_bg": bool(self.transp_var.get()),
            "shake_after_s": int(self.shake_after_var.get()),
            "shake_max_amp_px": int(self.shake_amp_var.get()),
            "home_monitor": int(self.home_monitor_var.get()),
        })
        autostart.set_enabled(bool(self.startup_var.get()))
        self.startup_var.set(autostart.is_enabled())
        self.status.set("Saved. Restart the widget for these changes to take effect.")

    def _launch(self) -> None:
        try:
            subprocess.Popen([str(_pythonw()), str(RUN_SCRIPT)], cwd=str(PROJECT_ROOT))
            self.status.set("Widget launched.")
        except OSError as exc:
            self.status.set(f"Could not launch widget: {exc}")

    def _open_pet(self) -> None:
        """Open the Pet window as its own process (so it works without a tray)."""
        try:
            subprocess.Popen([str(_pythonw()), "-m", "mascot.pet_window"], cwd=str(PROJECT_ROOT))
            self.status.set("Opened the Pet window.")
        except OSError as exc:
            self.status.set(f"Could not open Pet window: {exc}")

    def _reset_pet(self) -> None:
        """Overwrite pet.json with a fresh egg. A running widget picks this up via
        its external-change reload (it's the single writer; this is a deliberate
        out-of-band reset from Settings)."""
        from tkinter import messagebox
        if not messagebox.askyesno(
            "Reset pet progress",
            "Start over with a brand-new egg?\n\nThis clears the pet's coins, XP, "
            "level, needs, name, and inventory, and can't be undone.",
            icon="warning", parent=self.root,
        ):
            return
        try:
            now = time.time()
            pet_store.save(pet_store.PET_PATH, pet_store.default_pet(now), now)
            self.status.set("Pet progress reset — a fresh egg is on the way.")
        except OSError as exc:
            self.status.set(f"Could not reset pet: {exc}")

    def _uninstall(self) -> None:
        from tkinter import messagebox
        from . import uninstall as uninstall_mod
        if not messagebox.askyesno(
            "Uninstall Claude Familiar",
            "This removes the Claude Code hooks, Start-menu/desktop and run-at-login "
            "shortcuts, your saved settings and session state, and the generated app "
            "icon — resetting everything to its original form.\n\nContinue?",
            icon="warning", parent=self.root,
        ):
            return
        actions = uninstall_mod.full_uninstall()
        messagebox.showinfo(
            "Claude Familiar uninstalled",
            "Done:\n\n" + "\n".join(f"• {a}" for a in actions),
            parent=self.root,
        )
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    ControlPanel().run()


if __name__ == "__main__":
    main()
