import tempfile
import threading
import time
import unittest
from pathlib import Path

from toolsapi_worker.api import WhisperClaim, WorkerApiError, WorkerLeaseLostError
from toolsapi_worker.config import WorkerConfig
from toolsapi_worker.runtime import (
    LeaseHeartbeat,
    MlxWhisperHandler,
    WhisperResult,
    WorkerRuntime,
    build_whisper_handler,
)


class FakeClient:
    def __init__(self):
        self.progress_calls = []
        self.complete_calls = []
        self.diarization_complete_calls = []
        self.fail_calls = []
        self.complete_failures_remaining = 0
        self.complete_started = threading.Event()
        self.complete_release = None
        self.complete_lease_lost = False
        self.fail_started = threading.Event()
        self.fail_release = None
        self.diarization_complete_started = threading.Event()
        self.diarization_complete_release = None

    def report_whisper_progress(self, claim, progress_percent, stage_label=None, stage_detail=None):
        self.progress_calls.append((claim.job_id, progress_percent, stage_label, stage_detail))
        return {"id": claim.job_id, "progress_percent": progress_percent}

    def download_whisper_media(self, claim, destination):
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake media")
        return path

    def complete_whisper(self, claim, transcript_text, segments=None, runtime=None, diarization=None):
        self.complete_calls.append(
            (claim, transcript_text, list(segments or []), dict(runtime or {}), dict(diarization or {}))
        )
        self.complete_started.set()
        if self.complete_release is not None and not self.complete_release.wait(timeout=2.0):
            raise RuntimeError("synthetic completion acknowledgement timed out")
        if self.complete_lease_lost:
            raise WorkerLeaseLostError("synthetic lease loss during completion")
        if self.complete_failures_remaining > 0:
            self.complete_failures_remaining -= 1
            raise WorkerApiError("temporary network failure")
        return {"ok": True, "accepted": True}

    def complete_whisper_diarization(self, claim, diarization):
        self.diarization_complete_calls.append((claim, dict(diarization)))
        self.diarization_complete_started.set()
        if self.diarization_complete_release is not None and not self.diarization_complete_release.wait(timeout=2.0):
            raise RuntimeError("synthetic diarization acknowledgement timed out")
        return {"ok": True, "accepted": True}

    def fail_whisper(self, claim, error_code, message, retryable=True):
        self.fail_calls.append((claim, error_code, message, retryable))
        self.fail_started.set()
        if self.fail_release is not None and not self.fail_release.wait(timeout=2.0):
            raise RuntimeError("synthetic failure acknowledgement timed out")
        return {"ok": True, "accepted": True}


class SlowHandler:
    def __init__(self, delay=0.12, fail=False):
        self.delay = delay
        self.fail = fail
        self.calls = 0

    def transcribe(self, claim, input_path, heartbeat):
        self.calls += 1
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


class FakeDiarizer:
    supported = True

    def __init__(self, status="completed"):
        self.status = status
        self.calls = []

    def diarize(self, claim, input_path, segments, heartbeat):
        self.calls.append((claim.job_id, str(input_path), list(segments)))
        heartbeat.update(98, "Speaker diarization", "Synthetic diarization")
        labelled = [dict(segment, speaker_label="SPEAKER_00") for segment in segments]
        return labelled, {
            "requested": True,
            "status": self.status,
            "provider": "pyannote",
            "speaker_count": 1 if self.status == "completed" else 0,
            "speaker_turns": [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]
            if self.status == "completed"
            else [],
            "hf_token_present": True,
        }


class FailingDiarizer:
    supported = True

    def diarize(self, claim, input_path, segments, heartbeat):
        raise RuntimeError("provider exploded with hf_secret_never_return")


class BlockingDiarizer:
    supported = True

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def diarize(self, claim, input_path, segments, heartbeat):
        self.calls.append((claim.job_id, str(input_path), list(segments)))
        heartbeat.update(96, "Speaker diarization", "Blocked synthetic diarization")
        self.started.set()
        if not self.release.wait(timeout=2.0):
            raise RuntimeError("synthetic diarization release timed out")
        heartbeat.assert_owned()
        labelled = [dict(segment, speaker_label="SPEAKER_00") for segment in segments]
        return labelled, {
            "requested": True,
            "status": "completed",
            "provider": "pyannote",
            "speaker_count": 1,
            "speaker_turns": [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}],
            "hf_token_present": True,
        }


