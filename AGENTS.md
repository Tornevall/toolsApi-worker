# AGENTS.md

## Purpose

This repository contains standalone ToolsAPI workers. Workers execute delegated workloads, but ToolsAPI remains the authority for job ownership, lease validity, timeout, retry and persistence.

## Non-negotiable worker rules

- Workers poll ToolsAPI for work. Do not require inbound connectivity from ToolsAPI to worker hosts.
- Worker hosts run a continuous service/daemon around the poll loop. Do not replace polling with a periodic scheduler cadence.
- Job claims must be atomic and produce an opaque lease identifier plus generation/attempt.
- A worker may process or report on a job only while its current lease is valid.
- Heartbeat/progress refreshes ownership through ToolsAPI. Workers never decide that their own lease timeout has been extended.
- Long-running execution must keep heartbeat independent from model output/progress events. A slow model load, diarization model load or slow segment generator must not make a healthy worker appear dead.
- ToolsAPI decides when a worker has timed out based on the latest accepted report.
- Expired or superseded leases must be rejected for media access, progress, failure and completion submissions.
- Never allow two current lease generations for the same delegated job.
- Completion calls must be safely retryable/idempotent. A worker must not assume completion was accepted when the response is lost.
- A concurrency slot stays occupied while a terminal acknowledgement is unresolved. Do not claim new work merely because a terminal HTTP response was lost.
- The independent lease heartbeat remains active while terminal acknowledgement is unresolved and stops only after accepted terminal state or definitive lease loss.
- The initial executable runtime is serial. Keep `TOOLS_WORKER_CONCURRENCY=1` until parallel runtime ownership has dedicated implementation and tests.

## Workload contracts and reuse

- ToolsAPI sends declarative job requirements, never arbitrary shell/install commands or executable code.
- Handlers and dependencies are installed through normal worker deploy/versioning.
- Each delegated job identifies a handler contract version.
- Every production worker advertising the current `whisper.transcribe` contract must provide the same ordinary Whisper workload semantics. CPU, CUDA and Metal/MLX may differ in speed and scheduling priority, but they must not create different model, URL-source or diarization feature classes.
- The common Whisper model baseline is `large`, `turbo`, `medium`, `small`, `base`, `tiny`. Host configuration may add implementation-specific models, but it must never narrow a production worker below that baseline.
- Live `whisper.transcribe` workers must have a working speaker-diarization runtime before the first claim poll. A host with missing diarization dependencies, model access or configured device support is unhealthy and must fail startup instead of joining the worker pool with reduced semantics.
- Remote URL-origin work uses one transport contract on every host: ToolsAPI stages/verifies the source and leases it as `tools_media`. This worker runtime must advertise `accepts_url_sources=false` and must not fetch arbitrary external job URLs directly.
- Administrator-selected exact worker targets remain strict scheduling constraints. ToolsAPI may perform neutral preparation such as URL media staging, but another worker must never execute a transcription targeted at a named worker. The selected worker still receives the normal declarative job and lease-bound media contract.
- Live Whisper execution requires a capability-gated ToolsAPI claim policy for protocol safety. Refuse live work when the server does not advertise the required `claim_policy_version` or current contract. Capability fields may describe hardware/runtime telemetry, but the common workload baseline above is not an optional per-host scheduling subset.
- `whisper.transcribe` contract version 2 is diarization-aware. Workers must advertise truthful diarization support, and a production worker must not start live polling until that support is actually available.
- A claim with `diarization_requested=true` must run worker-side diarization before the completion payload is submitted. Do not silently defer a version 2 diarization request back to ToolsAPI.
- `operation=diarize` is diarization-only work against retained media for an already completed transcript. It must never run Whisper, submit transcript text/segments through transcript completion, or turn the existing transcript into a failed transcript job.
- Worker completion may report a diarization failure independently while preserving a successful transcript. Do not convert a completed Whisper transcript into a transcription failure merely because diarization failed.
- Never expose a Hugging Face token value in progress, terminal payloads, logs or error messages. A boolean token-presence diagnostic is allowed.
- Keep ToolsAPI business logic in ToolsAPI. Keep worker-side execution logic in this repository or in explicit reusable packages.
- Do not require a checkout of the ToolsAPI repository on worker hosts.
- Contract changes must be documented and tested in both repositories where compatibility can be affected.

## Whisper runtime

