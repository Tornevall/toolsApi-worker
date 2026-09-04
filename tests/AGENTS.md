# Worker test rules

This file supplements the repository-root `AGENTS.md` for `tests/`.

- Keep worker tests deterministic by default; do not require live ToolsAPI, provider credentials, model downloads or GPU hardware for protocol/runtime regressions.
- For heartbeat, lease, progress and terminal behavior, use bounded synthetic timing and fake clients so CI remains fast and repeatable.
- Tests for live transcript progress must assert that transcript payloads are bounded and never contain worker credentials or provider secrets.
- Keep platform-specific live/service checks in their existing dedicated CI jobs; ordinary unit regressions should stay cross-platform where practical.
