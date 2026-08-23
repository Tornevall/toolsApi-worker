from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class WorkerApiError(RuntimeError):
    """Base error for ToolsAPI worker protocol failures."""


class WorkerAuthenticationError(WorkerApiError):
    """Raised when ToolsAPI rejects the dedicated worker credential."""


class WorkerLeaseLostError(WorkerApiError):
    """Raised when ToolsAPI no longer accepts the current job lease."""


@dataclass(frozen=True)
class WhisperClaim:
    job_id: int
    lease_id: str
    generation: int
    contract: str
    contract_version: int
    lease_expires_at: str
    model: str
    language: str
    diarization_requested: bool
    input: dict[str, Any]

    @property
    def input_type(self) -> str:
        return str(self.input.get("type") or "")


class ToolsApiClient:
    def __init__(
        self,
        base_url: str,
        worker_token: str,
        worker_id: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.worker_token = worker_token.strip()
        self.worker_id = worker_id.strip()
        self.timeout_seconds = timeout_seconds

        if not self.base_url:
            raise ValueError("TOOLS_API_BASE_URL is required")
        if not self.worker_token:
            raise ValueError("TOOLS_WORKER_TOKEN is required")
        if not self.worker_id:
            raise ValueError("TOOLS_WORKER_ID is required")

    def claim_whisper(self) -> WhisperClaim | None:
        payload = self._request_json("POST", "/api/whisper/worker/claim", {})
        job = payload.get("job")
        if job is None:
            return None
        if not isinstance(job, dict):
            raise WorkerApiError("ToolsAPI returned an invalid Whisper claim payload")

        contract = str(job.get("contract") or job.get("handler") or "")
        contract_version = int(job.get("contract_version") or 0)
        if contract != "whisper.transcribe" or contract_version != 1:
            raise WorkerApiError(
                f"Unsupported Whisper worker contract {contract!r} version {contract_version}"
            )

        input_descriptor = job.get("input")
        if not isinstance(input_descriptor, dict):
            raise WorkerApiError("ToolsAPI returned a Whisper claim without an input descriptor")
        if str(input_descriptor.get("type") or "") not in {"url", "tools_media"}:
            raise WorkerApiError("ToolsAPI returned an unsupported Whisper input type")

        try:
            return WhisperClaim(
                job_id=int(job["job_id"]),
                lease_id=str(job["lease_id"]),
                generation=int(job["generation"]),
                contract=contract,
                contract_version=contract_version,
                lease_expires_at=str(job["lease_expires_at"]),
                model=str(job.get("model") or ""),
                language=str(job.get("language") or ""),
                diarization_requested=bool(job.get("diarization_requested", True)),
                input=dict(input_descriptor),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerApiError("ToolsAPI returned an incomplete Whisper claim payload") from exc

    def report_whisper_progress(
        self,
        claim: WhisperClaim,
        progress_percent: int,
        stage_label: str | None = None,
        stage_detail: str | None = None,
    ) -> dict[str, Any]:
        if progress_percent < 0 or progress_percent > 99:
            raise ValueError("progress_percent must be between 0 and 99")

        body: dict[str, Any] = {
            "lease_id": claim.lease_id,
            "generation": claim.generation,
            "progress_percent": progress_percent,
        }
        if stage_label:
            body["stage_label"] = stage_label
        if stage_detail:
            body["stage_detail"] = stage_detail

        payload = self._request_json(
            "POST",
            f"/api/whisper/worker/jobs/{claim.job_id}/progress",
            body,
        )
        job = payload.get("job")
        if not isinstance(job, dict):
            raise WorkerApiError("ToolsAPI returned an invalid Whisper progress response")
        return job

    def download_whisper_media(self, claim: WhisperClaim, destination: str | os.PathLike[str]) -> Path:
        if claim.input_type != "tools_media":
            raise ValueError("download_whisper_media requires a tools_media claim")

        configured_url = str(claim.input.get("download_url") or "").strip()
        if not configured_url:
            raise WorkerApiError("ToolsAPI claim did not include a media download URL")

        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(
            self._absolute_url(configured_url),
            method="GET",
            headers=self._headers(
                accept="application/octet-stream",
                extra={
                    "X-Tools-Lease-Id": claim.lease_id,
                    "X-Tools-Lease-Generation": str(claim.generation),
                },
            ),
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                with destination_path.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
        except urllib.error.HTTPError as exc:
            self._raise_http_error(exc)
        except urllib.error.URLError as exc:
            raise WorkerApiError("ToolsAPI worker media request could not reach the configured API") from exc
        except OSError as exc:
            raise WorkerApiError("Worker could not persist the leased Whisper input media") from exc

        if not destination_path.exists() or destination_path.stat().st_size <= 0:
            raise WorkerApiError("ToolsAPI returned an empty Whisper media response")
        return destination_path

    def complete_whisper(
        self,
        claim: WhisperClaim,
        transcript_text: str,
        segments: list[dict[str, Any]] | None = None,
        runtime: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not transcript_text.strip():
            raise ValueError("transcript_text is required")

        payload = self._request_json(
            "POST",
            f"/api/whisper/worker/jobs/{claim.job_id}/complete",
            {
                "lease_id": claim.lease_id,
                "generation": claim.generation,
                "transcript_text": transcript_text,
                "segments": list(segments or []),
                "runtime": dict(runtime or {}),
            },
        )
        if payload.get("accepted") is not True:
            raise WorkerApiError("ToolsAPI did not acknowledge the Whisper completion")
        return payload

    def fail_whisper(
        self,
        claim: WhisperClaim,
        error_code: str,
        message: str,
        retryable: bool = True,
    ) -> dict[str, Any]:
        if not error_code.strip() or not message.strip():
            raise ValueError("error_code and message are required")

        payload = self._request_json(
            "POST",
            f"/api/whisper/worker/jobs/{claim.job_id}/fail",
            {
                "lease_id": claim.lease_id,
                "generation": claim.generation,
                "error_code": error_code,
                "message": message,
                "retryable": bool(retryable),
            },
        )
        if payload.get("accepted") is not True:
            raise WorkerApiError("ToolsAPI did not acknowledge the Whisper failure")
        return payload

    def _request_json(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self._absolute_url(path),
            data=encoded,
            method=method,
            headers=self._headers(accept="application/json", content_type="application/json"),
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            self._raise_http_error(exc)
        except urllib.error.URLError as exc:
            raise WorkerApiError("ToolsAPI worker request could not reach the configured API") from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WorkerApiError("ToolsAPI worker response was not valid JSON") from exc

        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise WorkerApiError("ToolsAPI worker response did not acknowledge the request")

        return payload

    def _headers(
        self,
        accept: str,
        content_type: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "Authorization": f"Bearer {self.worker_token}",
            "X-Tools-Worker-Id": self.worker_id,
        }
        if content_type:
            headers["Content-Type"] = content_type
        headers.update(extra or {})
        return headers

    def _absolute_url(self, path_or_url: str) -> str:
        value = path_or_url.strip()
        if value.startswith("https://") or value.startswith("http://"):
            if not value.startswith(self.base_url + "/") and value != self.base_url:
                raise WorkerApiError("ToolsAPI returned a media URL outside the configured API origin")
            return value
        if not value.startswith("/"):
            value = "/" + value
        return self.base_url + value

    @staticmethod
    def _raise_http_error(exc: urllib.error.HTTPError) -> None:
        if exc.code in (401, 403):
            raise WorkerAuthenticationError(
                f"ToolsAPI rejected worker authentication with HTTP {exc.code}"
            ) from exc
        if exc.code == 409:
            raise WorkerLeaseLostError(
                "ToolsAPI rejected the current Whisper lease or terminal payload; stop processing this job"
            ) from exc
        raise WorkerApiError(f"ToolsAPI worker request failed with HTTP {exc.code}") from exc
