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
    WorkerAuthenticationError,
    WorkerLeaseLostError,
)
from .config import WorkerConfig
from .diarization import PyannoteDiarizer


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
        self.interval_seconds = max(0.05, interval_seconds)
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


def validate_whisper_runtime_device(config: WorkerConfig, ctranslate2_module: Any | None = None) -> None:
    if config.whisper_device != "cuda":
        return

    module = ctranslate2_module
    if module is None:
        try:
            import ctranslate2 as module
        except (ImportError, ModuleNotFoundError) as exc:
            raise RuntimeError(
                "Configured CUDA Whisper runtime requires CTranslate2/faster-whisper to be installed."
            ) from exc

    try:
        device_count = int(module.get_cuda_device_count())
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Configured CUDA Whisper runtime could not query native CUDA devices.") from exc
    if device_count < 1:
        raise RuntimeError("Configured CUDA Whisper runtime is unavailable on this worker.")

    try:
        supported_compute_types = {
            str(value).strip().lower()
            for value in module.get_supported_compute_types("cuda")
            if str(value).strip()
        }
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Configured CUDA Whisper runtime could not query supported compute types.") from exc

    compute_type = config.whisper_compute_type.strip().lower()
    if compute_type not in {"", "auto", "default"} and compute_type not in supported_compute_types:
        raise RuntimeError(
            f"Configured CUDA Whisper compute type {config.whisper_compute_type!r} is unavailable on this worker."
        )


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
                progress = 20 + int(ratio * 73)
                detail = f"{end:.1f} / {duration:.1f} seconds"
            else:
                progress = min(93, 20 + len(segments))
                detail = f"{len(segments)} segments produced"
            heartbeat.update(progress, "Transcribing", detail)

        heartbeat.assert_owned()
        transcript_text = " ".join(part for part in transcript_parts if part).strip()
        if not transcript_text:
            raise RuntimeError("Whisper returned an empty transcript")

        processing_seconds = round(time.monotonic() - started, 3)
        heartbeat.update(94, "Transcription complete", "Transcript ready; preparing requested post-processing.")

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


