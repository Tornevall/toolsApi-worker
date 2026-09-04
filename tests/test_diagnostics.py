import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from toolsapi_worker.cli import main
from toolsapi_worker.config import WorkerConfig
from toolsapi_worker.diagnostics import DiarizationDiagnostic


class _Turn:
    def __init__(self, start, end):
        self.start = start
        self.end = end


class _Annotation:
    def itertracks(self, yield_label=False):
        yield _Turn(0.0, 1.0), None, "SPEAKER_00"
        yield _Turn(1.0, 2.0), None, "SPEAKER_01"


class _Pipeline:
    def __call__(self, _path):
        return _Annotation()


class _FakeDiarizer:
    def __init__(self, pipeline=None, supported=True, failure=None):
        self.pipeline = pipeline or _Pipeline()
        self.supported = supported
        self.failure = failure

    def _support_failure(self):
        return "device_unavailable", "The configured speaker diarization device is unavailable on this worker."

    def _resolved_device(self):
        return "mps"

    def _create_pipeline(self):
        if self.failure is not None:
            raise self.failure
        return self.pipeline

    @staticmethod
    def _normalize_error(_exc):
        return "process_failed", "Speaker diarization failed on this worker."


class DiarizationDiagnosticTests(unittest.TestCase):
    def config(self):
        return WorkerConfig.from_mapping(
            {
                "TOOLS_API_BASE_URL": "https://tools.example.test",
                "TOOLS_WORKER_TOKEN": "worker-secret-never-print",
                "TOOLS_WORKER_ID": "mac-worker",
                "TOOLS_WORKER_DIARIZATION_ENABLED": "true",
                "TOOLS_WORKER_DIARIZATION_HF_TOKEN": "hf-secret-never-print",
                "TOOLS_WORKER_DIARIZATION_DEVICE": "auto",
            }
        )

    def test_model_load_only_diagnostic_reports_ready_without_secrets(self):
        report = DiarizationDiagnostic(self.config(), diarizer=_FakeDiarizer()).run()

        self.assertEqual("ready", report["status"])
        self.assertTrue(report["pipeline_loaded"])
        self.assertFalse(report["audio_checked"])
        self.assertEqual("mps", report["resolved_device"])
        self.assertTrue(report["hf_token_present"])
        self.assertNotIn("hf-secret-never-print", str(report))
        self.assertNotIn("worker-secret-never-print", str(report))

    def test_audio_diagnostic_runs_pipeline_and_reports_speakers(self):
        with tempfile.TemporaryDirectory() as root:
            media = Path(root) / "audio.wav"
            media.write_bytes(b"fake-audio")
            report = DiarizationDiagnostic(self.config(), diarizer=_FakeDiarizer()).run(str(media))

        self.assertEqual("completed", report["status"])
        self.assertTrue(report["audio_checked"])
        self.assertEqual(2, report["speaker_turns"])
        self.assertEqual(2, report["speaker_count"])

    def test_failure_diagnostic_redacts_hf_and_worker_tokens(self):
        config = self.config()
        failure = RuntimeError(
            "provider error hf-secret-never-print and worker-secret-never-print"
        )
        report = DiarizationDiagnostic(config, diarizer=_FakeDiarizer(failure=failure)).run()

        self.assertEqual("failed", report["status"])
        self.assertEqual("RuntimeError", report["exception_type"])
        self.assertIn("[REDACTED]", report["exception_message"])
        self.assertNotIn(config.diarization_hf_token, report["exception_message"])
        self.assertNotIn(config.worker_token, report["exception_message"])

    def test_missing_audio_returns_specific_failure(self):
        report = DiarizationDiagnostic(self.config(), diarizer=_FakeDiarizer()).run(
            "/definitely/not/a/real/audio-file.wav"
        )

        self.assertEqual("failed", report["status"])
        self.assertEqual("audio_missing", report["error_code"])
        self.assertEqual("FileNotFoundError", report["exception_type"])

    def test_cli_diarization_diagnostic_uses_env_file_and_returns_success(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as root:
            env_file = Path(root) / ".env"
            env_file.write_text(
                "TOOLS_API_BASE_URL=https://tools.example.test\n"
                "TOOLS_WORKER_TOKEN=worker-secret-never-print\n"
                "TOOLS_WORKER_ID=mac-worker\n"
                "TOOLS_WORKER_DIARIZATION_HF_TOKEN=hf-secret-never-print\n",
                encoding="utf-8",
            )
            with (
                patch("toolsapi_worker.cli.DiarizationDiagnostic") as diagnostic_class,
                redirect_stdout(output),
            ):
                diagnostic_class.return_value.run.return_value = {
                    "status": "ready",
                    "enabled": True,
                    "provider": "pyannote",
                    "model": "pyannote/speaker-diarization-community-1",
                    "model_dir_configured": False,
                    "hf_token_present": True,
                    "configured_device": "auto",
                    "resolved_device": "mps",
                    "supported": True,
                    "pipeline_loaded": True,
                    "audio_checked": False,
                }
                code = main(["diagnose", "diarization", "--env-file", str(env_file)])

        self.assertEqual(0, code)
        self.assertIn("status: ready", output.getvalue())
        self.assertIn("resolved_device: mps", output.getvalue())
        self.assertNotIn("hf-secret-never-print", output.getvalue())
        self.assertNotIn("worker-secret-never-print", output.getvalue())

    def test_cli_diarization_diagnostic_returns_nonzero_on_failure(self):
        output = io.StringIO()
        with (
            patch("toolsapi_worker.cli.load_config"),
            patch("toolsapi_worker.cli.DiarizationDiagnostic") as diagnostic_class,
            redirect_stdout(output),
        ):
            diagnostic_class.return_value.run.return_value = {
                "status": "failed",
                "error_code": "process_failed",
                "error_message": "Speaker diarization failed on this worker.",
                "exception_type": "RuntimeError",
                "exception_message": "safe local detail",
            }
            code = main(["diagnose", "diarization"])

        self.assertEqual(2, code)
        self.assertIn("error_code: process_failed", output.getvalue())
        self.assertIn("exception_message: safe local detail", output.getvalue())


if __name__ == "__main__":
    unittest.main()
