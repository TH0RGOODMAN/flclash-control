"""Headless native lifecycle CLI; independent of desktop mouse/keyboard."""
from __future__ import annotations
import argparse
import json
import sys
from .host import HostError
from .service import BridgeClient, serve

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    daemon = sub.add_parser("serve", help="Own the core until release; GUI must be normally exited")
    daemon.add_argument("--core", required=True, help="Installed FlClashCore.exe")
    daemon.add_argument("--home", help="Existing FlClash data directory")
    daemon.add_argument("--start", action="store_true")
    daemon.add_argument("--selection", help="Optional JSON snapshot of selector names")
    for name in ("status", "start", "stop", "restart", "release"):
        sub.add_parser(name)
    tun = sub.add_parser("tun"); tun.add_argument("state", choices=("on", "off"))
    mode = sub.add_parser("mode"); mode.add_argument("mode", choices=("rule", "global", "direct"))
    args = parser.parse_args()
    try:
        if args.command == "serve":
            serve(args.core, args.home, start=args.start, selection_path=args.selection)
        else:
            body = {"enabled": args.state == "on"} if args.command == "tun" else {"mode": args.mode} if args.command == "mode" else {}
            print(json.dumps(BridgeClient().call(args.command, body), ensure_ascii=False, indent=2))
        return 0
    except (HostError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
