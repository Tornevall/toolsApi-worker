import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from toolsapi_worker.api import (
    ToolsApiClient,
    WhisperClaim,
    WorkerApiError,
    WorkerAuthenticationError,
    WorkerLeaseLostError,
)


class FakeResponse:
    def __init__(self, payload):
        if isinstance(payload, bytes):
            self.payload = payload
        else:
            self.payload = json.dumps(payload).encode("utf-8")
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        if size is None or size < 0:
            data = self.payload[self.offset :]
            self.offset = len(self.payload)
            return data
        data = self.payload[self.offset : self.offset + size]
        self.offset += len(data)
        return data


class ToolsApiClientTest(unittest.TestCase):
    def setUp(self):
        self.client = ToolsApiClient(
            "https://tools.example.test",
            "worker-secret",
            "worker-mobile-slow",
        )

    def claim(self, input_descriptor=None, diarization_requested=False):
        return WhisperClaim(
            job_id=123,
            lease_id="lease-abc",
            generation=2,
            contract="whisper.transcribe",
            contract_version=2,
            lease_expires_at="2026-09-01T13:45:00+00:00",
            model="small",
            language="sv",
            diarization_requested=diarization_requested,
            input=input_descriptor or {
                "type": "url",
                "url": "https://media.example.test/audio.mp3",
            },
        )

    @patch("urllib.request.urlopen")
    def test_claim_uses_dedicated_worker_headers_and_advertises_capabilities(self, urlopen):
        urlopen.return_value = FakeResponse(
            {
                "ok": True,
                "claim_policy_version": 2,
                "job": {
                    "job_id": 123,
                    "lease_id": "lease-abc",
                    "generation": 2,
                    "contract": "whisper.transcribe",
                    "contract_version": 2,
                    "lease_expires_at": "2026-09-01T13:45:00+00:00",
                    "model": "small",
                    "language": "sv",
                    "diarization_requested": True,
                    "input": {
                        "type": "url",
                        "url": "https://media.example.test/audio.mp3",
                    },
                },
            }
        )

        claim = self.client.claim_whisper(
            models=("small", "medium"),
            device="cpu",
            compute_type="int8",
            accepts_url_sources=False,
            supports_diarization=True,
        )

        self.assertIsInstance(claim, WhisperClaim)
        self.assertEqual(123, claim.job_id)
        self.assertEqual(2, claim.generation)
        self.assertTrue(claim.diarization_requested)
        request = urlopen.call_args.args[0]
        self.assertEqual("Bearer worker-secret", request.get_header("Authorization"))
        self.assertEqual("worker-mobile-slow", request.get_header("X-tools-worker-id"))
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(2, body["contract_version"])
        self.assertEqual(["small", "medium"], body["models"])
        self.assertEqual("cpu", body["device"])
        self.assertEqual("int8", body["compute_type"])
        self.assertFalse(body["accepts_url_sources"])
        self.assertTrue(body["supports_diarization"])

    @patch("urllib.request.urlopen")
    def test_claim_returns_none_when_queue_is_empty(self, urlopen):
        urlopen.return_value = FakeResponse(
            {
                "ok": True,
                "job": None,
                "contract": "whisper.transcribe",
                "contract_version": 2,
                "claim_policy_version": 2,
            }
        )

        self.assertIsNone(self.client.claim_whisper())

    @patch("urllib.request.urlopen")
    def test_claim_refuses_toolsapi_without_current_capability_gate(self, urlopen):
        urlopen.return_value = FakeResponse(
            {
                "ok": True,
                "job": None,
                "contract": "whisper.transcribe",
                "contract_version": 2,
                "claim_policy_version": 1,
            }
        )

        with self.assertRaises(WorkerApiError) as caught:
            self.client.claim_whisper()

        self.assertIn("diarization-aware", str(caught.exception))

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
        claim = self.claim()

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

    @patch("urllib.request.urlopen")
    def test_tools_media_download_uses_lease_headers_and_streams_to_disk(self, urlopen):
        urlopen.return_value = FakeResponse(b"leased-media")
        claim = self.claim(
            {
                "type": "tools_media",
                "download_url": "https://tools.example.test/api/whisper/worker/jobs/123/media",
            }
        )

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "job-123.bin"
            result = self.client.download_whisper_media(claim, destination)
            self.assertEqual(b"leased-media", result.read_bytes())

        request = urlopen.call_args.args[0]
        self.assertEqual("lease-abc", request.get_header("X-tools-lease-id"))
        self.assertEqual("2", request.get_header("X-tools-lease-generation"))
        self.assertEqual("Bearer worker-secret", request.get_header("Authorization"))

    @patch("urllib.request.urlopen")
    def test_completion_and_failure_keep_terminal_payload_bound_to_lease(self, urlopen):
        urlopen.side_effect = [
            FakeResponse({"ok": True, "accepted": True, "duplicate": False, "job": {"id": 123, "status": "completed"}}),
            FakeResponse({"ok": True, "accepted": True, "duplicate": True, "job": {"id": 123, "status": "queued"}}),
        ]
        claim = self.claim(diarization_requested=True)

        completed = self.client.complete_whisper(
            claim,
            "Transcript",
            [{"start": 0, "end": 1.0, "text": "Transcript", "speaker_label": "SPEAKER_00"}],
            {"engine": "faster-whisper", "device": "cpu"},
            {
                "requested": True,
                "status": "completed",
                "provider": "pyannote",
                "speaker_count": 1,
                "speaker_turns": [{"start": 0, "end": 1.0, "speaker": "SPEAKER_00"}],
                "hf_token_present": True,
            },
        )
        failed = self.client.fail_whisper(claim, "worker_error", "Process failed", True)

        self.assertTrue(completed["accepted"])
        self.assertTrue(failed["accepted"])
        completion_request = urlopen.call_args_list[0].args[0]
        completion_body = json.loads(completion_request.data.decode("utf-8"))
        self.assertEqual("lease-abc", completion_body["lease_id"])
        self.assertEqual(2, completion_body["generation"])
        self.assertEqual("Transcript", completion_body["transcript_text"])
        self.assertEqual("completed", completion_body["diarization"]["status"])
        self.assertTrue(completion_body["diarization"]["hf_token_present"])
        failure_request = urlopen.call_args_list[1].args[0]
        failure_body = json.loads(failure_request.data.decode("utf-8"))
        self.assertEqual("worker_error", failure_body["error_code"])
        self.assertTrue(failure_body["retryable"])

    @patch("urllib.request.urlopen")
    def test_409_is_lease_loss(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://tools.example.test/api/whisper/worker/jobs/123/progress",
            409,
            "Conflict",
            {},
            io.BytesIO(b"{}"),
        )

        with self.assertRaises(WorkerLeaseLostError):
            self.client.report_whisper_progress(self.claim(), 50)

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
    def test_unknown_contract_or_input_is_rejected(self, urlopen):
        urlopen.return_value = FakeResponse(
            {
                "ok": True,
                "claim_policy_version": 2,
                "job": {
                    "job_id": 123,
                    "lease_id": "lease-abc",
                    "generation": 2,
                    "contract": "whisper.transcribe",
                    "contract_version": 99,
                    "lease_expires_at": "2026-09-01T13:45:00+00:00",
                    "input": {"type": "url", "url": "https://media.example.test/audio.mp3"},
                },
            }
        )

        with self.assertRaises(WorkerApiError):
            self.client.claim_whisper()


if __name__ == "__main__":
    unittest.main()
