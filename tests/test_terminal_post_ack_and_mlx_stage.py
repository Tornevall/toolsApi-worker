import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from toolsapi_worker.api import WhisperClaim
from toolsapi_worker.live_progress import MlxVerboseTranscriptCapture
from toolsapi_worker.runtime import LeaseHeartbeat, MlxWhisperHandler, WorkerRuntime


class _ProgressClient:
    def __init__(self):
        self.progress_calls = []
        self.progress_seen = threading.Event()

    def report_whisper_progress(
        self,
        claim,
        progress_percent,
        stage_label=None,
        stage_detail=None,
        transcript_text=None,
        segments=None,
    ):
        self.progress_calls.append((claim.job_id, progress_percent, stage_label, stage_detail))
        self.progress_seen.set()
        return {"ok": True}


class _RecordingHeartbeat:
    def __init__(self):
        self.updates = []
        self.transcripts = []

    def update(self, progress_percent, stage_label, stage_detail):
        self.updates.append((progress_percent, stage_label, stage_detail))

    def update_transcript(self, transcript_text, segments):
        self.transcripts.append((transcript_text, list(segments)))

    def assert_owned(self):
        return None


class TerminalAndMlxProgressRegressionTest(unittest.TestCase):
    def claim(self):
        return WhisperClaim(
            job_id=83,
            lease_id="lease-83",
            generation=4,
            contract="whisper.transcribe",
            contract_version=2,
            lease_expires_at="2026-09-09T12:30:00+02:00",
            operation="transcribe",
            model="small",
            language="sv",
            diarization_requested=False,
            input={"type": "tools_media", "download_url": "/api/whisper/worker/jobs/83/media"},
        )

    def test_accepted_terminal_response_stops_future_heartbeat_reports(self):
        client = _ProgressClient()
        heartbeat = LeaseHeartbeat(client, self.claim(), 0.05)
        heartbeat.start()
        heartbeat.update(42, "Transcribing", "Synthetic progress")
        self.assertTrue(client.progress_seen.wait(timeout=1.0))

        runtime = object.__new__(WorkerRuntime)
        runtime.config = SimpleNamespace(poll_seconds=0.01)
        runtime.sleep = lambda _seconds: None

        response = runtime._retry_terminal(lambda: {"ok": True, "accepted": True}, heartbeat)
        self.assertTrue(response["accepted"])
        calls_after_ack = len(client.progress_calls)
        time.sleep(0.15)
        heartbeat.stop()

        self.assertEqual(calls_after_ack, len(client.progress_calls))

    def test_mlx_waiting_before_first_segment_reports_preparation_not_active_transcription(self):
        heartbeat = _RecordingHeartbeat()

        def fake_transcribe(*_args, **_kwargs):
            self.assertEqual("Preparing MLX Whisper", heartbeat.updates[-1][1])
            self.assertIn("model loading/download", heartbeat.updates[-1][2])
            return {
                "text": "Synthetic transcript",
                "segments": [{"start": 0.0, "end": 1.5, "text": "Synthetic transcript"}],
            }

        config = SimpleNamespace(
            whisper_models=("small",),
            whisper_device="metal",
            whisper_compute_type="float16",
        )
        handler = MlxWhisperHandler(config, transcribe_func=fake_transcribe)
        result = handler.transcribe(self.claim(), Path("synthetic-audio.m4a"), heartbeat)

        self.assertEqual("Synthetic transcript", result.transcript_text)
        self.assertEqual("Loading Whisper model", heartbeat.updates[0][1])
        self.assertEqual("Preparing MLX Whisper", heartbeat.updates[1][1])
        self.assertEqual("Transcription complete", heartbeat.updates[-1][1])

    def test_first_mlx_timestamped_segment_switches_stage_to_transcribing(self):
        heartbeat = _RecordingHeartbeat()
        capture = MlxVerboseTranscriptCapture(heartbeat)

        capture.write("[00:00.000 --> 00:03.500] First segment\n")
        capture.finish()

        self.assertEqual("Transcribing", heartbeat.updates[-1][1])
        self.assertIn("3.5 seconds transcribed", heartbeat.updates[-1][2])
        self.assertEqual("First segment", heartbeat.transcripts[-1][0])


if __name__ == "__main__":
    unittest.main()