- Linux/CPU/CUDA and native Windows/CPU/CUDA production installation uses the `whisper` package extra and `faster-whisper`.
- Fresh Ubuntu installation must auto-detect the actual executable Whisper backend after dependencies are installed: use CUDA only when CTranslate2 sees a CUDA device and exposes a supported compute type, otherwise use CPU. Existing `.env` device/compute values remain authoritative on reinstall.
- Ubuntu diarization auto-detection is independent from Whisper: use CUDA only after PyTorch both reports CUDA availability and successfully executes a CUDA tensor/kernel probe; otherwise use CPU.
- Apple Silicon macOS production installation uses the `whisper-mlx` package extra and `mlx-whisper`; select it through the advertised Metal/MLX device capability.
- Speaker diarization uses `pyannote.audio` and `pyannote/speaker-diarization-community-1` on Linux, Windows and macOS. The configuration flag remains readable for diagnostics/maintenance, but a live `whisper.transcribe` service must keep diarization enabled and must fail before polling if the runtime is unavailable.
- `toolsapi-worker diagnose diarization` is the portable local diagnostic surface on every supported worker OS. It must never poll/claim ToolsAPI work, must validate real configured pyannote model loading, may optionally run a caller-supplied local audio file, must return non-zero on diagnostic failure, and must never print configured worker or Hugging Face token values. Bounded provider exception detail is allowed only after explicit local secret redaction.
- Python 3.10 or newer is the worker runtime on every supported platform.
- Ubuntu/Debian install paths must bootstrap the matching Python `venv` package automatically when `ensurepip` is missing and apt is available with root/sudo. Do not surface the raw Debian `ensurepip is not available` failure as the final installer result when it is repairable.
- Windows workers are native Windows services. Do not introduce WSL as a runtime dependency and do not use Task Scheduler as the worker execution model. PowerShell is for installation/service administration only; the worker process is the continuous Python poll loop.
- Windows service registration must keep `pythonservice.exe`, the loaded `pythonXX.dll` and `pywintypesXX.dll` inside the worker-controlled Python prefix. Never require writes into the base Python installation or Microsoft Store `WindowsApps` package directory.
- A failed pywin32 install/update command must propagate a non-zero process status. The installer must never continue into registry setup or `Start-Service` after service registration failed.
- Native Windows CUDA must be validated before a worker configured for `cuda` starts. An explicit CUDA configuration must fail closed when CTranslate2/faster-whisper or PyTorch/pyannote cannot execute on the NVIDIA GPU; never silently fall back to CPU.
- Do not treat the maximum CUDA version printed by `nvidia-smi` as the installed worker runtime version. Current CTranslate2/faster-whisper Windows execution requires its documented CUDA 12 cuBLAS/cuDNN runtime even when a newer NVIDIA driver advertises CUDA 13 capability.
- Fresh Windows NVIDIA installs must select the Whisper compute type from CTranslate2's actual reported CUDA capability instead of hard-coding fp16. Preserve preference for `float16`/`int8_float16` on capable GPUs, while allowing `int8_float32` or `float32` on Pascal-class devices such as compute capability 6.1.
- Existing Windows `.env` values remain authoritative for credentials, device, compute type and host-specific settings. An old/narrow `TOOLS_WORKER_WHISPER_MODELS` value must not narrow the effective common model baseline after a worker software upgrade.
- An explicitly configured compute type that is unavailable on the detected GPU must fail clearly with the supported-type set rather than being rewritten.
- PyTorch wheel selection for Windows diarization must consider GPU architecture, not only driver version. Maxwell/Pascal/Volta require the maintained CUDA 12.6 PyTorch compatibility channel while current CUDA 13 wheels target newer architectures; explicit installer overrides remain allowed.
- Windows PyTorch CUDA preflight must execute a real CUDA tensor/kernel operation before accepting the host. `torch.cuda.is_available()` alone is not sufficient because an architecture-incompatible wheel can see the driver but fail when kernels execute.
- Explicit accelerated runtime configuration must be revalidated at every worker process start before the first claim. Installer-time validation alone is insufficient because `.env`, drivers, CUDA libraries and PyTorch builds can change between starts.
- A fresh Windows installation may select CUDA automatically when a native NVIDIA driver is detected, but existing `.env` values remain authoritative and must be preserved.
- macOS launchd workers must receive a runtime `PATH` that can resolve the ffmpeg executable validated by the installer. Do not assume launchd inherits Homebrew paths from an interactive shell.
- CPU, CUDA and Apple Silicon Metal/MLX are configuration choices; do not hardcode one device into the cross-platform contract.
- Pyannote device selection is independent from the Whisper backend. `auto` prefers CUDA, then Apple MPS when available, then CPU. macOS MLX Whisper does not require pyannote to use the same backend.
- The effective model list must always include the common baseline. Additional explicitly configured models may be advertised only when the runtime can execute them.
- Temporary inputs must live in a per-job directory and be removed only after the ownership lifecycle ends through acknowledged terminal state or lease loss.
- Never dynamically install models, Python packages or arbitrary code based on job payloads.