class MlxWhisperHandler:
    MODEL_REPOSITORIES = {
        "tiny": "mlx-community/whisper-tiny-mlx",
        "base": "mlx-community/whisper-base-mlx",
        "small": "mlx-community/whisper-small-mlx",
        "medium": "mlx-community/whisper-medium-mlx",
        "large": "mlx-community/whisper-large-mlx",
        "large-v2": "mlx-community/whisper-large-v2-mlx",
        "large-v3": "mlx-community/whisper-large-v3-mlx",
        "turbo": "mlx-community/whisper-large-v3-turbo",
    }

    def __init__(
        self,
        config: WorkerConfig,
        transcribe_func: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.config = config
        self.transcribe_func = transcribe_func

    def transcribe(
        self,
        claim: WhisperClaim,
        input_path: Path,
        heartbeat: LeaseHeartbeat,
    ) -> WhisperResult:
        if claim.model not in self.config.whisper_models:
            raise RuntimeError(f"Unsupported Whisper model: {claim.model}")

        model_repository = self.MODEL_REPOSITORIES.get(claim.model)
        if model_repository is None:
            raise RuntimeError(f"No MLX model mapping for Whisper model: {claim.model}")

        heartbeat.update(15, "Loading Whisper model", f"Loading {claim.model} with MLX on Apple Silicon.")
        heartbeat.assert_owned()
        started = time.monotonic()
        heartbeat.update(20, "Transcribing", "MLX Whisper transcription started.")

        result = self._transcribe(
            str(input_path),
            path_or_hf_repo=model_repository,
            language=claim.language or None,
            verbose=False,
        )
        heartbeat.assert_owned()

        raw_segments = result.get("segments") or []
        segments: list[dict[str, Any]] = []
        for segment in raw_segments:
            if not isinstance(segment, dict):
                continue
            text = str(segment.get("text") or "").strip()
            start = float(segment.get("start") or 0.0)
            end = float(segment.get("end") or 0.0)
            if text and end > start:
                segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})

        transcript_text = str(result.get("text") or "").strip()
        if not transcript_text:
            transcript_text = " ".join(segment["text"] for segment in segments).strip()
        if not transcript_text:
            raise RuntimeError("Whisper returned an empty transcript")

        duration = max((float(segment["end"]) for segment in segments), default=0.0)
        processing_seconds = round(time.monotonic() - started, 3)
        heartbeat.update(94, "Transcription complete", "MLX transcript ready; preparing requested post-processing.")

        return WhisperResult(
            transcript_text=transcript_text,
            segments=segments,
            runtime={
                "engine": "mlx-whisper",
                "device": self.config.whisper_device,
                "compute_type": self.config.whisper_compute_type,
                "model": claim.model,
                "model_repository": model_repository,
                "duration_seconds": round(duration, 3) if duration > 0 else None,
                "processing_seconds": processing_seconds,
            },
        )

    def _transcribe(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if self.transcribe_func is not None:
            return self.transcribe_func(*args, **kwargs)

        import mlx_whisper

        return mlx_whisper.transcribe(*args, **kwargs)


def build_whisper_handler(config: WorkerConfig) -> FasterWhisperHandler | MlxWhisperHandler:
    if config.whisper_device in {"metal", "mlx", "mps"}:
        return MlxWhisperHandler(config)
    return FasterWhisperHandler(config)


class WorkerRuntime:
    def __init__(
        self,
        config: WorkerConfig,
        client: ToolsApiClient | None = None,
        handler: Any | None = None,
        diarizer: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.client = client or ToolsApiClient(
            config.api_base_url,
            config.worker_token,
            config.worker_id,
        )
        self.handler = handler or build_whisper_handler(config)
        self.diarizer = diarizer or PyannoteDiarizer(config)
        self.sleep = sleep

    def run_forever(self) -> None:
        self.config.validate_protocol_configuration()
        validate_whisper_runtime_device(self.config)
        if (
            self.config.diarization_enabled
            and self.config.diarization_device in {"cuda", "mps", "metal"}
            and not bool(getattr(self.diarizer, "supported", False))
        ):
            raise RuntimeError("Configured speaker diarization accelerator is unavailable on this worker.")

        while True:
            try:
                claim = self.client.claim_whisper(
                    models=self.config.whisper_models,
                    device=self.config.whisper_device,
                    compute_type=self.config.whisper_compute_type,
                    accepts_url_sources=self.config.accepts_url_sources,
                    supports_diarization=bool(getattr(self.diarizer, "supported", False)),
                )
            except WorkerAuthenticationError:
                raise
            except WorkerApiError:
                self.sleep(self.config.poll_seconds)
                continue

            if claim is None:
                self.sleep(self.config.poll_seconds)
                continue

            try:
                self.process_claim(claim)
            except WorkerLeaseLostError:
                continue

    def process_claim(self, claim: WhisperClaim) -> None:
        temp_root = Path(self.config.temp_root)
        temp_root.mkdir(parents=True, exist_ok=True)
        job_dir = Path(tempfile.mkdtemp(prefix=f"job-{claim.job_id}-", dir=temp_root))
        heartbeat = LeaseHeartbeat(self.client, claim, self.config.heartbeat_seconds)
        heartbeat.start()

        try:
            heartbeat.update(5, "Downloading input", "Fetching leased Whisper media from ToolsAPI.")
            input_path = self._prepare_input(claim, job_dir)
            heartbeat.assert_owned()

            result = self.handler.transcribe(claim, input_path, heartbeat)
            heartbeat.assert_owned()

            segments = result.segments
            diarization: dict[str, Any] = {
                "requested": False,
                "status": "skipped",
                "provider": self.config.diarization_provider,
                "reason": "not_requested",
            }
            if claim.diarization_requested:
                segments, diarization = self.diarizer.diarize(claim, input_path, segments, heartbeat)
                heartbeat.assert_owned()

            heartbeat.update(99, "Finalizing", "Submitting remote Whisper transcript and diarization result to ToolsAPI.")
            heartbeat.stop()
            self._retry_terminal(
                lambda: self.client.complete_whisper(
                    claim,
                    result.transcript_text,
                    segments,
                    result.runtime,
                    diarization,
                )
            )
        except WorkerLeaseLostError:
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
        finally:
            heartbeat.stop()
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
