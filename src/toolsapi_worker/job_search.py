from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

from .api import JobSearchClaim
from .config import WorkerConfig


class OpenAiJobSearchError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = "openai_request_failed",
        status_code: int = 0,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code
        self.retryable = retryable


class OpenAiJobSearchHandler:
    ENDPOINT = "https://api.openai.com/v1/responses"

    def __init__(
        self,
        config: WorkerConfig,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self.opener = opener or urllib.request.urlopen

    def execute(self, claim: JobSearchClaim) -> dict[str, Any]:
        api_key = self.config.openai_api_key.strip()
        if not api_key:
            raise OpenAiJobSearchError(
                "OpenAI is not configured for the Job Search worker.",
                error_code="openai_not_configured",
                retryable=False,
            )

        payload = dict(claim.request_payload)
        self._validate_payload(payload)

        request = urllib.request.Request(
            self.ENDPOINT,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "toolsapi-worker/job-search",
                "Idempotency-Key": claim.provider_request_id,
            },
        )

        try:
            with self.opener(request, timeout=self.config.openai_timeout_seconds) as response:
                status = int(getattr(response, "status", 200) or 200)
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = ""
            try:
                raw = exc.read().decode("utf-8")
            except Exception:
                raw = ""
            message = self._provider_error_message(raw, exc.code).replace(api_key, "[redacted]")
            raise OpenAiJobSearchError(
                message,
                error_code="openai_http_error",
                status_code=int(exc.code),
                retryable=int(exc.code) in {408, 409, 425, 429, 500, 502, 503, 504},
            ) from exc
        except urllib.error.URLError as exc:
            raise OpenAiJobSearchError(
                "OpenAI could not be reached from this worker.",
                error_code="openai_connection_error",
                retryable=True,
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise OpenAiJobSearchError(
                "OpenAI request timed out or lost the connection.",
                error_code="openai_transport_error",
                retryable=True,
            ) from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OpenAiJobSearchError(
                "OpenAI returned invalid JSON.",
                error_code="openai_invalid_json",
                status_code=status,
                retryable=status >= 500,
            ) from exc

        if not isinstance(data, dict):
            raise OpenAiJobSearchError(
                "OpenAI returned an invalid response object.",
                error_code="openai_invalid_response",
                status_code=status,
                retryable=False,
            )

        response_status = str(data.get("status") or "").strip().lower()
        if response_status and response_status != "completed":
            reason = str(((data.get("incomplete_details") or {}) if isinstance(data.get("incomplete_details"), dict) else {}).get("reason") or "").strip()
            suffix = f" ({reason})" if reason else ""
            raise OpenAiJobSearchError(
                f"OpenAI Responses API returned status {response_status}{suffix}.",
                error_code="openai_incomplete_response",
                status_code=status,
                retryable=response_status in {"queued", "in_progress"},
            )

        return {
            "ok": True,
            "status": status,
            "data": data,
            "diagnostics": {
                "provider": "openai",
                "endpoint": "responses",
                "executed_by": "toolsapi-worker",
            },
        }

    @staticmethod
    def _validate_payload(payload: dict[str, Any]) -> None:
        model = str(payload.get("model") or "").strip()
        if not model:
            raise OpenAiJobSearchError(
                "Job Search claim did not contain an OpenAI model.",
                error_code="invalid_provider_request",
                retryable=False,
            )

        tools = payload.get("tools")
        if not isinstance(tools, list) or not any(
            isinstance(tool, dict) and "web_search" in str(tool.get("type") or "").lower()
            for tool in tools
        ):
            raise OpenAiJobSearchError(
                "Job Search claim did not require OpenAI web search.",
                error_code="invalid_provider_request",
                retryable=False,
            )

    @staticmethod
    def _provider_error_message(raw: str, status: int) -> str:
        message = ""
        if raw:
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    error = payload.get("error")
                    if isinstance(error, dict):
                        message = str(error.get("message") or "").strip()
            except json.JSONDecodeError:
                message = ""

        if not message:
            message = f"OpenAI request failed with HTTP {status}."
        return message[:500]