## Runtime configuration

- `.env.example` is the committed configuration template.
- A real host `.env` must be created during installation when missing.
- The canonical production runtime configuration lives in the installed project directory at `/opt/toolsapi-worker/.env` by default on Ubuntu, `${HOME}/.local/toolsapi-worker/.env` by default on macOS, `%ProgramData%\Tornevall\toolsapi-worker\.env` by default on Windows, or `${PREFIX}/.env` when a custom prefix is used.
- Do not move the worker runtime `.env` into `/etc` or another external configuration directory.
- Install, reinstall and deploy must preserve an existing runtime `.env` and its values.
- Fresh-host hardware auto-detection may initialize device/compute values only while creating a previously missing `.env`; it must never rewrite an existing host configuration during reinstall/deploy.
- Uninstall preserves the project `.env` by default unless explicit configuration removal is requested.
- Never commit `.env`, credentials, worker tokens or deployment secrets.

## Testing

Every change affecting leases, claim semantics, heartbeat, retries, installer, configuration or handler contracts requires tests.

Tests should cover at minimum when relevant:

- simultaneous claims produce only one valid lease
- heartbeat extends ownership only when ToolsAPI accepts it
- heartbeat continues while model execution or diarization is slow and no new transcript segments are emitted
- stale leases become reassignable
- previous workers cannot submit after reassignment
- duplicate completion requests do not duplicate results
- lost terminal acknowledgements retry the exact same payload without claiming another job
- worker restart does not invent ownership
- protocol/contract mismatches are not claimed
- every production Whisper worker advertises and executes the common model baseline
- raw URL-source execution is not advertised and remote input uses lease-bound `tools_media`
- live Whisper polling fails before the first claim when diarization is disabled or unavailable
- exact worker targeting is preserved by ToolsAPI while neutral media staging remains allowed
- diarization-only claims never run Whisper and cannot submit or fail the existing transcript
- a successful diarization maps speaker labels onto segments and submits safe structured metadata
- a diarization failure preserves the transcript and never exposes the Hugging Face token value
- local diarization diagnostics load the configured pipeline without claiming live work, support optional audio inference, return non-zero on failure and redact configured worker/Hugging Face token values from exception output
- explicit CUDA configuration does not silently fall back to CPU
- fresh Ubuntu auto-detection selects CUDA only from executable CTranslate2/PyTorch capability and otherwise selects CPU
- missing Ubuntu/Debian `ensurepip`/venv support is repaired through the matching apt venv package when privilege is available
- explicit accelerated devices are validated before capability advertisement and before the first live claim after every process start
- Windows GPU policy covers Pascal compute capability 6.1, a modern fp16-capable capability set, compatible PyTorch CUDA channel selection and explicit index override behavior without requiring a physical CI GPU
- pyannote `auto` device preference selects CUDA before Apple MPS before CPU
- older ToolsAPI claim policies are rejected before live work is consumed
- temporary media is cleaned after acknowledged terminal state or lease loss
- installer is idempotent
- existing runtime `.env` survives reinstall/deploy
- install and uninstall preserve configuration according to documented policy
- macOS launchd installer output can resolve the same ffmpeg directory validated during installation
- Windows service tests verify the explicit worker-local service host/runtime DLL layout, registration failure exit propagation and a real Service Control Manager register/remove cycle on the Windows runner
- Windows PowerShell installer/uninstaller scripts parse on a Windows runner, the native Windows service module imports, and core protocol/runtime tests run on Windows without requiring a live provider or GPU

## Documentation

Update README and CHANGELOG with user-visible, operational or contract changes. Update `docs/contracts.md` or `docs/architecture.md` when protocol semantics change.

## Security

- Use dedicated revocable worker credentials.
- Never grant workers direct database access.
- Use lease-scoped or short-lived access to input media.
- Do not log secrets or raw credentials.
- Keep raw URL-source fetching disabled in the worker runtime; ToolsAPI owns source staging and verification.
- Remove temporary job inputs according to the ownership/retention rules above.