# AGENTS.md

## Scope

This repository contains the standalone ToolsAPI worker runtime. It is not a second ToolsAPI application and must not depend on a checked-out `toolsApi` repository at runtime.

## Non-negotiable worker rules

- ToolsAPI is the sole authority for job assignment, lease timeout, reassignment and terminal acceptance.
- Workers poll. ToolsAPI does not need to open inbound connections to worker hosts.
- A worker may execute only a job for which it holds the current valid lease generation.
- Every heartbeat, progress update and terminal result must include the active job id and lease identity/generation.
- A stale or superseded lease must never be allowed to submit a result.
- Claiming must be atomic. Never introduce a path where two workers can hold valid leases for the same job generation.
- A worker must keep reporting while it processes a job. Timeout is based on the latest report accepted by ToolsAPI.
- After processing finishes, the worker must keep ownership semantics until ToolsAPI accepts the terminal result. Retry the same idempotent completion request if acknowledgement is uncertain.
- Do not execute arbitrary installation commands, packages or code supplied dynamically by ToolsAPI.
- Workload compatibility is negotiated using versioned handler contracts and advertised capabilities.

## Repository boundaries

ToolsAPI owns users, authorization, source data, job state, scheduling, leases and persisted results. The worker owns local execution of explicit handlers.

Do not add direct database access, shared filesystem assumptions or Laravel/PHP dependencies.

## Documentation

Changes to worker behavior or contracts must update the relevant documentation under `docs/` and `CHANGELOG.md`. Installation/deployment changes must update `README.md` when user-facing behavior changes.

## Tests

Every new handler or lease-state behavior must include tests. Changes affecting installation must keep the Ubuntu installation smoke workflow passing. Changes affecting deployment must preserve manual deployment even when automatic deployment is disabled.

## Security

Never commit worker credentials, ToolsAPI tokens, SSH keys or production `.env` files. Worker credentials must be dedicated and revocable, not normal user/admin credentials.
