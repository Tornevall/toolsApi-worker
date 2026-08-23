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
- Worker protocol handling that preserves lease id/generation and treats HTTP 409 as loss of ownership or terminal-payload conflict.
- Mocked HTTP regression coverage for claim, media download, progress, completion, failure, authentication failures and unsupported contract versions.
- Documentation requirements and CI validation baseline.
- Ubuntu installer, Makefile, systemd service, installer smoke tests and guarded deployment workflow.
- Canonical runtime `.env` in the installed project directory at `/opt/toolsapi-worker/.env`.
- CI verification that reinstall/deploy preserves existing project `.env` values and that uninstall retains configuration by default.

### Changed

- Corrected `.env.example` so it no longer describes `/etc/toolsapi-worker/.env` as the canonical runtime configuration path.
- The production `run` loop remains disabled until the executable Whisper handler and terminal acknowledgement loop are complete; the protocol client can now perform every ToolsAPI-side request needed by that runtime.

### Security

- ToolsAPI remains sole authority for assignment and lease validity.
- Expired or superseded leases must not be able to read Tools-hosted media or submit progress/terminal results.
- Tools-hosted media URLs contain no bearer token or lease secret; lease ownership is supplied through headers.
- Workers do not execute arbitrary installation instructions supplied by jobs.
- Runtime `.env` and credentials are never committed; `.env.example` is the repository template.
- Worker client error messages do not include the configured bearer credential.
