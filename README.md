# toolsApi-worker

Standalone worker runtime for Tornevall Networks ToolsAPI.

The worker is intentionally generic. Whisper is the first workload, but the runtime is designed to execute delegated ToolsAPI workloads through explicit versioned contracts.

## Design principles

- Workers pull work from ToolsAPI. ToolsAPI does not need inbound access to worker hosts.
- Claiming is atomic and creates a lease.
- A lease remains valid while the worker keeps reporting heartbeat/progress.
- Lease timeout is based on the latest accepted report, not the original claim time.
- Stale leases become eligible for reassignment.
- Late results from expired/superseded leases are rejected.
- ToolsAPI remains the source of truth for jobs, users, permissions, source data and persisted results.
- Workers do not require Laravel, direct database access, a shared filesystem or a checkout of the ToolsAPI repository.
- ToolsAPI describes required workload contracts. It must not send arbitrary install commands or executable code to workers.

See [docs/architecture.md](docs/architecture.md) and [docs/contracts.md](docs/contracts.md).

## Whisper runtime

`whisper.transcribe` now has an executable serial worker lifecycle:

1. Advertise supported contract/model/device capability to ToolsAPI.
2. Claim one compatible job and receive lease id + generation.
3. Download lease-bound Tools-hosted media into a per-job temporary directory.
4. Run `faster-whisper` with the configured model/device/compute type.
5. Report heartbeat independently from transcript segment production so a slow CPU/model load remains visibly alive.
6. Report visible progress as segments are produced.
7. Submit the transcript, segments and safe runtime metadata.
8. Retry the exact same terminal submission after transient API failures until ToolsAPI acknowledges it or rejects the lease.
9. Remove local temporary media after the ownership lifecycle ends.

The initial executable runtime is deliberately serial (`TOOLS_WORKER_CONCURRENCY=1`). Parallel execution will be added only with dedicated ownership/lifecycle coverage.

Live polling also requires ToolsAPI to advertise `claim_policy_version >= 1`. If an older ToolsAPI deployment does not support capability-gated claims, the worker refuses to consume jobs. This makes deploy order safe.

### Initial input scope

`TOOLS_WORKER_ACCEPTS_URL_SOURCES=false` is the default and recommended initial setting. Live remote execution is therefore limited to Tools-hosted upload/staged media. URL-source jobs stay on the local ToolsAPI runner until remote URL fetching is explicitly hardened and enabled. URL jobs that require speaker diarization remain local as well.

## Ubuntu installation

Ubuntu is the primary host platform. The system installer installs the worker plus the `whisper` runtime extra (`faster-whisper>=1.2.1,<2`).

```bash
git clone https://github.com/Tornevall/toolsApi-worker.git
cd toolsApi-worker
sudo ./scripts/install.sh
```

The installer creates a dedicated `toolsapi-worker` system user, installs the package into `/opt/toolsapi-worker/.venv`, creates `/opt/toolsapi-worker/.env` when missing, installs the systemd unit and enables it. Existing project `.env` values are preserved on reinstall/deploy.

After configuring `/opt/toolsapi-worker/.env`:

```bash
sudo systemctl restart toolsapi-worker
sudo systemctl status toolsapi-worker
```

## Configuration

The committed template is `.env.example`. The real host configuration remains inside the installed project at `/opt/toolsapi-worker/.env`.

Core settings:

```text
TOOLS_API_BASE_URL=https://tools.example.test
TOOLS_WORKER_TOKEN=
TOOLS_WORKER_ID=worker-01
TOOLS_WORKER_CONCURRENCY=1
TOOLS_WORKER_POLL_SECONDS=5
TOOLS_WORKER_HEARTBEAT_SECONDS=30
TOOLS_WORKER_ENABLED_HANDLERS=whisper.transcribe
TOOLS_WORKER_WHISPER_MODELS=small
TOOLS_WORKER_WHISPER_DEVICE=cpu
TOOLS_WORKER_WHISPER_COMPUTE_TYPE=int8
TOOLS_WORKER_ACCEPTS_URL_SOURCES=false
TOOLS_WORKER_TEMP_ROOT=/tmp/toolsapi-worker
```

For a CUDA worker, set device/compute type according to the installed host runtime, for example `TOOLS_WORKER_WHISPER_DEVICE=cuda` and an appropriate `faster-whisper` compute type. The worker advertises these values to ToolsAPI but ToolsAPI remains the authority that decides whether a job is eligible.

## Development and tests

```bash
python -m pip install -e .
make check
make smoke-install
```

Protocol/runtime unit tests do not require loading a real Whisper model. The system-install GitHub Actions jobs exercise the actual installer, including the production `whisper` dependency extra.

CI runs on Ubuntu 22.04 and Ubuntu 24.04 across Python 3.10, 3.11 and 3.12, plus root/systemd install-reinstall-uninstall coverage.

## Deployment

`.github/workflows/deploy.yml` supports manual deployment through `workflow_dispatch`. Automatic deployment after a push to `main` is enabled only when repository/environment variable `WORKER_AUTODEPLOY` is `true`.

Deploy ToolsAPI capability-gated claim support before enabling/deploying this executable worker runtime. The worker contains an additional runtime guard and will refuse live claims from an older ToolsAPI deployment.

## Security

- Dedicated revocable worker credentials only.
- No direct database access.
- Lease/generation validation for media, progress and terminal calls.
- No lease/token embedded in media URLs.
- No worker bearer token in raised API errors.
- No live URL-source fetching by default.
- Temporary media isolated per job.

## Agent/development rules

[AGENTS.md](AGENTS.md) records the non-negotiable lease, split-brain, security, documentation and test rules for automated and human contributors.

## Versioning and changes

User-visible and contract changes are recorded in [CHANGELOG.md](CHANGELOG.md). Handler contract changes must document compatibility impact and be covered by tests before merge.

## Related work

- `Tornevall/toolsApi#469` - Remote Whisper worker support
- `Tornevall/toolsApi#710` - Capability/post-processing claim gate
- `Tornevall/toolsApi-worker#5` - Executable Whisper runtime
