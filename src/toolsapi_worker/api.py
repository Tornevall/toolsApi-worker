from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
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
        payload = self._request("POST", "/api/whisper/worker/claim", {})
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

        payload = self._request(
            "POST",
            f"/api/whisper/worker/jobs/{claim.job_id}/progress",
            body,
        )
        job = payload.get("job")
        if not isinstance(job, dict):
            raise WorkerApiError("ToolsAPI returned an invalid Whisper progress response")
        return job

    def _request(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=encoded,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.worker_token}",
                "X-Tools-Worker-Id": self.worker_id,
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise WorkerAuthenticationError(
                    f"ToolsAPI rejected worker authentication with HTTP {exc.code}"
                ) from exc
            if exc.code == 409:
                raise WorkerLeaseLostError(
                    "ToolsAPI rejected the current Whisper lease; stop processing this job"
                ) from exc
            raise WorkerApiError(f"ToolsAPI worker request failed with HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise WorkerApiError("ToolsAPI worker request could not reach the configured API") from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WorkerApiError("ToolsAPI worker response was not valid JSON") from exc

        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise WorkerApiError("ToolsAPI worker response did not acknowledge the request")

        return payload
