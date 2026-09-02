import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap-venv.sh"


class BootstrapVenvTest(unittest.TestCase):
    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def test_missing_ensurepip_installs_venv_package_and_retries(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            fake_bin = root_path / "bin"
            fake_bin.mkdir()
            marker = root_path / "venv-package-installed"
            apt_log = root_path / "apt.log"
            target = root_path / "venv"

            self._write_executable(
                fake_bin / "fakepython",
                r'''#!/usr/bin/env bash
                set -e
                if [[ "$1" == "-c" ]]; then
                  echo "3.10"
                  exit 0
                fi
                if [[ "$1" == "-m" && "$2" == "venv" ]]; then
                  if [[ ! -f "$TOOLS_TEST_VENV_MARKER" ]]; then
                    echo "The virtual environment was not created successfully because ensurepip is not available." >&2
                    exit 1
                  fi
                  mkdir -p "$3/bin"
                  : > "$3/bin/python"
                  exit 0
                fi
                exit 2
                ''',
            )
            self._write_executable(
                fake_bin / "apt-get",
                r'''#!/usr/bin/env bash
                echo "$*" >> "$TOOLS_TEST_APT_LOG"
                if [[ "$1" == "install" ]]; then
                  : > "$TOOLS_TEST_VENV_MARKER"
                fi
                exit 0
                ''',
            )
            self._write_executable(
                fake_bin / "sudo",
                r'''#!/usr/bin/env bash
                exec "$@"
                ''',
            )

            env = os.environ.copy()
            env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
            env["TOOLS_TEST_VENV_MARKER"] = str(marker)
            env["TOOLS_TEST_APT_LOG"] = str(apt_log)

            completed = subprocess.run(
                ["bash", str(SCRIPT), "fakepython", str(target)],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue(marker.exists())
            self.assertTrue((target / "bin" / "python").exists())
            log = apt_log.read_text(encoding="utf-8")
            self.assertIn("update", log)
            self.assertIn("install -y python3.10-venv", log)

    def test_unrelated_venv_failure_is_not_treated_as_missing_package(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            fake_bin = root_path / "bin"
            fake_bin.mkdir()
            apt_log = root_path / "apt.log"

            self._write_executable(
                fake_bin / "fakepython",
                r'''#!/usr/bin/env bash
                if [[ "$1" == "-m" && "$2" == "venv" ]]; then
                  echo "permission denied" >&2
                  exit 1
                fi
                exit 2
                ''',
            )
            self._write_executable(
                fake_bin / "apt-get",
                r'''#!/usr/bin/env bash
                echo "$*" >> "$TOOLS_TEST_APT_LOG"
                exit 0
                ''',
            )

            env = os.environ.copy()
            env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
            env["TOOLS_TEST_APT_LOG"] = str(apt_log)

            completed = subprocess.run(
                ["bash", str(SCRIPT), "fakepython", str(root_path / "venv")],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, completed.returncode)
            self.assertIn("permission denied", completed.stderr)
            self.assertFalse(apt_log.exists())


if __name__ == "__main__":
    unittest.main()
