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

`whisper.transcribe` contract version 2 has an executable serial worker lifecycle:

1. Advertise supported contract/model/device capability plus whether the worker can run speaker diarization.
2. Claim one compatible job and receive lease id + generation.
3. Download lease-bound Tools-hosted media into a per-job temporary directory.
4. Run the configured Whisper backend.
5. Report heartbeat independently from transcript production so a slow model load remains visibly alive.
6. If the claim has `diarization_requested=true`, run pyannote speaker diarization on the worker while the same lease heartbeat stays active.
7. Map the detected speaker turns onto Whisper transcript segments.
8. Submit transcript, speaker-labelled segments, safe runtime metadata and a structured diarization result.
9. Retry the exact same terminal submission after transient API failures until ToolsAPI acknowledges it or rejects the lease.
10. Remove local temporary media after the ownership lifecycle ends.

A diarization failure does not discard a successful transcript. The worker submits the transcript together with a separate `failed` or `unavailable` diarization status so ToolsAPI can preserve the text and show the speaker-processing failure independently.

The initial executable runtime is deliberately serial (`TOOLS_WORKER_CONCURRENCY=1`). Parallel execution will be added only with dedicated ownership/lifecycle coverage.

Live polling requires ToolsAPI to advertise `claim_policy_version >= 2`. If an older ToolsAPI deployment does not support the diarization-aware capability gate, the worker refuses to consume jobs. This makes deploy order safe.

### Whisper and diarization backends

Linux and native Windows CPU/CUDA workers use `faster-whisper` through the `whisper` package extra.

Apple Silicon macOS workers use `mlx-whisper` through the `whisper-mlx` package extra. The macOS installer configures `TOOLS_WORKER_WHISPER_DEVICE=metal`, which selects the MLX runtime and allows Whisper inference to use Apple Silicon acceleration. MLX model names are mapped to the corresponding `mlx-community` Whisper repositories.

Speaker diarization uses `pyannote.audio` with `pyannote/speaker-diarization-community-1` on Linux, Windows and macOS. Diarization is enabled by default and can be disabled explicitly with `TOOLS_WORKER_DIARIZATION_ENABLED=false`. The pyannote device is independent from the Whisper backend: `TOOLS_WORKER_DIARIZATION_DEVICE=auto` prefers CUDA, then Apple MPS when available, then CPU.

Python 3.10 or newer is the runtime on all supported platforms. Windows runs as a native Windows service and does not require WSL or an interactive CMD session. PowerShell is used only for installation and service administration; the long-running process is the Python polling runtime.

### Initial input scope

`TOOLS_WORKER_ACCEPTS_URL_SOURCES=false` is the default and recommended initial setting. Live remote execution is therefore limited to Tools-hosted upload/staged media. URL-source jobs stay on the local ToolsAPI runner until remote URL fetching is explicitly hardened and enabled.

## Local installation

`make install` always installs into a project-local `.venv`. It does not modify system Python and therefore works with PEP 668-managed Homebrew Python installations.

```bash
git clone https://github.com/Tornevall/toolsApi-worker.git
cd toolsApi-worker
make install
make status
```

On Apple Silicon macOS, `make install` installs the MLX Whisper extra. On other Unix-like platforms it installs the `faster-whisper` extra. Both extras also install pyannote speaker diarization dependencies.

Run the local worker with:

```bash
make run
```

## macOS Apple Silicon installation

Requirements:

- Apple Silicon Mac (`arm64`)
- Python 3.10 or newer
- `ffmpeg`

Install `ffmpeg` with Homebrew if needed:

```bash
brew install ffmpeg
```

Install the worker as a per-user launchd service:

```bash
make install-system
```

The installer resolves the `ffmpeg` executable from the interactive installation environment and writes an explicit launchd `PATH` containing that directory plus the normal Apple Silicon/Homebrew and system locations. This matters because launchd does not inherit the interactive shell PATH and MLX Whisper launches the `ffmpeg` CLI by name.

The default installed prefix is:

```text
~/.local/toolsapi-worker
```

The canonical host configuration is:

```text
~/.local/toolsapi-worker/.env
```

On first install the macOS installer defaults Whisper to:

```text
TOOLS_WORKER_ID=macos-apple-silicon
TOOLS_WORKER_WHISPER_MODELS=large-v3,turbo
TOOLS_WORKER_WHISPER_DEVICE=metal
TOOLS_WORKER_WHISPER_COMPUTE_TYPE=float16
TOOLS_WORKER_DIARIZATION_ENABLED=true
TOOLS_WORKER_DIARIZATION_DEVICE=auto
```

