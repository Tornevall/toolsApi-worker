import json
import threading
import time
import unittest
import urllib.error
from io import BytesIO
from unittest.mock import patch

from toolsapi_worker.api import JobSearchClaim, ToolsApiClient, WhisperClaim
from toolsapi_worker.config import WorkerConfig
from toolsapi_worker.job_search import OpenAiJobSearchError, OpenAiJobSearchHandler
from toolsapi_worker.runtime import WorkerRuntime


class _Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _config(enabled_handlers=("job_search.search",)):
    return WorkerConfig(
        api_base_url="https://tools.example.test",
        worker_token="worker-secret",
        worker_id="worker-01",
        concurrency=1,
        poll_seconds=0.05,
        heartbeat_seconds=5,
        enabled_handlers=enabled_handlers,
        whisper_models=("large", "turbo", "medium", "small", "base", "tiny"),
        whisper_device="cpu",
        whisper_compute_type="int8",
        accepts_url_sources=False,
        diarization_enabled=True,
        diarization_provider="pyannote",
        diarization_hf_token="",
        diarization_model="pyannote/speaker-diarization-community-1",
        diarization_model_dir="",
        diarization_min_speakers=None,
        diarization_max_speakers=None,
        diarization_device="cpu",
        temp_root="/tmp/toolsapi-worker-test",
        openai_api_key="openai-worker-secret",
        openai_timeout_seconds=30,
    )


class JobSearchApiClientTest(unittest.TestCase):
    def test_claim_job_search_validates_contract_and_request(self):
        payload = {
            "ok": True,
            "job": {
                "job_id": 42,
                "lease_id": "lease-42",
                "generation": 3,
                "contract": "job_search.search",
                "contract_version": 1,
                "lease_expires_at": "2026-09-20T12:00:00+02:00",
                "provider_request_id": "request-42",
                "request": {
                    "model": "gpt-5.6-sol",
                    "tools": [{"type": "web_search"}],
                    "input": "find jobs",
                },
            },
        }
        client = ToolsApiClient("https://tools.example.test", "worker-secret", "worker-01")

        with patch("toolsapi_worker.api.urllib.request.urlopen", return_value=_Response(payload)):
            claim = client.claim_job_search()

        self.assertIsInstance(claim, JobSearchClaim)
        self.assertEqual(42, claim.job_id)
        self.assertEqual("request-42", claim.provider_request_id)
        self.assertEqual("gpt-5.6-sol", claim.request_payload["model"])

    def test_complete_job_search_uses_worker_lease(self):
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _Response({"ok": True, "accepted": True})

        claim = JobSearchClaim(
            job_id=9,
            lease_id="lease-9",
            generation=2,
            contract="job_search.search",
            contract_version=1,
            lease_expires_at="2026-09-20T12:00:00+02:00",
            provider_request_id="request-9",
            request_payload={"model": "gpt-5.6-sol", "tools": [{"type": "web_search"}]},
        )
        client = ToolsApiClient("https://tools.example.test", "worker-secret", "worker-01")

        with patch("toolsapi_worker.api.urllib.request.urlopen", side_effect=opener):
            client.complete_job_search(claim, {"ok": True, "data": {"id": "resp_1"}})

        self.assertTrue(captured["url"].endswith("/api/job-search/worker/jobs/9/complete"))
        self.assertEqual("lease-9", captured["body"]["lease_id"])
        self.assertEqual(2, captured["body"]["generation"])
        self.assertNotIn("worker-secret", json.dumps(captured["body"]))


