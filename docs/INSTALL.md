# Installing Conductor — editions, native app, phone

The [README Quick Start](../README.md#quick-start) gets the web edition running. This page covers the
native desktop app and reaching Conductor from your phone.

## Editions

Conductor ships in two editions from the same codebase:

| Edition | What it is | Run |
|---|---|---|
| **Web Browser** | The dashboard served at `http://127.0.0.1:8765`, opened in any browser. | `make dev` / `make run` |
| **Native App** | The *same* dashboard wrapped in a native desktop window (pywebview → WebKitGTK), with its own app-menu launcher and dock icon. | `make native` |

Both editions ship in a **single release per version** (`vX.Y.Z`) — it's one
codebase at one commit, the edition is just how you run it. New features land
once and both editions get them.

### Native App Edition (Ubuntu)

The native edition runs the identical FastAPI + JS app inside a WebKitGTK window.
The uvicorn server runs in a background thread; **closing the window stops the
server** (nothing is left running). If a Conductor is already serving the port
(e.g. a `make dev` instance, or a second launch), the app *attaches* to it
instead of starting a duplicate.

```bash
# 1. System WebKitGTK (not pip-installable — provides PyGObject + the WebKit2 typelib)
sudo apt install python3-gi gir1.2-webkit2-4.0 libwebkit2gtk-4.0-37

# 2. Build the native venv (--system-site-packages, so it can see system gi/WebKit) + pywebview
make install-native

# 3. Launch the native window
make native

# 4. (Optional) Add a launcher to your app menu / dock, with this checkout's paths baked in
make install-desktop
```

`make install-native` creates a **separate** `.venv-native` so the Web edition's
`.venv` stays untouched. `make install-desktop` writes
`~/.local/share/applications/conductor.desktop` (icon: `assets/conductor.svg`,
`StartupWMClass=conductor` for dock grouping) — re-run it if you move the repo.

> Tested against WebKit2 **4.0** (Ubuntu 22.04). The SVG connection-line overlays
> and tile drag render correctly under WebKitGTK.

#### Two ways to “install” it

`make native` and `make install-desktop` both run the app **out of this cloned
repo** — keep the clone around. If you'd rather treat Conductor like a normal
installed app you can delete the clone afterward, use the staged install:

| Goal | Command | Where the code lives |
|---|---|---|
| Run from the clone (dev) | `make native` | this repo (foreground; closing the terminal stops it) |
| App-menu launcher, code in the clone | `make install-desktop` | this repo (don't delete it) |
| **Installed app, clone disposable** | **`make install-app`** | `~/.local/share/conductor/` (clone can be deleted) |

```bash
# One-time, self-contained install (after the apt deps above):
make install-app      # copies the app + builds its venv into ~/.local/share/conductor,
                      # then adds the app-menu launcher pointing there
# → launch "Conductor" from your app menu / dock; it runs detached (no terminal).
# → the cloned repo is now disposable. Re-run to update; `make uninstall-app` to remove.
```

`make install-app` stages the app (code, served frontend, icon, and the
`claude-tracked` relaunch helper) into `~/.local/share/conductor/`, builds the
WebKitGTK venv **there**, and points the `.desktop` launcher at that copy — so it
keeps full host access (it still spawns terminals, focuses windows, and reads
`~/.claude`) and survives deleting the clone. It is **not** a sandboxed package
(Flatpak/Snap would hide the host's processes from `psutil` and break session
discovery) nor a single-file binary — it's a self-contained local install that
behaves like an installed app.

---

## Phone access & notifications

Reach Conductor from your phone — the desktop board **and** the mobile ops console (`/m`) — and let it page you when something needs you. The server never leaves `127.0.0.1`; [Tailscale](https://tailscale.com)'s `serve` proxies it onto *your own* private tailnet (WireGuard), so it's reachable from your devices and nowhere else — never the LAN, never the public internet.

**1. Put Conductor on your tailnet** (HTTPS is required for Web Push and the service worker):

```bash
# one-time, if serve isn't permitted for your user yet:
sudo tailscale set --operator=$USER

# proxy Conductor onto the tailnet over HTTPS (Let's Encrypt cert, managed by Tailscale)
tailscale serve --bg --https=443 http://127.0.0.1:8765
```

Now `https://<host>.<tailnet>.ts.net/` (the board) and `.../m` (the mobile console) load on any device signed into your tailnet.

**2. Gate it with a token** (recommended once it's remotely reachable). Set `[server].auth_token` in `settings.toml` (or `$CONDUCTOR_AUTH_TOKEN`, which wins and never touches disk). With a token set, every `/api/*` call and the `/ws` handshake require it; leave it empty and localhost stays frictionless. The native desktop app auto-unlocks; the phone remembers it after first entry.

**3. Enable notifications** (optional). Open `/m` on the phone over HTTPS, allow notifications when asked, and Conductor registers a Web Push subscription. From then on it **pages you on exactly two things** — a Claude blocked on a question, and a gated `git push`. A **Test** button lets you tell "the pipe is dead" from "the fleet is just quiet," and the UI is honest about the limits (a PWA can't break Do-Not-Disturb, so it won't wake you at 3am — a push approval simply waits).

> Installed to the home screen it's a PWA (offline-tolerant shell, home-screen icon). The mobile console shares **nothing** with the desktop board but the API — it's a purpose-built *console*, not the workbench shrunk down.
