"""The launcher's PID file: where it lives, how it is written, what --stop kills.

Every test runs bin/omarchy-themes-explorer with --no-open or --stop against a
temporary HOME and XDG_RUNTIME_DIR, so no window opens and nothing of the
user's is touched.

    python3 -m unittest discover tests
"""

import os
import socket
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAUNCHER = REPO / "bin/omarchy-themes-explorer"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def gone(pid):
    """True once pid has exited -- a zombie awaiting its reaper counts."""
    try:
        return Path("/proc/%d/stat" % pid).read_text().split(") ")[1][0] == "Z"
    except (OSError, IndexError):
        return True


def wait_gone(pid, timeout=5):
    deadline = time.monotonic() + timeout
    while not gone(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


class LauncherPidTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home = root / "home"
        self.runtime = root / "runtime"
        self.home.mkdir()
        self.runtime.mkdir(mode=0o700)
        self.port = free_port()
        self.env = dict(os.environ, HOME=str(self.home), XDG_RUNTIME_DIR=str(self.runtime), OMARCHY_PATH=str(root))
        self.env.pop("XDG_CACHE_HOME", None)
        self.run_dir = self.runtime / "omarchy-themes-explorer"
        self.pid_file = self.run_dir / ("omarchy-themes-explorer.%d.pid" % self.port)

    def tearDown(self):
        subprocess.run([str(LAUNCHER), "--stop", "--port", str(self.port)], env=self.env, capture_output=True)
        self.tmp.cleanup()

    def launch(self, *args, env=None):
        return subprocess.run(
            [str(LAUNCHER), *args, "--port", str(self.port)],
            env=env or self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_start_writes_a_private_pid_file_and_stop_kills_the_server(self):
        self.assertEqual(self.launch("--no-open").returncode, 0)
        self.assertEqual(stat.S_IMODE(self.run_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.pid_file.stat().st_mode), 0o600)
        pid = int(self.pid_file.read_text())
        self.assertFalse(gone(pid))

        out = self.launch("--stop")
        self.assertEqual(out.stdout.strip(), "Stopped.")
        self.assertTrue(wait_gone(pid))
        self.assertFalse(self.pid_file.exists())

    def test_stop_does_not_signal_a_process_that_is_not_the_server(self):
        victim = subprocess.Popen(["sleep", "60"])
        try:
            self.run_dir.mkdir(mode=0o700)
            self.pid_file.write_text(str(victim.pid))
            out = self.launch("--stop")
            self.assertEqual(out.stdout.strip(), "Not running.")
            time.sleep(0.2)
            self.assertIsNone(victim.poll())
            self.assertFalse(self.pid_file.exists())
        finally:
            victim.kill()
            victim.wait()

    def test_stop_does_not_signal_the_server_on_another_port(self):
        other = free_port()
        self.assertEqual(self.launch("--no-open").returncode, 0)
        pid = int(self.pid_file.read_text())
        other_pid_file = self.run_dir / ("omarchy-themes-explorer.%d.pid" % other)
        other_pid_file.write_text(str(pid))
        out = subprocess.run(
            [str(LAUNCHER), "--stop", "--port", str(other)], env=self.env, capture_output=True, text=True
        )
        self.assertEqual(out.stdout.strip(), "Not running.")
        self.assertFalse(gone(pid))

    def test_a_planted_symlink_is_replaced_not_written_through(self):
        self.run_dir.mkdir(mode=0o700)
        victim = Path(self.tmp.name) / "victim"
        victim.write_text("keep me")
        self.pid_file.symlink_to(victim)
        self.assertEqual(self.launch("--no-open").returncode, 0)
        self.assertEqual(victim.read_text(), "keep me")
        self.assertFalse(self.pid_file.is_symlink())
        int(self.pid_file.read_text())

    def test_a_symlinked_run_dir_is_refused(self):
        elsewhere = Path(self.tmp.name) / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        self.run_dir.symlink_to(elsewhere)
        for args in (("--no-open",), ("--stop",)):
            out = self.launch(*args)
            self.assertNotEqual(out.returncode, 0, args)
            self.assertIn("Refusing", out.stderr)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_a_shared_run_dir_is_made_private(self):
        self.run_dir.mkdir(mode=0o777)
        os.chmod(self.run_dir, 0o777)
        self.assertEqual(self.launch("--no-open").returncode, 0)
        self.assertEqual(stat.S_IMODE(self.run_dir.stat().st_mode), 0o700)

    def test_without_a_runtime_dir_it_stays_out_of_tmp(self):
        env = dict(self.env)
        del env["XDG_RUNTIME_DIR"]
        self.assertEqual(self.launch("--no-open", env=env).returncode, 0)
        pid_file = self.home / ".cache/omarchy-themes-explorer/run" / self.pid_file.name
        self.assertEqual(stat.S_IMODE(pid_file.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(pid_file.stat().st_mode), 0o600)
        self.assertFalse(Path("/tmp", self.pid_file.name).exists())
        pid = int(pid_file.read_text())
        self.assertEqual(self.launch("--stop", env=env).stdout.strip(), "Stopped.")
        self.assertTrue(wait_gone(pid))


if __name__ == "__main__":
    unittest.main()
