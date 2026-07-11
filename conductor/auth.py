"""Token auth for the HTTP API + WebSocket.

Conductor binds ``127.0.0.1`` and, by default, has **no** auth — safe, because
nothing off the box can reach it. The moment you make it reachable (a phone over
Tailscale, say) that assumption breaks, and this surface can inject keystrokes
into your terminals and approve repo pushes. So when — and only when — an auth
token is configured, every ``/api/*`` request and the ``/ws`` handshake must
present it.

Design:
  • **Off by default.** Empty token ⇒ ``token_ok`` always passes ⇒ the local
    desktop / native app keeps working with zero friction. Nothing changes until
    you opt in by setting ``[server] auth_token`` (or ``$CONDUCTOR_AUTH_TOKEN``).
  • **The shell is public; the data is not.** ``/`` , ``/static/*``, the PWA
    manifest, service worker, and icons load without a token (they're just
    HTML/JS/CSS — no fleet data). Everything under ``/api/`` (except the version
    probe ``/api/health``) and the WebSocket require the token.
  • **Constant-time compare** (``hmac.compare_digest``) so the check can't be
    timing-probed.

The env var wins over the file so a token need never be written to disk / a
committed ``settings.toml``.
"""

from __future__ import annotations

import hmac
import os

from .settings import Settings

# Reachable without a token — the app shell and its static assets. These carry no
# fleet data; the API behind them is what's gated.
_PUBLIC_PATHS = frozenset({
    "/", "/index.html",
    "/api/health",              # liveness/version probe — safe, and used by monitors
    "/sw.js", "/manifest.webmanifest", "/favicon.ico",
})
_PUBLIC_PREFIXES = ("/static/",)


def resolved_token(settings: Settings) -> str:
    """The effective token: env override first (so it needn't touch disk), then
    ``settings.toml``. Empty string ⇒ auth disabled."""
    return (os.environ.get("CONDUCTOR_AUTH_TOKEN") or settings.server.auth_token or "").strip()


def auth_enabled(settings: Settings) -> bool:
    return bool(resolved_token(settings))


def path_requires_auth(path: str) -> bool:
    """Whether a request path is gated. The public shell + ``/api/health`` are not;
    the rest of the API and the WebSocket are."""
    if path in _PUBLIC_PATHS:
        return False
    if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return False
    return path.startswith("/api/") or path == "/ws"


def token_ok(configured: str, provided: str | None) -> bool:
    """Constant-time token check. An empty ``configured`` means auth is disabled,
    so everything passes (the local-only default)."""
    if not configured:
        return True
    if not provided:
        return False
    return hmac.compare_digest(configured, provided)
