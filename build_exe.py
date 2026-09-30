#!/usr/bin/env python3
"""
Build a standalone executable with PyInstaller.

Produces a single-file console binary named `message-guillotine`
(plus the OS-specific extension) in dist/.
"""

import sys
from pathlib import Path

import PyInstaller.__main__ as pyi

ICON = Path(__file__).parent / "branding" / "icon.ico"


def build():
    args = [
        "guillotine.py",
        "--onefile",
        "--console",
        "--name", "message-guillotine",
        "--clean",
        "--noconfirm",
    ]
    # Only Windows executables carry an icon resource; macOS icons belong to
    # .app bundles and Linux binaries get their icon from .desktop files.
    if sys.platform == "win32":
        args += ["--icon", str(ICON)]
    pyi.run(args)


if __name__ == "__main__":
    build()
