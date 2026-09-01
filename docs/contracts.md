# Worker Contracts

Worker contracts are versioned independently from deployment hostnames.

## Capability advertisement

The live `whisper.transcribe` claim request advertises the worker execution capability that ToolsAPI may assign against:

```json
{
  "contract_version": 1,
  "models": ["small", "medium"],
  "device": "cpu",
  "compute_type": "int8",
  "accepts_url_sources": false
}
```

ToolsAPI must leave incompatible jobs queued rather than mutating them. The current worker runtime defaults to `accepts_url_sources=false`, so live execution is restricted to Tools-hosted upload/staged media while URL fetching remains outside the worker runtime.

A successful claim response must include `claim_policy_version >= 1`. Workers enabling live polling refuse claims from older ToolsAPI deployments that do not advertise this capability gate. This protects deployment order: the worker cannot start consuming jobs against an older server that would ignore its supported models or source restrictions.

The `device` and `compute_type` values also describe the installed execution backend. CPU/CUDA values select `faster-whisper`; Apple Silicon workers advertise a Metal/MLX device value and use `mlx-whisper`. This does not change the worker contract or ownership semantics.

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
  "diarization_requested": true,
  "input": {
    "type": "tools_media",
    "download_url": "https://tools.example.test/api/whisper/worker/jobs/123/media"
  }
}
```

`input.type` remains `tools_media` or `url` at contract level. Live worker execution currently accepts `tools_media` only. URL-source jobs are not remotely assigned unless a worker explicitly advertises URL support, and URL jobs that request speaker diarization remain local until the remote path can preserve that post-processing behavior.

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

The production runtime reports heartbeat independently of segment production. A slow model load or slow transcription can therefore keep the lease alive even while the visible progress percentage is unchanged. An accepted update refreshes the lease and the shared Whisper runtime heartbeat used by web/mobile polling.

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

A worker must not claim new work for a concurrency slot until ToolsAPI has acknowledged the terminal result for the previous job or has explicitly rejected its lease. The initial executable runtime is deliberately serial (`concurrency=1`). Terminal network failures are retried with the exact same payload while the slot remains occupied.

Temporary job media is isolated in a per-job directory and removed only when processing leaves the ownership lifecycle after terminal acknowledgement or lease loss.

## Runtime dependency

Linux CPU/CUDA production installation uses the `whisper` package extra with `faster-whisper>=1.2.1,<2`. Apple Silicon macOS production installation uses the `whisper-mlx` package extra with `mlx-whisper>=0.4.3,<0.5`. Both modules are imported lazily by their execution handlers so protocol-only unit tests do not require model runtime loading.

## Compatibility

Breaking changes require a new contract version. Existing versions remain supported until deliberately retired. Cross-repository contract fixtures should be shared as versioned JSON examples or a small dedicated schema package, not by importing ToolsAPI application code.
