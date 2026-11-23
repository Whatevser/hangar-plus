#!/usr/bin/env python3
"""Offline tests for durable VHD systemd job lifecycle and status recovery."""
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[2] / "libexec/hangar-vhd-job"
loader = importlib.machinery.SourceFileLoader("hangar_vhd_job", str(PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
job = importlib.util.module_from_spec(spec)
loader.exec_module(job)
ID = "a" * 64


class VhdJobTests(unittest.TestCase):
    def fixture(self, root):
        state = root / "state"
        state.mkdir()
        portable = root / "hangar-portable"
        portable.write_text("runner")
        builder = root / "hangar-vhd"
        builder.write_text("builder")
        return patch.multiple(job, STATE_DIR=state, CURRENT=state / "current.json",
                              PROGRESS=state / "progress.json", LOCK=state / "control.lock",
                              RUNNER=str(portable), BUILDER=str(builder))

    def test_start_detaches_process_and_prevents_duplicate_jobs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            out = str(root / "disk.vhdx")
            calls = []
            def fake_run(args, **kw):
                calls.append(args)
                return type("Run", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            with self.fixture(root), patch.object(job, "systemd_state", return_value="active"), \
                 patch.object(job.subprocess, "run", side_effect=fake_run):
                result = job.start("full", ID, out)
                self.assertEqual(result["state"], "running")
                self.assertEqual(result["repo"], "full")
                self.assertTrue((root / "state/current.json").exists())
                self.assertEqual(len(calls), 1)
                args = calls[0]
                self.assertEqual(args[0], "systemd-run")
                self.assertIn("--service-type=exec", args)
                self.assertIn("--property=KillMode=process", args)
                self.assertEqual(args[-2:], [str(root / "state/progress.json"), result["job_id"]])
                with self.assertRaisesRegex(ValueError, "already running"):
                    job.start("full", ID, str(root / "different.vhdx"))
                self.assertEqual(len(calls), 1)

    def test_persisted_completion_survives_garbage_collected_unit(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with self.fixture(root):
                job.atomic_json(job.CURRENT, {
                    "job_id": "abcd", "unit": "hangar-vhd-1234567890abcdef.service",
                    "repo": "full", "snapshot": ID, "output": str(root / "disk.vhdx"),
                    "started": int(time.time()) - 15})
                job.atomic_json(job.PROGRESS, {
                    "job_id": "abcd", "state": "completed", "phase": "Completed",
                    "detail": "Image ready", "percent": 1, "updated": int(time.time())})
                with patch.object(job, "systemd_state", return_value="not-found"), \
                     patch.object(job.subprocess, "run", return_value=type("R", (), {
                         "returncode": 0, "stdout": "Job completed", "stderr": ""})()):
                    status = job.status()
                self.assertEqual(status["state"], "completed")
                self.assertEqual(status["percent"], 1)
                self.assertIn("Job completed", status["log"])

    def test_cancel_targets_only_running_unit_main_pid(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            calls = []
            def fake_run(args, **kwargs):
                calls.append(args)
                return type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()
            with self.fixture(root):
                job.atomic_json(job.CURRENT, {
                    "job_id": "abc", "unit": "hangar-vhd-1234567890abcdef.service",
                    "repo": "full", "snapshot": ID, "output": "out", "started": 1})
                job.atomic_json(job.PROGRESS, {"job_id": "abc", "state": "running"})
                with patch.object(job, "systemd_state", return_value="active"), \
                     patch.object(job.subprocess, "run", side_effect=fake_run):
                    result = job.cancel()
                self.assertEqual(result["state"], "cancelling")
                self.assertEqual(calls, [["systemctl", "kill", "--kill-who=main", "--signal=TERM",
                                          "hangar-vhd-1234567890abcdef.service"]])

    def test_failed_start_is_visible_to_next_session(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with self.fixture(root), \
                 patch.object(job, "systemd_state", return_value="not-found"), \
                 patch.object(job.subprocess, "run", return_value=type("R", (), {
                     "returncode": 1, "stdout": "", "stderr": "Failed to connect to bus"})()):
                with self.assertRaisesRegex(ValueError, "Failed to connect"):
                    job.start("full", ID, str(root / "disk.vhdx"))
                result = job.status()
                self.assertEqual(result["state"], "failed")
                self.assertIn("Failed to connect", result["error"])

    def test_rejects_unsanitized_inputs(self):
        with tempfile.TemporaryDirectory() as d, self.fixture(Path(d)):
            with self.assertRaises(ValueError):
                job.start("full;rm -rf", ID, str(Path(d) / "a.vhdx"))
            with self.assertRaises(ValueError):
                job.start("full", "../../evil", str(Path(d) / "a.vhdx"))
            with self.assertRaises(ValueError):
                job.start("full", ID, "/tmp/disallowed.iso")


if __name__ == "__main__":
    unittest.main()
