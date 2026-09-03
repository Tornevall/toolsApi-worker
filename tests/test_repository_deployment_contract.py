import unittest
from pathlib import Path


class RepositoryDeploymentContractTest(unittest.TestCase):
    def test_main_push_deployment_is_not_gated_by_default_off_variable(self):
        repo_root = Path(__file__).resolve().parents[1]
        workflow = (repo_root / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("push:", workflow)
        self.assertIn("branches: [main]", workflow)
        self.assertNotIn("WORKER_AUTODEPLOY", workflow)

    def test_generated_build_output_is_ignored(self):
        repo_root = Path(__file__).resolve().parents[1]
        ignored = (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()

        self.assertIn("build/", ignored)


if __name__ == "__main__":
    unittest.main()
