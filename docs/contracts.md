# Worker Contracts

Worker contracts are versioned independently from deployment hostnames. API route URLs are not versioned.

## Capability advertisement

The live `whisper.transcribe` claim request advertises the worker runtime state:

```json
{
  "contract_version": 2,
  "models": ["large", "turbo", "medium", "small", "base", "tiny"],
  "device": "cuda",
  "compute_type": "int8_float32",
  "accepts_url_sources": false,
  "supports_diarization": true
}
```

All supported production workers use the same ordinary Whisper workload baseline. The required model set is `large`, `turbo`, `medium`, `small`, `base`, `tiny`, and a live worker must have working speaker diarization before it starts polling. CPU, CUDA and Metal/MLX remain meaningful device/performance signals, but they do not define different ordinary job feature classes.

Host configuration may add runtime-specific models such as an MLX-specific model name, but it cannot remove models from the common baseline. Existing narrower `.env` values are upgraded in memory to the common set so a software upgrade does not leave an otherwise healthy worker permanently unable to see ordinary work.

Raw external URL fetching is not part of the standalone worker runtime. Workers advertise `accepts_url_sources=false`; ToolsAPI stages and verifies URL-origin media and returns it through the same lease-bound `tools_media` descriptor used for uploaded or retained media. This keeps source acquisition, URL verification and media ownership on ToolsAPI and gives every worker the same input contract.

A successful claim response must include `claim_policy_version >= 2`. Workers enabling live polling refuse claims from older ToolsAPI deployments that do not advertise the current diarization-aware policy. Worker authentication, current contract version, lease/generation ownership and source-media integrity remain hard protocol boundaries.

The `device` and `compute_type` values describe the installed Whisper backend. CPU/CUDA values select `faster-whisper`; Apple Silicon workers advertise a Metal/MLX device value and use `mlx-whisper`. Speaker diarization remains pyannote-based on all supported platforms and has its own device selection.

On Windows, `device=cuda` means native Windows CUDA. WSL is not part of the worker runtime. A fresh NVIDIA installation derives the advertised compute type from CTranslate2's actual capability set instead of assuming fp16; Pascal-class GPUs may therefore advertise `int8_float32` while newer GPUs can advertise `float16`. Existing explicit device/compute `.env` values are preserved and rejected clearly if unsupported. The worker must also prove that PyTorch/pyannote is executable before it may start live polling.

## Whisper claim

Workers authenticate with a dedicated bearer credential and stable worker id, then call:

`POST /api/whisper/worker/claim`

A successful claim may contain a job or the existing idle result `job: null`. A null job is not an error and the worker must continue its normal poll loop.

ToolsAPI may deliberately return `job: null` because of administrator scheduling policy even when queued work exists. In particular, a CPU worker may be deferred while a fresh accelerated worker is available. This is a priority/capacity choice, not a different workload-capability contract.

An administrator-selected named remote worker is an exact scheduling constraint. ToolsAPI may do neutral preparation before the selected worker claims the job, including downloading and staging URL-origin media, but another worker or the local runner must not execute the transcription. An offline exact target therefore remains queued until that worker returns or an administrator changes the target.

A claim containing work includes the current lease/generation, an explicit operation and an input descriptor:

```json
{
  "job_id": 123,
  "contract": "whisper.transcribe",
  "contract_version": 2,
  "lease_id": "opaque-value",
  "generation": 2,
  "lease_expires_at": "2026-09-01T13:45:00+00:00",
  "operation": "transcribe",
  "model": "medium",
  "language": "sv",
  "diarization_requested": true,
  "input": {
    "type": "tools_media",
    "download_url": "https://tools.example.test/api/whisper/worker/jobs/123/media"
  }
}
```

Supported operations are:

- `transcribe`: run Whisper and, when requested, speaker diarization before transcript completion.
- `diarize`: run only speaker diarization against retained media for an already completed transcript. Whisper must not run and the worker must not submit transcript text or transcript segments through the transcript-completion endpoint.

