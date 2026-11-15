import os
import sys
import types
import unittest
from unittest.mock import patch

import ffmpeg_support


class FFmpegSupportTests(unittest.TestCase):
    def test_explicit_override_has_highest_priority(self):
        expected = os.path.normcase(os.path.abspath("/custom/ffmpeg"))
        with patch.dict(os.environ, {"REDSPINDLE_FFMPEG": "/custom/ffmpeg"}, clear=False):
            with patch("ffmpeg_support.shutil.which", return_value="/usr/bin/ffmpeg"):
                with patch("ffmpeg_support._is_usable_ffmpeg", side_effect=lambda p: p in {expected, os.path.normcase(os.path.abspath("/usr/bin/ffmpeg"))}):
                    self.assertEqual(ffmpeg_support.get_ffmpeg_executable(), expected)

    def test_system_ffmpeg_is_preferred_to_bundled_binary(self):
        fake_module = types.SimpleNamespace(get_ffmpeg_exe=lambda: "/venv/imageio_ffmpeg/ffmpeg")
        with patch.dict(os.environ, {"REDSPINDLE_FFMPEG": ""}, clear=False):
            with patch("ffmpeg_support.shutil.which", return_value="/usr/bin/ffmpeg"):
                with patch.dict(sys.modules, {"imageio_ffmpeg": fake_module}):
                    with patch("ffmpeg_support._is_usable_ffmpeg", return_value=True):
                        self.assertEqual(ffmpeg_support.get_ffmpeg_executable(), os.path.normcase(os.path.abspath("/usr/bin/ffmpeg")))

    def test_bundled_binary_is_used_when_system_ffmpeg_is_missing(self):
        fake_module = types.SimpleNamespace(get_ffmpeg_exe=lambda: "/venv/imageio_ffmpeg/ffmpeg")
        with patch.dict(os.environ, {"REDSPINDLE_FFMPEG": ""}, clear=False):
            with patch("ffmpeg_support.shutil.which", return_value=None):
                with patch.dict(sys.modules, {"imageio_ffmpeg": fake_module}):
                    with patch("ffmpeg_support._is_usable_ffmpeg", return_value=True):
                        self.assertEqual(ffmpeg_support.get_ffmpeg_executable(), os.path.normcase(os.path.abspath("/venv/imageio_ffmpeg/ffmpeg")))

    def test_invalid_system_ffmpeg_falls_back_to_bundled_binary(self):
        fake_module = types.SimpleNamespace(get_ffmpeg_exe=lambda: "/venv/imageio_ffmpeg/ffmpeg")
        def usable(path):
            return path.replace("\\", "/").endswith("imageio_ffmpeg/ffmpeg")
        with patch.dict(os.environ, {"REDSPINDLE_FFMPEG": ""}, clear=False):
            with patch("ffmpeg_support.shutil.which", return_value="/usr/bin/ffmpeg"):
                with patch.dict(sys.modules, {"imageio_ffmpeg": fake_module}):
                    with patch("ffmpeg_support._is_usable_ffmpeg", side_effect=usable):
                        result = ffmpeg_support.get_ffmpeg_executable()
                        self.assertIsNotNone(result)
                        self.assertTrue(result.replace("\\", "/").endswith("imageio_ffmpeg/ffmpeg"))

    def test_missing_mp3_encoder_falls_back_to_bundled_ffmpeg(self):
        fake_module = types.SimpleNamespace(get_ffmpeg_exe=lambda: "/venv/imageio_ffmpeg/ffmpeg")
        def has_encoder(path, name):
            return path.replace("\\", "/").endswith("imageio_ffmpeg/ffmpeg") and name == "libmp3lame"
        with patch.dict(os.environ, {"REDSPINDLE_FFMPEG": ""}, clear=False):
            with patch("ffmpeg_support.shutil.which", return_value="/usr/bin/ffmpeg"):
                with patch.dict(sys.modules, {"imageio_ffmpeg": fake_module}):
                    with patch("ffmpeg_support._is_usable_ffmpeg", return_value=True):
                        with patch("ffmpeg_support.ffmpeg_has_encoder", side_effect=has_encoder):
                            result = ffmpeg_support.get_ffmpeg_executable(required_encoder="libmp3lame")
                            self.assertIsNotNone(result)
                            self.assertTrue(result.replace("\\", "/").endswith("imageio_ffmpeg/ffmpeg"))

    def test_returns_none_when_no_candidate_is_usable(self):
        fake_module = types.SimpleNamespace(get_ffmpeg_exe=lambda: "/missing/ffmpeg")
        with patch.dict(os.environ, {"REDSPINDLE_FFMPEG": ""}, clear=False):
            with patch("ffmpeg_support.shutil.which", return_value=None):
                with patch.dict(sys.modules, {"imageio_ffmpeg": fake_module}):
                    with patch("ffmpeg_support._is_usable_ffmpeg", return_value=False):
                        self.assertIsNone(ffmpeg_support.get_ffmpeg_executable())

    def test_returns_none_when_required_encoder_is_missing_everywhere(self):
        fake_module = types.SimpleNamespace(get_ffmpeg_exe=lambda: "/venv/imageio_ffmpeg/ffmpeg")
        with patch.dict(os.environ, {"REDSPINDLE_FFMPEG": ""}, clear=False):
            with patch("ffmpeg_support.shutil.which", return_value="/usr/bin/ffmpeg"):
                with patch.dict(sys.modules, {"imageio_ffmpeg": fake_module}):
                    with patch("ffmpeg_support._is_usable_ffmpeg", return_value=True):
                        with patch("ffmpeg_support.ffmpeg_has_encoder", return_value=False):
                            self.assertIsNone(ffmpeg_support.get_ffmpeg_executable(required_encoder="libmp3lame"))

    def test_mp3_encoder_check_detects_encoder_line(self):
        result = types.SimpleNamespace(returncode=0, stdout=" A....D libmp3lame           libmp3lame MP3 (MPEG audio layer 3) (codec mp3)\n")
        with patch("ffmpeg_support.subprocess.run", return_value=result):
            self.assertTrue(ffmpeg_support.ffmpeg_has_encoder("/usr/bin/ffmpeg", "libmp3lame"))

    def test_mp3_encoder_check_rejects_missing_encoder(self):
        result = types.SimpleNamespace(returncode=0, stdout=" A....D aac                  AAC (Advanced Audio Coding) (codec aac)\n")
        with patch("ffmpeg_support.subprocess.run", return_value=result):
            self.assertFalse(ffmpeg_support.ffmpeg_has_encoder("/usr/bin/ffmpeg", "libmp3lame"))


if __name__ == "__main__":
    unittest.main()
