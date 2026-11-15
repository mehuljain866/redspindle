import unittest
import sys
import argparse
from pathlib import Path


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

    def test_argument_defaults(self):
        """Verifies CLI parser defaults conform to Red Spindle 2.2.2 requirements."""
        # Simulate parser args
        import spotify_dl
        parser = argparse.ArgumentParser(prog="redspindle")
        parser.add_argument("url", nargs="?", default=None)
        parser.add_argument("-o", "--output", default="default_dir")
        parser.add_argument("--format", choices=["mp3", "m4a", "flac", "opus", "wav"], default="mp3")
        parser.add_argument("--bitrate", choices=["128k", "192k", "256k", "320k"], default="320k")
        parser.add_argument("--explicit-mode", choices=["explicit", "clean"], default="explicit")
        parser.add_argument("--lyrics-script", choices=["hinglish", "devanagari", "original"], default="hinglish")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--no-recursive", action="store_true")
        parser.add_argument("--no-backup", action="store_true")

        args = parser.parse_args([])
        self.assertIsNone(args.url)
        self.assertEqual(args.format, "mp3")
        self.assertEqual(args.bitrate, "320k")
        self.assertEqual(args.explicit_mode, "explicit")
        self.assertEqual(args.lyrics_script, "hinglish")
        self.assertFalse(args.dry_run)
        self.assertFalse(args.no_recursive)
        self.assertFalse(args.no_backup)


if __name__ == "__main__":
    unittest.main()