Set the real ToolsAPI URL, dedicated worker token, a stable unique worker id and the Hugging Face token needed to acquire Community-1 when it is not already local. Never put the token in logs or issue reports. Then rerun:

```bash
make install-system
```

Reinstall preserves the existing `.env`. The service uses `~/Library/LaunchAgents/net.tornevall.toolsapi-worker.plist` and logs to:

```text
~/Library/Logs/toolsapi-worker.log
~/Library/Logs/toolsapi-worker.error.log
```

Uninstall the runtime and launchd service while preserving `.env`:

```bash
make uninstall
```

Remove configuration as well only when explicitly intended:

```bash
REMOVE_CONFIG=true bash ./scripts/uninstall-macos.sh
```

## Windows installation

Requirements:

- Native Windows 10/11 or Windows Server with PowerShell
- Python 3.10 or newer installed for Windows
- `ffmpeg` in the Windows system `PATH` for pyannote audio handling
- For NVIDIA GPU execution: a native Windows NVIDIA driver plus CUDA 12 cuBLAS and cuDNN 9 visible to the service process
- A CUDA-enabled PyTorch build when pyannote should run on the NVIDIA GPU

WSL is not used. The worker is installed directly on Windows so CUDA is exposed directly to faster-whisper/CTranslate2 and PyTorch/pyannote.

From an elevated PowerShell in a repository checkout:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
```

The default prefix is `%ProgramData%\Tornevall\toolsapi-worker`. The installer creates an isolated `.venv`, installs `faster-whisper`, pyannote, PyTorch and the Windows service runtime, preserves an existing `.env`, and registers `ToolsAPIWorker` as an automatic Windows service. The service continuously runs the normal ToolsAPI poll loop; there is no Task Scheduler cadence and no interactive CMD process.

Configure:

```text
%ProgramData%\Tornevall\toolsapi-worker\.env
```

On a fresh installation, if native `nvidia-smi.exe` is available, the installer selects:

```text
TOOLS_WORKER_WHISPER_DEVICE=cuda
TOOLS_WORKER_WHISPER_COMPUTE_TYPE=float16
TOOLS_WORKER_DIARIZATION_DEVICE=cuda
```

It then verifies both GPU paths before the service is installed. The faster-whisper probe requires CTranslate2 to see a CUDA device with a GPU compute type. The diarization probe requires `torch.cuda.is_available()` to be true. An explicitly configured `cuda` device never silently falls back to CPU.

If the normal PyTorch dependency resolved to a CPU-only build, rerun the installer with the official CUDA wheel index appropriate for the host, for example:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1 -TorchIndexUrl "<official PyTorch CUDA index URL>"
```

The installer deliberately does not hardcode a CUDA-specific PyTorch index because the supported CUDA wheel channel changes independently of this repository. Use the current official PyTorch CUDA index for the installed driver/toolchain.

To intentionally disable speaker diarization while keeping Whisper running:

```text
TOOLS_WORKER_DIARIZATION_ENABLED=false
```

Uninstall the Windows service and runtime while preserving `.env`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall-windows.ps1
```

Remove configuration too only when explicitly intended:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall-windows.ps1 -RemoveConfig
```

## Ubuntu installation

Ubuntu remains the primary Linux host platform. The system installer installs the worker plus the `whisper` runtime extra, including faster-whisper and pyannote diarization dependencies.

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

The committed template is `.env.example`. The real host configuration remains inside the installed project directory.

Core settings:

```text
TOOLS_API_BASE_URL=https://tools.example.test
TOOLS_WORKER_TOKEN=
TOOLS_WORKER_ID=worker-01
TOOLS_WORKER_CONCURRENCY=1
TOOLS_WORKER_POLL_SECONDS=60
TOOLS_WORKER_HEARTBEAT_SECONDS=30
TOOLS_WORKER_ENABLED_HANDLERS=whisper.transcribe
TOOLS_WORKER_WHISPER_MODELS=small
TOOLS_WORKER_WHISPER_DEVICE=cpu
TOOLS_WORKER_WHISPER_COMPUTE_TYPE=int8
TOOLS_WORKER_ACCEPTS_URL_SOURCES=false
TOOLS_WORKER_DIARIZATION_ENABLED=true
TOOLS_WORKER_DIARIZATION_PROVIDER=pyannote
TOOLS_WORKER_DIARIZATION_HF_TOKEN=
TOOLS_WORKER_DIARIZATION_MODEL=pyannote/speaker-diarization-community-1
TOOLS_WORKER_DIARIZATION_MODEL_DIR=
TOOLS_WORKER_DIARIZATION_MIN_SPEAKERS=
TOOLS_WORKER_DIARIZATION_MAX_SPEAKERS=
TOOLS_WORKER_DIARIZATION_DEVICE=auto
TOOLS_WORKER_TEMP_ROOT=
```

