# AGENTS.md

## Purpose

This repository contains standalone ToolsAPI workers. Workers execute delegated workloads, but ToolsAPI remains the authority for job ownership, lease validity, timeout, retry and persistence.

## Non-negotiable worker rules

- Workers poll ToolsAPI for work. Do not require inbound connectivity from ToolsAPI to worker hosts.
- Job claims must be atomic and produce an opaque lease identifier plus generation/attempt.
- A worker may process or report on a job only while its current lease is valid.
- Heartbeat/progress refreshes ownership through ToolsAPI. Workers never decide that their own lease timeout has been extended.
- ToolsAPI decides when a worker has timed out based on the latest accepted report.
- Expired or superseded leases must be rejected for progress, failure and completion submissions.
- Never allow two current lease generations for the same delegated job.
- Completion calls must be safely retryable/idempotent. A worker must not assume completion was accepted when the response is lost.
- Workers may claim new work only according to concurrency/capability policy after ToolsAPI has accepted terminal state for prior work.

## Workload contracts and reuse

- ToolsAPI sends declarative job requirements, never arbitrary shell/install commands or executable code.
- Handlers and dependencies are installed through normal worker deploy/versioning.
- Each delegated job identifies a handler contract version.
- Workers advertise installed handler versions and capabilities and only claim compatible jobs.
- Keep ToolsAPI business logic in ToolsAPI. Keep worker-side execution logic in this repository or in explicit reusable packages.
- Do not require a checkout of the ToolsAPI repository on worker hosts.
- Contract changes must be documented and tested in both repositories where compatibility can be affected.

## Runtime configuration

- `.env.example` is the committed configuration template.
- A real host `.env` must be created during installation when missing.
- The canonical production runtime configuration lives in the installed project directory at `/opt/toolsapi-worker/.env` by default, or `${PREFIX}/.env` when a custom prefix is used.
- Do not move the worker runtime `.env` into `/etc` or another external configuration directory.
- Install, reinstall and deploy must preserve an existing runtime `.env` and its values.
- Uninstall preserves the project `.env` by default unless explicit configuration removal is requested.
- Never commit `.env`, credentials, worker tokens or deployment secrets.

## Testing

Every change affecting leases, claim semantics, heartbeat, retries, installer, configuration or handler contracts requires tests.

Tests should cover at minimum when relevant:

- simultaneous claims produce only one valid lease
- heartbeat extends ownership only when ToolsAPI accepts it
- stale leases become reassignable
- previous workers cannot submit after reassignment
- duplicate completion requests do not duplicate results
- worker restart does not invent ownership
- capability/contract mismatches are not claimed
- installer is idempotent
- existing runtime `.env` survives reinstall/deploy
- install and uninstall preserve configuration according to documented policy

## Documentation

Update README and CHANGELOG with user-visible, operational or contract changes. Update `docs/contracts.md` or `docs/architecture.md` when protocol semantics change.

## Security

- Use dedicated revocable worker credentials.
- Never grant workers direct database access.
- Use lease-scoped or short-lived access to input media.
- Do not log secrets or raw credentials.
- Remove temporary job inputs when retention policy requires it.
