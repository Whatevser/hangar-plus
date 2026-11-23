#!/usr/bin/env python3
"""Offline bootable RAW/VHDX export safety and assembly tests, without starting a VM."""
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
            self.assertEqual(vhd.output_format(Path(d) / "disk.raw"), "raw")
            self.assertEqual(vhd.output_format(Path(d) / "disk.img"), "raw")
            self.assertEqual(vhd.output_format(Path(d) / "legacy.vhd"), "vpc")
            with self.assertRaisesRegex(ValueError, r"\.raw"):
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

    def test_raw_skips_conversion_and_keeps_sparse_virtual_length(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / "recovered.raw"
            password = Path(d) / "key"
            password.write_text("test-secret")
            def fake_raw(restic, snapshot, raw, root, size):
                # This is intentionally a sparse file, like the real builder.
                with raw.open("wb") as f:
                    f.truncate(16 * 1024 * 1024)
                    f.seek(512)
                    f.write(b"EFI TEST DATA")
            with patch.object(vhd, "preflight", side_effect=vhd.output_format), \
                 patch.object(vhd, "restore_bytes", return_value=1024), \
                 patch.object(vhd, "make_raw", side_effect=fake_raw), \
                 patch.object(vhd, "convert_with_progress", side_effect=AssertionError(
                     "RAW must never be converted")), \
                 patch.object(vhd, "command", side_effect=AssertionError(
                     "RAW must never call qemu-img")), \
                 patch.object(vhd, "PROGRESS_FILE", None):
                vhd.build("/repo", password, "latest", output)
            self.assertEqual(output.stat().st_size, 16 * 1024 * 1024)
            with output.open("rb") as f:
                f.seek(512)
                self.assertEqual(f.read(13), b"EFI TEST DATA")
            # On Linux filesystems where sparse support exists, no full-capacity
            # 16 MiB allocation should have appeared.
            self.assertLess(output.stat().st_blocks * 512, output.stat().st_size // 2)

    def test_vhdx_still_uses_conversion_on_request(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / "recovered.vhdx"
            password = Path(d) / "key"
            password.write_text("test-secret")
            conversions = []
            def fake_raw(restic, snapshot, raw, root, size):
                raw.write_bytes(b"raw")
            def fake_convert(raw, target, fmt):
                conversions.append((fmt, target.suffix))
                target.write_bytes(b"vhdx")
            commands = []
            def fake_command(argv, **kwargs):
                commands.append(argv)
            with patch.object(vhd, "preflight", side_effect=vhd.output_format), \
                 patch.object(vhd, "restore_bytes", return_value=1024), \
                 patch.object(vhd, "make_raw", side_effect=fake_raw), \
                 patch.object(vhd, "convert_with_progress", side_effect=fake_convert), \
                 patch.object(vhd, "command", side_effect=fake_command), \
                 patch.object(vhd, "PROGRESS_FILE", None):
                vhd.build("/repo", password, "latest", output)
            self.assertEqual(conversions, [("vhdx", ".vhdx")])
            self.assertIn(["qemu-img", "info", "-f", "vhdx",
                           next(c[-1] for c in commands if c[0] == "qemu-img")],
                          commands)
            self.assertEqual(output.read_bytes(), b"vhdx")

    def test_raw_preflight_does_not_require_qemu_img(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "disk.raw"
            vhdx = Path(d) / "disk.vhdx"
            original_is_dir = Path.is_dir
            def is_dir(p):
                return True if str(p) == "/usr/lib/grub/x86_64-efi" else original_is_dir(p)
            def which(name):
                return None if name == "qemu-img" else "/bin/" + name
            with patch.object(vhd.os, "geteuid", return_value=0), \
                 patch.object(vhd.shutil, "which", side_effect=which), \
                 patch.object(Path, "is_dir", is_dir):
                self.assertEqual(vhd.preflight(raw), "raw")
                with self.assertRaisesRegex(ValueError, "qemu-img"):
                    vhd.preflight(vhdx)

    def test_sparse_fallback_copy_if_link_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "source.raw"
            dest = Path(d) / "dest.raw"
            with source.open("wb") as f:
                f.truncate(8 * 1024 * 1024)
                f.seek(1 * 1024 * 1024)
                f.write(b"boot-sector")
            with patch.object(vhd.os, "link", side_effect=OSError(95, "not supported")):
                vhd.publish_image(source, dest, preserve_sparse=True)
            self.assertEqual(dest.stat().st_size, source.stat().st_size)
            with dest.open("rb") as f:
                f.seek(1024 * 1024)
                self.assertEqual(f.read(11), b"boot-sector")
            self.assertLess(dest.stat().st_blocks * 512, dest.stat().st_size // 2)

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

    def test_restic_stream_updates_private_status_and_shows_errors(self):
        with tempfile.TemporaryDirectory() as d:
            progress_path = Path(d) / "progress.json"
            def fake_stream(args, callback, **kw):
                self.assertIn("--json", args)
                callback('{"message_type":"status","percent_done":0.42,'
                         '"bytes_restored":420,"total_bytes":1000}')
                callback('{"message_type":"error","error":{"message":"file cannot be read"}}')
                callback('{"message_type":"status","percent_done":0.7,'
                         '"bytes_restored":700,"total_bytes":1000}')
            with patch.object(vhd, "PROGRESS_FILE", progress_path), \
                 patch.object(vhd, "JOB_ID", "test-job"), \
                 patch.object(vhd, "LAST_WARNING", None), \
                 patch.object(vhd, "stream_command", side_effect=fake_stream):
                vhd.restore_with_progress(["restic"], "latest", Path(d) / "restored")
                report = __import__("json").loads(progress_path.read_text())
                self.assertEqual(report["job_id"], "test-job")
                self.assertEqual(report["percent"], 1)
                self.assertEqual(report["warning"], "file cannot be read")

    def test_streaming_qemu_conversion_reports_percent(self):
        with tempfile.TemporaryDirectory() as d:
            progress_path = Path(d) / "progress.json"
            def fake_stream(args, callback, **kw):
                self.assertIn("-p", args)
                callback("    (18.43/100%)")
                callback("    (73.13/100%)")
            with patch.object(vhd, "PROGRESS_FILE", progress_path), \
                 patch.object(vhd, "JOB_ID", "conversion"), \
                 patch.object(vhd, "stream_command", side_effect=fake_stream):
                vhd.convert_with_progress("in.raw", "out.vhdx", "vhdx")
                report = __import__("json").loads(progress_path.read_text())
                self.assertEqual(report["percent"], 1)
                self.assertEqual(report["phase"], "Conversion complete")

    def test_cancelled_command_terminates_its_process_group(self):
        fake_proc = type("FakeProcess", (), {"communicate": lambda self, **kw:
                            (_ for _ in ()).throw(vhd.ExportCancelled()),
                            "pid": 42})()
        with patch.object(vhd.subprocess, "Popen", return_value=fake_proc), \
             patch.object(vhd, "terminate_process") as terminate:
            with self.assertRaises(vhd.ExportCancelled):
                vhd.command(["fake"], stdout=None)
        terminate.assert_called_once_with(fake_proc)

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
                    # grub-install can create a locator referring to a
                    # temporary host mount; Hangar must replace it afterwards.
                    (root / "boot/efi/EFI/BOOT/grub.cfg").write_text(
                        "search --fs-uuid --set=root wrong-host-uuid\n")
            def do_restore(restic, snapshot, target):
                cmd(["restic", "restore", snapshot, target])
            with patch.object(vhd, "command", side_effect=cmd), \
                 patch.object(vhd, "restore_with_progress", side_effect=do_restore), \
                 patch.object(vhd, "check_output",
                              side_effect=["/dev/loop42", "550e8400-e29b-41d4-a716-446655440000", "ABCD-0123"]), \
                 patch.object(vhd, "verify_loop"), \
                 patch.object(vhd, "partitions", return_value=(Path("/dev/loop42p1"), Path("/dev/loop42p2"))), \
                 patch.object(vhd, "cleanup_loop", return_value=[]):
                vhd.make_raw(["restic"], "latest", raw, root, 16)
            self.assertEqual([a[0] for a in calls],
                             ["sfdisk", "mkfs.vfat", "mkfs.ext4", "mount",
                              "restic", "mount", "grub-install", "sync", "sync"])
            esp_cfg = (root / "boot/efi/EFI/BOOT/grub.cfg").read_text()
            self.assertIn("550e8400-e29b-41d4-a716-446655440000", esp_cfg)
            self.assertIn("set prefix=($root)/boot/grub", esp_cfg)
            self.assertIn("configfile $prefix/grub.cfg", esp_cfg)
            self.assertNotIn("wrong-host-uuid", esp_cfg)
            self.assertIn("550e8400-e29b-41d4-a716-446655440000",
                          (root / "boot/grub/grub.cfg").read_text())

    def test_efi_locator_rejects_bad_uuid_and_symlink(self):
        with self.assertRaisesRegex(ValueError, "Invalid image root UUID"):
            vhd.make_efi_grub_locator("wrong; command")
        with tempfile.TemporaryDirectory() as d:
            esp = Path(d)
            boot = esp / "EFI/BOOT"
            boot.mkdir(parents=True)
            (boot / "grub.cfg").symlink_to(Path(d) / "outside")
            with self.assertRaisesRegex(ValueError, "symlinked"):
                vhd.install_efi_grub_locator(
                    esp, "550e8400-e29b-41d4-a716-446655440000")

    def test_efi_locator_is_image_specific_not_host_specific(self):
        a = vhd.make_efi_grub_locator(
            "550e8400-e29b-41d4-a716-446655440000")
        b = vhd.make_efi_grub_locator(
            "a1f8f726-22f9-49c0-a799-4ddbaef579fb")
        self.assertNotEqual(a, b)
        self.assertIn("search --no-floppy --fs-uuid", a)
        self.assertIn("configfile $prefix/grub.cfg", a)
        self.assertNotIn("/dev/loop", a)


if __name__ == "__main__":
    unittest.main()
