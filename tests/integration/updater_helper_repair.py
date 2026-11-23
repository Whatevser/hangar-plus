#!/usr/bin/env python3
"""Regression tests: old updater can omit newly introduced libexec helpers."""
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def module(name, relative):
    path = ROOT / relative
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


updater = module("hangar_updater_repair", "libexec/hangar-update")
portable = module("hangar_portable_fallback", "libexec/hangar-portable")
SHA = "a" * 40


class MissingHelperTests(unittest.TestCase):
    def test_same_commit_self_repairs_only_missing_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin = root / "plugin"
            installed = root / "executables"
            source = plugin / "libexec"
            source.mkdir(parents=True)
            installed.mkdir()
            for name in updater.EXECUTABLES:
                (source / name).write_text("new " + name)
                if name != "hangar-vhd":
                    (installed / name).write_text("existing " + name)
            (root / "installed-commit").write_text(SHA + "\n")
            with patch.object(updater, "PLUGIN", plugin), \
                 patch.object(updater, "EXEC", installed), \
                 patch.object(updater, "COMMIT_FILE", root / "installed-commit"), \
                 patch.object(updater, "LOCK_FILE", str(root / "update.lock")), \
                 patch.object(updater, "CONF", root), \
                 patch.object(updater, "latest_commit", return_value=SHA):
                state = updater.state(include_latest=True)
                self.assertTrue(state["available"])
                self.assertEqual(updater.missing_executables(), ["hangar-vhd"])
                updater.apply()
                self.assertEqual((installed / "hangar-vhd").read_text(), "new hangar-vhd")
                self.assertEqual((installed / "hangar-run").read_text(), "existing hangar-run")
                self.assertEqual((installed / "hangar-vhd").stat().st_mode & 0o777, 0o755)
                self.assertEqual((root / "installed-commit").read_text(), SHA + "\n")
                self.assertFalse(updater.state(include_latest=True)["available"])
                self.assertEqual(updater.repair_missing_executables(), [])

    def test_missing_source_does_not_mark_install_as_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "libexec").mkdir()
            missing = root / "missing"
            with patch.object(updater, "PLUGIN", root), \
                 patch.object(updater, "EXEC", missing):
                with self.assertRaisesRegex(RuntimeError, "lacks"):
                    updater.repair_missing_executables()
                self.assertFalse(missing.exists())

    def test_portable_uses_bundle_if_old_updater_skipped_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installed = root / "missing-vhd"
            bundled = root / "hangar/libexec/hangar-vhd"
            bundled.parent.mkdir(parents=True)
            bundled.write_text("valid script")
            with patch.object(portable, "VHD_EXEC", installed), \
                 patch.object(portable, "VHD_BUNDLED", bundled):
                self.assertEqual(portable.vhd_builder(), bundled)
                installed.write_text("installed script")
                self.assertEqual(portable.vhd_builder(), installed)
                installed.unlink()
                bundled.unlink()
                with self.assertRaisesRegex(ValueError, "missing"):
                    portable.vhd_builder()

    def test_portable_does_not_execute_symlinked_builder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            symlink = root / "vhd"
            real = root / "target"
            real.write_text("script")
            symlink.symlink_to(real)
            with patch.object(portable, "VHD_EXEC", symlink), \
                 patch.object(portable, "VHD_BUNDLED", root / "not-there"):
                with self.assertRaisesRegex(ValueError, "missing"):
                    portable.vhd_builder()


if __name__ == "__main__":
    unittest.main()
