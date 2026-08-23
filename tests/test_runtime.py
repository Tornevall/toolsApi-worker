import tempfile
import time
import unittest
from pathlib import Path

from toolsapi_worker.api import WhisperClaim, WorkerApiError
from toolsapi_worker.config import WorkerConfig
from toolsapi_worker.runtime import LeaseHeartbeat, WhisperResult, WorkerRuntime


class FakeClient:
    def __init__(self):
        self.progress_calls = []
        self.complete_calls = []
        self.fail_calls = []
        self.complete_failures_remaining = 0

    def report_whisper_progress(self, claim, progress_percent, stage_label=None, stage_detail=None):
        self.progress_calls.append((claim.job_id, progress_percent, stage_label, stage_detail))
        return {"id": claim.job_id, "progress_percent": progress_percent}

    def download_whisper_media(self, claim, destination):
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake media")
        return path

    def complete_whisper(self, claim, transcript_text, segments=None, runtime=None):
        self.complete_calls.append((claim, transcript_text, list(segments or []), dict(runtime or {})))
        if self.complete_failures_remaining > 0:
            self.complete_failures_remaining -= 1
            raise WorkerApiError("temporary network failure")
        return {"ok": True, "accepted": True}

    def fail_whisper(self, claim, error_code, message, retryable=True):
        self.fail_calls.append((claim, error_code, message, retryable))
        return {"ok": True, "accepted": True}


class SlowHandler:
    def __init__(self, delay=0.12, fail=False):
        self.delay = delay
        self.fail = fail

    def transcribe(self, claim, input_path, heartbeat):
        heartbeat.update(30, "Transcribing", "Slow test handler")
        time.sleep(self.delay)
        heartbeat.assert_owned()
        if self.fail:
            raise RuntimeError("synthetic transcription failure")
        return WhisperResult(
            transcript_text="Test transcript",
            segments=[{"start": 0.0, "end": 1.0, "text": "Test transcript"}],
            runtime={"engine": "faster-whisper", "device": "cpu", "model": claim.model},
        )


class WorkerRuntimeTest(unittest.TestCase):
    def config(self, temp_root, heartbeat_seconds=0.05):
        return WorkerConfig(
            api_base_url="https://tools.example.test",
            worker_token="worker-secret",
            worker_id="worker-01",
            concurrency=1,
            poll_seconds=0.01,
            heartbeat_seconds=heartbeat_seconds,
            enabled_handlers=("whisper.transcribe",),
            whisper_models=("small",),
            whisper_device="cpu",
            whisper_compute_type="int8",
            accepts_url_sources=False,
            temp_root=str(temp_root),
        )

    def claim(self):
        return WhisperClaim(
            job_id=123,
            lease_id="lease-abc",
            generation=2,
            contract="whisper.transcribe",
            contract_version=1,
            lease_expires_at="2026-08-23T14:30:00+00:00",
            model="small",
            language="sv",
            diarization_requested=True,
            input={"type": "tools_media", "download_url": "https://tools.example.test/api/whisper/worker/jobs/123/media"},
        )

    def test_heartbeat_continues_while_handler_is_slow(self):
        client = FakeClient()
        heartbeat = LeaseHeartbeat(client, self.claim(), 0.05)
        heartbeat.update(40, "Transcribing", "slow")
        heartbeat.start()
        time.sleep(0.13)
        heartbeat.stop()

        self.assertGreaterEqual(len(client.progress_calls), 2)
        self.assertTrue(all(call[1] == 40 for call in client.progress_calls))

    def test_completed_job_retries_terminal_ack_and_cleans_temp_media(self):
        with tempfile.TemporaryDirectory() as root:
            client = FakeClient()
            client.complete_failures_remaining = 1
            sleeps = []
            runtime = WorkerRuntime(
                self.config(root),
                client=client,
                handler=SlowHandler(delay=0.01),
                sleep=lambda seconds: sleeps.append(seconds),
            )

            runtime.process_claim(self.claim())

            self.assertEqual(2, len(client.complete_calls))
            self.assertEqual([0.01], sleeps)
            self.assertEqual([], client.fail_calls)
            self.assertEqual([], list(Path(root).iterdir()))
            first = client.complete_calls[0]
            second = client.complete_calls[1]
            self.assertEqual(first[1:], second[1:])

    def test_handler_failure_is_reported_and_temp_media_is_cleaned(self):
        with tempfile.TemporaryDirectory() as root:
            client = FakeClient()
            runtime = WorkerRuntime(
                self.config(root),
                client=client,
                handler=SlowHandler(delay=0.01, fail=True),
                sleep=lambda seconds: None,
            )

            runtime.process_claim(self.claim())

            self.assertEqual(1, len(client.fail_calls))
            self.assertEqual("transcription_failed", client.fail_calls[0][1])
            self.assertIn("synthetic transcription failure", client.fail_calls[0][2])
            self.assertEqual([], list(Path(root).iterdir()))

    def test_url_source_is_not_executed_when_runtime_has_url_support_disabled(self):
        with tempfile.TemporaryDirectory() as root:
            client = FakeClient()
            claim = self.claim()
            claim = WhisperClaim(
                job_id=claim.job_id,
                lease_id=claim.lease_id,
                generation=claim.generation,
                contract=claim.contract,
                contract_version=claim.contract_version,
                lease_expires_at=claim.lease_expires_at,
                model=claim.model,
                language=claim.language,
                diarization_requested=False,
                input={"type": "url", "url": "https://example.test/audio.mp3"},
            )
            runtime = WorkerRuntime(
                self.config(root),
                client=client,
                handler=SlowHandler(delay=0.01),
                sleep=lambda seconds: None,
            )

            runtime.process_claim(claim)

            self.assertEqual(1, len(client.fail_calls))
            self.assertIn("URL-source execution is disabled", client.fail_calls[0][2])


if __name__ == "__main__":
    unittest.main()
