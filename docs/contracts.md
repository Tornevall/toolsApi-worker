# Worker Contracts

Worker contracts are versioned independently from deployment hostnames.

## Capability advertisement

A worker advertises the handler contracts it supports, for example:

```json
{
  "worker_id": "gpu-node-01",
  "handlers": {
    "whisper.transcribe": ["1"]
  },
  "capabilities": {
    "cpu": true,
    "gpu": {
      "available": true,
      "vendor": "nvidia",
      "vram_mb": 12288
    },
    "whisper": {
      "engines": ["faster-whisper"],
      "models": ["small", "medium", "turbo", "large"],
      "compute_types": ["float16", "int8_float16"]
    }
  },
  "concurrency": 1
}
```

Capability advertisement/routing remains part of the broader worker implementation and is not enabled by the protocol client alone.

## Whisper claim

Workers authenticate with a dedicated bearer credential and stable worker id, then call:

`POST /api/whisper/worker/claim`

A claim contains the current lease/generation and an input descriptor:

```json
{
  "job_id": 123,
  "contract": "whisper.transcribe",
  "contract_version": 1,
  "lease_id": "opaque-value",
  "generation": 2,
  "lease_expires_at": "2026-08-23T13:45:00+00:00",
  "model": "small",
  "language": "sv",
  "diarization_requested": false,
  "input": {
    "type": "tools_media",
    "download_url": "https://tools.example.test/api/whisper/worker/jobs/123/media"
  }
}
```

`input.type` is either `tools_media` or `url`. A URL-source claim carries the original external source URL only inside the authenticated claim response. A Tools-hosted media URL contains no bearer token or lease id.

## Lease-bound media

For `tools_media` claims the worker downloads the source through the supplied URL and sends:

- `Authorization: Bearer <worker credential>`
- `X-Tools-Worker-Id`
- `X-Tools-Lease-Id`
- `X-Tools-Lease-Generation`

ToolsAPI validates current ownership before streaming the file. HTTP `409` means ownership is no longer valid and processing must stop.

## Heartbeat/progress

Workers send progress through:

`POST /api/whisper/worker/jobs/{job_id}/progress`

```json
{
  "lease_id": "opaque-value",
  "generation": 2,
  "progress_percent": 42,
  "stage_label": "Transcribing",
  "stage_detail": "168 / 401 seconds"
}
```

An accepted update refreshes the lease and the shared Whisper runtime heartbeat used by web/mobile polling.

## Completion

Workers submit completed transcripts through:

`POST /api/whisper/worker/jobs/{job_id}/complete`

```json
{
  "lease_id": "opaque-value",
  "generation": 2,
  "transcript_text": "Example transcript",
  "segments": [
    {"start": 0.0, "end": 1.2, "text": "Example transcript"}
  ],
  "runtime": {
    "engine": "faster-whisper",
    "device": "cpu",
    "compute_type": "int8"
  }
}
```

ToolsAPI persists the result before acknowledging it. The exact same terminal submission may be retried after a lost acknowledgement and returns `duplicate=true`. A conflicting terminal payload for the same lease generation is rejected with HTTP `409`.

## Failure

Structured failures use:

`POST /api/whisper/worker/jobs/{job_id}/fail`

```json
{
  "lease_id": "opaque-value",
  "generation": 2,
  "error_code": "transcription_failed",
  "message": "Worker process failed",
  "retryable": true
}
```

Retryable failures return the job to the ToolsAPI queue while attempts remain. Exact duplicate failure submissions are idempotent.

## Worker ownership rule

A worker must not claim new work for a concurrency slot until ToolsAPI has acknowledged the terminal result for the previous job or has explicitly rejected its lease. This is especially important when the HTTP acknowledgement is lost after ToolsAPI already persisted a result.

## Compatibility

Breaking changes require a new contract version. Existing versions remain supported until deliberately retired. Cross-repository contract fixtures should be shared as versioned JSON examples or a small dedicated schema package, not by importing ToolsAPI application code.
