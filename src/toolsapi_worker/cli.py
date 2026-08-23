import argparse
import sys

from . import __version__
from .config import WorkerConfig
from .runtime import WorkerRuntime


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
        config = WorkerConfig.from_environment()
        configured = bool(config.api_base_url and config.worker_token and config.worker_id)
        state = "configured" if configured else "installed, credentials pending"
        print(
            "toolsapi-worker: "
            f"{state}; device={config.whisper_device}; "
            f"compute={config.whisper_compute_type}; models={','.join(config.whisper_models)}"
        )
        return 0

    if args.command == "run":
        try:
            config = WorkerConfig.from_environment()
            config.validate_protocol_configuration()
            WorkerRuntime(config).run_forever()
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"toolsapi-worker: {exc}", file=sys.stderr)
            return 2
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