If `operation` is omitted, workers treat the claim as `transcribe` for compatibility with earlier contract-version-2 responses. Unknown operations are rejected.

The wire parser still recognizes the historical `url` descriptor for compatibility, but the production runtime does not execute it. Current ToolsAPI remote scheduling must stage URL-origin media first and issue `tools_media`.

## Lease-bound media

For `tools_media` claims the worker downloads the source through the supplied URL and sends:

- `Authorization: Bearer <worker credential>`
- `X-Tools-Worker-Id`
- `X-Tools-Lease-Id`
- `X-Tools-Lease-Generation`

ToolsAPI validates current ownership before streaming the file. HTTP `409` means ownership is no longer valid and processing must stop.

## Heartbeat/progress

Transcript operations send progress through:

`POST /api/whisper/worker/jobs/{job_id}/progress`

Diarization-only operations send progress through:

`POST /api/whisper/worker/jobs/{job_id}/diarization/progress`

Both carry the current lease and generation. Transcript operations may additionally send a bounded cumulative live transcript snapshot and timestamped segments:

```json
{
  "lease_id": "opaque-value",
  "generation": 2,
  "progress_percent": 31,
  "stage_label": "Transcribing",
  "stage_detail": "42.0 seconds transcribed · 8 segments received.",
  "transcript_text": "Partial transcript text received so far.",
  "segments": [
    {
      "start": 37.2,
      "end": 42.0,
      "text": "Partial transcript text received so far."
    }
  ]
}
```

Live transcript fields are progress evidence, not terminal state. ToolsAPI may use the latest accepted segment timestamp to derive trustworthy progress and estimated completion while the job remains leased. The final `/complete` submission remains authoritative and still carries the entire final transcript and normalized segment set.

`faster-whisper` publishes live snapshots while consuming its segment iterator. Apple Silicon MLX captures `mlx-whisper`'s incremental timestamped verbose segment output and forwards it through the same bounded progress contract; transcript text is not written to local worker logs. The independent heartbeat remains active even when the backend produces no new segment.

The production runtime reports heartbeat independently of transcript production and diarization progress. Slow Whisper or pyannote model loading can therefore keep the lease alive even while visible progress is unchanged. An accepted update refreshes the lease and the shared Whisper runtime heartbeat used by web/mobile polling.

A transient heartbeat/progress transport failure does not grant or extend ownership locally. After a retryable worker API error, the runtime resubmits the current snapshot on a shorter bounded cadence, by default no slower than one third of the normal heartbeat interval and capped at five seconds, until ToolsAPI accepts an update or definitively rejects the lease. HTTP `409` remains terminal lease loss. Only an accepted ToolsAPI report refreshes the authoritative lease expiry.

The same independent heartbeat remains active while a terminal completion, failure, or diarization result is awaiting acknowledgement or retry. The worker stops it only after ToolsAPI accepts terminal state or definitively rejects the lease, so a transient terminal HTTP/network failure cannot create a lease-expiry gap after expensive processing has finished.

The worker host itself is a continuously running service/daemon around this poll loop. Windows uses a native Windows service, Linux uses systemd and macOS uses launchd. Task Scheduler is not the worker execution model.

## Transcript completion

`operation=transcribe` workers submit completed transcripts through:

`POST /api/whisper/worker/jobs/{job_id}/complete`

```json
{
  "lease_id": "opaque-value",
  "generation": 2,
  "transcript_text": "Example transcript",
  "segments": [
    {
      "start": 0.0,
      "end": 1.2,
      "text": "Example transcript",
      "speaker_label": "SPEAKER_00"
    }
  ],
  "runtime": {
    "engine": "faster-whisper",
    "device": "cuda",
    "compute_type": "int8_float32"
  },
  "diarization": {
    "requested": true,
    "status": "completed",
    "provider": "pyannote",
    "model": "pyannote/speaker-diarization-community-1",
    "speaker_count": 1,
    "speaker_labels": ["SPEAKER_00"],
    "speaker_turns": [
      {"start": 0.0, "end": 1.2, "speaker": "SPEAKER_00"}
    ],
    "labelled_segment_count": 1,
    "hf_token_present": true
  }
}
```

