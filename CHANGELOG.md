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
- Worker protocol handling that preserves lease id/generation and treats HTTP 409 as loss of ownership.
- Mocked HTTP regression coverage for claim, progress, authentication failures and unsupported contract versions.
- Documentation requirements and CI validation baseline.
- Ubuntu installer, Makefile, systemd service, installer smoke tests and guarded deployment workflow.
- Canonical runtime `.env` in the installed project directory at `/opt/toolsapi-worker/.env`.
- CI verification that reinstall/deploy preserves existing project `.env` values and that uninstall retains configuration by default.

### Changed

- Corrected `.env.example` so it no longer describes `/etc/toolsapi-worker/.env` as the canonical runtime configuration path.
- Kept the production `run` loop from claiming live jobs until secure input download and acknowledged terminal result/failure handling are implemented.

### Security

- ToolsAPI remains sole authority for assignment and lease validity.
- Expired or superseded leases must not be able to submit progress or terminal results.
- Workers do not execute arbitrary installation instructions supplied by jobs.
- Runtime `.env` and credentials are never committed; `.env.example` is the repository template.
- Worker client error messages do not include the configured bearer credential.
