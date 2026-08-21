# Changelog

All notable changes to toolsApi-worker are documented here.

## Unreleased

### Added

- Initial standalone worker repository architecture.
- Pull-based polling and atomic claim/lease design.
- Heartbeat-driven lease freshness and ToolsAPI-controlled timeout/reassignment rules.
- Versioned workload contract model.
- Initial `whisper.transcribe` workload direction.
- Documentation requirements and CI validation baseline.
- Ubuntu installer, Makefile, systemd service, installer smoke tests and guarded deployment workflow.
- Canonical host runtime `.env` at `/etc/toolsapi-worker/.env`, exposed to the installed application through `/opt/toolsapi-worker/.env`.
- CI verification that reinstall/deploy preserves existing `.env` values.

### Security

- ToolsAPI remains sole authority for assignment and lease validity.
- Expired or superseded leases must not be able to submit progress or terminal results.
- Workers do not execute arbitrary installation instructions supplied by jobs.
- Runtime `.env` and credentials are never committed; `.env.example` is the repository template.