The `diarization` object is safe metadata only. It must never include a Hugging Face token value. `hf_token_present` is a boolean diagnostic and may be submitted. When diarization fails after a successful transcription, the worker still submits the completed transcript with a `failed` or `unavailable` diarization status plus a safe error code/message.

ToolsAPI persists the transcript and normalized diarization result before acknowledging it. Version 2 worker results must not cause a second local diarization pass. The exact same terminal submission may be retried after a lost acknowledgement and returns `duplicate=true`. A conflicting terminal payload for the same lease generation is rejected with HTTP `409`.

## Diarization-only completion

`operation=diarize` is isolated from transcript completion and uses:

`POST /api/whisper/worker/jobs/{job_id}/diarization`

```json
{
  "lease_id": "opaque-value",
  "generation": 3,
  "diarization": {
    "requested": true,
    "status": "completed",
    "provider": "pyannote",
    "speaker_count": 2,
    "speaker_turns": [
      {"start": 0.0, "end": 2.1, "speaker": "SPEAKER_00"},
      {"start": 2.1, "end": 4.0, "speaker": "SPEAKER_01"}
    ]
  }
}
```

A diarization-only worker must never send `transcript_text` or transcript `segments` as part of this terminal operation and must never call the transcript failure endpoint. A diarization-only failure is returned as a safe diarization result with `status=failed` or `status=unavailable`, leaving the already completed transcript untouched.

## Failure

Structured transcript failures use:

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

This endpoint is for failures that prevent a usable transcript. A diarization failure after successful transcription is represented in the transcript completion's diarization metadata. A diarization-only operation uses its dedicated diarization terminal endpoint instead and can therefore never turn an existing completed transcript into a failed transcript job.

Retryable transcript failures return the job to the ToolsAPI queue while attempts remain. Exact duplicate failure submissions are idempotent.

## Worker ownership rule

A worker must not claim new work for a concurrency slot until ToolsAPI has acknowledged the terminal result for the previous job or has explicitly rejected its lease. The initial executable runtime is deliberately serial (`concurrency=1`). Terminal network failures are retried with the exact same payload while the slot remains occupied.

Temporary job media is isolated in a per-job directory and removed only when processing leaves the ownership lifecycle after terminal acknowledgement or lease loss.

## Runtime dependency

Linux and native Windows CPU/CUDA production installation uses the `whisper` package extra with `faster-whisper>=1.2.1,<2`, `pyannote.audio>=4,<5` and PyTorch. Apple Silicon macOS production installation uses the `whisper-mlx` package extra with `mlx-whisper>=0.4.3,<0.5`, `pyannote.audio>=4,<5` and PyTorch.

Current faster-whisper/CTranslate2 CUDA execution requires CUDA 12 cuBLAS and cuDNN 9. Windows must expose the required native DLL directories through the service environment. The `CUDA Version` field shown by `nvidia-smi` describes driver capability and does not select the worker runtime. Fresh Windows NVIDIA installs choose a CTranslate2 compute type from the device's reported set. Pyannote CUDA is independently validated through PyTorch; Maxwell/Pascal/Volta hosts use the maintained CUDA 12.6 PyTorch wheel channel because current CUDA 13 PyTorch builds no longer cover those architectures. Explicit CUDA configuration is fail-closed rather than silently falling back to CPU.

Python 3.10 or newer is required on every supported platform. Windows service installation is PowerShell-based and does not require WSL or an interactive `cmd.exe` runtime. Both Whisper and pyannote modules are imported lazily so protocol-only deterministic tests do not require model loading or live Hugging Face access.

## Compatibility

Contract version 2 remains the current wire contract and existing API route paths remain unchanged and unversioned. Live transcript progress is additive to the existing progress payload; older ToolsAPI deployments ignore none of the required terminal semantics, while current ToolsAPI persists the optional live fields when present. The uniform-worker change tightens production runtime prerequisites and remote source staging without adding a new URL or route namespace. Version 1 workers must not claim version 2 jobs.
