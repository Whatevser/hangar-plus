#!/usr/bin/env python3
"""Offline VHDX export safety and assembly tests, without starting a VM."""
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BUILDER = Path(__file__).resolve().parents[2] / "libexec/hangar-vhd"
loader = importlib.machinery.SourceFileLoader("hangar_vhd", str(BUILDER))
spec = importlib.util.spec_from_loader(loader.name, loader)
vhd = importlib.util.module_from_spec(spec)
loader.exec_module(vhd)


class VirtualDiskTests(unittest.TestCase):
    def test_outputs_are_explicit_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "my-backup.vhdx"
            self.assertEqual(vhd.output_format(target), "vhdx")
            self.assertEqual(vhd.output_format(Path(d) / "legacy.vhd"), "vpc")
            with self.assertRaisesRegex(ValueError, r"\.vhdx"):
                vhd.output_format(Path(d) / "not-bootable.iso")
            target.write_bytes(b"original")
            with self.assertRaisesRegex(ValueError, "already exists"):
                vhd.output_format(target)
            staged = Path(d) / "temp.vhdx"
            staged.write_bytes(b"new")
            with self.assertRaises(ValueError):
                vhd.publish_image(staged, target)
            self.assertEqual(target.read_bytes(), b"original")
            target.unlink()
            vhd.publish_image(staged, target)
            self.assertEqual(target.read_bytes(), b"new")

    def test_sparse_sizing_and_gpt(self):
        self.assertEqual(vhd.disk_gib(1024), 16)
        self.assertGreaterEqual(vhd.disk_gib(100 * vhd.GIB), 143)
        self.assertEqual(vhd.disk_gib(100 * vhd.GIB, 200), 200)
        with self.assertRaisesRegex(ValueError, "16 GiB"):
            vhd.disk_gib(100, 4)
        script = vhd.partition_script()
        self.assertIn("label: gpt", script)
        self.assertIn("1048576,U", script)
        self.assertIn(",,L", script)

    def test_select_matching_linux_kernel_and_initrd(self):
        with tempfile.TemporaryDirectory() as d:
            boot = Path(d) / "boot"
            boot.mkdir()
            for version in ("6.9.0-1", "6.10.0-1"):
                (boot / ("vmlinuz-" + version)).write_bytes(b"vmlinuz")
                (boot / ("initrd.img-" + version)).write_bytes(b"initrd")
            (boot / "vmlinuz-7.0").write_bytes(b"no matching initrd")
            self.assertEqual(vhd.kernel_files(Path(d)), "6.10.0-1")

    def test_refuse_home_only_and_luks_snapshots(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with self.assertRaisesRegex(ValueError, "/etc"):
                vhd.check_restored_system(root)
            (root / "etc").mkdir()
            (root / "usr/lib/systemd").mkdir(parents=True)
            (root / "usr/lib/systemd/systemd").write_text("x")
            (root / "etc/os-release").write_text("ID=ubuntu\n")
            (root / "boot").mkdir()
            (root / "boot/vmlinuz-6.8.0").write_text("kernel")
            (root / "boot/initrd.img-6.8.0").write_text("initrd")
            with self.assertRaisesRegex(ValueError, "kernel modules"):
                vhd.check_restored_system(root)
            (root / "usr/lib/modules/6.8.0").mkdir(parents=True)
            self.assertEqual(vhd.check_restored_system(root), "6.8.0")
            (root / "etc/crypttab").write_text("cryptroot UUID=123 none luks\n")
            with self.assertRaisesRegex(ValueError, "LUKS"):
                vhd.check_restored_system(root)

    def test_patch_changes_only_the_mounted_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "etc/systemd/system").mkdir(parents=True)
            (root / "boot").mkdir()
            timer = root / "etc/systemd/system/hangar-auto-update.timer"
            timer.write_text("active timer")
            vhd.patch_image_root(root, "6.8.0", "root-uuid", "efi-uuid")
            self.assertIn("UUID=root-uuid / ext4", (root / "etc/fstab").read_text())
            self.assertIn("UUID=efi-uuid /boot/efi", (root / "etc/fstab").read_text())
            self.assertIn("root=UUID=root-uuid", (root / "boot/grub/grub.cfg").read_text())
            self.assertNotIn("grub-install", (root / "boot/grub/grub.cfg").read_text())
            self.assertEqual(os.readlink(timer), "/dev/null")

    def test_rejects_unverified_loop_device(self):
        with patch.object(vhd, "check_output", return_value="/private/mismatch.raw"):
            with self.assertRaisesRegex(ValueError, "not backed"):
                vhd.verify_loop("/dev/loop42", "/private/expected.raw")
        with self.assertRaisesRegex(ValueError, "Unsafe loop device"):
            vhd.verify_loop("/dev/sda", "/tmp/temporary.raw")

    def test_cleanup_unmounts_before_detaching_loop(self):
        calls = []
        def fake_run(cmd):
            calls.append(cmd)
            return type("Result", (), {"returncode": 0})()
        with patch.object(vhd.subprocess, "run", side_effect=fake_run):
            self.assertEqual(vhd.cleanup_loop("/dev/loop9", Path("/tmp/staged"), True, True), [])
        self.assertEqual([c[0] for c in calls], ["umount", "umount", "losetup"])

    def test_failed_unmount_must_not_detach_backing_file(self):
        calls = []
        def fake_run(cmd):
            calls.append(cmd)
            return type("Result", (), {"returncode": 1})()
        with patch.object(vhd.subprocess, "run", side_effect=fake_run):
            self.assertEqual(vhd.cleanup_loop("/dev/loop9", Path("/tmp/staged"), False, True),
                             ["root unmount"])
        self.assertEqual([c[0] for c in calls], ["umount"])

    def test_root_bootloader_uses_image_only_and_no_nvram(self):
        # Exercise the full command sequence without actual root, loop devices,
        # grub-install, conversion or OS writes.
        with tempfile.TemporaryDirectory() as d:
            root, raw = Path(d) / "root", Path(d) / "disk.raw"
            root.mkdir()
            calls = []
            def cmd(args, **kwargs):
                calls.append(args)
                op = args[0]
                if op == "sfdisk":
                    self.assertEqual(args[-1], raw)
                if op == "restic":
                    (root / "etc").mkdir(exist_ok=True)
                    (root / "usr/lib/systemd").mkdir(parents=True, exist_ok=True)
                    (root / "usr/lib/systemd/systemd").write_text("x")
                    (root / "etc/os-release").write_text("ID=ubuntu")
                    (root / "usr/lib/modules/6.8.0").mkdir(parents=True, exist_ok=True)
                    (root / "boot").mkdir(exist_ok=True)
                    (root / "boot/vmlinuz-6.8.0").write_text("kernel")
                    (root / "boot/initrd.img-6.8.0").write_text("initrd")
                if op == "grub-install":
                    self.assertTrue(any(s.startswith("--efi-directory=" + str(root)) for s in args))
                    self.assertIn("--removable", args)
                    self.assertIn("--no-nvram", args)
                    (root / "boot/efi/EFI/BOOT").mkdir(parents=True)
                    (root / "boot/efi/EFI/BOOT/BOOTX64.EFI").write_text("grub")
            with patch.object(vhd, "command", side_effect=cmd), \
                 patch.object(vhd, "check_output",
                              side_effect=["/dev/loop42", "550e8400-e29b-41d4-a716-446655440000", "ABCD-0123"]), \
                 patch.object(vhd, "verify_loop"), \
                 patch.object(vhd, "partitions", return_value=(Path("/dev/loop42p1"), Path("/dev/loop42p2"))), \
                 patch.object(vhd, "cleanup_loop", return_value=[]):
                vhd.make_raw(["restic"], "latest", raw, root, 16)
            self.assertEqual([a[0] for a in calls],
                             ["sfdisk", "mkfs.vfat", "mkfs.ext4", "mount",
                              "restic", "mount", "grub-install", "sync", "sync"])


if __name__ == "__main__":
    unittest.main()
