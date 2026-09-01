from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def read_env_file(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = Path(path).expanduser()
    for line_number, raw_line in enumerate(env_path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()

        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not _ENV_KEY.fullmatch(key):
            raise ValueError(f"Invalid environment entry at {env_path}:{line_number}")

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value

    return values


def _optional_positive_int(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    parsed = int(text)
    return parsed if parsed > 0 else None


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class WorkerConfig:
    api_base_url: str
    worker_token: str
    worker_id: str
    concurrency: int
    poll_seconds: float
    heartbeat_seconds: float
    enabled_handlers: tuple[str, ...]
    whisper_models: tuple[str, ...]
    whisper_device: str
    whisper_compute_type: str
    accepts_url_sources: bool
    diarization_enabled: bool
    diarization_provider: str
    diarization_hf_token: str
    diarization_model: str
    diarization_model_dir: str
    diarization_min_speakers: int | None
    diarization_max_speakers: int | None
    diarization_device: str
    temp_root: str

    @classmethod
    def from_environment(cls) -> "WorkerConfig":
        return cls.from_mapping(os.environ)

    @classmethod
    def from_env_file(cls, path: str | Path) -> "WorkerConfig":
        values = read_env_file(path)
        values.update(os.environ)
        return cls.from_mapping(values)

    @classmethod
    def from_mapping(cls, environment: Mapping[str, str]) -> "WorkerConfig":
        def env(name: str, default: str = "") -> str:
            return str(environment.get(name, default))

        concurrency = max(1, int(env("TOOLS_WORKER_CONCURRENCY", "1")))
        poll_seconds = max(1.0, float(env("TOOLS_WORKER_POLL_SECONDS", "60")))
        heartbeat_seconds = max(5.0, float(env("TOOLS_WORKER_HEARTBEAT_SECONDS", "30")))
        handlers = tuple(
            handler.strip()
            for handler in env("TOOLS_WORKER_ENABLED_HANDLERS", "whisper.transcribe").split(",")
            if handler.strip()
        )
        models = tuple(
            model.strip().lower()
            for model in env("TOOLS_WORKER_WHISPER_MODELS", "small").split(",")
            if model.strip()
        )
        accepts_url_sources = _truthy(env("TOOLS_WORKER_ACCEPTS_URL_SOURCES", "false"))
        diarization_enabled = _truthy(env("TOOLS_WORKER_DIARIZATION_ENABLED", "true"))
        temp_root_default = str(Path(tempfile.gettempdir()) / "toolsapi-worker")

        return cls(
            api_base_url=env("TOOLS_API_BASE_URL").strip(),
            worker_token=env("TOOLS_WORKER_TOKEN").strip(),
            worker_id=env("TOOLS_WORKER_ID").strip(),
            concurrency=concurrency,
            poll_seconds=poll_seconds,
            heartbeat_seconds=heartbeat_seconds,
            enabled_handlers=handlers,
            whisper_models=models,
            whisper_device=env("TOOLS_WORKER_WHISPER_DEVICE", "cpu").strip().lower() or "cpu",
            whisper_compute_type=env("TOOLS_WORKER_WHISPER_COMPUTE_TYPE", "int8").strip() or "int8",
            accepts_url_sources=accepts_url_sources,
            diarization_enabled=diarization_enabled,
            diarization_provider=env("TOOLS_WORKER_DIARIZATION_PROVIDER", "pyannote").strip().lower() or "pyannote",
            diarization_hf_token=env("TOOLS_WORKER_DIARIZATION_HF_TOKEN").strip(),
            diarization_model=env(
                "TOOLS_WORKER_DIARIZATION_MODEL",
                "pyannote/speaker-diarization-community-1",
            ).strip() or "pyannote/speaker-diarization-community-1",
            diarization_model_dir=env("TOOLS_WORKER_DIARIZATION_MODEL_DIR").strip(),
            diarization_min_speakers=_optional_positive_int(env("TOOLS_WORKER_DIARIZATION_MIN_SPEAKERS")),
            diarization_max_speakers=_optional_positive_int(env("TOOLS_WORKER_DIARIZATION_MAX_SPEAKERS")),
            diarization_device=env("TOOLS_WORKER_DIARIZATION_DEVICE", "auto").strip().lower() or "auto",
            temp_root=env("TOOLS_WORKER_TEMP_ROOT", temp_root_default).strip() or temp_root_default,
        )

    def validate_protocol_configuration(self) -> None:
        missing = []
        if not self.api_base_url:
            missing.append("TOOLS_API_BASE_URL")
        if not self.worker_token:
            missing.append("TOOLS_WORKER_TOKEN")
        if not self.worker_id:
            missing.append("TOOLS_WORKER_ID")
        if missing:
            raise ValueError("Missing worker configuration: " + ", ".join(missing))

        if "whisper.transcribe" in self.enabled_handlers and not self.whisper_models:
            raise ValueError("TOOLS_WORKER_WHISPER_MODELS must contain at least one model")

        if self.concurrency != 1:
            raise ValueError("TOOLS_WORKER_CONCURRENCY must remain 1 until parallel runtime support is implemented")

        if self.diarization_provider != "pyannote":
            raise ValueError("TOOLS_WORKER_DIARIZATION_PROVIDER must currently be pyannote")

        if (
            self.diarization_min_speakers is not None
            and self.diarization_max_speakers is not None
            and self.diarization_min_speakers > self.diarization_max_speakers
        ):
            raise ValueError("TOOLS_WORKER_DIARIZATION_MIN_SPEAKERS cannot exceed TOOLS_WORKER_DIARIZATION_MAX_SPEAKERS")
