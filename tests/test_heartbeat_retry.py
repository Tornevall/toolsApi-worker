import threading
import time
import unittest

from toolsapi_worker.api import WhisperClaim, WorkerApiError, WorkerLeaseLostError
from toolsapi_worker.runtime import LeaseHeartbeat


class FlakyProgressClient:
    def __init__(self, failures=1, lease_lost=False):
        self.failures = failures
        self.lease_lost = lease_lost
        self.calls = []
        self.called = threading.Event()
        self.recovered = threading.Event()

    def report_whisper_progress(self, claim, progress_percent, stage_label=None, stage_detail=None):
        self.calls.append(time.monotonic())
        self.called.set()
        if self.lease_lost:
            raise WorkerLeaseLostError("synthetic expired lease")
        if self.failures > 0:
            self.failures -= 1
            raise WorkerApiError("synthetic transport failure")
        self.recovered.set()
        return {"id": claim.job_id, "progress_percent": progress_percent}


class LeaseHeartbeatRetryTest(unittest.TestCase):
    @staticmethod
    def claim():
        return WhisperClaim(
            job_id=78,
            lease_id="lease-heartbeat-test",
            generation=5,
            contract="whisper.transcribe",
            contract_version=2,
            lease_expires_at="2026-09-04T20:40:00+02:00",
            operation="diarize",
            model="small",
            language="sv",
            diarization_requested=True,
            input={
                "type": "tools_media",
                "download_url": "https://tools.example.test/api/whisper/worker/jobs/78/media",
            },
        )

    def test_transient_progress_failure_retries_before_normal_heartbeat_interval(self):
        client = FlakyProgressClient(failures=1)
        heartbeat = LeaseHeartbeat(
            client,
            self.claim(),
            interval_seconds=2.0,
            retry_seconds=0.05,
        )
        heartbeat.update(40, "Speaker diarization", "Synthetic long-running diarization")
        heartbeat.start()
        try:
            self.assertTrue(client.recovered.wait(timeout=0.5))
        finally:
            heartbeat.stop()

        self.assertGreaterEqual(len(client.calls), 2)
        self.assertLess(client.calls[1] - client.calls[0], 0.4)
        heartbeat.assert_owned()

    def test_explicit_lease_loss_still_stops_heartbeat_immediately(self):
        client = FlakyProgressClient(lease_lost=True)
        heartbeat = LeaseHeartbeat(
            client,
            self.claim(),
            interval_seconds=2.0,
            retry_seconds=0.05,
        )
        heartbeat.update(40, "Speaker diarization", "Synthetic lease loss")
        heartbeat.start()
        try:
            self.assertTrue(client.called.wait(timeout=0.5))
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                try:
                    heartbeat.assert_owned()
                except WorkerLeaseLostError:
                    break
                time.sleep(0.01)
            else:
                self.fail("Heartbeat did not surface definitive lease loss")
            time.sleep(0.1)
        finally:
            heartbeat.stop()

        self.assertEqual(1, len(client.calls))

    def test_default_retry_cadence_is_bounded_below_steady_state_interval(self):
        client = FlakyProgressClient()
        heartbeat = LeaseHeartbeat(client, self.claim(), interval_seconds=30.0)

        self.assertEqual(30.0, heartbeat.interval_seconds)
        self.assertEqual(5.0, heartbeat.retry_seconds)


if __name__ == "__main__":
    unittest.main()
