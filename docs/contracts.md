# Worker Contracts

Worker contracts are versioned independently from deployment hostnames. API route URLs are not versioned.

## Capability advertisement

The live `whisper.transcribe` claim request advertises the worker execution capability that ToolsAPI may assign against:

```json
{
  "contract_version": 2,
  "models": ["small", "medium"],
  "device": "cuda",
  "compute_type": "float16",
  "accepts_url_sources": false,
  "supports_diarization": true
}
```

ToolsAPI must leave incompatible jobs queued rather than mutating them. A job with `diarization_requested=true` may only be assigned to a version 2 worker that advertises `supports_diarization=true`. Diarization-only work is also restricted to workers that truthfully advertise this capability.

The current worker runtime defaults to `accepts_url_sources=false`, so live execution is restricted to Tools-hosted upload/staged media while URL fetching remains outside the worker runtime.

A successful claim response must include `claim_policy_version >= 2`. Workers enabling live polling refuse claims from older ToolsAPI deployments that do not advertise the diarization-aware capability gate. This protects deployment order: an old server cannot assign a requested diarization job to a worker without checking capability.

The `device` and `compute_type` values describe the installed Whisper backend. CPU/CUDA values select `faster-whisper`; Apple Silicon workers advertise a Metal/MLX device value and use `mlx-whisper`. Speaker diarization remains pyannote-based on all supported platforms and has its own device selection.

On Windows, `device=cuda` means native Windows CUDA. WSL is not part of the worker runtime. A fresh NVIDIA installation derives the advertised compute type from CTranslate2's actual capability set instead of assuming fp16; Pascal-class GPUs may therefore advertise `int8_float32` while newer GPUs can advertise `float16`. Existing explicit `.env` values are preserved and rejected clearly if unsupported. When diarization is configured for CUDA, the worker must prove that PyTorch can execute and synchronize a real CUDA tensor operation before advertising diarization support or polling for live work.

## Whisper claim

Workers authenticate with a dedicated bearer credential and stable worker id, then call:

`POST /api/whisper/worker/claim`

A claim contains the current lease/generation, an explicit operation and an input descriptor:

```json
{
  "job_id": 123,
  "contract": "whisper.transcribe",
  "contract_version": 2,
  "lease_id": "opaque-value",
  "generation": 2,
  "lease_expires_at": "2026-09-01T13:45:00+00:00",
  "operation": "transcribe",
  "model": "small",
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

`input.type` remains `tools_media` or `url` at contract level. Live worker execution currently accepts `tools_media` only. URL-source jobs are not remotely assigned unless a worker explicitly advertises URL support.

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

Both carry the current lease and generation:

```json
{
  "lease_id": "opaque-value",
  "generation": 2,
  "progress_percent": 96,
  "stage_label": "Speaker diarization",
  "stage_detail": "Detecting speaker turns."
}
```

The production runtime reports heartbeat independently of transcript production and diarization progress. Slow Whisper or pyannote model loading can therefore keep the lease alive even while visible progress is unchanged. An accepted update refreshes the lease and the shared Whisper runtime heartbeat used by web/mobile polling.

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
    "compute_type": "float16"
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

Contract version 2 adds explicit diarization capability, structured diarization result data and the `operation` discriminator used for transcript versus diarization-only work. Version 1 workers must not claim version 2 jobs. Existing API route paths remain unchanged and unversioned.
