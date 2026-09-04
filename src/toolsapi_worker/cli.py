import argparse
import sys
from contextlib import contextmanager
from datetime import datetime
from typing import Callable, TextIO

from . import __version__
from .config import WorkerConfig
from .diagnostics import DiarizationDiagnostic
from .runtime import WorkerRuntime


def _local_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class TimestampedTextStream:
    def __init__(self, stream: TextIO, timestamp_factory: Callable[[], str] | None = None) -> None:
        self._stream = stream
        self._timestamp_factory = timestamp_factory or _local_timestamp
        self._line_start = True

    def write(self, text: str) -> int:
        if not text:
            return 0

        for part in text.splitlines(keepends=True):
            is_blank_line = part in {"\n", "\r", "\r\n"}
            if self._line_start and not is_blank_line:
                self._stream.write(f"[{self._timestamp_factory()}] ")

            self._stream.write(part)
            self._line_start = part.endswith(("\n", "\r"))

        return len(text)

    def flush(self) -> None:
        self._stream.flush()

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


@contextmanager
def _timestamp_runtime_streams():
    stdout = sys.stdout
    stderr = sys.stderr
    wrapped_stdout = TimestampedTextStream(stdout)
    wrapped_stderr = TimestampedTextStream(stderr)
    sys.stdout = wrapped_stdout
    sys.stderr = wrapped_stderr
    try:
        yield
    finally:
        wrapped_stdout.flush()
        wrapped_stderr.flush()
        sys.stdout = stdout
        sys.stderr = stderr


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="toolsapi-worker")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="Start the worker polling loop")
    run_parser.add_argument("--env-file", help="Load worker configuration from an env file without shell evaluation")

    status_parser = sub.add_parser("status", help="Print local worker status")
    status_parser.add_argument("--env-file", help="Load worker configuration from an env file without shell evaluation")

    diagnose_parser = sub.add_parser("diagnose", help="Run local worker diagnostics without claiming live work")
    diagnostics = diagnose_parser.add_subparsers(dest="diagnostic")
    diarization_parser = diagnostics.add_parser("diarization", help="Validate the local pyannote diarization runtime")
    diarization_parser.add_argument(
        "--env-file",
        help="Load worker configuration from an env file without shell evaluation",
    )
    diarization_parser.add_argument(
        "--audio",
        help="Optional local audio file to run through the configured diarization pipeline",
    )
    return parser


def load_config(env_file: str | None) -> WorkerConfig:
    if env_file:
        return WorkerConfig.from_env_file(env_file)
    return WorkerConfig.from_environment()


def _print_diarization_report(report: dict[str, object]) -> None:
    print("toolsapi-worker diarization diagnostic")
    ordered_fields = (
        "status",
        "enabled",
        "provider",
        "model",
        "model_dir_configured",
        "hf_token_present",
        "configured_device",
        "resolved_device",
        "supported",
        "pipeline_loaded",
        "audio_checked",
        "speaker_turns",
        "speaker_count",
        "error_code",
        "error_message",
        "exception_type",
        "exception_message",
    )
    for key in ordered_fields:
        if key in report and report[key] is not None:
            print(f"{key}: {report[key]}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        config = load_config(args.env_file)
        configured = bool(config.api_base_url and config.worker_token and config.worker_id)
        state = "configured" if configured else "installed, credentials pending"
        print(
            "toolsapi-worker: "
            f"{state}; device={config.whisper_device}; "
            f"compute={config.whisper_compute_type}; models={','.join(config.whisper_models)}"
        )
        return 0

    if args.command == "diagnose":
        if args.diagnostic != "diarization":
            parser.print_help()
            return 0

        try:
            config = load_config(args.env_file)
            report = DiarizationDiagnostic(config).run(args.audio)
        except Exception as exc:  # noqa: BLE001
            print(f"toolsapi-worker: diarization diagnostic could not start: {exc}", file=sys.stderr)
            return 2

        _print_diarization_report(report)
        return 0 if report.get("status") in {"ready", "completed"} else 2

    if args.command == "run":
        with _timestamp_runtime_streams():
            try:
                config = load_config(args.env_file)
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
