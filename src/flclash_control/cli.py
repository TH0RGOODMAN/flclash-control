"""Control the running FlClash GUI without taking desktop input."""
from __future__ import annotations
import argparse
import json
import sys
from .client import ControlClient, ControlError

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", help="Optional local bridge authorization file")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "start", "stop", "restart", "show", "exit"):
        sub.add_parser(name)
    for name in ("tun", "system-proxy"):
        item = sub.add_parser(name); item.add_argument("state", choices=("on", "off"))
    mode = sub.add_parser("mode"); mode.add_argument("mode", choices=("rule", "global", "direct"))
    args = parser.parse_args()
    params = {"enabled": args.state == "on"} if args.command in {"tun", "system-proxy"} else {"mode": args.mode} if args.command == "mode" else {}
    try:
        result = ControlClient(args.token_file).call(args.command, params)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ControlError as exc:
        print(str(exc), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
