import unittest

from toolsapi_worker.dry_run import DryRunCoordinator, run_dry_run


class DryRunContractTest(unittest.TestCase):
    def test_full_dry_run_contract(self) -> None:
        result = run_dry_run()
        self.assertTrue(result["ok"])
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["final_generation"], 2)

    def test_heartbeat_refreshes_timeout_origin(self) -> None:
        coordinator = DryRunCoordinator(timeout_seconds=90)
        lease = coordinator.claim("job-1", "worker-a")
        coordinator.advance(80)
        coordinator.heartbeat(lease)
        coordinator.advance(80)
        self.assertFalse(coordinator.is_stale(lease))
        coordinator.advance(11)
        self.assertTrue(coordinator.is_stale(lease))

    def test_old_generation_cannot_finish_reassigned_job(self) -> None:
        coordinator = DryRunCoordinator(timeout_seconds=10)
        old = coordinator.claim("job-1", "worker-a")
        coordinator.advance(11)
        new = coordinator.claim("job-1", "worker-b")
        with self.assertRaises(RuntimeError):
            coordinator.complete(old)
        coordinator.complete(new)
        self.assertTrue(new.completed)


if __name__ == "__main__":
    unittest.main()
