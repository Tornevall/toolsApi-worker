from __future__ import annotations

import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .api import (
    ToolsApiClient,
    WhisperClaim,
    WorkerApiError,
    WorkerLeaseLostError,
)
from .config import WorkerConfig


@dataclass
class HeartbeatState:
    progress_percent: int = 1
    stage_label: str = "Remote worker"
    stage_detail: str = "Preparing Whisper job."


class LeaseHeartbeat:
    def __init__(
        self,
        client: ToolsApiClient,
        claim: WhisperClaim,
        interval_seconds: float,
    ) -> None:
        self.client = client
        self.claim = claim
        self.interval_seconds = max(5.0, interval_seconds)
        self.state = HeartbeatState()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._lease_lost = threading.Event()
        self._last_error: WorkerApiError | None = None
        self._thread = threading.Thread(target=self._run, name=f"whisper-heartbeat-{claim.job_id}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def update(self, progress_percent: int, stage_label: str, stage_detail: str) -> None:
        with self._lock:
            self.state.progress_percent = max(1, min(99, int(progress_percent)))
            self.state.stage_label = stage_label
            self.state.stage_detail = stage_detail

    def assert_owned(self) -> None:
        if self._lease_lost.is_set():
            raise WorkerLeaseLostError("ToolsAPI no longer accepts this Whisper lease") from self._last_error

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self.interval_seconds + 1)

    def _snapshot(self) -> HeartbeatState:
        with self._lock:
            return HeartbeatState(
                progress_percent=self.state.progress_percent,
                stage_label=self.state.stage_label,
                stage_detail=self.state.stage_detail,
            )

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            state = self._snapshot()
            try:
                self.client.report_whisper_progress(
                    self.claim,
                    state.progress_percent,
                    state.stage_label,
                    state.stage_detail,
                )
            except WorkerLeaseLostError as exc:
                self._last_error = exc
                self._lease_lost.set()
                return
            except WorkerApiError as exc:
                self._last_error = exc
                continue


@dataclass(frozen=True)
class WhisperResult:
    transcript_text: str
    segments: list[dict[str, Any]]
    runtime: dict[str, Any]


