from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import WorkerConfig
from .diarization import PyannoteDiarizer


class DiarizationDiagnostic:
    """Run local pyannote checks without polling ToolsAPI or claiming a lease."""

    def __init__(self, config: WorkerConfig, diarizer: PyannoteDiarizer | None = None) -> None:
        self.config = config
        self.diarizer = diarizer or PyannoteDiarizer(config)

    def run(self, audio_path: str | None = None) -> dict[str, Any]:
        report: dict[str, Any] = {
            "status": "checking",
            "enabled": self.config.diarization_enabled,
            "provider": self.config.diarization_provider,
            "model": self.config.diarization_model,
            "model_dir_configured": bool(self.config.diarization_model_dir.strip()),
            "hf_token_present": bool(self.config.diarization_hf_token),
            "configured_device": self.config.diarization_device,
            "supported": bool(self.diarizer.supported),
            "pipeline_loaded": False,
            "audio_checked": False,
        }

        if not report["supported"]:
            error_code, error_message = self.diarizer._support_failure()
            report.update(
                {
                    "status": "unavailable",
                    "error_code": error_code,
                    "error_message": error_message,
                }
            )
            return report

        try:
            report["resolved_device"] = self.diarizer._resolved_device()
            pipeline = self.diarizer._create_pipeline()
            report["pipeline_loaded"] = True

            if not audio_path:
                report["status"] = "ready"
                return report

            media = Path(audio_path).expanduser()
            if not media.is_file():
                raise FileNotFoundError(f"Local diagnostic audio file does not exist: {media}")

            output = pipeline(str(media))
            annotation = getattr(output, "speaker_diarization", output)
            if not hasattr(annotation, "itertracks"):
                raise RuntimeError("Speaker diarization returned an unsupported result shape.")

            turn_count = 0
            speakers: set[str] = set()
            for turn, _, speaker in annotation.itertracks(yield_label=True):
                label = str(speaker or "").strip()
                start = float(getattr(turn, "start", 0.0) or 0.0)
                end = float(getattr(turn, "end", 0.0) or 0.0)
                if not label or end <= start:
                    continue
                turn_count += 1
                speakers.add(label)

            if turn_count == 0:
                raise RuntimeError("Speaker diarization returned no speaker turns for this audio.")

            report.update(
                {
                    "status": "completed",
                    "audio_checked": True,
                    "speaker_turns": turn_count,
                    "speaker_count": len(speakers),
                }
            )
            return report
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, FileNotFoundError):
                error_code = "audio_missing"
                error_message = "The requested local diagnostic audio file does not exist."
            else:
                error_code, error_message = self.diarizer._normalize_error(exc)

            status = "unavailable" if error_code in {"missing_dependency", "unsupported_provider"} else "failed"
            report.update(
                {
                    "status": status,
                    "error_code": error_code,
                    "error_message": error_message,
                    "exception_type": type(exc).__name__,
                    "exception_message": self._safe_exception_message(exc),
                }
            )
            return report

    def _safe_exception_message(self, exc: Exception) -> str:
        message = str(exc).strip() or type(exc).__name__
        for secret in (self.config.diarization_hf_token, self.config.worker_token):
            if secret:
                message = message.replace(secret, "[REDACTED]")
        return message[:1000]
