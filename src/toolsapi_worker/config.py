from __future__ import annotations

import os
from dataclasses import dataclass


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
    temp_root: str

    @classmethod
    def from_environment(cls) -> "WorkerConfig":
        concurrency = max(1, int(os.getenv("TOOLS_WORKER_CONCURRENCY", "1")))
        poll_seconds = max(1.0, float(os.getenv("TOOLS_WORKER_POLL_SECONDS", "5")))
        heartbeat_seconds = max(5.0, float(os.getenv("TOOLS_WORKER_HEARTBEAT_SECONDS", "30")))
        handlers = tuple(
            handler.strip()
            for handler in os.getenv("TOOLS_WORKER_ENABLED_HANDLERS", "whisper.transcribe").split(",")
            if handler.strip()
        )
        models = tuple(
            model.strip().lower()
            for model in os.getenv("TOOLS_WORKER_WHISPER_MODELS", "small").split(",")
            if model.strip()
        )
        accepts_url_sources = os.getenv("TOOLS_WORKER_ACCEPTS_URL_SOURCES", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        return cls(
            api_base_url=os.getenv("TOOLS_API_BASE_URL", "").strip(),
            worker_token=os.getenv("TOOLS_WORKER_TOKEN", "").strip(),
            worker_id=os.getenv("TOOLS_WORKER_ID", "").strip(),
            concurrency=concurrency,
            poll_seconds=poll_seconds,
            heartbeat_seconds=heartbeat_seconds,
            enabled_handlers=handlers,
            whisper_models=models,
            whisper_device=os.getenv("TOOLS_WORKER_WHISPER_DEVICE", "cpu").strip().lower() or "cpu",
            whisper_compute_type=os.getenv("TOOLS_WORKER_WHISPER_COMPUTE_TYPE", "int8").strip() or "int8",
            accepts_url_sources=accepts_url_sources,
            temp_root=os.getenv("TOOLS_WORKER_TEMP_ROOT", "/tmp/toolsapi-worker").strip() or "/tmp/toolsapi-worker",
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
