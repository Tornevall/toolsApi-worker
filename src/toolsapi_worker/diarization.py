from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from typing import Any, Callable

from .api import WhisperClaim, WorkerLeaseLostError
from .config import WorkerConfig


class PyannoteDiarizer:
    def __init__(
        self,
        config: WorkerConfig,
        pipeline_factory: Callable[..., Any] | None = None,
        torch_module: Any | None = None,
    ) -> None:
        self.config = config
        self.pipeline_factory = pipeline_factory
        self.torch_module = torch_module

    @property
    def supported(self) -> bool:
        if not self.config.diarization_enabled or self.config.diarization_provider != "pyannote":
            return False
        if self.pipeline_factory is not None:
            return True
        return self._runtime_dependencies_available()

    def diarize(
        self,
        claim: WhisperClaim,
        input_path: Path,
        segments: list[dict[str, Any]],
        heartbeat: Any,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not claim.diarization_requested:
            return segments, {
                "requested": False,
                "status": "skipped",
                "provider": self.config.diarization_provider,
                "reason": "not_requested",
            }

        if not self.supported:
            error_code = "disabled"
            error_message = "Speaker diarization is disabled on this worker."
            if self.config.diarization_enabled and self.config.diarization_provider != "pyannote":
                error_code = "unsupported_provider"
                error_message = "Speaker diarization provider is unsupported on this worker."
            elif self.config.diarization_enabled:
                error_code = "missing_dependency"
                error_message = "Speaker diarization dependencies are missing on this worker."
            return segments, {
                "requested": True,
                "status": "unavailable",
                "provider": self.config.diarization_provider,
                "error_code": error_code,
                "error_message": error_message,
                "hf_token_present": bool(self.config.diarization_hf_token),
            }

        heartbeat.update(95, "Speaker diarization", "Loading pyannote speaker diarization model.")
        heartbeat.assert_owned()

        try:
            pipeline = self._create_pipeline()
            heartbeat.assert_owned()
            heartbeat.update(96, "Speaker diarization", "Detecting speaker turns.")

            kwargs: dict[str, Any] = {}
            if self.config.diarization_min_speakers is not None:
                kwargs["min_speakers"] = self.config.diarization_min_speakers
            if self.config.diarization_max_speakers is not None:
                kwargs["max_speakers"] = self.config.diarization_max_speakers

            output = pipeline(str(input_path), **kwargs)
            heartbeat.assert_owned()
            annotation = getattr(output, "speaker_diarization", output)
            if not hasattr(annotation, "itertracks"):
                raise RuntimeError("Speaker diarization returned an unsupported result shape.")

            turns: list[dict[str, Any]] = []
            labels: set[str] = set()
            for turn, _, speaker in annotation.itertracks(yield_label=True):
                heartbeat.assert_owned()
                label = str(speaker or "").strip()
                start = float(getattr(turn, "start", 0.0) or 0.0)
                end = float(getattr(turn, "end", 0.0) or 0.0)
                if not label or end <= start:
                    continue
                turns.append({"start": round(start, 3), "end": round(end, 3), "speaker": label})
                labels.add(label)

            if not turns:
                raise RuntimeError("Speaker diarization returned no speaker turns for this audio.")

            labelled_segments = self._map_speakers(segments, turns)
            labelled_count = sum(1 for segment in labelled_segments if segment.get("speaker_label"))
            heartbeat.update(99, "Speaker diarization", f"Detected {len(labels)} speaker(s).")

            return labelled_segments, {
                "requested": True,
                "status": "completed",
                "provider": "pyannote",
                "model": self.config.diarization_model,
                "speaker_turns": turns,
                "speaker_labels": sorted(labels),
                "speaker_count": len(labels),
                "labelled_segment_count": labelled_count,
                "hf_token_present": bool(self.config.diarization_hf_token),
                "device": self._resolved_device(),
            }
        except WorkerLeaseLostError:
            raise
        except Exception as exc:  # noqa: BLE001
            error_code, error_message = self._normalize_error(exc)
            status = "unavailable" if error_code in {"missing_dependency", "unsupported_provider"} else "failed"
            heartbeat.update(99, "Speaker diarization", error_message)
            return segments, {
                "requested": True,
                "status": status,
                "provider": "pyannote",
                "model": self.config.diarization_model,
                "error_code": error_code,
                "error_message": error_message,
                "speaker_turns": [],
                "speaker_labels": [],
                "speaker_count": 0,
                "labelled_segment_count": 0,
                "hf_token_present": bool(self.config.diarization_hf_token),
            }

    def _create_pipeline(self) -> Any:
        if self.pipeline_factory is not None:
            pipeline = self.pipeline_factory(
                self._model_source(),
                token=self.config.diarization_hf_token or None,
            )
            return self._move_pipeline(pipeline)

        try:
            from pyannote.audio import Pipeline
        except (ImportError, ModuleNotFoundError) as exc:
            raise RuntimeError("Speaker diarization dependencies are missing on this worker.") from exc

        source = self._model_source()
        token = self.config.diarization_hf_token or None
        if Path(source).exists():
            pipeline = Pipeline.from_pretrained(source)
        elif token is None:
            pipeline = Pipeline.from_pretrained(source)
        else:
            pipeline = self._from_pretrained_with_token(Pipeline, source, token)
        return self._move_pipeline(pipeline)

    def _model_source(self) -> str:
        configured = self.config.diarization_model_dir.strip()
        if configured:
            model_dir = Path(configured).expanduser()
            if not model_dir.is_dir():
                raise RuntimeError("Configured speaker diarization model directory does not exist.")
            return str(model_dir)
        return self.config.diarization_model

    @staticmethod
    def _from_pretrained_with_token(pipeline_class: Any, source: str, token: str) -> Any:
        try:
            parameters = inspect.signature(pipeline_class.from_pretrained).parameters
        except (TypeError, ValueError):
            parameters = {}

        if "token" in parameters:
            return pipeline_class.from_pretrained(source, token=token)
        if "use_auth_token" in parameters:
            return pipeline_class.from_pretrained(source, use_auth_token=token)

        try:
            return pipeline_class.from_pretrained(source, token=token)
        except TypeError:
            return pipeline_class.from_pretrained(source, use_auth_token=token)

    def _resolved_device(self) -> str:
        configured = self.config.diarization_device
        if configured != "auto":
            return configured

        torch = self._torch()
        cuda = getattr(torch, "cuda", None)
        if cuda is not None and bool(getattr(cuda, "is_available", lambda: False)()):
            return "cuda"

        backends = getattr(torch, "backends", None)
        mps = getattr(backends, "mps", None) if backends is not None else None
        if mps is not None and bool(getattr(mps, "is_available", lambda: False)()):
            return "mps"

        return "cpu"

    def _move_pipeline(self, pipeline: Any) -> Any:
        device = self._resolved_device()
        if device == "cpu":
            return pipeline

        torch = self._torch()
        if device == "cuda" and not bool(getattr(getattr(torch, "cuda", None), "is_available", lambda: False)()):
            raise RuntimeError("CUDA diarization was requested but CUDA is unavailable on this worker.")
        if device in {"mps", "metal"}:
            backends = getattr(torch, "backends", None)
            mps = getattr(backends, "mps", None) if backends is not None else None
            if mps is None or not bool(getattr(mps, "is_available", lambda: False)()):
                raise RuntimeError("MPS diarization was requested but Apple GPU acceleration is unavailable on this worker.")
            device = "mps"
        if hasattr(pipeline, "to"):
            pipeline.to(torch.device(device))
        return pipeline

    def _torch(self) -> Any:
        if self.torch_module is not None:
            return self.torch_module
        try:
            import torch
        except (ImportError, ModuleNotFoundError) as exc:
            raise RuntimeError("Speaker diarization dependencies are missing on this worker.") from exc
        return torch

    def _runtime_dependencies_available(self) -> bool:
        return self._module_available("pyannote.audio") and self._module_available("torch")

    @staticmethod
    def _module_available(name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    @staticmethod
    def _map_speakers(
        segments: list[dict[str, Any]],
        turns: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        mapped: list[dict[str, Any]] = []
        for segment in segments:
            normalized = dict(segment)
            start = float(segment.get("start") or 0.0)
            end = float(segment.get("end") or 0.0)
            best_overlap = 0.0
            best_label: str | None = None
            for turn in turns:
                turn_start = float(turn.get("start") or 0.0)
                turn_end = float(turn.get("end") or 0.0)
                overlap = max(0.0, min(end, turn_end) - max(start, turn_start))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_label = str(turn.get("speaker") or "").strip() or None
            normalized["speaker_label"] = best_label
            mapped.append(normalized)
        return mapped

    def _normalize_error(self, exc: Exception) -> tuple[str, str]:
        text = str(exc).strip()
        lowered = text.lower()

        if "dependencies are missing" in lowered or "no module named" in lowered or "modulenotfounderror" in lowered:
            return "missing_dependency", "Speaker diarization dependencies are missing on this worker."
        if "no speaker turns" in lowered:
            return "empty_result", "Speaker diarization returned no speaker turns for this audio."
        if "unsupported result shape" in lowered:
            return "unsupported_result", "Speaker diarization returned an unsupported result shape."
        if "model directory does not exist" in lowered:
            return "missing_model", "Configured speaker diarization model directory does not exist."
        if "cuda" in lowered and "unavailable" in lowered:
            return "device_unavailable", "Requested CUDA diarization is unavailable on this worker."
        if ("mps" in lowered or "apple gpu" in lowered) and "unavailable" in lowered:
            return "device_unavailable", "Requested Apple GPU diarization is unavailable on this worker."
        if any(value in lowered for value in ["timed out", "timeout", "connection error", "network is unreachable", "local cache"]):
            return "model_network_unavailable", "Speaker diarization model is not available locally and could not be fetched."
        if any(value in lowered for value in ["401", "403", "gated repo", "access denied", "accept the conditions"]):
            if not self.config.diarization_hf_token:
                return "missing_token", "Speaker diarization requires a Hugging Face token on this worker."
            return "model_access_denied", "Speaker diarization could not access the configured pyannote model."
        if "token" in lowered and not self.config.diarization_hf_token:
            return "missing_token", "Speaker diarization requires a Hugging Face token on this worker."

        return "process_failed", "Speaker diarization failed on this worker."
