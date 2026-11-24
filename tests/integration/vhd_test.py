#!/usr/bin/env python3
"""Offline bootable disk-format export safety and assembly tests, without a VM."""
import importlib.machinery
import importlib.util
import os
import shutil
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
            for suffix, expected in ((".vhd", "vpc"), (".qcow2", "qcow2"),
                                     (".vdi", "vdi"), (".vmdk", "vmdk")):
                with self.subTest(format=suffix):
                    self.assertEqual(vhd.output_format(Path(d) / ("disk" + suffix)), expected)
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

    def test_converted_formats_use_matching_qemu_driver_and_staging_extension(self):
        formats = ((".vhdx", "vhdx"), (".vhd", "vpc"),
                   (".qcow2", "qcow2"), (".vdi", "vdi"), (".vmdk", "vmdk"))
        for suffix, driver in formats:
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as d:
                output = Path(d) / ("recovered" + suffix)
                password = Path(d) / "key"
                password.write_text("test-secret")
                conversions = []
                commands = []

                def fake_raw(restic, snapshot, raw, root, size):
                    raw.write_bytes(b"raw")

                def fake_convert(raw, target, fmt):
                    self.assertEqual(raw.suffix, ".raw")
                    conversions.append((fmt, target.suffix))
                    target.write_bytes(b"converted")

                with patch.object(vhd, "preflight", side_effect=vhd.output_format), \
                     patch.object(vhd, "restore_bytes", return_value=1024), \
                     patch.object(vhd, "make_raw", side_effect=fake_raw), \
                     patch.object(vhd, "convert_with_progress", side_effect=fake_convert), \
                     patch.object(vhd, "command", side_effect=lambda argv, **kw: commands.append(argv)), \
                     patch.object(vhd, "PROGRESS_FILE", None):
                    vhd.build("/repo", password, "latest", output)

                self.assertEqual(conversions, [(driver, suffix)])
                info = [argv for argv in commands if argv[:2] == ["qemu-img", "info"]]
                self.assertEqual(len(info), 1)
                self.assertEqual(info[0][2:4], ["-f", driver])
                self.assertEqual(Path(info[0][4]).suffix, suffix)
                self.assertEqual(output.read_bytes(), b"converted")

    def test_raw_preflight_does_not_require_qemu_img(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "disk.raw"
            vhdx = Path(d) / "disk.vhdx"
            converted = [Path(d) / ("disk" + ext) for ext in
                         (".vhd", ".qcow2", ".vdi", ".vmdk")]
            original_is_dir = Path.is_dir
            def is_dir(p):
                return True if str(p) == "/usr/lib/grub/x86_64-efi" else original_is_dir(p)
            def which(name):
                return None if name == "qemu-img" else "/bin/" + name
            with patch.object(vhd.os, "geteuid", return_value=0), \
                 patch.object(vhd.shutil, "which", side_effect=which), \
                 patch.object(Path, "is_dir", is_dir):
                self.assertEqual(vhd.preflight(raw), "raw")
                self.assertEqual(vhd.preflight(Path(d) / "disk.img"), "raw")
                for target in [vhdx] + converted:
                    with self.subTest(format=target.suffix), self.assertRaisesRegex(
                            ValueError, "qemu-img"):
                        vhd.preflight(target)

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
                self.assertEqual(args[args.index("-O") + 1], "vhdx")
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

    def test_root_bootloader_embeds_image_locator_into_removable_efi(self):
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
                if op == "grub-mkstandalone":
                    self.assertIn("--format=x86_64-efi", args)
                    self.assertTrue(any(x.startswith("--modules=") for x in args))
                    self.assertIn("/boot/grub/grub.cfg=" +
                                  str(root / "boot/efi/EFI/BOOT/grub.cfg"), args)
                    loader = Path(next(a.split("=", 1)[1] for a in args
                                       if a.startswith("--output=")))
                    self.assertEqual(loader.name, "BOOTX64.EFI.hangar-new")
                    loader.write_bytes(b"MZ" + bytes(2046))
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
                              "restic", "mount", "grub-mkstandalone", "sync", "sync"])
            esp_cfg = (root / "boot/efi/EFI/BOOT/grub.cfg").read_text()
            self.assertIn("550e8400-e29b-41d4-a716-446655440000", esp_cfg)
            self.assertNotIn("set prefix=", esp_cfg)
            self.assertIn("configfile ($root)/boot/grub/grub.cfg", esp_cfg)
            self.assertEqual((root / "boot/efi/EFI/BOOT/BOOTX64.EFI").stat().st_size,
                             2048)
            self.assertFalse((root / "boot/efi/EFI/BOOT/BOOTX64.EFI.hangar-new").exists())
            # Sidecar config is retained for debugging and alternative loaders;
            # standalone EFI's embedded copy is what guarantees automatic boot.
            # The signed Ubuntu GRUB binary can look under EFI/ubuntu even
            # when launched via the removable EFI/BOOT path.
            self.assertEqual(esp_cfg,
                (root / "boot/efi/EFI/ubuntu/grub.cfg").read_text())
            self.assertEqual(esp_cfg,
                (root / "boot/efi/EFI/debian/grub.cfg").read_text())
            self.assertIn("550e8400-e29b-41d4-a716-446655440000",
                          (root / "boot/grub/grub.cfg").read_text())

    def test_standalone_grub_replaces_old_loader_only_after_validation(self):
        with tempfile.TemporaryDirectory() as d:
            esp = Path(d)
            boot = esp / "EFI/BOOT"
            boot.mkdir(parents=True)
            loader = boot / "BOOTX64.EFI"
            loader.write_bytes(b"MZoriginal signed loader")
            uuid = "550e8400-e29b-41d4-a716-446655440000"
            commands = []

            def valid_build(args, **kwargs):
                commands.append(args)
                staged = Path(next(arg.split("=", 1)[1] for arg in args
                                   if arg.startswith("--output=")))
                self.assertEqual(staged.parent, boot)
                self.assertTrue((boot / "grub.cfg").is_file())
                staged.write_bytes(b"MZ" + bytes(2046))

            with patch.object(vhd, "command", side_effect=valid_build):
                vhd.install_standalone_grub(esp, uuid)
            self.assertEqual(loader.read_bytes(), b"MZ" + bytes(2046))
            self.assertFalse((boot / "BOOTX64.EFI.hangar-new").exists())
            self.assertEqual(commands[0][0], "grub-mkstandalone")
            self.assertIn("/boot/grub/grub.cfg=" + str(boot / "grub.cfg"),
                          commands[0])
            self.assertIn(uuid, (boot / "grub.cfg").read_text())

    def test_invalid_standalone_grub_does_not_destroy_existing_loader(self):
        with tempfile.TemporaryDirectory() as d:
            esp = Path(d)
            boot = esp / "EFI/BOOT"
            boot.mkdir(parents=True)
            loader = boot / "BOOTX64.EFI"
            original = b"MZoriginal signed loader"
            loader.write_bytes(original)

            def broken_build(args, **kwargs):
                staged = Path(next(arg.split("=", 1)[1] for arg in args
                                   if arg.startswith("--output=")))
                staged.write_bytes(b"NO" + bytes(2046))

            with patch.object(vhd, "command", side_effect=broken_build):
                with self.assertRaisesRegex(ValueError, "invalid executable header"):
                    vhd.install_standalone_grub(
                        esp, "550e8400-e29b-41d4-a716-446655440000")
            self.assertEqual(loader.read_bytes(), original)
            self.assertFalse((boot / "BOOTX64.EFI.hangar-new").exists())

    def test_standalone_grub_refuses_symlinked_efi_loader(self):
        with tempfile.TemporaryDirectory() as d:
            esp = Path(d)
            boot = esp / "EFI/BOOT"
            boot.mkdir(parents=True)
            (boot / "BOOTX64.EFI").symlink_to(Path(d) / "external")
            with patch.object(vhd, "command") as command:
                with self.assertRaisesRegex(ValueError, "unsafe existing EFI bootloader"):
                    vhd.install_standalone_grub(
                        esp, "550e8400-e29b-41d4-a716-446655440000")
            command.assert_not_called()

    def test_missing_runtime_mountpoints_rebuilt_inside_image_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "mounted-image"
            root.mkdir()
            (root / "tmp").mkdir(mode=0o700)
            (root / "tmp" / "keep").write_text("snapshot")
            untouched = (root / "tmp").stat().st_mode & 0o7777
            vhd.ensure_boot_directories(root)
            for rel in ("dev", "proc", "sys", "run", "tmp", "var", "var/tmp"):
                self.assertTrue((root / rel).is_dir(), rel)
            self.assertEqual((root / "tmp").stat().st_mode & 0o7777, untouched)
            self.assertEqual((root / "tmp/keep").read_text(), "snapshot")
            self.assertEqual((root / "var/tmp").stat().st_mode & 0o7777, 0o1777)
            self.assertEqual((root / "proc").stat().st_mode & 0o7777, 0o555)
            self.assertEqual((root / "sys").stat().st_mode & 0o7777, 0o555)
            self.assertFalse((Path(d) / "run").exists())

    def test_missing_mountpoint_conflicts_fail_without_following_symlinks(self):
        for rel in ("dev", "proc", "sys", "run", "tmp", "var", "var/tmp"):
            with self.subTest(path=rel), tempfile.TemporaryDirectory() as d:
                root = Path(d) / "root"
                root.mkdir()
                conflict = root / rel
                conflict.parent.mkdir(parents=True, exist_ok=True)
                conflict.write_text("not a directory")
                with self.assertRaisesRegex(ValueError, "Unsafe essential directory"):
                    vhd.ensure_boot_directories(root)
                self.assertEqual(conflict.read_text(), "not a directory")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "root"
            root.mkdir()
            (root / "dev").symlink_to("/dev")
            with self.assertRaisesRegex(ValueError, "Unsafe essential directory"):
                vhd.ensure_boot_directories(root)

    def test_inplace_raw_repair_refuses_running_vm_and_unsafe_input(self):
        with tempfile.TemporaryDirectory() as d:
            image = Path(d) / "disk.raw"
            image.write_bytes(b"test-file")
            link = Path(d) / "linked.raw"
            link.symlink_to(image)
            with patch.object(vhd.os, "geteuid", return_value=0):
                with self.assertRaisesRegex(ValueError, "regular file"):
                    vhd.repair_raw_image(link)
                with self.assertRaisesRegex(ValueError, "absolute path"):
                    vhd.repair_raw_image(Path("relative.raw"))
                with self.assertRaisesRegex(ValueError, "absolute path"):
                    vhd.repair_raw_image(Path(d) / "image.vhdx")
                with patch.object(vhd.shutil, "which", return_value="/usr/bin/tool"), \
                     patch.object(vhd.subprocess, "run",
                                  return_value=type("Status", (), {"returncode": 0})()):
                    with self.assertRaisesRegex(ValueError, "in use"):
                        vhd.repair_raw_image(image)

    def test_repair_raw_rebuilds_embedded_loader_and_keeps_backup(self):
        # Positive repair regression: old GRUB reaches grub> even though the
        # root menu exists. The new EFI binary must embed its UUID locator.
        with tempfile.TemporaryDirectory() as d:
            image = Path(d) / "snapshot.raw"
            image.write_bytes(b"raw-image")
            work = Path(d) / "mounted"
            work.mkdir()
            uuid = "550e8400-e29b-41d4-a716-446655440000"
            original = b"MZprevious EFI loader"
            state = {}
            values = iter(["", "/dev/loop42", "vfat", "HANGAR_EFI",
                           "ext4", "HANGAR_ROOT", uuid])

            def fake_command(args, **kwargs):
                if args[:3] == ["mount", "-t", "ext4"]:
                    (work / "boot/grub").mkdir(parents=True)
                    (work / "boot/grub/grub.cfg").write_text(
                        "menuentry 'recovered' { search --fs-uuid " + uuid + " }")
                    (work / "boot/efi/EFI/BOOT").mkdir(parents=True)
                    (work / "boot/efi/EFI/BOOT/BOOTX64.EFI").write_bytes(original)
                elif args[0] == "grub-mkstandalone":
                    state["grub_command"] = args
                    staged = Path(next(a.split("=", 1)[1] for a in args
                                       if a.startswith("--output=")))
                    staged.write_bytes(b"MZ" + bytes(2046))
                elif args[0] == "sync" and "backup" not in state:
                    boot = work / "boot/efi/EFI/BOOT"
                    state["backup"] = (boot / "BOOTX64.EFI.before-hangar-repair").read_bytes()
                    state["installed"] = (boot / "BOOTX64.EFI").read_bytes()

            def fake_cleanup(*args):
                for child in work.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                return []

            with patch.object(vhd.os, "geteuid", return_value=0), \
                 patch.object(vhd.shutil, "which", return_value="/usr/bin/tool"), \
                 patch.object(vhd.subprocess, "run", return_value=type(
                     "Status", (), {"returncode": 1})()), \
                 patch.object(vhd, "check_output", side_effect=lambda *a: next(values)), \
                 patch.object(vhd, "verify_loop"), \
                 patch.object(vhd, "partitions", return_value=(
                     Path("/dev/loop42p1"), Path("/dev/loop42p2"))), \
                 patch.object(vhd, "command", side_effect=fake_command), \
                 patch.object(vhd, "cleanup_loop", side_effect=fake_cleanup), \
                 patch.object(vhd.tempfile, "mkdtemp", return_value=str(work)):
                vhd.repair_raw_image(image)

            self.assertEqual(state["backup"], original)
            self.assertEqual(state["installed"], b"MZ" + bytes(2046))
            self.assertEqual(state["grub_command"][0], "grub-mkstandalone")
            self.assertIn("/boot/grub/grub.cfg=", " ".join(state["grub_command"]))
            self.assertFalse(work.exists())

    def test_efi_vendor_paths_have_valid_image_uuid_locator(self):
        with tempfile.TemporaryDirectory() as d:
            esp = Path(d)
            boot = esp / "EFI/BOOT"
            boot.mkdir(parents=True)
            vhd.install_efi_grub_locator(esp, "550e8400-e29b-41d4-a716-446655440000")
            cfg = (boot / "grub.cfg").read_text()
            self.assertIn("search --no-floppy --fs-uuid --set=root", cfg)
            self.assertNotIn("set prefix=", cfg)
            self.assertIn("configfile ($root)/boot/grub/grub.cfg", cfg)
            self.assertNotIn("/dev/loop", cfg)

    def test_efi_locator_rejects_bad_uuid_and_symlink(self):
        with self.assertRaisesRegex(ValueError, "Invalid image root UUID"):
            vhd.make_efi_grub_locator("wrong; command")
        with tempfile.TemporaryDirectory() as d:
            esp = Path(d)
            boot = esp / "EFI/BOOT"
            boot.mkdir(parents=True)
            (boot / "grub.cfg").symlink_to(Path(d) / "outside")
            with self.assertRaisesRegex(ValueError, "unsafe EFI GRUB configuration"):
                vhd.install_efi_grub_locator(
                    esp, "550e8400-e29b-41d4-a716-446655440000")

    def test_efi_locator_is_image_specific_not_host_specific(self):
        a = vhd.make_efi_grub_locator(
            "550e8400-e29b-41d4-a716-446655440000")
        b = vhd.make_efi_grub_locator(
            "a1f8f726-22f9-49c0-a799-4ddbaef579fb")
        self.assertNotEqual(a, b)
        self.assertIn("search --no-floppy --fs-uuid", a)
        self.assertIn("configfile ($root)/boot/grub/grub.cfg", a)
        self.assertNotIn("/dev/loop", a)


if __name__ == "__main__":
    unittest.main()
