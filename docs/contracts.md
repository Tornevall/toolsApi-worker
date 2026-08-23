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

ToolsAPI may assign a job only if the worker advertises a compatible handler contract and required capabilities. Capability advertisement/routing is part of the broader worker implementation and is not yet enabled by the first progress-client slice.

## Current Whisper claim endpoint

The first implemented ToolsAPI contract is version `1` of `whisper.transcribe`.

Workers authenticate with their dedicated bearer credential and stable worker id, then call:

`POST /api/whisper/worker/claim`

A successful claim currently contains:

```json
{
  "job_id": 123,
  "contract": "whisper.transcribe",
  "contract_version": 1,
  "lease_id": "opaque-value",
  "generation": 2,
  "lease_expires_at": "2026-08-23T13:45:00+00:00",
  "model": "small",
  "language": "sv"
}
```

`lease_id` is opaque and must never be logged as a credential-like value. `generation` identifies the current ownership generation and changes when an expired job is reassigned.

The worker client also accepts `handler` as an alias for `contract` so the naming can evolve without silently accepting an unknown version.

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

ToolsAPI validates the worker identity, job id, lease id and generation before accepting the update. An accepted progress report refreshes the remote lease and the shared Whisper runtime heartbeat used by web/mobile job polling.

HTTP `409` means the lease is stale, expired or no longer owned by this worker. The worker must treat that response as ownership loss and stop processing as soon as practical.

## Terminal result

Terminal submissions will be idempotent for the current valid lease. That endpoint is not implemented yet and therefore the production polling loop must not claim live jobs solely on the basis of the claim/progress client.

The intended terminal shape remains:

```json
{
  "job_id": 123,
  "lease_id": "opaque-value",
  "generation": 2,
  "status": "completed",
  "result": {}
}
```

ToolsAPI must acknowledge persistence. Until acknowledgement is received, a worker may retry the exact same terminal submission. It must not acquire a second job merely because an acknowledgement was lost if its configured concurrency is exhausted.

## Compatibility

Breaking changes require a new contract version. Existing versions remain supported until deliberately retired. Cross-repository contract fixtures should be shared as versioned JSON examples or a small dedicated schema package, not by importing ToolsAPI application code.
