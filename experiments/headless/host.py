"""Own an installed FlClash core through its native Windows Helper and IPC.

Headless ownership is exclusive. A running GUI is always refused. This module
does not edit GUI preferences, subscription files, or the generated config.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import threading
from typing import Any, Callable

import httpx
import yaml

from .ipc import IpcChannel, IpcError, private_security_attributes

HELPER_URL = "http://127.0.0.1:47890"


class HostError(RuntimeError):
    """A safe host lifecycle failure."""


def gui_is_running(process_name: str = "FlClash.exe") -> bool:
    if os.name != "nt":
        raise HostError("Headless FlClash control requires Windows")
    result = subprocess.run(
        ["tasklist.exe", "/FI", f"IMAGENAME eq {process_name}", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, timeout=5,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise HostError("Cannot verify whether FlClash GUI is running")
    return any(row and row[0].casefold() == process_name.casefold()
               for row in csv.reader(io.StringIO(result.stdout)))


def full_tun_update(source: dict[str, Any], enabled: bool) -> dict[str, Any]:
    """All pointer-backed fields are required by FlClash 0.8.93 updateConfig."""
    if not isinstance(enabled, bool):
        raise HostError("TUN state must be a boolean")
    tun = source.get("tun") or {}
    if not isinstance(tun, dict):
        raise HostError("Configuration TUN field is invalid")
    stack = str(tun.get("stack", "mixed")).lower()
    if stack not in {"mixed", "system", "gvisor"}:
        raise HostError("Configuration TUN stack is unsupported")
    hijack = tun.get("dns-hijack", ["any:53"])
    addresses = tun.get("route-address", [])
    if not isinstance(hijack, list) or not isinstance(addresses, list):
        raise HostError("Configuration TUN route/DNS fields must be lists")
    if not all(isinstance(item, str) for item in hijack + addresses):
        raise HostError("Configuration TUN route/DNS entries must be strings")
    return {
        "enable": enabled, "device": str(tun.get("device", "FlClash")),
        "stack": stack, "dns-hijack": list(hijack),
        "auto-route": bool(tun.get("auto-route", True)),
        "route-address": list(addresses),
    }


class FlClashHost:
    """Synchronous lifecycle controller, suitable for an MCP/CLI daemon.

    A daemon must keep this object alive: closing its pipe ends the core.
    Runtime TUN/mode overrides survive native restart in this host, but do not
    alter FlClash GUI preferences. Pass selected_map from a GUI REST snapshot
    when handing over; subsequent restarts capture selector choices by RPC.
    """

    def __init__(
        self, core_path: str | Path, home_dir: str | Path | None = None,
        *, request_timeout: float = 15.0, pipe_timeout: float = 15.0,
        gui_process_name: str = "FlClash.exe",
        selected_map: dict[str, str] | None = None,
        process_probe: Callable[[], bool] | None = None,
        channel_factory: Callable[..., Any] = IpcChannel,
        helper_client: Any = None,
    ):
        self.core_path = Path(core_path).resolve()
        self.home_dir = (Path(home_dir) if home_dir is not None else
                         Path(os.environ.get("APPDATA", "")) / "com.follow" / "clash").resolve()
        self.request_timeout = request_timeout
        self.pipe_timeout = pipe_timeout
        self.gui_process_name = gui_process_name
        self._process_probe = process_probe or (lambda: gui_is_running(gui_process_name))
        self._channel_factory = channel_factory
        self._helper = helper_client or httpx.Client(
            base_url=HELPER_URL, timeout=request_timeout, trust_env=False,
            follow_redirects=False,
        )
        self._owns_client = helper_client is None
        self._channel = None
        self._ownership = None
        self._owns_core = False
        self._running = False
        self._lock = threading.RLock()
        self._source: dict[str, Any] = {}
        self._tun_override: bool | None = None
        self._mode_override: str | None = None
        self._selected_map = dict(selected_map or {})

    @property
    def is_connected(self) -> bool:
        return self._channel is not None and self._channel.is_connected

    @property
    def is_running(self) -> bool:
        return self.is_connected and self._running

    def _assert_gui_closed(self) -> None:
        if self._process_probe():
            raise HostError("FlClash GUI is running. Exit it normally before using headless control.")

    def _acquire_ownership(self) -> None:
        if self._ownership is not None:
            return
        if os.name != "nt":
            raise HostError("Headless FlClash control requires Windows")
        import win32api
        import win32event
        try:
            handle = win32event.CreateMutex(
                private_security_attributes(), False, r"Global\FlClashControlHelperOwner"
            )
            if win32api.GetLastError() == 183:
                handle.Close()
                raise HostError("Another headless FlClash controller already owns the Helper")
            self._ownership = handle
        except HostError:
            raise
        except Exception as exc:
            raise HostError("Unable to acquire exclusive Helper ownership") from exc

    def _release_ownership(self) -> None:
        handle, self._ownership = self._ownership, None
        if handle is not None:
            handle.Close()

    def _request_helper(self, method: str, route: str, **kwargs):
        try:
            response = self._helper.request(method, route, **kwargs)
            response.raise_for_status()
            return response
        except Exception as exc:
            raise HostError(f"FlClash Helper request {route} failed") from exc

    def _preflight(self) -> None:
        self._assert_gui_closed()
        if not self.core_path.is_file() or self.core_path.name.casefold() != "flclashcore.exe":
            raise HostError("core_path must point to the installed FlClashCore.exe")
        source_path = self.home_dir / "config.yaml"
        if not source_path.is_file():
            raise HostError("FlClash generated config.yaml is missing")
        try:
            source = yaml.safe_load(source_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            raise HostError("Unable to parse FlClash config.yaml") from exc
        if not isinstance(source, dict):
            raise HostError("FlClash config.yaml must contain a mapping")
        full_tun_update(source, bool((source.get("tun") or {}).get("enable", False)))
        # Retain only safe update fields. Node passwords/URLs are never returned.
        self._source = {key: source.get(key) for key in ("tun", "mode", "external-controller", "mixed-port")}
        with self.core_path.open("rb") as core_file:
            expected = hashlib.file_digest(core_file, "sha256").hexdigest()
        ping = self._request_helper("GET", "/ping").text.strip().strip('"').lower()
        if ping != expected:
            raise HostError("Installed core hash does not match the Helper; use native service repair")

    def rpc(self, method: str, data: Any = None) -> Any:
        if not self.is_connected:
            raise HostError("Headless core is not connected")
        try:
            return self._channel.request(method, data, timeout=self.request_timeout)
        except IpcError as exc:
            raise HostError(str(exc)) from exc

    def _json_rpc(self, method: str, value: dict[str, Any]) -> Any:
        return self.rpc(method, json.dumps(value, ensure_ascii=False, separators=(",", ":")))

    @staticmethod
    def _expect_empty(value: Any, method: str) -> None:
        if value not in (None, ""):
            raise HostError(f"Core did not accept {method}")

    def connect(self, *, start: bool = False) -> dict[str, Any]:
        with self._lock:
            self._assert_gui_closed()
            if self.is_connected:
                if start:
                    self.start()
                return self.status()
            if self._channel is not None:
                self._disconnect_core()
            self._acquire_ownership()
            try:
                self._preflight()
                self._channel = self._channel_factory(request_timeout=self.request_timeout)
                self._assert_gui_closed()  # Re-check before the first mutation.
                self._owns_core = True  # /start can succeed after a client timeout.
                response = self._request_helper("POST", "/start", json={
                    "path": str(self.core_path), "arg": self._channel.address,
                })
                if response.text.strip():
                    raise HostError("FlClash Helper did not accept the core startup request")
                self._channel.wait_connected(self.pipe_timeout)
                if self._json_rpc("initClash", {"home-dir": str(self.home_dir), "version": 10}) is not True:
                    raise HostError("FlClash core initialization failed")
                value = self._json_rpc("setupConfig", {
                    "selected-map": self._selected_map,
                    "test-url": "https://www.gstatic.com/generate_204",
                })
                self._expect_empty(value, "setupConfig")
                updates: dict[str, Any] = {}
                if self._tun_override is not None:
                    updates["tun"] = full_tun_update(self._source, self._tun_override)
                if self._mode_override is not None:
                    updates["mode"] = self._mode_override
                if updates:
                    self._expect_empty(self._json_rpc("updateConfig", updates), "updateConfig")
                if start:
                    self.start()
                return self.status()
            except Exception:
                try:
                    self._disconnect_core()
                finally:
                    self._release_ownership()
                raise

    def start(self) -> dict[str, Any]:
        with self._lock:
            self._assert_gui_closed()
            if not self.is_connected:
                return self.connect(start=True)
            if self.rpc("startListener") is not True:
                raise HostError("Core did not start its listeners")
            self._running = True
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._assert_gui_closed()
            if self.is_connected:
                if self.rpc("stopListener") is not True:
                    raise HostError("Core did not stop its listeners")
            self._running = False
            return self.status()

    def set_tun(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            self._assert_gui_closed()
            if not isinstance(enabled, bool):
                raise HostError("TUN state must be a boolean")
            if not self.is_connected:
                self.connect()
            update = full_tun_update(self._source, enabled)
            self._expect_empty(self._json_rpc("updateConfig", {"tun": update}), "updateConfig")
            self._tun_override = enabled
            return self.status()

    def set_mode(self, mode: str) -> dict[str, Any]:
        with self._lock:
            self._assert_gui_closed()
            if mode not in {"rule", "global", "direct"}:
                raise HostError("Mode must be rule, global or direct")
            if not self.is_connected:
                self.connect()
            self._expect_empty(self._json_rpc("updateConfig", {"mode": mode}), "updateConfig")
            self._mode_override = mode
            return self.status()

    def _capture_selection(self) -> None:
        if not self.is_connected:
            return
        data = self.rpc("getProxies")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                return
        if not isinstance(data, dict):
            return
        for name, value in (data.get("proxies") or {}).items():
            if isinstance(value, dict) and value.get("type") == "Selector" and isinstance(value.get("now"), str):
                self._selected_map[name] = value["now"]

    def restart(self) -> dict[str, Any]:
        with self._lock:
            self._assert_gui_closed()
            running = self.is_running
            self._capture_selection()
            self._disconnect_core()
            return self.connect(start=running)

    def status(self) -> dict[str, Any]:
        with self._lock:
            initialized = self.rpc("getIsInit") is True if self.is_connected else False
            tun = self._source.get("tun") or {}
            return {
                "connected": self.is_connected, "initialized": initialized,
                "running": self.is_running, "management": "flclash-helper-ipc",
                "tun_enabled": self._tun_override if self._tun_override is not None else bool(tun.get("enable", False)),
                "mode": self._mode_override or self._source.get("mode") or "rule",
                "settings_scope": "headless-runtime", "gui_settings_changed": False,
            }

    def _disconnect_core(self) -> None:
        error = None
        if self._owns_core:
            try:
                # Never send /stop against a core the GUI has since taken over.
                self._assert_gui_closed()
                response = self._request_helper("POST", "/stop")
                if response.text.strip():
                    raise HostError("FlClash Helper did not accept the core stop request")
            except Exception as exc:
                error = exc
            self._owns_core = False
        channel, self._channel = self._channel, None
        if channel is not None:
            channel.close()
        self._running = False
        if error is not None:
            raise error

    def close(self) -> None:
        with self._lock:
            try:
                self._disconnect_core()
            finally:
                self._release_ownership()
                if self._owns_client:
                    self._helper.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
