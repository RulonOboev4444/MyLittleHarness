from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.vcs import probe_vcs


class VcsProbeTests(unittest.TestCase):
    def test_probe_reports_non_git_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(command, 128, "", "fatal: not a git repository")

            posture = probe_vcs(Path(tmp), runner)
            self.assertTrue(posture.git_available)
            self.assertFalse(posture.is_worktree)
            self.assertEqual("non-git", posture.state)
            self.assertIn("not a git repository", posture.detail or "")

    def test_probe_reports_missing_git_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
                raise FileNotFoundError("git")

            posture = probe_vcs(Path(tmp), runner)
            self.assertFalse(posture.git_available)
            self.assertFalse(posture.is_worktree)
            self.assertEqual("unknown", posture.state)
            self.assertIn("git executable unavailable", posture.detail or "")

    def test_probe_reports_clean_git_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()

            def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
                if command[-1] == "--is-inside-work-tree":
                    return subprocess.CompletedProcess(command, 0, "true\n", "")
                if command[-1] == "--show-toplevel":
                    return subprocess.CompletedProcess(command, 0, f"{root}\n", "")
                if command[-1] == "--porcelain=v1":
                    return subprocess.CompletedProcess(command, 0, "", "")
                return subprocess.CompletedProcess(command, 1, "", "unexpected")

            posture = probe_vcs(root, runner)
            self.assertTrue(posture.git_available)
            self.assertTrue(posture.is_worktree)
            self.assertEqual("clean", posture.state)
            self.assertEqual(str(root), posture.top_level)
            self.assertEqual(0, posture.changed_count)

    def test_probe_reports_dirty_samples_from_porcelain_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()

            def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
                if command[-1] == "--is-inside-work-tree":
                    return subprocess.CompletedProcess(command, 0, "true\n", "")
                if command[-1] == "--show-toplevel":
                    return subprocess.CompletedProcess(command, 0, f"{root}\n", "")
                if command[-1] == "--porcelain=v1":
                    return subprocess.CompletedProcess(command, 0, " M README.md\n?? notes.md\n", "")
                return subprocess.CompletedProcess(command, 1, "", "unexpected")

            posture = probe_vcs(root, runner)
            self.assertEqual("dirty", posture.state)
            self.assertEqual(2, posture.changed_count)
            self.assertEqual("M", posture.changed_samples[0].status)
            self.assertEqual("README.md", posture.changed_samples[0].path)
            self.assertEqual("??", posture.changed_samples[1].status)
            self.assertEqual("notes.md", posture.changed_samples[1].path)

    def test_probe_reports_status_failure_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()

            def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
                if command[-1] == "--is-inside-work-tree":
                    return subprocess.CompletedProcess(command, 0, "true\n", "")
                if command[-1] == "--show-toplevel":
                    return subprocess.CompletedProcess(command, 0, f"{root}\n", "")
                if command[-1] == "--porcelain=v1":
                    return subprocess.CompletedProcess(command, 1, "", "status failed")
                return subprocess.CompletedProcess(command, 1, "", "unexpected")

            posture = probe_vcs(root, runner)
            self.assertTrue(posture.git_available)
            self.assertTrue(posture.is_worktree)
            self.assertEqual("unknown", posture.state)
            self.assertIn("status failed", posture.detail or "")


if __name__ == "__main__":
    unittest.main()
