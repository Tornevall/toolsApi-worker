import argparse
import sys
import time

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="toolsapi-worker")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="Start the worker polling loop")
    sub.add_parser("status", help="Print local worker status")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        print("toolsapi-worker: bootstrap runtime installed")
        return 0

    if args.command == "run":
        print("toolsapi-worker: polling runtime not implemented yet", file=sys.stderr)
        return 2

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
