import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import platform_utils


class PlatformOpenPathTests(unittest.TestCase):
    def test_windows_uses_startfile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(platform_utils.sys, "platform", "win32"):
                with patch.object(platform_utils.os, "startfile", create=True) as startfile:
                    platform_utils.open_path(Path(tmpdir))
            startfile.assert_called_once_with(str(Path(tmpdir).resolve()))

    def test_macos_uses_open_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(platform_utils.sys, "platform", "darwin"):
                with patch("platform_utils.subprocess.Popen") as popen:
                    platform_utils.open_path(Path(tmpdir))
            self.assertEqual(popen.call_args.args[0][0], "open")

    def test_linux_uses_xdg_open(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(platform_utils.sys, "platform", "linux"):
                with patch("platform_utils.shutil.which", return_value="/usr/bin/xdg-open"):
                    with patch("platform_utils.subprocess.Popen") as popen:
                        platform_utils.open_path(Path(tmpdir))
            self.assertEqual(popen.call_args.args[0][0], "/usr/bin/xdg-open")

    def test_missing_target_raises(self):
        with self.assertRaises(FileNotFoundError):
            platform_utils.open_path(Path("/this/path/should/not/exist/redspindle"))


if __name__ == "__main__":
    unittest.main()