`TOOLS_WORKER_POLL_SECONDS` is only the idle/no-job and transient claim retry interval. Active-job liveness is independent and uses `TOOLS_WORKER_HEARTBEAT_SECONDS`, so a 60-second idle poll does not weaken a running lease's normal 30-second heartbeat.

`TOOLS_WORKER_DIARIZATION_HF_TOKEN` is only used locally to acquire/access the pyannote model. The worker never submits its value to ToolsAPI. It may report only whether a token was present. `TOOLS_WORKER_DIARIZATION_MODEL_DIR` can point at an already available local Community-1 directory and avoids requiring the job payload to choose or install code.

For a CUDA worker, set `TOOLS_WORKER_WHISPER_DEVICE=cuda` and a suitable `faster-whisper` compute type such as `float16`. Native Windows CUDA requires CUDA 12 cuBLAS and cuDNN 9 for current CTranslate2/faster-whisper releases.

For Apple Silicon, use `TOOLS_WORKER_WHISPER_DEVICE=metal` and `TOOLS_WORKER_WHISPER_COMPUTE_TYPE=float16`. The device value is advertised to ToolsAPI and selects the MLX Whisper backend locally. `TOOLS_WORKER_DIARIZATION_DEVICE=auto` prefers Apple MPS for pyannote when PyTorch reports it available and otherwise uses CPU. ToolsAPI remains the authority that decides whether a job is eligible.

## Development and tests

```bash
python -m pip install -e .
make check
make smoke-install
```

Protocol/runtime unit tests do not require loading a real Whisper or pyannote model. Diarization tests use injected deterministic pipeline doubles and do not make live Hugging Face calls. The Ubuntu system-install GitHub Actions jobs exercise the production `whisper` dependency extra. CI also verifies that `make install` works on macOS without modifying managed system Python and validates that the generated launchd service receives the resolved ffmpeg directory in PATH.

CI runs the core suite on Ubuntu 22.04 and Ubuntu 24.04 across Python 3.10, 3.11 and 3.12, plus Ubuntu root/systemd install-reinstall-uninstall coverage, macOS local/install coverage and Windows native protocol/runtime tests with PowerShell/service syntax validation. CI does not pretend to provide a physical NVIDIA GPU; native CUDA is validated by the Windows installer on actual GPU hosts before the service starts.

## Deployment

`.github/workflows/deploy.yml` supports manual deployment through `workflow_dispatch`. Automatic deployment after a push to `main` is enabled only when repository/environment variable `WORKER_AUTODEPLOY` is `true`.

Deploy the ToolsAPI diarization-aware contract/policy support before enabling/deploying this worker runtime. The worker contains an additional runtime guard and refuses live claims from an older ToolsAPI deployment.

## Security

- Dedicated revocable worker credentials only.
- No direct database access.
- Lease/generation validation for media, progress and terminal calls.
- No lease/token embedded in media URLs.
- No worker bearer token or Hugging Face token in raised API errors or terminal payloads.
- No live URL-source fetching by default.
- Temporary media isolated per job.

## Agent/development rules

[AGENTS.md](AGENTS.md) records the non-negotiable lease, split-brain, security, documentation and test rules for automated and human contributors.

## Versioning and changes

User-visible and contract changes are recorded in [CHANGELOG.md](CHANGELOG.md). Handler contract changes must document compatibility impact and be covered by tests before merge.

## Related work

- `Tornevall/toolsApi#469` - Remote Whisper worker support
- `Tornevall/toolsApi#710` - Capability/post-processing claim gate
- `Tornevall/toolsApi#1585` - Enable diarization by default and require remote workers to execute it
- `Tornevall/toolsApi-worker#5` - Executable Whisper runtime
- `Tornevall/toolsApi-worker#8` - macOS and Apple Silicon MLX worker support
- `Tornevall/toolsApi-worker#10` - macOS ffmpeg PATH and idle polling follow-up
- `Tornevall/toolsApi-worker#13` - Cross-platform worker diarization