class FasterWhisperHandler:
    def __init__(
        self,
        config: WorkerConfig,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self.model_factory = model_factory

    def transcribe(
        self,
        claim: WhisperClaim,
        input_path: Path,
        heartbeat: LeaseHeartbeat,
    ) -> WhisperResult:
        if claim.model not in self.config.whisper_models:
            raise RuntimeError(f"Unsupported Whisper model: {claim.model}")

        heartbeat.update(15, "Loading Whisper model", f"Loading {claim.model} on {self.config.whisper_device}.")
        heartbeat.assert_owned()
        model = self._create_model(claim.model)

        started = time.monotonic()
        heartbeat.update(20, "Transcribing", "Whisper model loaded; transcription started.")
        segments_iter, info = model.transcribe(
            str(input_path),
            language=claim.language or None,
            vad_filter=True,
        )

        duration = float(getattr(info, "duration", 0.0) or 0.0)
        segments: list[dict[str, Any]] = []
        transcript_parts: list[str] = []

        for segment in segments_iter:
            heartbeat.assert_owned()
            text = str(getattr(segment, "text", "") or "").strip()
            start = float(getattr(segment, "start", 0.0) or 0.0)
            end = float(getattr(segment, "end", 0.0) or 0.0)
            if text and end > start:
                segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
                transcript_parts.append(text)

            if duration > 0:
                ratio = min(1.0, max(0.0, end / duration))
                progress = 20 + int(ratio * 74)
                detail = f"{end:.1f} / {duration:.1f} seconds"
            else:
                progress = min(94, 20 + len(segments))
                detail = f"{len(segments)} segments produced"
            heartbeat.update(progress, "Transcribing", detail)

        heartbeat.assert_owned()
        transcript_text = " ".join(part for part in transcript_parts if part).strip()
        if not transcript_text:
            raise RuntimeError("Whisper returned an empty transcript")

        processing_seconds = round(time.monotonic() - started, 3)
        heartbeat.update(97, "Finalizing", "Submitting remote Whisper transcript to ToolsAPI.")

        return WhisperResult(
            transcript_text=transcript_text,
            segments=segments,
            runtime={
                "engine": "faster-whisper",
                "device": self.config.whisper_device,
                "compute_type": self.config.whisper_compute_type,
                "model": claim.model,
                "duration_seconds": round(duration, 3) if duration > 0 else None,
                "processing_seconds": processing_seconds,
            },
        )

    def _create_model(self, model_name: str) -> Any:
        if self.model_factory is not None:
            return self.model_factory(
                model_name,
                device=self.config.whisper_device,
                compute_type=self.config.whisper_compute_type,
            )

        from faster_whisper import WhisperModel

        return WhisperModel(
            model_name,
            device=self.config.whisper_device,
            compute_type=self.config.whisper_compute_type,
        )


class WorkerRuntime:
    def __init__(
        self,
        config: WorkerConfig,
        client: ToolsApiClient | None = None,
        handler: FasterWhisperHandler | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.client = client or ToolsApiClient(
            config.api_base_url,
            config.worker_token,
            config.worker_id,
        )
        self.handler = handler or FasterWhisperHandler(config)
        self.sleep = sleep

    def run_forever(self) -> None:
        self.config.validate_protocol_configuration()
        while True:
            claim = self.client.claim_whisper(
                models=self.config.whisper_models,
                device=self.config.whisper_device,
                compute_type=self.config.whisper_compute_type,
                accepts_url_sources=self.config.accepts_url_sources,
            )
            if claim is None:
                self.sleep(self.config.poll_seconds)
                continue
            self.process_claim(claim)

    def process_claim(self, claim: WhisperClaim) -> None:
        temp_root = Path(self.config.temp_root)
        temp_root.mkdir(parents=True, exist_ok=True)
        job_dir = Path(tempfile.mkdtemp(prefix=f"job-{claim.job_id}-", dir=temp_root))
        heartbeat = LeaseHeartbeat(self.client, claim, self.config.heartbeat_seconds)
        terminal_acknowledged = False
        heartbeat.start()

        try:
            heartbeat.update(5, "Downloading input", "Fetching leased Whisper media from ToolsAPI.")
            input_path = self._prepare_input(claim, job_dir)
            heartbeat.assert_owned()

            result = self.handler.transcribe(claim, input_path, heartbeat)
            heartbeat.assert_owned()
            heartbeat.stop()
            self._retry_terminal(
                lambda: self.client.complete_whisper(
                    claim,
                    result.transcript_text,
                    result.segments,
                    result.runtime,
                )
            )
            terminal_acknowledged = True
        except WorkerLeaseLostError:
            terminal_acknowledged = True
            raise
        except Exception as exc:
            heartbeat.stop()
            self._retry_terminal(
                lambda: self.client.fail_whisper(
                    claim,
                    "transcription_failed",
                    self._safe_error_message(exc),
                    retryable=True,
                )
            )
            terminal_acknowledged = True
        finally:
            heartbeat.stop()
            if terminal_acknowledged:
                shutil.rmtree(job_dir, ignore_errors=True)

    def _prepare_input(self, claim: WhisperClaim, job_dir: Path) -> Path:
        if claim.input_type == "tools_media":
            return self.client.download_whisper_media(claim, job_dir / "input-media")
        raise RuntimeError("URL-source execution is disabled on this worker")

    def _retry_terminal(self, submit: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        while True:
            try:
                return submit()
            except WorkerLeaseLostError:
                raise
            except WorkerApiError:
                self.sleep(self.config.poll_seconds)

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        text = str(exc).strip() or exc.__class__.__name__
        return text[:1000]