class WorkerRuntimeTest(unittest.TestCase):
    def config(self, temp_root, heartbeat_seconds=0.05, device="cpu", compute_type="int8", models=("small",)):
        return WorkerConfig(
            api_base_url="https://tools.example.test",
            worker_token="worker-secret",
            worker_id="worker-01",
            concurrency=1,
            poll_seconds=0.01,
            heartbeat_seconds=heartbeat_seconds,
            enabled_handlers=("whisper.transcribe",),
            whisper_models=models,
            whisper_device=device,
            whisper_compute_type=compute_type,
            accepts_url_sources=False,
            diarization_enabled=True,
            diarization_provider="pyannote",
            diarization_hf_token="hf_test_only",
            diarization_model="pyannote/speaker-diarization-community-1",
            diarization_model_dir="",
            diarization_min_speakers=None,
            diarization_max_speakers=None,
            diarization_device="cpu",
            temp_root=str(temp_root),
        )

    def claim(self, model="small", diarization_requested=True, operation="transcribe"):
        return WhisperClaim(
            job_id=123,
            lease_id="lease-abc",
            generation=2,
            contract="whisper.transcribe",
            contract_version=2,
            lease_expires_at="2026-09-01T14:30:00+00:00",
            operation=operation,
            model=model,
            language="sv",
            diarization_requested=diarization_requested,
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

    def test_heartbeat_continues_while_diarization_is_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            client = FakeClient()
            diarizer = BlockingDiarizer()
            runtime = WorkerRuntime(
                self.config(root, heartbeat_seconds=0.05),
                client=client,
                handler=SlowHandler(delay=0.01),
                diarizer=diarizer,
                sleep=lambda seconds: None,
            )
            worker_thread = threading.Thread(target=runtime.process_claim, args=(self.claim(),), daemon=True)
            worker_thread.start()

            self.assertTrue(diarizer.started.wait(timeout=1.0))
            try:
                progress_before_wait = len(client.progress_calls)
                deadline = time.monotonic() + 1.0
                speaker_updates = []
                while time.monotonic() < deadline:
                    speaker_updates = [
                        call for call in client.progress_calls
                        if call[2] == "Speaker diarization" and call[1] == 96
                    ]
                    if len(speaker_updates) >= 2:
                        break
                    time.sleep(0.01)
                progress_after_wait = len(client.progress_calls)
                self.assertGreaterEqual(progress_after_wait - progress_before_wait, 1)
                self.assertGreaterEqual(len(speaker_updates), 2)
            finally:
                diarizer.release.set()
                worker_thread.join(timeout=1.0)

            self.assertFalse(worker_thread.is_alive())
            self.assertEqual(1, len(diarizer.calls))
            self.assertEqual(1, len(client.complete_calls))
            self.assertEqual([], client.fail_calls)

    def test_heartbeat_continues_until_completion_acknowledgement(self):
        with tempfile.TemporaryDirectory() as root:
            client = FakeClient()
            client.complete_release = threading.Event()
            runtime = WorkerRuntime(
                self.config(root, heartbeat_seconds=0.05),
                client=client,
                handler=SlowHandler(delay=0.01),
                diarizer=FakeDiarizer(),
                sleep=lambda seconds: None,
            )
            worker_thread = threading.Thread(target=runtime.process_claim, args=(self.claim(),), daemon=True)
            worker_thread.start()

            self.assertTrue(client.complete_started.wait(timeout=1.0))
            progress_before_wait = len(client.progress_calls)
            time.sleep(0.16)
            progress_after_wait = len(client.progress_calls)
            finalizing_updates = [call for call in client.progress_calls if call[2] == "Finalizing" and call[1] == 99]
            self.assertGreaterEqual(progress_after_wait - progress_before_wait, 2)
            self.assertGreaterEqual(len(finalizing_updates), 2)

            client.complete_release.set()
            worker_thread.join(timeout=1.0)
            self.assertFalse(worker_thread.is_alive())
            self.assertEqual(1, len(client.complete_calls))
            self.assertEqual([], client.fail_calls)
            self.assertEqual([], list(Path(root).iterdir()))

    def test_heartbeat_continues_until_failure_acknowledgement(self):
        with tempfile.TemporaryDirectory() as root:
            client = FakeClient()
            client.fail_release = threading.Event()
            runtime = WorkerRuntime(
                self.config(root, heartbeat_seconds=0.05),
                client=client,
                handler=SlowHandler(delay=0.01, fail=True),
                diarizer=FakeDiarizer(),
                sleep=lambda seconds: None,
            )
            worker_thread = threading.Thread(target=runtime.process_claim, args=(self.claim(),), daemon=True)
            worker_thread.start()

            self.assertTrue(client.fail_started.wait(timeout=1.0))
            progress_before_wait = len(client.progress_calls)
            time.sleep(0.16)
            progress_after_wait = len(client.progress_calls)
            self.assertGreaterEqual(progress_after_wait - progress_before_wait, 2)

            client.fail_release.set()
            worker_thread.join(timeout=1.0)
            self.assertFalse(worker_thread.is_alive())
            self.assertEqual(1, len(client.fail_calls))
            self.assertEqual([], list(Path(root).iterdir()))

    def test_heartbeat_continues_until_diarization_only_acknowledgement(self):
        with tempfile.TemporaryDirectory() as root:
            client = FakeClient()
            client.diarization_complete_release = threading.Event()
            runtime = WorkerRuntime(
                self.config(root, heartbeat_seconds=0.05),
                client=client,
                handler=SlowHandler(delay=0.01),
                diarizer=FakeDiarizer(),
                sleep=lambda seconds: None,
            )
            claim = self.claim(operation="diarize", diarization_requested=True)
            worker_thread = threading.Thread(target=runtime.process_claim, args=(claim,), daemon=True)
            worker_thread.start()

            self.assertTrue(client.diarization_complete_started.wait(timeout=1.0))
            progress_before_wait = len(client.progress_calls)
            time.sleep(0.16)
            progress_after_wait = len(client.progress_calls)
            self.assertGreaterEqual(progress_after_wait - progress_before_wait, 2)

            client.diarization_complete_release.set()
            worker_thread.join(timeout=1.0)
            self.assertFalse(worker_thread.is_alive())
            self.assertEqual(1, len(client.diarization_complete_calls))
            self.assertEqual([], client.fail_calls)
            self.assertEqual([], list(Path(root).iterdir()))

    def test_completion_lease_loss_never_falls_through_to_failure_submission(self):
        with tempfile.TemporaryDirectory() as root:
            client = FakeClient()
            client.complete_lease_lost = True
            runtime = WorkerRuntime(
                self.config(root),
                client=client,
                handler=SlowHandler(delay=0.01),
                diarizer=FakeDiarizer(),
                sleep=lambda seconds: None,
            )

            with self.assertRaises(WorkerLeaseLostError):
                runtime.process_claim(self.claim())

            self.assertEqual(1, len(client.complete_calls))
            self.assertEqual([], client.fail_calls)
            self.assertEqual([], list(Path(root).iterdir()))

    def test_completed_job_runs_diarization_before_terminal_ack_and_cleans_temp_media(self):
        with tempfile.TemporaryDirectory() as root:
            client = FakeClient()
            client.complete_failures_remaining = 1
            sleeps = []
            diarizer = FakeDiarizer()
            runtime = WorkerRuntime(
                self.config(root),
                client=client,
                handler=SlowHandler(delay=0.01),
                diarizer=diarizer,
                sleep=lambda seconds: sleeps.append(seconds),
            )

            runtime.process_claim(self.claim())

            self.assertEqual(1, len(diarizer.calls))
            self.assertEqual(2, len(client.complete_calls))
            self.assertEqual([0.01], sleeps)
            self.assertEqual([], client.fail_calls)
            self.assertEqual([], list(Path(root).iterdir()))
            first = client.complete_calls[0]
            second = client.complete_calls[1]
            self.assertEqual(first[1:], second[1:])
            self.assertEqual("SPEAKER_00", first[2][0]["speaker_label"])
            self.assertEqual("completed", first[4]["status"])

    def test_diarization_only_claim_never_runs_whisper_or_submits_transcript(self):
        with tempfile.TemporaryDirectory() as root:
            client = FakeClient()
            handler = SlowHandler(delay=0.01, fail=True)
            diarizer = FakeDiarizer()
            runtime = WorkerRuntime(
                self.config(root),
                client=client,
                handler=handler,
                diarizer=diarizer,
                sleep=lambda seconds: None,
            )

            runtime.process_claim(self.claim(operation="diarize", diarization_requested=True))

            self.assertEqual(0, handler.calls)
            self.assertEqual(1, len(diarizer.calls))
            self.assertEqual([], diarizer.calls[0][2])
            self.assertEqual([], client.complete_calls)
            self.assertEqual([], client.fail_calls)
            self.assertEqual(1, len(client.diarization_complete_calls))
            self.assertEqual("completed", client.diarization_complete_calls[0][1]["status"])
            self.assertEqual([], list(Path(root).iterdir()))

    def test_diarization_only_runtime_failure_cannot_fail_or_replace_transcript(self):
        with tempfile.TemporaryDirectory() as root:
            client = FakeClient()
            runtime = WorkerRuntime(
                self.config(root),
                client=client,
                handler=SlowHandler(delay=0.01, fail=True),
                diarizer=FailingDiarizer(),
                sleep=lambda seconds: None,
            )

            runtime.process_claim(self.claim(operation="diarize", diarization_requested=True))

            self.assertEqual([], client.complete_calls)
            self.assertEqual([], client.fail_calls)
            self.assertEqual(1, len(client.diarization_complete_calls))
            payload = client.diarization_complete_calls[0][1]
            self.assertEqual("failed", payload["status"])
            self.assertEqual("worker_error", payload["error_code"])
            self.assertNotIn("hf_secret_never_return", str(payload))
            self.assertEqual([], list(Path(root).iterdir()))

    def test_non_diarization_job_skips_diarizer(self):
        with tempfile.TemporaryDirectory() as root:
            client = FakeClient()
            diarizer = FakeDiarizer()
            runtime = WorkerRuntime(
                self.config(root),
                client=client,
                handler=SlowHandler(delay=0.01),
                diarizer=diarizer,
                sleep=lambda seconds: None,
            )

            runtime.process_claim(self.claim(diarization_requested=False))

            self.assertEqual([], diarizer.calls)
            self.assertEqual("skipped", client.complete_calls[0][4]["status"])
            self.assertFalse(client.complete_calls[0][4]["requested"])

    def test_handler_failure_is_reported_and_temp_media_is_cleaned(self):
        with tempfile.TemporaryDirectory() as root:
            client = FakeClient()
            runtime = WorkerRuntime(
                self.config(root),
                client=client,
                handler=SlowHandler(delay=0.01, fail=True),
                diarizer=FakeDiarizer(),
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
            claim = self.claim(diarization_requested=False)
            claim = WhisperClaim(
                job_id=claim.job_id,
                lease_id=claim.lease_id,
                generation=claim.generation,
                contract=claim.contract,
                contract_version=claim.contract_version,
                lease_expires_at=claim.lease_expires_at,
                operation=claim.operation,
                model=claim.model,
                language=claim.language,
                diarization_requested=False,
                input={"type": "url", "url": "https://example.test/audio.mp3"},
            )
            runtime = WorkerRuntime(
                self.config(root),
                client=client,
                handler=SlowHandler(delay=0.01),
                diarizer=FakeDiarizer(),
                sleep=lambda seconds: None,
            )

            runtime.process_claim(claim)

            self.assertEqual(1, len(client.fail_calls))
            self.assertIn("URL-source execution is disabled", client.fail_calls[0][2])

    def test_metal_device_selects_mlx_handler(self):
        with tempfile.TemporaryDirectory() as root:
            handler = build_whisper_handler(self.config(root, device="metal", compute_type="float16"))
        self.assertIsInstance(handler, MlxWhisperHandler)

    def test_mlx_handler_normalizes_transcript_and_segments(self):
        calls = []

        def fake_transcribe(path, **kwargs):
            calls.append((path, kwargs))
            return {
                "text": " Hej världen ",
                "segments": [
                    {"start": 0.0, "end": 1.25, "text": " Hej "},
                    {"start": 1.25, "end": 2.5, "text": " världen "},
                ],
                "language": "sv",
            }

        with tempfile.TemporaryDirectory() as root:
            config = self.config(root, device="metal", compute_type="float16", models=("large-v3",))
            handler = MlxWhisperHandler(config, transcribe_func=fake_transcribe)
            heartbeat = LeaseHeartbeat(FakeClient(), self.claim(model="large-v3"), 1)
            input_path = Path(root) / "audio.m4a"
            input_path.write_bytes(b"fake")

            result = handler.transcribe(self.claim(model="large-v3"), input_path, heartbeat)

        self.assertEqual("Hej världen", result.transcript_text)
        self.assertEqual(2, len(result.segments))
        self.assertEqual("mlx-whisper", result.runtime["engine"])
        self.assertEqual("metal", result.runtime["device"])
        self.assertEqual("mlx-community/whisper-large-v3-mlx", result.runtime["model_repository"])
        self.assertEqual(str(input_path), calls[0][0])
        self.assertEqual("mlx-community/whisper-large-v3-mlx", calls[0][1]["path_or_hf_repo"])
        self.assertEqual("sv", calls[0][1]["language"])
        self.assertFalse(calls[0][1]["verbose"])


if __name__ == "__main__":
    unittest.main()