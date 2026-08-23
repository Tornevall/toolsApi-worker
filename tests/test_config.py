import os
import unittest
from unittest.mock import patch

from toolsapi_worker.config import WorkerConfig


class WorkerConfigTest(unittest.TestCase):
    def test_loads_protocol_configuration_from_environment(self):
        env = {
            "TOOLS_API_BASE_URL": "https://tools.example.test",
            "TOOLS_WORKER_TOKEN": "worker-secret",
            "TOOLS_WORKER_ID": "worker-mobile-slow",
            "TOOLS_WORKER_CONCURRENCY": "2",
            "TOOLS_WORKER_POLL_SECONDS": "4",
            "TOOLS_WORKER_HEARTBEAT_SECONDS": "25",
            "TOOLS_WORKER_ENABLED_HANDLERS": "whisper.transcribe",
        }
        with patch.dict(os.environ, env, clear=True):
            config = WorkerConfig.from_environment()

        config.validate_protocol_configuration()
        self.assertEqual("https://tools.example.test", config.api_base_url)
        self.assertEqual("worker-secret", config.worker_token)
        self.assertEqual("worker-mobile-slow", config.worker_id)
        self.assertEqual(2, config.concurrency)
        self.assertEqual(4.0, config.poll_seconds)
        self.assertEqual(25.0, config.heartbeat_seconds)
        self.assertEqual(("whisper.transcribe",), config.enabled_handlers)

    def test_missing_protocol_configuration_is_rejected_without_echoing_secrets(self):
        with patch.dict(os.environ, {}, clear=True):
            config = WorkerConfig.from_environment()

        with self.assertRaises(ValueError) as caught:
            config.validate_protocol_configuration()

        message = str(caught.exception)
        self.assertIn("TOOLS_API_BASE_URL", message)
        self.assertIn("TOOLS_WORKER_TOKEN", message)
        self.assertIn("TOOLS_WORKER_ID", message)


if __name__ == "__main__":
    unittest.main()
