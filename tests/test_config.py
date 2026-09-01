import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from toolsapi_worker.config import WorkerConfig, read_env_file


class WorkerConfigTest(unittest.TestCase):
    def test_loads_protocol_configuration_from_environment(self):
        env = {
            "TOOLS_API_BASE_URL": "https://tools.example.test",
            "TOOLS_WORKER_TOKEN": "worker-secret",
            "TOOLS_WORKER_ID": "worker-mobile-slow",
            "TOOLS_WORKER_CONCURRENCY": "1",
            "TOOLS_WORKER_POLL_SECONDS": "4",
            "TOOLS_WORKER_HEARTBEAT_SECONDS": "25",
            "TOOLS_WORKER_ENABLED_HANDLERS": "whisper.transcribe",
            "TOOLS_WORKER_WHISPER_MODELS": "small,medium",
            "TOOLS_WORKER_WHISPER_DEVICE": "cpu",
            "TOOLS_WORKER_WHISPER_COMPUTE_TYPE": "int8",
            "TOOLS_WORKER_ACCEPTS_URL_SOURCES": "false",
            "TOOLS_WORKER_DIARIZATION_ENABLED": "true",
            "TOOLS_WORKER_DIARIZATION_HF_TOKEN": "hf_test_only",
            "TOOLS_WORKER_DIARIZATION_MIN_SPEAKERS": "2",
            "TOOLS_WORKER_DIARIZATION_MAX_SPEAKERS": "4",
            "TOOLS_WORKER_DIARIZATION_DEVICE": "cpu",
            "TOOLS_WORKER_TEMP_ROOT": "/tmp/toolsapi-worker-test",
        }
        with patch.dict(os.environ, env, clear=True):
            config = WorkerConfig.from_environment()

        config.validate_protocol_configuration()
        self.assertEqual("https://tools.example.test", config.api_base_url)
        self.assertEqual("worker-secret", config.worker_token)
        self.assertEqual("worker-mobile-slow", config.worker_id)
        self.assertEqual(1, config.concurrency)
        self.assertEqual(4.0, config.poll_seconds)
        self.assertEqual(25.0, config.heartbeat_seconds)
        self.assertEqual(("whisper.transcribe",), config.enabled_handlers)
        self.assertEqual(("small", "medium"), config.whisper_models)
        self.assertEqual("cpu", config.whisper_device)
        self.assertEqual("int8", config.whisper_compute_type)
        self.assertFalse(config.accepts_url_sources)
        self.assertTrue(config.diarization_enabled)
        self.assertEqual("pyannote", config.diarization_provider)
        self.assertEqual("hf_test_only", config.diarization_hf_token)
        self.assertEqual(2, config.diarization_min_speakers)
        self.assertEqual(4, config.diarization_max_speakers)
        self.assertEqual("cpu", config.diarization_device)
        self.assertEqual("/tmp/toolsapi-worker-test", config.temp_root)

    def test_default_idle_poll_and_diarization_are_enabled(self):
        env = {
            "TOOLS_API_BASE_URL": "https://tools.example.test",
            "TOOLS_WORKER_TOKEN": "worker-secret",
            "TOOLS_WORKER_ID": "worker-01",
        }
        with patch.dict(os.environ, env, clear=True):
            config = WorkerConfig.from_environment()

        self.assertEqual(60.0, config.poll_seconds)
        self.assertEqual(30.0, config.heartbeat_seconds)
        self.assertTrue(config.diarization_enabled)
        self.assertEqual("pyannote/speaker-diarization-community-1", config.diarization_model)
        self.assertEqual("auto", config.diarization_device)
        self.assertTrue(config.temp_root.endswith("toolsapi-worker"))

    def test_env_file_is_parsed_without_shell_evaluation(self):
        with tempfile.TemporaryDirectory() as root:
            env_file = Path(root) / ".env"
            env_file.write_text(
                "# Worker config\n"
                "TOOLS_API_BASE_URL=https://tools.example.test\n"
                "TOOLS_WORKER_TOKEN=12|token$with;separators\n"
                "TOOLS_WORKER_ID='mac worker'\n"
                "TOOLS_WORKER_WHISPER_DEVICE=metal\n"
                "TOOLS_WORKER_WHISPER_MODELS=large-v3,turbo\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                config = WorkerConfig.from_env_file(env_file)

        self.assertEqual("12|token$with;separators", config.worker_token)
        self.assertEqual("mac worker", config.worker_id)
        self.assertEqual("metal", config.whisper_device)
        self.assertEqual(("large-v3", "turbo"), config.whisper_models)
        self.assertTrue(config.diarization_enabled)

    def test_process_environment_overrides_env_file(self):
        with tempfile.TemporaryDirectory() as root:
            env_file = Path(root) / ".env"
            env_file.write_text("TOOLS_WORKER_ID=file-worker\n", encoding="utf-8")
            with patch.dict(os.environ, {"TOOLS_WORKER_ID": "process-worker"}, clear=True):
                config = WorkerConfig.from_env_file(env_file)

        self.assertEqual("process-worker", config.worker_id)

    def test_invalid_env_file_entry_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            env_file = Path(root) / ".env"
            env_file.write_text("not valid shell text\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_env_file(env_file)

    def test_missing_protocol_configuration_is_rejected_without_echoing_secrets(self):
        with patch.dict(os.environ, {}, clear=True):
            config = WorkerConfig.from_environment()

        with self.assertRaises(ValueError) as caught:
            config.validate_protocol_configuration()

        message = str(caught.exception)
        self.assertIn("TOOLS_API_BASE_URL", message)
        self.assertIn("TOOLS_WORKER_TOKEN", message)
        self.assertIn("TOOLS_WORKER_ID", message)

    def test_parallel_runtime_is_not_enabled_accidentally(self):
        env = {
            "TOOLS_API_BASE_URL": "https://tools.example.test",
            "TOOLS_WORKER_TOKEN": "worker-secret",
            "TOOLS_WORKER_ID": "worker-01",
            "TOOLS_WORKER_CONCURRENCY": "2",
        }
        with patch.dict(os.environ, env, clear=True):
            config = WorkerConfig.from_environment()

        with self.assertRaises(ValueError):
            config.validate_protocol_configuration()

    def test_invalid_speaker_bounds_are_rejected(self):
        env = {
            "TOOLS_API_BASE_URL": "https://tools.example.test",
            "TOOLS_WORKER_TOKEN": "worker-secret",
            "TOOLS_WORKER_ID": "worker-01",
            "TOOLS_WORKER_DIARIZATION_MIN_SPEAKERS": "5",
            "TOOLS_WORKER_DIARIZATION_MAX_SPEAKERS": "2",
        }
        with patch.dict(os.environ, env, clear=True):
            config = WorkerConfig.from_environment()

        with self.assertRaises(ValueError):
            config.validate_protocol_configuration()


if __name__ == "__main__":
    unittest.main()
