#!/usr/bin/env python3
"""Non-destructive live-ISO builder contract tests (no real disks or chroot)."""
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "libexec/hangar-live-iso"
loader = importlib.machinery.SourceFileLoader("hangar_live_iso", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
live = importlib.util.module_from_spec(spec)
loader.exec_module(live)


class LiveISOTests(unittest.TestCase):
    def test_grub_default_is_a_shell_not_a_background_services_boot(self):
        cfg = live.grub_config("1234")
        self.assertIn("set default=0", cfg)
        first = cfg.split("menuentry ")[1]
        self.assertIn("init=/bin/bash", first)
        self.assertIn("nopersistence", first)
        self.assertNotIn("systemd.unit", first)
        second = cfg.split("menuentry ")[2]
        self.assertIn("systemd.unit=multi-user.target", second)

    def test_snapshot_must_contain_system_and_matching_modules(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "etc").mkdir()
            with self.assertRaisesRegex(ValueError, "lacks systemd"):
                live.check_snapshot_root(root, "1.2.3")
            (root / "usr/lib/systemd").mkdir(parents=True)
            (root / "usr/lib/systemd/systemd").write_text("x")
            (root / "usr/lib/os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
            with patch.object(live, "read_os_release", return_value={"ID": "ubuntu", "VERSION_ID": "24.04"}):
                with self.assertRaisesRegex(ValueError, "kernel modules"):
                    live.check_snapshot_root(root, "1.2.3")
                (root / "usr/lib/modules/1.2.3").mkdir(parents=True)
                self.assertTrue(live.check_snapshot_root(root, "1.2.3"))

    def test_prepare_does_not_mutate_host_or_any_file_outside_restored_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "snapshot"
            (root / "etc").mkdir(parents=True)
            (root / "etc/fstab").write_text("REAL DISK UUID=/\n")
            (root / "etc/crypttab").write_text("REAL LUKS UUID\n")
            (root / "etc/systemd/system").mkdir(parents=True)
            (root / "etc/systemd/system/hangar-auto-update.timer").write_text("[Timer]\n")
            live.prepare_live_root(root)
            self.assertNotIn("UUID", (root / "etc/fstab").read_text())
            self.assertNotIn("UUID", (root / "etc/crypttab").read_text())
            timer = root / "etc/systemd/system/hangar-auto-update.timer"
            self.assertTrue(timer.is_symlink())
            self.assertEqual(os.readlink(timer), "/dev/null")

    def test_rejects_symlinked_snapshot_config(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "etc").mkdir()
            (root / "etc/fstab").symlink_to("/etc/fstab")
            (root / "usr/lib/systemd").mkdir(parents=True)
            (root / "usr/lib/systemd/systemd").write_text("x")
            (root / "usr/lib/modules/kernel").mkdir(parents=True)
            (root / "usr/lib/os-release").write_text("ID=ubuntu\n")
            with patch.object(live, "read_os_release", return_value={"ID": "ubuntu", "VERSION_ID": "24.04"}):
                with self.assertRaisesRegex(ValueError, "symlinked"):
                    live.check_snapshot_root(root, "kernel")

    def test_will_not_replace_existing_output(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            stage, dest = p / "staging.iso", p / "saved.iso"
            stage.write_bytes(b"new")
            dest.write_bytes(b"old")
            with self.assertRaises(FileExistsError):
                live.publish_iso(stage, dest)
            self.assertEqual(dest.read_bytes(), b"old")
            dest.unlink()
            live.publish_iso(stage, dest)
            self.assertEqual(dest.read_bytes(), b"new")
            self.assertEqual(dest.stat().st_mode & 0o777, 0o600)

    def test_host_guard_rejects_wrong_arch_without_touching_anything(self):
        with tempfile.TemporaryDirectory() as d, patch.object(live.os, "geteuid", return_value=0):
            with patch.object(live.platform, "machine", return_value="aarch64"):
                with self.assertRaisesRegex(ValueError, "x86_64"):
                    live.check_host("6.8.0", Path(d) / "live.iso")

    def test_live_builder_does_not_modify_repo_or_source_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            key, output = p / "secret", p / "live.iso"
            key.write_text("password")
            recorded = []
            real_mkdir = Path.mkdir
            def fake_run(*args, **kwargs):
                recorded.append(args)
                if args[0] == "restic":
                    root = Path(args[args.index("--target") + 1])
                    (root / "etc").mkdir(parents=True)
                    (root / "etc/fstab").write_text("ORIGINAL")
                elif args[0] == "mksquashfs":
                    Path(args[2]).write_bytes(b"fake squashfs")
                elif args[0] == "mkinitramfs":
                    Path(args[2]).write_bytes(b"fake initrd")
                elif args[0] == "grub-mkrescue":
                    Path(args[2]).write_bytes(b"fake ISO")
            def fake_copy2(src, dst):
                Path(dst).write_bytes(b"fake kernel")
            with patch.object(live, "check_host", return_value=True), \
                 patch.object(live, "check_snapshot_root", return_value=True), \
                 patch.object(live, "run", side_effect=fake_run), \
                 patch.object(live.shutil, "copy2", side_effect=fake_copy2), \
                 patch.object(live.subprocess, "check_output", return_value="scripts/live\n"):
                live.build("/private/backup", key, "latest", output, "fake-kernel")
            self.assertEqual(output.read_bytes(), b"fake ISO")
            self.assertEqual([x[0] for x in recorded],
                             ["restic", "mksquashfs", "mkinitramfs", "grub-mkrescue"])
            self.assertTrue(all("grub-install" not in x for x in recorded))


if __name__ == "__main__":
    unittest.main()
