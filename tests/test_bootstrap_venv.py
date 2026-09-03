import os
import shutil
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

    def _run_bootstrap(
        self,
        fake_bin: Path,
        target: Path,
        marker: Path,
        apt_log: Path,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()

        if os.name == "nt":
            bash = shutil.which("bash")
            self.assertIsNotNone(bash, "Git Bash is required for bootstrap-venv shell tests on Windows")

            env["TOOLS_TEST_FAKE_BIN"] = str(fake_bin)
            env["TOOLS_TEST_VENV_MARKER"] = str(marker)
            env["TOOLS_TEST_APT_LOG"] = str(apt_log)

            return subprocess.run(
                [
                    bash,
                    "-c",
                    r'''
                    set -e
                    fake_bin="$(cygpath -u "$TOOLS_TEST_FAKE_BIN")"
                    marker="$(cygpath -u "$TOOLS_TEST_VENV_MARKER")"
                    apt_log="$(cygpath -u "$TOOLS_TEST_APT_LOG")"
                    script="$(cygpath -u "$1")"
                    target="$(cygpath -u "$2")"
                    export PATH="${fake_bin}:$PATH"
                    export TOOLS_TEST_VENV_MARKER="${marker}"
                    export TOOLS_TEST_APT_LOG="${apt_log}"
                    exec bash "${script}" fakepython "${target}"
                    ''',
                    "bootstrap-venv-test",
                    str(SCRIPT),
                    str(target),
                ],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
        env["TOOLS_TEST_VENV_MARKER"] = str(marker)
        env["TOOLS_TEST_APT_LOG"] = str(apt_log)

        return subprocess.run(
            ["bash", str(SCRIPT), "fakepython", str(target)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

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
                fake_bin / "uname",
                r'''#!/usr/bin/env bash
                if [[ "${1:-}" == "-s" ]]; then
                  echo "Linux"
                  exit 0
                fi
                echo "Linux"
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

            completed = self._run_bootstrap(fake_bin, target, marker, apt_log)

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
            marker = root_path / "unused-marker"
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

            completed = self._run_bootstrap(fake_bin, root_path / "venv", marker, apt_log)

            self.assertNotEqual(0, completed.returncode)
            self.assertIn("permission denied", completed.stderr)
            self.assertFalse(apt_log.exists())


if __name__ == "__main__":
    unittest.main()
