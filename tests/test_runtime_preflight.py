import tempfile
import unittest
from unittest.mock import patch

from toolsapi_worker.config import WorkerConfig
from toolsapi_worker.runtime import WorkerRuntime, validate_whisper_runtime_device


class FakeCTranslate2:
    def __init__(self, device_count=1, compute_types=("float16", "int8_float16")):
        self.device_count = device_count
        self.compute_types = set(compute_types)

    def get_cuda_device_count(self):
        return self.device_count

    def get_supported_compute_types(self, device):
        if device != "cuda":
            raise AssertionError(f"unexpected device {device}")
        return self.compute_types


class NeverClaimClient:
    def claim_whisper(self, **_kwargs):
        raise AssertionError("claim_whisper must not run before startup preflight succeeds")


class StaticDiarizer:
    def __init__(self, supported=True):
        self.supported = supported


class WorkerRuntimePreflightTest(unittest.TestCase):
    def config(self, temp_root, whisper_device="cuda", compute_type="float16", diarization_device="cpu"):
        return WorkerConfig(
            api_base_url="https://tools.example.test",
            worker_token="worker-secret",
            worker_id="worker-01",
            concurrency=1,
            poll_seconds=1,
            heartbeat_seconds=30,
            enabled_handlers=("whisper.transcribe",),
            whisper_models=("small",),
            whisper_device=whisper_device,
            whisper_compute_type=compute_type,
            accepts_url_sources=False,
            diarization_enabled=True,
            diarization_provider="pyannote",
            diarization_hf_token="",
            diarization_model="pyannote/speaker-diarization-community-1",
            diarization_model_dir="",
            diarization_min_speakers=None,
            diarization_max_speakers=None,
            diarization_device=diarization_device,
            temp_root=str(temp_root),
        )

    def test_cuda_preflight_accepts_available_device_and_compute_type(self):
        with tempfile.TemporaryDirectory() as root:
            validate_whisper_runtime_device(
                self.config(root),
                FakeCTranslate2(device_count=1, compute_types=("float16", "int8_float16")),
            )

    def test_cuda_preflight_rejects_missing_native_device(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "CUDA Whisper runtime is unavailable"):
                validate_whisper_runtime_device(
                    self.config(root),
                    FakeCTranslate2(device_count=0),
                )

    def test_cuda_preflight_rejects_unsupported_compute_type(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "compute type"):
                validate_whisper_runtime_device(
                    self.config(root, compute_type="float16"),
                    FakeCTranslate2(device_count=1, compute_types=("int8",)),
                )

    def test_non_cuda_whisper_does_not_require_ctranslate2_probe(self):
        with tempfile.TemporaryDirectory() as root:
            validate_whisper_runtime_device(
                self.config(root, whisper_device="cpu", compute_type="int8"),
                object(),
            )

    def test_run_forever_preflights_whisper_before_first_claim(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = WorkerRuntime(
                self.config(root),
                client=NeverClaimClient(),
                handler=object(),
                diarizer=StaticDiarizer(True),
            )
            with patch(
                "toolsapi_worker.runtime.validate_whisper_runtime_device",
                side_effect=RuntimeError("synthetic CUDA preflight failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "synthetic CUDA preflight failure"):
                    runtime.run_forever()

    def test_run_forever_rejects_unavailable_explicit_diarization_accelerator_before_claim(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = WorkerRuntime(
                self.config(root, whisper_device="cpu", compute_type="int8", diarization_device="cuda"),
                client=NeverClaimClient(),
                handler=object(),
                diarizer=StaticDiarizer(False),
            )
            with self.assertRaisesRegex(RuntimeError, "diarization accelerator is unavailable"):
                runtime.run_forever()


if __name__ == "__main__":
    unittest.main()
