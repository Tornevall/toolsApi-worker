# Architecture

## Authority model

ToolsAPI is the sole authority for job state, assignment, timeout and reassignment.

Workers use a pull model:

1. Poll ToolsAPI for eligible work while advertising installed workload capabilities.
2. Atomically claim one compatible job.
3. Receive an opaque lease identifier and generation/attempt.
4. Process only while that lease remains valid.
5. Send heartbeat/progress reports while processing, including long model-load and diarization phases.
6. Submit a terminal result using the same lease.
7. Continue polling only after ToolsAPI has accepted the terminal result or explicitly indicates that the lease is no longer valid.

A worker must never decide by itself that an assigned job has timed out or become available to another worker.

## Lease safety

For each delegated job, ToolsAPI stores at least:

- job id
- worker id
- lease id/token
- lease generation/attempt
- claimed timestamp
- latest accepted report timestamp
- configurable stale timeout
- state

The effective timeout is calculated from the latest accepted heartbeat/progress/result-related report. A long-running process therefore stays assigned as long as it remains alive and reports within the configured interval.

When ToolsAPI decides that a lease is stale:

- the old lease is invalidated,
- the generation/attempt is advanced,
- the job may become claimable again,
- every later update from the old lease is rejected.

The claim transition must be atomic. At no time may two workers hold valid leases for the same job generation.

## Worker loop

A worker can be busy and still communicate with ToolsAPI. Heartbeat/reporting runs independently from the workload handler so a slow Whisper model invocation or pyannote diarization model load cannot accidentally stop liveness reports.

After successful completion, the worker reports the result and waits for acknowledgement. Only an acknowledged terminal result completes ownership from the worker's perspective. If acknowledgement is lost, the worker retries the same idempotent result request with the same lease rather than assuming completion.

## Inputs and outputs

ToolsAPI owns persisted inputs and outputs. A worker never needs direct database or shared-filesystem access.

For media jobs, ToolsAPI issues lease-bound authenticated download access. Workers download to temporary local storage and remove temporary data after the ownership lifecycle finishes.

For `whisper.transcribe` contract version 2, the worker returns the transcript plus structured diarization metadata when requested. ToolsAPI remains canonical for persisted speaker-aware presentation, but it does not rerun a diarization step already executed by a version 2 worker.

A successful transcript and a diarization failure are separate outcomes. The worker submits the transcript and safe diarization error metadata together so ToolsAPI can preserve the text instead of failing the whole transcription.

## Code ownership and reuse

Do not give a production worker a checkout of the ToolsAPI repository as a runtime dependency.

Responsibilities are split as follows:

- ToolsAPI: business rules, authorization, storage, scheduling, retry policy, notification, persistence and presentation.
- toolsApi-worker: generic worker protocol plus execution handlers, including the requested Whisper and pyannote execution on the worker host.
- Shared contracts: versioned schemas describing requests, capabilities, progress and results.

When execution code is genuinely reusable across repositories, extract it into a versioned package/library with its own tests instead of importing application internals from ToolsAPI.

ToolsAPI must not remotely instruct workers to install arbitrary packages or execute arbitrary code. Workers advertise installed handler versions and capabilities. ToolsAPI only assigns compatible jobs.

## Whisper workload

The initial handler is `whisper.transcribe`. ToolsAPI keeps the canonical audio and transcript records; the worker performs transcription execution and, when requested, speaker diarization before returning structured data and runtime metadata.

Execution is platform-specific behind the same worker lifecycle:

- Linux CPU/CUDA: `faster-whisper` plus pyannote.
- Windows CPU/CUDA: `faster-whisper` plus pyannote, installed and launched through PowerShell tooling without requiring an interactive CMD session.
- Apple Silicon macOS: `mlx-whisper` for transcription plus pyannote for speaker diarization.

Backend selection never changes lease ownership, heartbeat, retry or terminal acknowledgement rules.
