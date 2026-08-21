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
- Python package/CLI bootstrap used by installation and smoke tests.
- Makefile with development, test, packaging, system installation and uninstall targets.
- Idempotent Ubuntu/systemd installer and uninstall scripts.
- Hardened systemd service definition.
- `AGENTS.md` with repository invariants for automated and human contributors.
- Ubuntu 22.04/24.04 CI coverage including real installer/idempotency tests.
- Manual and optional automatic production deployment workflow using GitHub Environments and SSH.

### Security

- ToolsAPI remains sole authority for assignment and lease validity.
- Expired or superseded leases must not be able to submit progress or terminal results.
- Workers do not execute arbitrary installation instructions supplied by jobs.
- Production deployment is opt-in and uses environment-scoped secrets.
- System installation preserves worker credentials outside the repository and does not start with placeholder configuration.
