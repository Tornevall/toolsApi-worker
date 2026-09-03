# GitHub workflow rules

- Production worker runtime fixes merged to `main` must run the production deployment workflow automatically. Do not place the `main` push deployment behind a default-off repository or environment variable.
- Keep `workflow_dispatch` as a manual recovery/redeploy path in addition to automatic `main` deployment.
- Production deployment must install the exact triggering commit and preserve the existing runtime `.env` and credentials.
- Deployment failures must fail the workflow visibly; do not silently skip a configured production deployment after a successful merge.
- Generated Python build output is not a source of truth. Runtime and packaging changes must come from `src/toolsapi_worker` and generated `build/` artifacts must not be committed.
