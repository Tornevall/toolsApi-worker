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

ToolsAPI may assign a job only if the worker advertises a compatible handler contract and required capabilities.

## Claim response

A successful claim should contain an opaque lease and immutable generation:

```json
{
  "job_id": 123,
  "handler": "whisper.transcribe",
  "contract_version": "1",
  "lease_id": "opaque-value",
  "generation": 2,
  "lease_timeout_seconds": 120,
  "input": {
    "download_url": "short-lived-lease-bound-url"
  },
  "payload": {}
}
```

## Heartbeat/progress

Every report includes `job_id`, `lease_id` and `generation`. ToolsAPI validates all three before updating `last_reported_at`.

```json
{
  "job_id": 123,
  "lease_id": "opaque-value",
  "generation": 2,
  "state": "running",
  "progress": 42,
  "stage": "transcribing"
}
```

A rejected heartbeat means the worker no longer owns the job and must stop processing as soon as practical.

## Terminal result

Terminal submissions are idempotent for the current valid lease.

```json
{
  "job_id": 123,
  "lease_id": "opaque-value",
  "generation": 2,
  "status": "completed",
  "result": {}
}
```

ToolsAPI acknowledges persistence. Until acknowledgement is received, a worker may retry the exact same terminal submission. It must not acquire a second job merely because an acknowledgement was lost if its configured concurrency is exhausted.

## Compatibility

Breaking changes require a new contract version. Existing versions remain supported until deliberately retired. Cross-repository contract fixtures should be shared as versioned JSON examples or a small dedicated schema package, not by importing ToolsAPI application code.
