"""Control the running FlClash GUI without taking desktop input."""
from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import sys

from . import __version__
from .client import ControlClient, ControlError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flclash-control", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--token-file", help="Optional local bridge authorization file")
    parser.add_argument("--timeout", type=float, default=None, help="Request timeout in seconds (default: 45)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "health", "doctor", "start", "stop", "restart", "show"):
        sub.add_parser(name)
    exit_parser = sub.add_parser("exit")
    exit_parser.add_argument("--wait", action="store_true", help="Wait for the GUI bridge to close after scheduling exit")
    exit_parser.add_argument("--wait-timeout", type=float, default=10.0, help="Maximum seconds to wait with --wait")
    for name in ("tun", "system-proxy"):
        item = sub.add_parser(name)
        item.add_argument("state", choices=("on", "off"))
    mode = sub.add_parser("mode")
    mode.add_argument("mode", choices=("rule", "global", "direct"))
    args = parser.parse_args(argv)

    try:
        client = ControlClient(args.token_file, timeout=args.timeout)
        if args.command == "health":
            result = client.health()
        elif args.command == "doctor":
            result = client.doctor()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("ok") is True else 1
        elif args.command == "exit" and args.wait:
            result = client.exit_and_wait(wait_timeout=args.wait_timeout)
        else:
            params = (
                {"enabled": args.state == "on"}
                if args.command in {"tun", "system-proxy"}
                else {"mode": args.mode}
                if args.command == "mode"
                else {}
            )
            result = client.call(args.command, params)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ControlError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
