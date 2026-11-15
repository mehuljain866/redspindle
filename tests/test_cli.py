import unittest
import sys
import tempfile
import contextlib
import io
from pathlib import Path
from unittest.mock import patch


class CLITests(unittest.TestCase):
    def setUp(self):
        # Import parser creator or test argument parsing directly
        import spotify_dl
        # Extract argument parser configuration
        from spotify_dl import (
            _cluster_album_tracks,
            get_audio_file_bitrate,
            make_output_path,
        )

    def test_output_path_sanitization(self):
        from spotify_dl import make_output_path
        track = {
            "title": 'Song: "Special" / <Remix>?',
            "artist": "AC/DC * & Friend",
            "album": "Highway to Hell",
        }
        dest = make_output_path(Path("/music"), track, fmt="mp3")
        # Ensure invalid Windows characters (: * ? " < > | / \) are replaced in the filename
        bad_chars = [':', '*', '?', '"', '<', '>', '|']
        for ch in bad_chars:
            self.assertNotIn(ch, dest.name)
        self.assertTrue(dest.name.endswith(".mp3"))

    def test_defaults_are_read_from_the_real_application_parser(self):
        """Run main() with defaults and inspect the real downsize dispatch."""
        import spotify_dl
        fake_result = {
            "total_files": 0, "processed": 0, "original_bytes": 0,
            "new_bytes": 0, "saved_bytes": 0,
        }
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sys, "argv", ["spotify_dl.py", "--downsize", folder]):
                with patch.object(spotify_dl, "batch_transcode_folder", return_value=fake_result) as transcode:
                    with contextlib.redirect_stdout(io.StringIO()):
                        spotify_dl.main()

        kwargs = transcode.call_args.kwargs
        self.assertEqual(kwargs["target_bitrate"], "320k")
        self.assertIsNone(kwargs["target_fmt"])
        self.assertEqual(kwargs["max_workers"], 4)

    def test_real_parser_rejects_unsupported_format(self):
        import spotify_dl
        with patch.object(sys, "argv", ["spotify_dl.py", "--format", "aac"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    spotify_dl.main()
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
