import tempfile
import unittest
from pathlib import Path

from toolsapi_worker.api import WhisperClaim
from toolsapi_worker.config import WorkerConfig
from toolsapi_worker.diarization import PyannoteDiarizer


class _Turn:
    def __init__(self, start, end):
        self.start = start
        self.end = end


class _Annotation:
    def itertracks(self, yield_label=False):
        yield _Turn(0.0, 1.5), None, "SPEAKER_00"
        yield _Turn(1.5, 4.0), None, "SPEAKER_01"


class _Pipeline:
    def __call__(self, _path, **_kwargs):
        return _Annotation()


class _Heartbeat:
    def __init__(self):
        self.updates = []

    def update(self, progress, label, detail):
        self.updates.append((progress, label, detail))

    def assert_owned(self):
        return None


class WorkerDiarizationTest(unittest.TestCase):
    def config(self, **overrides):
        values = {
            "TOOLS_API_BASE_URL": "https://tools.example.test",
            "TOOLS_WORKER_TOKEN": "worker-secret",
            "TOOLS_WORKER_ID": "worker-01",
            "TOOLS_WORKER_WHISPER_MODELS": "small",
            "TOOLS_WORKER_DIARIZATION_ENABLED": "true",
            "TOOLS_WORKER_DIARIZATION_HF_TOKEN": "hf_secret_never_return",
            "TOOLS_WORKER_DIARIZATION_DEVICE": "cpu",
        }
        values.update(overrides)
        return WorkerConfig.from_mapping(values)

    def claim(self, requested=True):
        return WhisperClaim(
            job_id=1,
            lease_id="lease-1",
            generation=1,
            contract="whisper.transcribe",
            contract_version=2,
            lease_expires_at="2026-09-01T12:00:00Z",
            model="small",
            language="sv",
            diarization_requested=requested,
            input={"type": "tools_media", "download_url": "https://tools.example.test/media"},
        )

    def test_maps_pyannote_turns_onto_whisper_segments(self):
        diarizer = PyannoteDiarizer(
            self.config(),
            pipeline_factory=lambda _source, token=None: _Pipeline(),
        )
        heartbeat = _Heartbeat()
        segments = [
            {"start": 0.0, "end": 1.0, "text": "Hej"},
            {"start": 2.0, "end": 3.0, "text": "Hallå"},
        ]

        with tempfile.TemporaryDirectory() as root:
            media = Path(root) / "audio.wav"
            media.write_bytes(b"fake")
            mapped, result = diarizer.diarize(self.claim(), media, segments, heartbeat)

        self.assertEqual("completed", result["status"])
        self.assertEqual(2, result["speaker_count"])
        self.assertTrue(result["hf_token_present"])
        self.assertNotIn("hf_secret_never_return", str(result))
        self.assertEqual("SPEAKER_00", mapped[0]["speaker_label"])
        self.assertEqual("SPEAKER_01", mapped[1]["speaker_label"])
        self.assertTrue(any(label == "Speaker diarization" for _, label, _ in heartbeat.updates))

    def test_diarization_failure_preserves_transcript_segments(self):
        def broken_pipeline(_source, token=None):
            raise RuntimeError("401 gated repo access denied")

        diarizer = PyannoteDiarizer(self.config(), pipeline_factory=broken_pipeline)
        heartbeat = _Heartbeat()
        segments = [{"start": 0.0, "end": 1.0, "text": "Bevaras"}]

        with tempfile.TemporaryDirectory() as root:
            media = Path(root) / "audio.wav"
            media.write_bytes(b"fake")
            mapped, result = diarizer.diarize(self.claim(), media, segments, heartbeat)

        self.assertEqual(segments, mapped)
        self.assertEqual("failed", result["status"])
        self.assertEqual("model_access_denied", result["error_code"])
        self.assertTrue(result["hf_token_present"])
        self.assertNotIn("hf_secret_never_return", str(result))

    def test_not_requested_is_skipped_without_loading_pipeline(self):
        called = False

        def pipeline(_source, token=None):
            nonlocal called
            called = True
            return _Pipeline()

        diarizer = PyannoteDiarizer(self.config(), pipeline_factory=pipeline)
        segments = [{"start": 0.0, "end": 1.0, "text": "Ingen diarization"}]
        mapped, result = diarizer.diarize(self.claim(False), Path("unused.wav"), segments, _Heartbeat())

        self.assertFalse(called)
        self.assertEqual(segments, mapped)
        self.assertEqual("skipped", result["status"])
        self.assertFalse(result["requested"])


if __name__ == "__main__":
    unittest.main()
