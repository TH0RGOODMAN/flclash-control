# FlClash Control

[![CI](https://github.com/TH0RGOODMAN/flclash-control/actions/workflows/tests.yml/badge.svg)](https://github.com/TH0RGOODMAN/flclash-control/actions/workflows/tests.yml)
[![Release](https://img.shields.io/github/v/release/TH0RGOODMAN/flclash-control?include_prereleases&label=release)](https://github.com/TH0RGOODMAN/flclash-control/releases)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)
[![MCP SDK](https://img.shields.io/badge/MCP%20SDK-v2-6e56cf)](pyproject.toml)
[![License: GPL v3+](https://img.shields.io/badge/license-GPLv3%2B-blue)](LICENSE)

**[简体中文](README.md)** · English

**Authenticated CLI and stdio MCP control bridge for a running FlClash Windows GUI — updating real GUI state and persistent settings without desktop mouse/keyboard injection.**

---

## Why Not Just Use the Mihomo REST API?

Controlling a desktop FlClash instance solely through Mihomo's `:9090` REST API leaves three practical gaps:

1. **No GUI state sync or persistence**: `PATCH /configs` mutates in-memory kernel state only; FlClash's Riverpod UI switches stay out of sync, and the next GUI profile apply overwrites your changes.
2. **No Windows system-proxy control**: Windows system proxy settings are managed by FlClash's native desktop plugin, outside Mihomo's API.
3. **Different restart semantics**: Mihomo's `/restart` does not run FlClash's native Windows Helper/IPC core reconnection flow.

`FlClash Control` embeds a small, opt-in loopback bridge (`--dart-define=FLCLASH_CONTROL=true`) inside the FlClash GUI process so CLI scripts and MCP-capable AI agents can drive GUI-persistent switches and native Helper/IPC lifecycle actions directly, while node selection, delay testing, and DNS/log queries continue to use standard Mihomo tools.

---

## MCP Tools & CLI Reference

| MCP Tool | CLI Command | Annotations | Description |
|---|---|---|---|
| `flclash_health` | `doctor` / `health` | Read-only | Verify local DPAPI token readiness, loopback bridge reachability, and state-file vs live PID match |
| `flclash_status` | `status` | Read-only | Read core connection, listener run state, mode, TUN/system-proxy switches, and pending queue status |
| `flclash_start` | `start` | Idempotent | Start proxy listeners and apply synchronized GUI settings |
| `flclash_stop` | `stop` | Idempotent | Stop proxy listeners while keeping the GUI and control bridge running |
| `flclash_restart_core` | `restart` | Lifecycle | Reconnect Helper/IPC and reinitialize `FlClashCore`, preserving running/stopped state |
| `flclash_set_tun` | `tun on\|off` | Idempotent | Toggle and save the GUI TUN switch with native permission checks |
| `flclash_set_system_proxy` | `system-proxy on\|off` | Idempotent | Toggle and save the Windows system-proxy switch via the native plugin |
| `flclash_set_mode` | `mode rule\|global\|direct` | Idempotent | Switch and save outbound routing mode (`rule`, `global`, or `direct`) |
| `flclash_show_window` | `show` | Idempotent | Reveal the existing GUI window without desktop input injection |
| `flclash_exit` | `exit [--wait]` | Destructive | Save preferences and normally exit the GUI and core (with optional shutdown polling) |

---

## Quick Start

> [!IMPORTANT]
> Stock upstream FlClash installers do not include this control bridge. You must first build and install the bridge-enabled `app.so` against **`chen08209/FlClash` `v0.8.93`** (Windows x64, Flutter `3.41.9`, engine `42d3d75a56efe1a2e9902f52dc8006099c45d937`) — see [integration/flclash/README.md](integration/flclash/README.md) and [docs/usage.md](docs/usage.md).

### 1. Install the Python Client

```powershell
git clone https://github.com/TH0RGOODMAN/flclash-control.git
cd flclash-control
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .

.\.venv\Scripts\flclash-control.exe doctor
.\.venv\Scripts\flclash-control.exe status
```

### 2. Configure an MCP Client

No plaintext token is needed in your MCP configuration — authentication is decrypted automatically per Windows user via DPAPI:

```json
{
  "mcpServers": {
    "flclash-control": {
      "command": "C:\\Tools\\flclash-control\\.venv\\Scripts\\flclash-control-mcp.exe",
      "args": []
    }
  }
}
```

---

## Security & Completion Guarantees

- **Loopback + DPAPI Per-Launch Token**: Binds exclusively to `127.0.0.1:47892`. Each GUI launch generates a fresh 256-bit token encrypted with current-user Windows DPAPI in `%LOCALAPPDATA%\FlClash-Control\gui-bridge.json`. Browser `Origin` and `Sec-Fetch-Site` headers are rejected (`403`).
- **Allowlisted Error Codes**: Neither server responses nor client exceptions echo subscription URLs, node names, or bearer tokens; only 25 fixed diagnostic codes are surfaced.
- **Strict Completion Semantics**: Core start/restart operations await both profile setup and listener startup `Future`s, propagating missing IPC replies or native failures instead of reporting false positives. Native Windows UAC prompts still require manual user confirmation.

---

## Testing & CI

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q
```

GitHub Actions continuously runs the Windows client/MCP test matrix across Python 3.11, 3.12, and 3.13, audits built wheel contents, and verifies that `integration/flclash/integration.patch` applies cleanly to `chen08209/FlClash` `v0.8.93`.

## License

Released under **[GPL-3.0-or-later](LICENSE)**. Unofficial extension, unaffiliated with the upstream FlClash project. When distributing modified FlClash binaries incorporating the integration patch, preserve upstream notices and provide corresponding source code.
