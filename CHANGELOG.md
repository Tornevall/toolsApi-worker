# Changelog

All notable changes to toolsApi-worker are documented here.

## Unreleased

### Fixed

- Normalize socket/read/connect timeouts from ToolsAPI JSON requests into retryable worker transport errors so a lost terminal HTTP acknowledgement retries the exact same completion payload instead of escaping into a conflicting `/fail` submission. This repairs the production job #78 failure pattern while preserving HTTP 401/403 authentication and HTTP 409 lease-loss semantics. Fixes #43.
- Keep the independent Whisper lease heartbeat active while transcript completion, failure, or diarization-only terminal acknowledgement is unresolved. Transient terminal retries now retain lease freshness and the occupied worker slot until ToolsAPI accepts the exact payload or definitively rejects ownership; a completion HTTP 409 lease loss cannot fall through into a conflicting failure submission. Fixes #37.
- Remote Whisper now publishes bounded cumulative live transcript text and timestamped segments while transcription is still running. `faster-whisper` streams from its segment iterator and Apple Silicon MLX captures incremental timestamp output, allowing ToolsAPI to show real transcript evidence and progress before terminal completion without writing transcript content to worker logs. Fixes #39.

### Added

- Portable `toolsapi-worker diagnose diarization` host diagnostics for Linux, Windows and macOS. The command safely reports configured/resolved diarization runtime state, verifies that the configured pyannote pipeline can actually load, optionally runs a local audio file through the pipeline, returns non-zero on failure, and redacts worker/Hugging Face token values from local exception details. Fixes #40.
- Initial standalone worker repository architecture.
- Pull-based polling and atomic claim/lease design.
- Heartbeat-driven lease freshness and ToolsAPI-controlled timeout/reassignment rules.
- Versioned workload contract model.
- Initial `whisper.transcribe` workload direction.
- Dependency-free ToolsAPI client for Whisper claim and progress requests.
- Lease-bound Tools-hosted media download support using dedicated worker auth plus lease/generation headers.
- Idempotent Whisper completion and structured failure client calls using the same lease id and generation as the claim.
- Executable serial `faster-whisper` runtime with CPU/CUDA device and compute-type configuration.
- Apple Silicon MLX Whisper runtime selected by Metal/MLX device capability.
- Pyannote Community-1 speaker diarization as part of the normal Whisper runtime on Linux, Windows and macOS.
- Diarization capability advertisement and contract version 2 completion payloads with speaker turns, speaker-labelled segments and safe token-presence diagnostics.
- Diarization-only `operation=diarize` claims with dedicated progress/result endpoints so an available diarization-capable worker can process retained media without rerunning Whisper or modifying an existing transcript.
- Transcript-preserving diarization failure handling so speaker processing can fail independently from a successful transcription.
- Native Windows service support through pywin32. The service continuously runs the normal polling loop and does not depend on Task Scheduler, WSL or an interactive CMD session.
- Native Windows NVIDIA detection and fail-closed CUDA validation for both CTranslate2/faster-whisper and PyTorch/pyannote before a CUDA-configured service starts.
- Optional Windows installer `-TorchIndexUrl` support for installing the official CUDA-enabled PyTorch wheel channel appropriate for the host.
- Windows GPU policy helpers and deterministic Windows regression coverage for Pascal compute capability 6.1, modern fp16-capable GPUs, automatic CUDA 12.6 PyTorch selection for Maxwell/Pascal/Volta and explicit PyTorch index overrides.
- Windows CI coverage for deterministic protocol/runtime tests, Windows service module import/compile checks, real Service Control Manager registration/removal and PowerShell installer syntax/content validation.
- Per-user macOS launchd installer and uninstaller with configuration preservation.
- PEP 668-safe local installation through an isolated project virtual environment.
- Ubuntu/Debian venv bootstrap that installs the matching `pythonX.Y-venv` package (with `python3-venv` fallback) when `ensurepip` is missing and root/sudo is available.
- Fresh Ubuntu runtime auto-detection for CTranslate2 Whisper device/compute type and independent PyTorch diarization device selection, including a real CUDA tensor probe before diarization selects CUDA.
- Safe `--env-file` configuration loading for launchd and direct CLI execution without shell evaluation.
- macOS CI coverage for local installation, launchd install/reinstall/uninstall and plist validation.
- Independent heartbeat reporting while model loading, transcription or diarization is slow, so liveness does not depend on new transcript segments.
- Capability-aware claim advertisement for supported models, device, compute type, URL-source support and diarization support.
- Per-job temporary media isolation and cleanup after acknowledged terminal state or lease loss.
- Terminal acknowledgement retry that keeps the worker slot occupied and retries the exact same payload after transient API failures until ToolsAPI acknowledges it or rejects the lease.
- Worker protocol handling that preserves lease id/generation and treats HTTP 409 as loss of ownership or terminal-payload conflict.
- Regression coverage for protocol, runtime heartbeat, terminal retry, temp cleanup, diarization, GPU preference, configuration and installer behavior.
- Deterministic regression coverage proving the lease heartbeat continues while diarization itself is blocked.
- Regression coverage proving diarization-only claims never invoke Whisper, never submit transcript fields and cannot turn a completed transcript into a failed transcript job.
- Documentation requirements and CI validation baseline.
- Ubuntu installer, Makefile, systemd service, installer smoke tests and guarded deployment workflow.
- Canonical runtime `.env` in the installed project directory at `/opt/toolsapi-worker/.env` on Ubuntu, `~/.local/toolsapi-worker/.env` on macOS and `%ProgramData%\Tornevall\toolsapi-worker\.env` on Windows.
- CI verification that reinstall/deploy preserves existing project `.env` values and that uninstall retains configuration by default.

