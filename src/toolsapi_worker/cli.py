import argparse
import json
import sys

from . import __version__
from .dry_run import run_dry_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="toolsapi-worker")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="Start the worker polling loop")
    sub.add_parser("status", help="Print local worker status")
    dry_run = sub.add_parser("dry-run", help="Simulate poll/claim/lease/heartbeat/failover without network or GPU work")
    dry_run.add_argument("--json", action="store_true", dest="as_json", help="Print machine-readable result")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        print("toolsapi-worker: bootstrap runtime installed")
        return 0

    if args.command == "dry-run":
        result = run_dry_run()
        if args.as_json:
            print(json.dumps(result, sort_keys=True))
        else:
            for name, ok in result["checks"].items():
                print(f"{name}: {'ok' if ok else 'failed'}")
            print(f"dry-run: {'ok' if result['ok'] else 'failed'}")
        return 0 if result["ok"] else 1

    if args.command == "run":
        print("toolsapi-worker: polling runtime not implemented yet", file=sys.stderr)
        return 2

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
