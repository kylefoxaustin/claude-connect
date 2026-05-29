"""Native App Edition launcher for Conductor.

Runs the *same* FastAPI app as the Web Browser Edition, but inside a native
desktop window (pywebview → WebKitGTK on Ubuntu) instead of a browser tab.

The uvicorn server runs in a background daemon thread bound to the host/port
from ``settings.toml``; closing the window stops the server and exits the
process. That window-owns-the-server lifecycle matches Conductor's
restart-clean, no-persistence design — there's nothing left running afterward.

Run:  python app.py     (use the system-site-packages venv; see README)
"""

from __future__ import annotations

import socket
import threading
import time

import uvicorn
import webview

from conductor.main import app
from conductor.settings import load_settings


def _port_open(host: str, port: int) -> bool:
    """True if something is already accepting connections on host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def _wait_for_server(host: str, port: int, timeout: float = 10.0) -> bool:
    """Block until the uvicorn thread is accepting connections (or time out)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(host, port):
            return True
        time.sleep(0.1)
    return False


def main() -> None:
    settings = load_settings()
    host = settings.server.host
    port = settings.server.port

    # If a Conductor (or anything) is already serving this port — e.g. a
    # `make dev` instance, or a second launch of this app — attach to it
    # instead of starting a doomed second server. We must NOT shut it down on
    # window close, since we don't own it.
    attached = _port_open(host, port)
    server: uvicorn.Server | None = None
    server_thread: threading.Thread | None = None

    if not attached:
        # log_level="warning" keeps the console quiet for an app launch.
        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        server = uvicorn.Server(config)
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        if not _wait_for_server(host, port):
            raise SystemExit(f"Conductor server did not start on {host}:{port}")

    # A bind host of 0.0.0.0 / :: isn't a connectable URL host — point the
    # window at loopback in that case.
    url_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host

    webview.create_window(
        "Conductor",
        f"http://{url_host}:{port}",
        width=1400,
        height=900,
        min_size=(900, 600),
    )

    # Give the GTK window a stable WM_CLASS ("conductor") so the .desktop file's
    # StartupWMClass can group it under the Conductor icon in the dock/taskbar —
    # otherwise GTK derives it from the script name ("app.py"). Must run before
    # the GUI loop initializes GTK. Guarded so a non-GTK backend still launches.
    try:
        from gi.repository import GLib

        GLib.set_prgname("conductor")
    except Exception:  # noqa: BLE001 — cosmetic only; never block the launch
        pass

    # Blocks on the GUI event loop until the window is closed.
    webview.start()

    # Window closed: wind down only the server we started ourselves. The daemon
    # thread would die with the process anyway, but this releases the port
    # cleanly first. An attached-to server is left running untouched.
    if server is not None and server_thread is not None:
        server.should_exit = True
        server_thread.join(timeout=3.0)


if __name__ == "__main__":
    main()
