"""Authenticated, loopback-only command bridge for the long-lived core host."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading

import httpx

from .host import FlClashHost, HostError

PORT = 47891
MAX_BODY = 8192

def state_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "FlClash-Control" / "daemon.json"

def save_state(path: Path, token: str) -> None:
    """Store a new bridge token encrypted for this Windows user with DPAPI."""
    import win32crypt
    path.parent.mkdir(parents=True, exist_ok=True)
    protected = win32crypt.CryptProtectData(token.encode(), "FlClash-Control", None, None, None, 0)[1]
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"port": PORT, "pid": os.getpid(), "protected_token": protected.hex()}), encoding="utf-8")
    temp.replace(path)

def load_token(path: Path) -> str:
    import win32crypt
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("port") != PORT:
        raise HostError("Unexpected local bridge port")
    return win32crypt.CryptUnprotectData(bytes.fromhex(state["protected_token"]), None, None, None, 0)[1].decode()

class BridgeClient:
    def __init__(self, path: Path | None = None):
        self.path = path or state_path()

    def call(self, command: str, args: dict | None = None) -> dict:
        try:
            token = load_token(self.path)
            with httpx.Client(trust_env=False, timeout=45, follow_redirects=False) as client:
                response = client.post(f"http://127.0.0.1:{PORT}/command", headers={"Authorization": f"Bearer {token}"}, json={"command": command, "args": args or {}})
            response.raise_for_status()
            data = response.json()
        except (OSError, KeyError, ValueError, httpx.HTTPError) as exc:
            raise HostError("Headless bridge is unavailable. Run flclash-control serve after exiting the GUI normally.") from exc
        if not data.get("ok"):
            raise HostError(data.get("error", "Headless command failed"))
        return data["data"]

def dispatch(host: FlClashHost, command: str, args: dict) -> dict:
    if command == "status":
        return host.status()
    if command == "start":
        return host.start()
    if command == "stop":
        return host.stop()
    if command == "restart":
        return host.restart()
    if command == "tun":
        return host.set_tun(args.get("enabled"))
    if command == "mode":
        return host.set_mode(args.get("mode"))
    if command == "release":
        host.close()
        return {"released": True}
    raise HostError("Unknown headless command")

def serve(core_path: str, home_dir: str | None = None, *, start: bool = False, selection_path: str | None = None) -> None:
    selected = json.loads(Path(selection_path).read_text(encoding="utf-8")) if selection_path else {}
    if not isinstance(selected, dict) or not all(isinstance(k, str) and isinstance(v, str) for k,v in selected.items()):
        raise HostError("Selection snapshot must contain string names only")
    host = FlClashHost(core_path, home_dir, selected_map=selected)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != "/command":
                self.send_error(404); return
            if not secrets.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
                self.send_error(403); return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > MAX_BODY:
                    self.send_error(413); return
                body = json.loads(self.rfile.read(size))
                command, args = body.get("command"), body.get("args", {})
                if not isinstance(command, str) or not isinstance(args, dict):
                    raise HostError("Invalid bridge request")
                result = {"ok": True, "data": dispatch(host, command, args)}
            except (HostError, ValueError, TypeError) as exc:
                result = {"ok": False, "error": str(exc)}
                command = None
            data = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data)
            if command == "release" and result["ok"]:
                threading.Thread(target=self.server.shutdown, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    path = state_path()
    try:
        host.connect(start=start)
        save_state(path, token)
        server.serve_forever(poll_interval=.25)
    finally:
        server.server_close()
        host.close()
        # Keep encrypted stale state for diagnostics; it cannot authenticate a new server.
