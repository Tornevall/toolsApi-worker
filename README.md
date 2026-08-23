# toolsApi-worker

Standalone worker runtime for Tornevall Networks ToolsAPI.

The worker is intentionally generic. Whisper is the first workload, but the runtime is designed to execute any delegated ToolsAPI workload that has an explicit handler contract.

## Design principles

- Workers pull work from ToolsAPI. ToolsAPI does not need inbound access to worker hosts.
- Claiming is atomic and creates a lease.
- A lease remains valid while the worker keeps reporting heartbeats/progress.
- Lease timeout is based on the latest accepted report, not the original claim time.
- Stale leases become eligible for reassignment.
- Late results from expired/superseded leases are rejected.
- ToolsAPI remains the source of truth for jobs, users, permissions, source data and persisted results.
- Workers do not require Laravel, direct database access, a shared filesystem or a checkout of the ToolsAPI repository.
- ToolsAPI describes required workload contracts. It must not send arbitrary install commands or executable code to workers.

## Reusing existing Tools functionality

The worker should not duplicate business logic that belongs to ToolsAPI. Existing functionality is split by responsibility:

- **ToolsAPI owns orchestration:** authentication, authorization, queueing, job metadata, storage, retries, notifications and persistence.
- **Worker owns execution:** CPU/GPU-heavy or isolated processing performed by a versioned handler.
- **Contracts connect them:** each job declares a handler and contract version; each worker advertises which handler versions and capabilities it supports.

A worker claims a job only when its installed handler matches the required contract and capabilities. Dependencies are installed when the worker is deployed or upgraded, never dynamically from arbitrary job instructions.

When reusable execution code exists in ToolsAPI, prefer extracting a stable contract or portable library/package rather than giving the worker runtime access to the full ToolsAPI repository. Cross-repository contract tests should detect incompatible changes.

See [docs/architecture.md](docs/architecture.md) and [docs/contracts.md](docs/contracts.md).

## Initial workload

`whisper.transcribe`

The worker package now contains the ToolsAPI protocol client needed for the full network side of a remote transcription:

- claim a version 1 Whisper job
- preserve lease id + generation
- report heartbeat/progress
- download Tools-hosted media with lease/generation headers
- submit completed transcript text + segments + safe runtime metadata
- submit structured retryable/non-retryable failures
- treat HTTP 409 as ownership loss or terminal-payload conflict

Terminal calls are deliberately retryable with the exact same payload so a lost HTTP acknowledgement does not force the worker to guess whether ToolsAPI persisted the result.

The production `run` loop remains disabled until the executable Whisper handler and terminal acknowledgement loop are complete and tested. The protocol client no longer blocks that work; the remaining part is local execution/lifecycle control.

Planned execution support includes `faster-whisper`, CPU/CUDA execution, model/capability advertisement and retranscription with a requested model.

## Ubuntu installation

Ubuntu is the primary host platform. The repository provides a Makefile and an idempotent system installer.

```bash
git clone https://github.com/Tornevall/toolsApi-worker.git
cd toolsApi-worker
sudo ./scripts/install.sh
```

Or:

```bash
make install-system
```

The installer creates a dedicated `toolsapi-worker` system user, installs the Python package into `/opt/toolsapi-worker/.venv`, creates the runtime configuration directly in the installed project at `/opt/toolsapi-worker/.env`, installs a hardened systemd unit and enables it. It does not start a worker until a non-placeholder ToolsAPI URL and worker token exist.

The runtime `.env` is created from the committed `.env.example` only when `/opt/toolsapi-worker/.env` does not already exist. Reinstall and deploy preserve the existing project `.env` and its secrets. The file is owned by `root:toolsapi-worker` with mode `0640`.

After configuring `/opt/toolsapi-worker/.env`:

```bash
sudo systemctl restart toolsapi-worker
sudo systemctl status toolsapi-worker
```

Uninstall with `make uninstall`. The project `.env` is retained by default; set `REMOVE_CONFIG=true` only when the configuration should also be removed.

## Development and tests

```bash
python -m pip install -e .
make check
make smoke-install
```

`make check` runs compile/import sanity checks and unit tests. `make smoke-install` installs the package into an isolated virtual environment and verifies the CLI. Worker protocol tests mock ToolsAPI HTTP responses so credentials are never required in CI.

## CI and installation testing

GitHub Actions runs on Ubuntu 22.04 and Ubuntu 24.04. CI tests Python 3.10, 3.11 and 3.12, repository/documentation requirements, unit tests, isolated package installation and the actual root/systemd installer. The system installer is run twice to verify idempotency and `/opt/toolsapi-worker/.env` preservation, then uninstalled while confirming the same project configuration remains intact.

## Deployment

`.github/workflows/deploy.yml` supports manual deployment through `workflow_dispatch`. Automatic deployment after a push to `main` is enabled only when repository/environment variable `WORKER_AUTODEPLOY` is set to `true`.

Deployment uses the GitHub `production` Environment and expects these secrets:

- `WORKER_DEPLOY_HOST`
- `WORKER_DEPLOY_USER`
- `WORKER_DEPLOY_PORT` (optional, defaults to 22)
- `WORKER_DEPLOY_SSH_KEY`

The remote host checks out the exact commit SHA and reruns the idempotent installer. Existing `/opt/toolsapi-worker/.env` configuration is preserved. Production Environment protection rules can be used to require approval before deployment.

## Configuration

`.env.example` is the committed template. The real host configuration is `/opt/toolsapi-worker/.env`, inside the installed project directory. Secrets must never be committed. Local development `.env` files are ignored by Git.

`TOOLS_API_BASE_URL`, `TOOLS_WORKER_TOKEN` and `TOOLS_WORKER_ID` identify the ToolsAPI endpoint and dedicated worker credential. The configured token must correspond to a revocable ToolsAPI `provider_whisper_worker` credential whose name matches the worker id.

## Agent/development rules

[AGENTS.md](AGENTS.md) records the non-negotiable lease, split-brain, security, documentation and test rules for automated and human contributors.

## Versioning and changes

User-visible and contract changes are recorded in [CHANGELOG.md](CHANGELOG.md). Handler contract changes must document compatibility impact and be covered by tests before merge.

## Related work

- `Tornevall/toolsApi#468` - Whisper retranscription with another model
- `Tornevall/toolsApi#469` - Remote Whisper worker support
- `Tornevall/toolsApi#471` - Standalone worker repository planning
- `Tornevall/toolsApi#701` - ToolsAPI claim/lease/progress bridge
- `Tornevall/toolsApi#703` - ToolsAPI media + terminal protocol
- `Tornevall/toolsApi-worker#1` - Worker bootstrap
- `Tornevall/toolsApi-worker#3` - Whisper claim/progress client
- `Tornevall/toolsApi-worker#5` - Media/terminal/runtime worker work
