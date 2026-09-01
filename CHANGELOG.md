# Changelog

All notable changes to toolsApi-worker are documented here.

## Unreleased

### Added

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
- Transcript-preserving diarization failure handling so speaker processing can fail independently from a successful transcription.
- Native Windows service support through pywin32. The service continuously runs the normal polling loop and does not depend on Task Scheduler, WSL or an interactive CMD session.
- Native Windows NVIDIA detection and fail-closed CUDA validation for both CTranslate2/faster-whisper and PyTorch/pyannote before a CUDA-configured service starts.
- Optional Windows installer `-TorchIndexUrl` support for installing the official CUDA-enabled PyTorch wheel channel appropriate for the host.
- Windows CI coverage for deterministic protocol/runtime tests, Windows service module import/compile checks and PowerShell installer syntax/content validation.
- Per-user macOS launchd installer and uninstaller with configuration preservation.
- PEP 668-safe local installation through an isolated project virtual environment.
- Safe `--env-file` configuration loading for launchd and direct CLI execution without shell evaluation.
- macOS CI coverage for local installation, launchd install/reinstall/uninstall and plist validation.
- Independent heartbeat reporting while model loading, transcription or diarization is slow, so liveness does not depend on new transcript segments.
- Capability-aware claim advertisement for supported models, device, compute type, URL-source support and diarization support.
- Per-job temporary media isolation and cleanup after acknowledged terminal state or lease loss.
- Terminal acknowledgement retry that keeps the worker slot occupied and retries the exact same payload after transient API failures.
- Worker protocol handling that preserves lease id/generation and treats HTTP 409 as loss of ownership or terminal-payload conflict.
- Regression coverage for protocol, runtime heartbeat, terminal retry, temp cleanup, diarization, GPU preference, configuration and installer behavior.
- Deterministic regression coverage proving the lease heartbeat continues while diarization itself is blocked.
- Documentation requirements and CI validation baseline.
- Ubuntu installer, Makefile, systemd service, installer smoke tests and guarded deployment workflow.
- Canonical runtime `.env` in the installed project directory at `/opt/toolsapi-worker/.env` on Ubuntu, `~/.local/toolsapi-worker/.env` on macOS and `%ProgramData%\Tornevall\toolsapi-worker\.env` on Windows.
- CI verification that reinstall/deploy preserves existing project `.env` values and that uninstall retains configuration by default.

### Changed

- `whisper.transcribe` is now contract version 2 and requires ToolsAPI `claim_policy_version >= 2`, preventing older workers/servers from silently consuming diarization-required jobs.
- Speaker diarization is enabled by default in worker configuration, can be explicitly disabled with `TOOLS_WORKER_DIARIZATION_ENABLED=false`, and uses `pyannote/speaker-diarization-community-1`.
- Diarization capability advertisement now verifies both the installed pyannote/PyTorch runtime and the configured execution device; an explicit CUDA or Apple GPU device is not advertised when PyTorch cannot use it.
- Explicit accelerator configuration is revalidated on every worker process start before the first claim, so preserved `.env` changes, driver/library changes, or CPU-only PyTorch/CTranslate2 builds cannot cause a worker to advertise and consume GPU work it cannot execute.
- Pyannote `auto` device selection prefers CUDA, then Apple MPS, then CPU.
- Fresh Windows installs automatically select CUDA/fp16 for Whisper and CUDA for diarization when native `nvidia-smi.exe` is available; existing `.env` values remain authoritative.
- Explicit Windows `cuda` configuration no longer permits silent CPU fallback. CTranslate2 must see a native CUDA device and PyTorch must report CUDA availability for enabled CUDA diarization.
- Windows `.env` parsing accepts a UTF-8 BOM written by Windows PowerShell 5.1, so preserved configuration remains usable across reinstall and service startup.
- `make install` now creates and installs into `.venv` instead of attempting to modify the system/Homebrew Python environment.
- `make install-system` and `make uninstall` dispatch to systemd tooling on Linux and launchd tooling on macOS; Windows uses the dedicated elevated PowerShell service installer scripts.
- Corrected `.env.example` so it documents the canonical runtime configuration paths for Ubuntu, macOS and the Windows service.
- Production Linux and Windows installation uses the `whisper` runtime extra with `faster-whisper>=1.2.1,<2`, `pyannote.audio>=4,<5` and PyTorch.
- Production Apple Silicon macOS installation uses the `whisper-mlx` runtime extra with `mlx-whisper`, `pyannote.audio>=4,<5` and PyTorch, and defaults to `device=metal`, `compute_type=float16`, and `large-v3,turbo` for Whisper.
- The macOS launchd installer records an explicit runtime `PATH` containing the resolved ffmpeg directory plus standard Apple Silicon/Homebrew locations, so MLX Whisper can invoke the ffmpeg CLI when launched outside an interactive shell.
- The default idle claim interval is 60 seconds; active-job heartbeat remains independently configured at 30 seconds by default.
- `toolsapi-worker run` executes the live serial polling lifecycle.
- URL-source execution remains disabled by default (`TOOLS_WORKER_ACCEPTS_URL_SOURCES=false`). Initial live execution is restricted to lease-bound Tools-hosted media.
- Runtime concurrency is deliberately limited to `1` until parallel ownership/lifecycle handling has dedicated coverage.

### Security

- ToolsAPI remains sole authority for assignment and lease validity.
- Expired or superseded leases must not be able to read Tools-hosted media or submit progress/terminal results.
- Tools-hosted media URLs contain no bearer token or lease secret; lease ownership is supplied through headers.
- Workers do not execute arbitrary installation instructions supplied by jobs.
- Runtime `.env` and credentials are never committed; `.env.example` is the repository template.
- Hugging Face token values stay local to the worker and are never logged or submitted to ToolsAPI; only a boolean token-presence diagnostic may leave the worker.
- Unclassified pyannote/provider exceptions are reduced to a generic safe error before heartbeat or completion reporting, so configured token values and raw provider text cannot leave the worker through fallback diagnostics.
- macOS launchd and Windows service startup do not source `.env` as executable shell code; the worker parses configuration data directly so credential values are not executed by a shell.
- Worker client error messages do not include the configured bearer credential.
- Workers refuse live claims from ToolsAPI deployments that do not advertise the current diarization-aware capability policy.
