"""Authenticated client for the control bridge hosted by the running GUI."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any

import httpx

PORT = 47892
MAX_RESPONSE = 128 * 1024

class ControlError(RuntimeError):
    pass

def default_token_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "FlClash-Control" / "gui-bridge.json"

class ControlClient:
    def __init__(self, token_path: Path | str | None = None, *, timeout: float = 45.0, transport=None):
        self.token_path = Path(token_path) if token_path is not None else default_token_path()
        self.timeout = timeout
        self.transport = transport

    def _token(self) -> str:
        try:
            data = json.loads(self.token_path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or not isinstance(data.get("protected_token"), str):
                raise ValueError("Invalid bridge state")
            if data.get("protocol") != 1 or data.get("port") != PORT:
                raise ValueError("Invalid bridge state")
            import win32crypt
            token = win32crypt.CryptUnprotectData(bytes.fromhex(data["protected_token"]), None, None, None, 0)[1].decode()
            if len(token) < 32:
                raise ValueError("Invalid bridge authorization")
            return token
        except Exception as exc:
            raise ControlError("FlClash control bridge is unavailable. Start the bridge-enabled FlClash build.") from exc

    def call(self, action: str, params: dict[str, Any] | None = None) -> dict:
        token = self._token()
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{PORT}", timeout=self.timeout,
                              trust_env=False, follow_redirects=False, transport=self.transport) as client:
                response = client.post("/command", headers={"Authorization": f"Bearer {token}"},
                                       json={"action": "system_proxy" if action == "system-proxy" else action, "params": params or {}})
            if response.status_code == 401 or response.status_code == 403:
                raise ControlError("FlClash bridge authorization failed; retry after the GUI has finished starting.")
            if response.status_code < 200 or response.status_code >= 300:
                raise ControlError(f"FlClash bridge rejected the command (HTTP {response.status_code}).")
            if len(response.content) > MAX_RESPONSE:
                raise ControlError("Unexpectedly large control response")
            data = response.json()
        except httpx.TimeoutException as exc:
            raise ControlError("FlClash command outcome is unknown after timeout. Check status before retrying; native authorization may still be pending.") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ControlError("Cannot reach the running FlClash control bridge.") from exc
        if not isinstance(data, dict) or data.get("ok") is not True or not isinstance(data.get("data"), dict):
            raise ControlError("FlClash did not complete the requested control action.")
        return data["data"]