class OpenAiJobSearchHandlerTest(unittest.TestCase):
    def test_executes_toolsapi_prepared_web_search_with_stable_idempotency_key(self):
        captured = {}

        def opener(request, timeout):
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _Response({
                "id": "resp_1",
                "status": "completed",
                "output": [],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            })

        claim = JobSearchClaim(
            job_id=1,
            lease_id="lease",
            generation=1,
            contract="job_search.search",
            contract_version=1,
            lease_expires_at="2026-09-20T12:00:00+02:00",
            provider_request_id="stable-request",
            request_payload={
                "model": "gpt-5.6-sol",
                "input": "find jobs",
                "tools": [{"type": "web_search"}],
            },
        )

        result = OpenAiJobSearchHandler(_config(), opener=opener).execute(claim)

        self.assertTrue(result["ok"])
        self.assertEqual("completed", result["data"]["status"])
        self.assertEqual("stable-request", captured["headers"]["Idempotency-key"])
        self.assertEqual(30, captured["timeout"])
        self.assertEqual("find jobs", captured["payload"]["input"])

    def test_incomplete_provider_response_is_returned_to_toolsapi_for_policy_handling(self):
        claim = JobSearchClaim(
            job_id=1,
            lease_id="lease",
            generation=1,
            contract="job_search.search",
            contract_version=1,
            lease_expires_at="2026-09-20T12:00:00+02:00",
            provider_request_id="stable-request",
            request_payload={
                "model": "gpt-5.6-sol",
                "input": "find jobs",
                "tools": [{"type": "web_search"}],
            },
        )
        handler = OpenAiJobSearchHandler(
            _config(),
            opener=lambda *args, **kwargs: _Response({
                "id": "resp_incomplete",
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [{"type": "message", "content": []}],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            }),
        )

        result = handler.execute(claim)

        self.assertTrue(result["ok"])
        self.assertEqual("incomplete", result["data"]["status"])
        self.assertEqual("max_output_tokens", result["data"]["incomplete_details"]["reason"])

    def test_provider_error_redacts_worker_openai_key(self):
        key = "openai-worker-secret"
        raw = json.dumps({
            "error": {
                "message": ("x" * 490) + key + " was rejected",
            },
        }).encode("utf-8")
        error = urllib.error.HTTPError(
            "https://api.openai.com/v1/responses",
            401,
            "Unauthorized",
            {},
            BytesIO(raw),
        )
        handler = OpenAiJobSearchHandler(_config(), opener=lambda *args, **kwargs: (_ for _ in ()).throw(error))
        claim = JobSearchClaim(
            job_id=1,
            lease_id="lease",
            generation=1,
            contract="job_search.search",
            contract_version=1,
            lease_expires_at="2026-09-20T12:00:00+02:00",
            provider_request_id="stable-request",
            request_payload={"model": "gpt-5.6-sol", "tools": [{"type": "web_search"}]},
        )

        with self.assertRaises(OpenAiJobSearchError) as caught:
            handler.execute(claim)

        message = str(caught.exception)
        self.assertNotIn(key, message)
        self.assertNotIn(key[:10], message)
        self.assertIn("[redacted]", message)
        self.assertLessEqual(len(message), 500)


class IndependentWorkloadRuntimeTest(unittest.TestCase):
    def test_job_search_polling_is_not_blocked_by_busy_whisper_slot(self):
        whisper_claim = WhisperClaim(
            job_id=1,
            lease_id="whisper-lease",
            generation=1,
            contract="whisper.transcribe",
            contract_version=2,
            lease_expires_at="2026-09-20T12:00:00+02:00",
            operation="transcribe",
            model="small",
            language="sv",
            diarization_requested=True,
            input={"type": "tools_media", "download_url": "/media/1"},
        )
        job_claim = JobSearchClaim(
            job_id=2,
            lease_id="job-lease",
            generation=1,
            contract="job_search.search",
            contract_version=1,
            lease_expires_at="2026-09-20T12:00:00+02:00",
            provider_request_id="job-request",
            request_payload={"model": "gpt-5.6-sol", "tools": [{"type": "web_search"}]},
        )

        class Client:
            def __init__(self):
                self.whisper_sent = False
                self.job_sent = False

            def claim_whisper(self, **kwargs):
                if not self.whisper_sent:
                    self.whisper_sent = True
                    return whisper_claim
                return None

            def claim_job_search(self):
                if not self.job_sent:
                    self.job_sent = True
                    return job_claim
                return None

        class Diarizer:
            supported = True

        whisper_started = threading.Event()
        whisper_release = threading.Event()
        job_seen = threading.Event()
        stop = threading.Event()

        class Runtime(WorkerRuntime):
            def process_claim(self, claim):
                whisper_started.set()
                whisper_release.wait(2)

            def process_job_search_claim(self, claim):
                job_seen.set()
                stop.set()

        runtime = Runtime(
            _config(("whisper.transcribe", "job_search.search")),
            client=Client(),
            handler=object(),
            diarizer=Diarizer(),
            job_search_handler=object(),
        )

        with patch("toolsapi_worker.runtime.validate_whisper_runtime_device", return_value=None):
            thread = threading.Thread(target=runtime.run_forever, args=(stop,), daemon=True)
            thread.start()
            self.assertTrue(whisper_started.wait(1))
            self.assertTrue(job_seen.wait(1), "Job Search must run while Whisper remains occupied")
            whisper_release.set()
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
