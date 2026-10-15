#!/usr/bin/env python3
"""Entry point for MARAT — CLI and Desktop Executable Server."""

from __future__ import annotations

import sys
import threading
import time
import webbrowser

from src.cli import MARAT_BANNER, app, console, serve


def _open_browser_when_ready(url: str = "http://localhost:8000"):
    time.sleep(1.2)
    try:
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Running as a standalone application / double-clicked
        console.print(MARAT_BANNER)
        console.print("[bold green]Starting MARAT desktop server at http://localhost:8000[/]")
        console.print("[dim]Opening your default browser... (Press CTRL+C in this console to stop)[/]\n")
        threading.Thread(target=_open_browser_when_ready, daemon=True).start()
        serve(host="127.0.0.1", port=8000)
    else:
        app()
