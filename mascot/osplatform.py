"""Tiny OS-detection helper shared across the mascot's platform-specific code.

Named ``osplatform`` (not ``platform``) so it never shadows the stdlib module.
"""
from __future__ import annotations

import sys

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"
