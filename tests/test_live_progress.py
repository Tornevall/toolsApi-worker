import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from toolsapi_worker.api import ToolsApiClient, WhisperClaim
from toolsapi_worker.config import WorkerConfig
from toolsapi_worker.live_progress import MlxVerboseTranscriptCapture, timestamp_seconds
from toolsapi_worker.runtime import FasterWhisperHandler, LeaseHeartbeat


class FakeClient:
    def __init__(self):
        self.progress_calls = []

    def report_whisper_progress(
        self,
        claim,
        progress_percent,
        stage_label=None,
        stage_detail=None,
        transcript_text=None,
        segments=None,
    ):
        self.progress_calls.append(
            {
                "job_id": claim.job_id,
                "progress_percent": progress_percent,
                "stage_label": stage_label,
                "stage_detail": stage_detail,
                "transcript_text": transcript_text,
                "segments": list(segments or []),
            }
        )
        return {"id": claim.job_id, "progress_percent": progress_percent}


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        return self.payload


class LiveWhisperProgressTest(unittest.TestCase):
    def claim(self, model="small"):
        return WhisperClaim(
            job_id=77,
            lease_id="lease-live",
            generation=3,
            contract="whisper.transcribe",
            contract_version=2,
            lease_expires_at="2026-09-04T14:15:00+02:00",
            operation="transcribe",
            model=model,
            language="en",
            diarization_requested=False,
            input={"type": "tools_media", "download_url": "https://tools.example.test/api/whisper/worker/jobs/77/media"},
        )

    def config(self, root, device="cpu", compute="int8", models=("small",)):
        return WorkerConfig(
            api_base_url="https://tools.example.test",
            worker_token="worker-secret",
            worker_id="worker-live",
            concurrency=1,
            poll_seconds=0.01,
            heartbeat_seconds=0.05,
            enabled_handlers=("whisper.transcribe",),
            whisper_models=models,
            whisper_device=device,
            whisper_compute_type=compute,
            accepts_url_sources=False,
            diarization_enabled=True,
            diarization_provider="pyannote",
            diarization_hf_token="hf_test_only",
            diarization_model="pyannote/speaker-diarization-community-1",
            diarization_model_dir="",
            diarization_min_speakers=None,
            diarization_max_speakers=None,
            diarization_device="cpu",
            temp_root=str(root),
        )

    def test_timestamp_parser_handles_hour_long_audio(self):
        self.assertAlmostEqual(4367.25, timestamp_seconds("01:12:47.250"), places=3)
        self.assertAlmostEqual(67.5, timestamp_seconds("01:07.500"), places=3)

    def test_heartbeat_publishes_live_transcript_snapshot(self):
        client = FakeClient()
        heartbeat = LeaseHeartbeat(client, self.claim(), 0.05)
        heartbeat.start()
        heartbeat.update(27, "Transcribing", "31.0 seconds transcribed")
        heartbeat.update_transcript(
            "Hello world",
            [{"start": 0.0, "end": 31.0, "text": "Hello world"}],
        )
        time.sleep(0.08)
        heartbeat.stop()

        self.assertGreaterEqual(len(client.progress_calls), 1)
        latest = client.progress_calls[-1]
        self.assertEqual("Hello world", latest["transcript_text"])
        self.assertEqual(31.0, latest["segments"][0]["end"])

    def test_mlx_verbose_capture_streams_segments_incrementally(self):
        client = FakeClient()
        heartbeat = LeaseHeartbeat(client, self.claim(model="large-v3"), 0.05)
        capture = MlxVerboseTranscriptCapture(heartbeat)

        capture.write("Detected language: English\n[00:00.000 --> 00:04.250] First")
        capture.write(" sentence\n[00:04.250 --> 00:09.500] Second sentence\n")
        capture.finish()

        snapshot = heartbeat._snapshot()
        self.assertEqual("First sentence Second sentence", snapshot.transcript_text)
        self.assertEqual(2, len(snapshot.transcript_segments))
        self.assertEqual(9.5, snapshot.transcript_segments[-1]["end"])
        self.assertIn("2 segments received", snapshot.stage_detail)

    def test_faster_whisper_publishes_segments_while_iterating(self):
        class FakeModel:
            def transcribe(self, path, language=None, vad_filter=True):
                segments = iter([
                    SimpleNamespace(start=0.0, end=5.0, text="Alpha"),
                    SimpleNamespace(start=5.0, end=12.0, text="Beta"),
                ])
                return segments, SimpleNamespace(duration=20.0)

        client = FakeClient()
        heartbeat = LeaseHeartbeat(client, self.claim(), 0.05)
        with tempfile.TemporaryDirectory() as root:
            handler = FasterWhisperHandler(self.config(root), model_factory=lambda *args, **kwargs: FakeModel())
            input_path = Path(root) / "audio.mp3"
            input_path.write_bytes(b"fake")
            result = handler.transcribe(self.claim(), input_path, heartbeat)

        snapshot = heartbeat._snapshot()
        self.assertEqual("Alpha Beta", snapshot.transcript_text)
        self.assertEqual(12.0, snapshot.transcript_segments[-1]["end"])
        self.assertEqual("Alpha Beta", result.transcript_text)

    @patch("urllib.request.urlopen")
    def test_api_progress_payload_contains_bounded_live_transcript(self, urlopen):
        urlopen.return_value = FakeResponse(
            {
                "ok": True,
                "job": {"id": 77, "status": "transcribing", "progress_percent": 31},
            }
        )
        client = ToolsApiClient("https://tools.example.test", "worker-secret", "worker-live")
        client.report_whisper_progress(
            self.claim(),
            31,
            "Transcribing",
            "42 seconds transcribed",
            "Live text",
            [{"start": 0.0, "end": 42.0, "text": "Live text"}],
        )

        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual("Live text", body["transcript_text"])
        self.assertEqual(42.0, body["segments"][0]["end"])
        self.assertNotIn("worker-secret", json.dumps(body))


if __name__ == "__main__":
    unittest.main()
