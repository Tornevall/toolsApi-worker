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

        return cls(
            api_base_url=os.getenv("TOOLS_API_BASE_URL", "").strip(),
            worker_token=os.getenv("TOOLS_WORKER_TOKEN", "").strip(),
            worker_id=os.getenv("TOOLS_WORKER_ID", "").strip(),
            concurrency=concurrency,
            poll_seconds=poll_seconds,
            heartbeat_seconds=heartbeat_seconds,
            enabled_handlers=handlers,
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