### Changed

- Production deployment now runs for every push to `main` as well as manual dispatch, so merged worker runtime fixes cannot remain undeployed behind a default-off repository variable.
- Generated `build/` output is no longer tracked as runtime source material. The stale generated copy that still honored narrow `TOOLS_WORKER_WHISPER_MODELS` values was removed, leaving `src/toolsapi_worker` as the canonical implementation.
- Standardized the current production `whisper.transcribe` runtime across CPU, CUDA and Apple Silicon workers. Every live worker now has the common effective model set `large`, `turbo`, `medium`, `small`, `base`, `tiny`; legacy narrower `.env` model lists are preserved on disk but expanded in memory, while additional runtime-specific models remain additive.
- Made a working speaker-diarization runtime part of the production Whisper worker startup contract. A worker with diarization disabled, missing dependencies/model access or an unavailable configured diarization device now fails before the first live claim instead of joining the pool with reduced semantics.
- Stopped advertising raw external URL execution. The compatibility configuration name remains, but the runtime reports `accepts_url_sources=false` and expects ToolsAPI to stage URL-origin media into authenticated lease-bound `tools_media` for every remote worker.
- Preserved administrator-selected exact worker semantics: ToolsAPI may stage media before the claim, but another worker must not execute a transcription explicitly targeted at a named worker. Companion server work is tracked by `Tornevall/toolsApi#1745`; this worker change is tracked by #29.
- Updated fresh macOS installation to retain the MLX-specific `large-v3` option while also declaring the complete common Tools model baseline.
- Clarified exact administrator-target claim semantics for ToolsAPI #1732 / worker #26: a returned current-contract exact-target claim remains authoritative, but current production workers are expected to satisfy the common runtime baseline rather than rely on per-host model/diarization feature subsets.
- Documented that ToolsAPI may intentionally return the existing successful idle `job: null` response to CPU workers while a fresh accelerated worker is online when the administrator GPU-preference scheduling policy is enabled. The worker keeps polling normally; request schema, authentication, lease handling and runtime code are unchanged.
- `whisper.transcribe` is now contract version 2 and requires ToolsAPI `claim_policy_version >= 2`, preventing older workers/servers from silently consuming diarization-required jobs.
- Contract-version-2 claims now accept `operation=transcribe|diarize`; omitted operation remains compatible as `transcribe`, while unknown operations fail closed.
- Speaker diarization is enabled by default in worker configuration and is mandatory for a live `whisper.transcribe` service under the current common runtime contract.
- Diarization capability advertisement now verifies both the installed pyannote/PyTorch runtime and the configured execution device; a worker does not begin live polling when that runtime is unavailable.
- Explicit accelerator configuration is revalidated on every worker process start before the first claim, so preserved `.env` changes, driver/library changes, or CPU-only PyTorch/CTranslate2 builds cannot cause a worker to advertise and consume GPU work it cannot execute.
- Pyannote `auto` device selection prefers CUDA, then Apple MPS, then CPU.
- Fresh Ubuntu system installs now initialize Whisper to the fastest executable detected CTranslate2 backend (`cuda` with the best supported compute type, otherwise `cpu`) and initialize diarization independently to CUDA only after a successful PyTorch CUDA kernel probe; existing `.env` values are never rewritten on reinstall.
- `make install` now uses the shared venv bootstrap helper so a repairable Debian/Ubuntu missing-`ensurepip` failure installs the required apt venv package automatically instead of stopping at the raw Python error.
- Fresh Windows NVIDIA installs no longer hard-code `float16`. The installer queries CTranslate2's actual CUDA compute-type capability and selects the best supported worker type in priority order `float16`, `int8_float16`, `int8_float32`, then `float32`; Pascal GPUs such as GTX 1060 can therefore use `int8_float32` instead of being rejected by the old fp16-only preflight.
- Existing Windows `.env` values remain authoritative for credentials/device/compute settings. An explicitly configured CUDA compute type that the GPU does not support now fails with the exact supported-type list instead of being misreported as a missing CUDA installation.
- Windows GPU diagnostics now distinguish NVIDIA driver visibility from the CUDA 12 cuBLAS/cuDNN 9 runtime required by current CTranslate2/faster-whisper. The maximum CUDA version printed by `nvidia-smi` is no longer treated as the worker runtime version.
- Native Windows pyannote setup automatically uses the official PyTorch CUDA 12.6 wheel channel for Maxwell/Pascal/Volta architectures, while an explicit `-TorchIndexUrl` still overrides automatic selection. `torch` and `torchaudio` are upgraded together.
- Native Windows installation now rejects Microsoft Store `WindowsApps` Python aliases, prefers the Python Launcher when available, installs the PyTorch audio stack before the worker extras, and includes `torchcodec` explicitly so pip failures identify the failing installation phase instead of mixing CPU/GPU resolver churn.
- Windows diarization preflight now executes and synchronizes a real one-element CUDA tensor operation rather than relying only on `torch.cuda.is_available()`, catching architecture-incompatible CUDA wheels before service installation.
- Explicit Windows `cuda` configuration does not permit silent CPU fallback. CTranslate2 must see a native CUDA device and the selected compute type, and PyTorch must execute a CUDA kernel for enabled CUDA diarization.
- Windows `.env` parsing accepts a UTF-8 BOM written by Windows PowerShell 5.1, so preserved configuration remains usable across reinstall and service startup.
- Native Windows service installation and update now place pywin32 `--startup auto` before the `install`/`update` action, matching `win32serviceutil.HandleCommandLine()` syntax instead of falling through to the usage screen and aborting registration.
- Native Windows service registration now prepares an explicit `pythonservice.exe` together with the active `pythonXX.dll` and `pywintypesXX.dll` inside the worker Python prefix. This avoids pywin32 attempting to write helper DLLs into a Microsoft Store Python `WindowsApps` package while giving LocalSystem a worker-controlled service host.
- Native Windows service registration now stages the pywin32 service extension modules and writes both a stable service class and per-service Python import path, fixing SCM startup failures where `pythonservice.exe` could not import `servicemanager`.
- Pywin32 service-registration return codes are now propagated by the worker service module, so failed install/update operations stop the PowerShell installer before registry setup or `Start-Service` instead of being printed and then ignored.
- `make install` now creates and installs into `.venv` instead of attempting to modify the system/Homebrew Python environment.
- `make install-system` and `make uninstall` dispatch to systemd tooling on Linux and launchd tooling on macOS; Windows uses the dedicated elevated PowerShell service installer scripts.
- Corrected `.env.example` so it documents the canonical runtime configuration paths for Ubuntu, macOS and the Windows service.
- Production Linux and Windows installation uses the `whisper` runtime extra with `faster-whisper>=1.2.1,<2`, `pyannote.audio>=4,<5` and PyTorch.
- Production Linux, Windows and Apple Silicon diarization extras now declare the PyTorch audio stack explicitly with `torch>=2.8`, `torchaudio>=2.8` and `torchcodec>=0.7`, matching pyannote.audio 4.x resolver expectations.
- Production Apple Silicon macOS installation uses the `whisper-mlx` runtime extra with `mlx-whisper`, `pyannote.audio>=4,<5` and PyTorch, and defaults to `device=metal`, `compute_type=float16`, the common model baseline plus `large-v3`.
- The macOS launchd installer records an explicit runtime `PATH` containing the resolved ffmpeg directory plus standard Apple Silicon/Homebrew locations, so MLX Whisper can invoke the ffmpeg CLI when launched outside an interactive shell.
- The default idle claim interval is 60 seconds; active-job heartbeat remains independently configured at 30 seconds by default.
- `toolsapi-worker run` executes the live serial polling lifecycle.
- Raw URL-source execution is disabled in the standalone runtime. Remote URL-origin jobs are expected as lease-bound Tools-hosted media after ToolsAPI staging.
- Runtime concurrency is deliberately limited to `1` until parallel ownership/lifecycle handling has dedicated coverage.
- Development version advanced from `0.1.1.dev0` to `0.1.2.dev0` for the Microsoft Store Python/native Windows service registration repair.

