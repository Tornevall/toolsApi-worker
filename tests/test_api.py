import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from toolsapi_worker.api import (
    ToolsApiClient,
    WhisperClaim,
    WorkerApiError,
    WorkerAuthenticationError,
    WorkerLeaseLostError,
)


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


class ToolsApiClientTest(unittest.TestCase):
    def setUp(self):
        self.client = ToolsApiClient(
            "https://tools.example.test",
            "worker-secret",
            "worker-mobile-slow",
        )

    @patch("urllib.request.urlopen")
    def test_claim_uses_dedicated_worker_headers_and_parses_versioned_contract(self, urlopen):
        urlopen.return_value = FakeResponse(
            {
                "ok": True,
                "job": {
                    "job_id": 123,
                    "lease_id": "lease-abc",
                    "generation": 2,
                    "contract": "whisper.transcribe",
                    "contract_version": 1,
                    "lease_expires_at": "2026-08-23T13:45:00+00:00",
                    "model": "small",
                    "language": "sv",
                },
            }
        )

        claim = self.client.claim_whisper()

        self.assertIsInstance(claim, WhisperClaim)
        self.assertEqual(123, claim.job_id)
        self.assertEqual(2, claim.generation)
        request = urlopen.call_args.args[0]
        self.assertEqual("Bearer worker-secret", request.get_header("Authorization"))
        self.assertEqual("worker-mobile-slow", request.get_header("X-tools-worker-id"))
        self.assertEqual("https://tools.example.test/api/whisper/worker/claim", request.full_url)

    @patch("urllib.request.urlopen")
    def test_claim_returns_none_when_queue_is_empty(self, urlopen):
        urlopen.return_value = FakeResponse(
            {
                "ok": True,
                "job": None,
                "contract": "whisper.transcribe",
                "contract_version": 1,
            }
        )

        self.assertIsNone(self.client.claim_whisper())

    @patch("urllib.request.urlopen")
    def test_progress_sends_current_lease_and_generation(self, urlopen):
        urlopen.return_value = FakeResponse(
            {
                "ok": True,
                "job": {
                    "id": 123,
                    "status": "transcribing",
                    "progress_percent": 47,
                    "stage_label": "Transcribing",
                    "stage_detail": "188 / 401 seconds",
                },
            }
        )
        claim = WhisperClaim(
            job_id=123,
            lease_id="lease-abc",
            generation=2,
            contract="whisper.transcribe",
            contract_version=1,
            lease_expires_at="2026-08-23T13:45:00+00:00",
            model="small",
            language="sv",
        )

        response = self.client.report_whisper_progress(
            claim,
            47,
            "Transcribing",
            "188 / 401 seconds",
        )

        self.assertEqual(47, response["progress_percent"])
        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual("lease-abc", body["lease_id"])
        self.assertEqual(2, body["generation"])
        self.assertEqual(47, body["progress_percent"])
        self.assertEqual("Transcribing", body["stage_label"])

    @patch("urllib.request.urlopen")
    def test_409_is_lease_loss(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://tools.example.test/api/whisper/worker/jobs/123/progress",
            409,
            "Conflict",
            {},
            io.BytesIO(b"{}"),
        )
        claim = WhisperClaim(123, "lease-abc", 2, "whisper.transcribe", 1, "", "small", "sv")

        with self.assertRaises(WorkerLeaseLostError):
            self.client.report_whisper_progress(claim, 50)

    @patch("urllib.request.urlopen")
    def test_authentication_failure_never_includes_worker_secret(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://tools.example.test/api/whisper/worker/claim",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b"{}"),
        )

        with self.assertRaises(WorkerAuthenticationError) as caught:
            self.client.claim_whisper()

        self.assertNotIn("worker-secret", str(caught.exception))

    @patch("urllib.request.urlopen")
    def test_unknown_contract_is_rejected(self, urlopen):
        urlopen.return_value = FakeResponse(
            {
                "ok": True,
                "job": {
                    "job_id": 123,
                    "lease_id": "lease-abc",
                    "generation": 2,
                    "contract": "whisper.transcribe",
                    "contract_version": 99,
                    "lease_expires_at": "2026-08-23T13:45:00+00:00",
                },
            }
        )

        with self.assertRaises(WorkerApiError):
            self.client.claim_whisper()


if __name__ == "__main__":
    unittest.main()
