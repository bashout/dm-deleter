#!/usr/bin/env python3
"""
Build a standalone executable with PyInstaller.

Produces a single-file console binary named `message-deleter`
(plus the OS-specific extension) in dist/.
"""

import PyInstaller.__main__ as pyi


def build():
    pyi.run(
        [
            "dm_deleter.py",
            "--onefile",
            "--console",
            "--name", "message-deleter",
            "--clean",
            "--noconfirm",
        ]
    )


if __name__ == "__main__":
    build()
