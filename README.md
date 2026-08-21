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

Planned runtime support includes `faster-whisper`, CPU/CUDA execution, model/capability advertisement and retranscription with a requested model.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

## CI

GitHub Actions validates the package on supported Python versions, runs unit/contract tests, checks that core documentation exists and verifies that the package can be built.

## Configuration

Copy `.env.example` and provide a ToolsAPI endpoint and dedicated worker credential. Secrets must never be committed.

## Versioning and changes

User-visible and contract changes are recorded in [CHANGELOG.md](CHANGELOG.md). Handler contract changes must document compatibility impact and be covered by tests before merge.

## Related work

- `Tornevall/toolsApi#468` - Whisper retranscription with another model
- `Tornevall/toolsApi#469` - Remote Whisper worker support
- `Tornevall/toolsApi#471` - Standalone worker repository planning
- `Tornevall/toolsApi-worker#1` - Worker bootstrap
