# AGENTS.md

## Purpose

This repository contains standalone ToolsAPI workers. Workers execute delegated workloads, but ToolsAPI remains the authority for job ownership, lease validity, timeout, retry and persistence.

## Non-negotiable worker rules

- Workers poll ToolsAPI for work. Do not require inbound connectivity from ToolsAPI to worker hosts.
- Job claims must be atomic and produce an opaque lease identifier plus generation/attempt.
- A worker may process or report on a job only while its current lease is valid.
- Heartbeat/progress refreshes ownership through ToolsAPI. Workers never decide that their own lease timeout has been extended.
- Long-running execution must keep heartbeat independent from model output/progress events. A slow model load or a slow segment generator must not make a healthy worker appear dead.
- ToolsAPI decides when a worker has timed out based on the latest accepted report.
- Expired or superseded leases must be rejected for media access, progress, failure and completion submissions.
- Never allow two current lease generations for the same delegated job.
- Completion calls must be safely retryable/idempotent. A worker must not assume completion was accepted when the response is lost.
- A concurrency slot stays occupied while a terminal acknowledgement is unresolved. Do not claim new work merely because a terminal HTTP response was lost.
- The initial executable runtime is serial. Keep `TOOLS_WORKER_CONCURRENCY=1` until parallel runtime ownership has dedicated implementation and tests.

## Workload contracts and reuse

- ToolsAPI sends declarative job requirements, never arbitrary shell/install commands or executable code.
- Handlers and dependencies are installed through normal worker deploy/versioning.
- Each delegated job identifies a handler contract version.
- Workers advertise installed handler versions and capabilities and only claim compatible jobs.
- Live Whisper execution requires a capability-gated ToolsAPI claim policy. Refuse live work when the server does not advertise the required `claim_policy_version`.
- URL-source execution must remain disabled unless the worker explicitly advertises support and the implementation has appropriate URL/network safety. Default to Tools-hosted lease-bound media.
- Keep ToolsAPI business logic in ToolsAPI. Keep worker-side execution logic in this repository or in explicit reusable packages.
- Do not require a checkout of the ToolsAPI repository on worker hosts.
- Contract changes must be documented and tested in both repositories where compatibility can be affected.

## Whisper runtime

- Linux/CPU/CUDA production installation uses the `whisper` package extra and `faster-whisper`.
- Apple Silicon macOS production installation uses the `whisper-mlx` package extra and `mlx-whisper`; select it through the advertised Metal/MLX device capability.
- macOS launchd workers must receive a runtime `PATH` that can resolve the ffmpeg executable validated by the installer. Do not assume launchd inherits Homebrew paths from an interactive shell.
- CPU, CUDA and Apple Silicon Metal/MLX are configuration choices; do not hardcode one device into the contract.
- Supported models are explicit runtime configuration and are advertised on every claim.
- Temporary inputs must live in a per-job directory and be removed only after the ownership lifecycle ends through acknowledged terminal state or lease loss.
- Never dynamically install models, Python packages or arbitrary code based on job payloads.

## Runtime configuration

- `.env.example` is the committed configuration template.
- A real host `.env` must be created during installation when missing.
- The canonical production runtime configuration lives in the installed project directory at `/opt/toolsapi-worker/.env` by default on Ubuntu, `${HOME}/.local/toolsapi-worker/.env` by default on macOS, or `${PREFIX}/.env` when a custom prefix is used.
- Do not move the worker runtime `.env` into `/etc` or another external configuration directory.
- Install, reinstall and deploy must preserve an existing runtime `.env` and its values.
- Uninstall preserves the project `.env` by default unless explicit configuration removal is requested.
- Never commit `.env`, credentials, worker tokens or deployment secrets.

## Testing

Every change affecting leases, claim semantics, heartbeat, retries, installer, configuration or handler contracts requires tests.

Tests should cover at minimum when relevant:

- simultaneous claims produce only one valid lease
- heartbeat extends ownership only when ToolsAPI accepts it
- heartbeat continues while model execution is slow and no new segments are emitted
- stale leases become reassignable
- previous workers cannot submit after reassignment
- duplicate completion requests do not duplicate results
- lost terminal acknowledgements retry the exact same payload without claiming another job
- worker restart does not invent ownership
- capability/contract mismatches are not claimed
- older ToolsAPI claim policies are rejected before live work is consumed
- temporary media is cleaned after acknowledged terminal state or lease loss
- installer is idempotent
- existing runtime `.env` survives reinstall/deploy
- install and uninstall preserve configuration according to documented policy
- macOS launchd installer output can resolve the same ffmpeg directory validated during installation

## Documentation

Update README and CHANGELOG with user-visible, operational or contract changes. Update `docs/contracts.md` or `docs/architecture.md` when protocol semantics change.

## Security

- Use dedicated revocable worker credentials.
- Never grant workers direct database access.
- Use lease-scoped or short-lived access to input media.
- Do not log secrets or raw credentials.
- Keep URL-source fetching disabled by default.
- Remove temporary job inputs according to the ownership/retention rules above.