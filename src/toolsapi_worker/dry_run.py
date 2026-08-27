from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Lease:
    job_id: str
    worker_id: str
    lease_id: str
    generation: int
    last_reported_at: int
    completed: bool = False


class DryRunCoordinator:
    """Deterministic in-memory simulation of the ToolsAPI worker lease contract."""

    def __init__(self, timeout_seconds: int = 90) -> None:
        self.timeout_seconds = timeout_seconds
        self.now = 0
        self.generation = 0
        self.active: Lease | None = None

    def advance(self, seconds: int) -> None:
        self.now += seconds

    def claim(self, job_id: str, worker_id: str) -> Lease:
        if self.active and not self.active.completed and not self.is_stale(self.active):
            raise RuntimeError("job already has an active lease")
        self.generation += 1
        self.active = Lease(
            job_id=job_id,
            worker_id=worker_id,
            lease_id=f"lease-{self.generation}",
            generation=self.generation,
            last_reported_at=self.now,
        )
        return self.active

    def is_stale(self, lease: Lease) -> bool:
        return self.now - lease.last_reported_at > self.timeout_seconds

    def heartbeat(self, lease: Lease) -> None:
        self._require_current(lease)
        lease.last_reported_at = self.now

    def complete(self, lease: Lease) -> None:
        self._require_current(lease)
        lease.completed = True

    def _require_current(self, lease: Lease) -> None:
        if self.active is None:
            raise RuntimeError("no active lease")
        if self.is_stale(lease):
            raise RuntimeError("lease expired")
        if (
            lease.job_id != self.active.job_id
            or lease.lease_id != self.active.lease_id
            or lease.generation != self.active.generation
            or lease.worker_id != self.active.worker_id
        ):
            raise RuntimeError("lease superseded")


def run_dry_run() -> dict[str, object]:
    coordinator = DryRunCoordinator(timeout_seconds=90)

    first = coordinator.claim("job-1", "worker-a")
    duplicate_claim_blocked = False
    try:
        coordinator.claim("job-1", "worker-b")
    except RuntimeError:
        duplicate_claim_blocked = True

    coordinator.advance(45)
    coordinator.heartbeat(first)
    heartbeat_extended_lease = first.last_reported_at == 45

    coordinator.advance(91)
    second = coordinator.claim("job-1", "worker-b")
    reassigned_after_timeout = second.generation == first.generation + 1

    stale_completion_blocked = False
    try:
        coordinator.complete(first)
    except RuntimeError:
        stale_completion_blocked = True

    coordinator.heartbeat(second)
    coordinator.complete(second)
    current_completion_accepted = second.completed

    checks = {
        "duplicate_claim_blocked": duplicate_claim_blocked,
        "heartbeat_extended_lease": heartbeat_extended_lease,
        "reassigned_after_timeout": reassigned_after_timeout,
        "stale_completion_blocked": stale_completion_blocked,
        "current_completion_accepted": current_completion_accepted,
    }

    return {
        "ok": all(checks.values()),
        "checks": checks,
        "final_generation": second.generation,
    }
