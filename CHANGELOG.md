# Changelog

All notable changes to toolsApi-worker are documented here.

## Unreleased

### Added

- Initial standalone worker repository architecture.
- Pull-based polling and atomic claim/lease design.
- Heartbeat-driven lease freshness and ToolsAPI-controlled timeout/reassignment rules.
- Versioned workload contract model.
- Initial `whisper.transcribe` workload direction.
- Dependency-free ToolsAPI client for version 1 Whisper claim and progress requests.
- Lease-bound Tools-hosted media download support using dedicated worker auth plus lease/generation headers.
- Idempotent Whisper completion and structured failure client calls using the same lease id and generation as the claim.
- Executable serial `faster-whisper` runtime with CPU/CUDA device and compute-type configuration.
- Apple Silicon MLX Whisper runtime selected by Metal/MLX device capability.
- Per-user macOS launchd installer and uninstaller with configuration preservation.
- PEP 668-safe local installation through an isolated project virtual environment.
- Safe `--env-file` configuration loading for launchd and direct CLI execution without shell evaluation.
- macOS CI coverage for local installation, launchd install/reinstall/uninstall and plist validation.
- Independent heartbeat reporting while model loading/transcription is slow, so liveness does not depend on new transcript segments.
- Capability-aware claim advertisement for supported models, device, compute type and URL-source support.
- Per-job temporary media isolation and cleanup after acknowledged terminal state or lease loss.
- Terminal acknowledgement retry that keeps the worker slot occupied and retries the exact same payload after transient API failures.
- Worker protocol handling that preserves lease id/generation and treats HTTP 409 as loss of ownership or terminal-payload conflict.
- Regression coverage for protocol, runtime heartbeat, terminal retry, temp cleanup, configuration and installer behavior.
- Documentation requirements and CI validation baseline.
- Ubuntu installer, Makefile, systemd service, installer smoke tests and guarded deployment workflow.
- Canonical runtime `.env` in the installed project directory at `/opt/toolsapi-worker/.env`.
- CI verification that reinstall/deploy preserves existing project `.env` values and that uninstall retains configuration by default.

### Changed

- `make install` now creates and installs into `.venv` instead of attempting to modify the system/Homebrew Python environment.
- `make install-system` and `make uninstall` dispatch to systemd tooling on Linux and launchd tooling on macOS.
- Corrected `.env.example` so it no longer describes `/etc/toolsapi-worker/.env` as the canonical runtime configuration path.
- Production Linux system installation installs the `whisper` runtime extra with `faster-whisper>=1.2.1,<2`.
- Production Apple Silicon macOS installation installs the `whisper-mlx` runtime extra with `mlx-whisper` and defaults to `device=metal`, `compute_type=float16`, and `large-v3,turbo`.
- `toolsapi-worker run` now executes the live serial polling lifecycle instead of returning the bootstrap placeholder error.
- Live polling requires ToolsAPI `claim_policy_version >= 1`; older server deployments are rejected before any job is consumed.
- URL-source execution remains disabled by default (`TOOLS_WORKER_ACCEPTS_URL_SOURCES=false`). Initial live execution is restricted to lease-bound Tools-hosted media.
- Runtime concurrency is deliberately limited to `1` until parallel ownership/lifecycle handling has dedicated coverage.

### Security

- ToolsAPI remains sole authority for assignment and lease validity.
- Expired or superseded leases must not be able to read Tools-hosted media or submit progress/terminal results.
- Tools-hosted media URLs contain no bearer token or lease secret; lease ownership is supplied through headers.
- Workers do not execute arbitrary installation instructions supplied by jobs.
- Runtime `.env` and credentials are never committed; `.env.example` is the repository template.
- macOS launchd does not source `.env` as shell code; the worker parses configuration data directly so credential values are not executed by a shell.
- Worker client error messages do not include the configured bearer credential.
- Workers refuse live claims from ToolsAPI deployments that do not advertise capability-gated assignment policy.
