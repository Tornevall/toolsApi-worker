import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from toolsapi_worker.api import ToolsApiClient, WhisperClaim
from toolsapi_worker.runtime import WorkerRuntime


class _FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


class TerminalAcknowledgementRetryTest(unittest.TestCase):
    def test_completion_timeout_retries_exact_same_terminal_payload(self):
        client = ToolsApiClient(
            "https://tools.example.test",
            "worker-secret",
            "test-worker",
            timeout_seconds=0.1,
        )
        claim = WhisperClaim(
            job_id=78,
            lease_id="lease-78",
            generation=3,
            contract="whisper.transcribe",
            contract_version=2,
            lease_expires_at="2026-09-04T15:00:00+02:00",
            operation="transcribe",
            model="large-v3",
            language="sv",
            diarization_requested=True,
            input={"type": "tools_media", "download_url": "/api/whisper/worker/jobs/78/media"},
        )

        runtime = object.__new__(WorkerRuntime)
        runtime.config = SimpleNamespace(poll_seconds=0.01)
        runtime.sleep = lambda _seconds: None

        requests = []
        outcomes = [
            TimeoutError("read operation timed out"),
            _FakeResponse({"ok": True, "accepted": True, "duplicate": True}),
        ]

        def fake_urlopen(request, timeout=None):
            requests.append(request)
            outcome = outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        submit = lambda: client.complete_whisper(
            claim,
            "Stored transcript text.",
            [{"start": 0.0, "end": 1.0, "text": "Stored transcript text.", "speaker_label": "SPEAKER_00"}],
            {"engine": "mlx-whisper", "device": "metal"},
            {
                "requested": True,
                "status": "completed",
                "provider": "pyannote",
                "speaker_count": 1,
                "speaker_labels": ["SPEAKER_00"],
                "speaker_turns": [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}],
                "labelled_segment_count": 1,
            },
        )

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            response = runtime._retry_terminal(submit)

        self.assertTrue(response["accepted"])
        self.assertTrue(response["duplicate"])
        self.assertEqual(2, len(requests))
        self.assertTrue(all(request.full_url.endswith("/api/whisper/worker/jobs/78/complete") for request in requests))
        self.assertEqual(requests[0].data, requests[1].data)
        self.assertNotIn(b"transcription_failed", requests[0].data)
        self.assertNotIn(b"transcription_failed", requests[1].data)


if __name__ == "__main__":
    unittest.main()
