# ADR-0001: Allow required runtime dependencies

- **Status:** Accepted
- **Date:** 2026-06-18
- **Resolves:** [#16](https://github.com/NadimJebali/Claude-Familiar/issues/16)
- **Unblocks:** #17 (psutil), #18 (pystray), #19 (plyer/desktop-notifier), #20 (pywin32)

## Context

The project began as **pure standard library, zero runtime dependencies** — a
stated feature in the README, and the explicit reason PyInstaller was rejected
(see TASK.md, 2026-06-17). The cross-platform support and OS integration were
hand-rolled against `ctypes`: Win32 Toolhelp + `/proc` parsing for process
discovery (`hooks/proc.py`, `mascot/proc.py`), a Windows-only `Shell_NotifyIconW`
tray (`mascot/tray.py`), ctypes/COM `.lnk` creation (`mascot/shortcuts.py`).

That hand-rolled code works and is tested, but it has real costs:
- The system tray exists only on Windows; Linux/macOS users get none.
- There are no native OS notifications — only the in-app speech bubble.
- The ctypes/COM code is fragile, verbose, and Windows-version-sensitive.

Four issues (#17–#20) propose replacing or extending these with well-maintained
third-party packages. They were all blocked on this policy decision.

## Decision

**Allow required (hard) runtime dependencies.** Third-party packages may be listed
in `requirements.txt` and imported directly by the widget where they replace
fragile hand-rolled `ctypes` code or extend platform support. The pure-stdlib
constraint is retired as a hard rule.

Policy details:
- Runtime deps live in `requirements.txt`; `pip install -r requirements.txt`
  becomes part of setup. Dev/test tools stay in `requirements-dev.txt`.
- **OS-specific deps are gated by environment markers** so they are only installed
  where they apply, e.g. `pywin32; sys_platform == "win32"`.
- Prefer widely-used, actively-maintained packages. New runtime deps should be
  weighed against this ADR; a dep that only saves a few lines is not worth the
  install/supply-chain cost.

## Consequences

**Positive**
- Unblocks #18 (cross-platform tray via pystray) and #19 (native notifications) —
  genuine UX wins for non-Windows users.
- Lets #17/#20 drop fragile ctypes/COM in favor of `psutil`/`pywin32`.
- Simpler, more readable, better-tested platform code.

**Negative**
- The "no external dependencies" promise is gone; install is heavier and run-from-
  source needs a `pip install`.
- Adds a supply-chain surface (each dep + its transitive deps) the project did not
  have before.
- Pillow (pulled in by pystray) is a comparatively large native dependency.

**Mitigations**
- Environment markers keep each platform's install minimal.
- Per-issue evaluation (#17–#20) still applies: this ADR *permits* deps, it does
  not mandate adopting all four. Each is judged on whether the dependency earns its
  cost over the working hand-rolled code.

## Notes

This reverses the prior pure-stdlib stance. The PyInstaller rejection (TASK.md)
stands on its own merits (build artifact size, AV fragility) and is not reopened
by this ADR.