### Security

- ToolsAPI remains sole authority for assignment and lease validity.
- Expired or superseded leases must not be able to read Tools-hosted media or submit progress/terminal results.
- Tools-hosted media URLs contain no bearer token or lease secret; lease ownership is supplied through headers.
- Workers do not execute arbitrary installation instructions supplied by jobs.
- Runtime `.env` and credentials are never committed; `.env.example` is the repository template.
- Hugging Face token values stay local to the worker and are never logged or submitted to ToolsAPI; only a boolean token-presence diagnostic may leave the worker.
- Unclassified pyannote/provider exceptions are reduced to a generic safe error before heartbeat or completion reporting, so configured token values and raw provider text cannot leave the worker through fallback diagnostics.
- Local diarization diagnostics may show bounded provider exception detail only on the worker host; configured worker and Hugging Face token values are explicitly redacted before printing.
- Diarization-only terminal payloads cannot contain transcript text or transcript segments and cannot use the transcript failure endpoint.
- macOS launchd and Windows service startup do not source `.env` as executable shell code; the worker parses configuration data directly so credential values are not executed by a shell.
- Worker client error messages do not include the configured bearer credential.
- Workers refuse live claims from ToolsAPI deployments that do not advertise the current diarization-aware capability policy.
- Raw external URL fetching stays outside the worker runtime; ToolsAPI provides lease-bound staged media instead.