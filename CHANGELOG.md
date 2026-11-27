# Changelog

## [0.2.0] — 2026-11-27

### Added

- **`flclash_health` MCP tool & `health` / `doctor` CLI commands**: inspect loopback bridge reachability (`GET /health`), DPAPI token decryption readiness, and `gui-bridge.json` vs live GUI PID agreement without exposing credentials.
- **Actionable Safe Bridge Error Diagnostics**: `ControlClient` now maps the 25 fixed `control_bridge.dart` error codes (such as `tun_authorization_or_apply_failed`, `gui_not_initialized`, `command_queue_full`, `native_core_not_ready`) into structured `ControlError(message, code=...)` explanations while still refusing to echo unknown response bodies or secrets.
- **Graceful Exit Waiting (`exit --wait` / `flclash_exit(wait_for_exit=True)`)**: optionally poll `/health` after scheduling exit to confirm the GUI process and bridge have actually closed.
- **Complete MCP v2 Schema & Annotations**: added `ToolAnnotations` (`read_only_hint`, `destructive_hint`, `idempotent_hint`, `open_world_hint=False`) across all 10 tools, `Literal["rule", "global", "direct"]` JSON Schema enum validation for `flclash_set_mode`, `ToolError` wrapping, PEP 561 `py.typed`, and `FLCLASH_CONTROL_TOKEN_FILE` / `FLCLASH_CONTROL_TIMEOUT` environment configuration.
- **Bilingual Documentation & Patch CI**: added [English README](README.en.md), expanded GitHub Actions across Python 3.11 / 3.12 / 3.13 on Windows, wheel content verification, and automated `git apply --check` validation against upstream `chen08209/FlClash` `v0.8.93`.

### Removed

- Removed undeployed `experiments/headless/` prototype modules from the main tree so the repository focuses cleanly on the verified GUI control bridge architecture (historical prototype commits remain in Git history).

## [0.1.0](https://github.com/TH0RGOODMAN/flclash-control/releases/tag/v0.1.0) — 2026-11-16

Initial experimental release for Windows x64 (`chen08209/FlClash` `v0.8.93`, Flutter `3.41.9`).

- In-process Dart `ControlBridge` (`127.0.0.1:47892`) with per-launch 256-bit token encrypted via current-user Windows DPAPI.
- CLI and 9 stdio MCP tools synchronizing Riverpod GUI switches, persistent preferences, Windows system proxy plugin, and native Helper/IPC core restart.
- Reproducible Dart AOT build script (`scripts/build_aot.ps1`) and Dart/Python test suites.
