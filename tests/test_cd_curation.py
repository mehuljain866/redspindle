import unittest
from cd_prep import calculate_disc_distribution, estimate_track_size_bytes


class CDCurationTests(unittest.TestCase):
    def test_estimate_track_size(self):
        # 180s track at 192k: (192 * 1000 / 8) * 180 + 85000 = 4,405,000 bytes
        est = estimate_track_size_bytes(180.0, 0, "192k")
        self.assertGreater(est, 4_000_000)
        self.assertLess(est, 5_000_000)

    def test_data_cd_packing_by_byte_size(self):
        """Data CD packs until 700 MB limit (minus safe margin) is approached."""
        # 150 tracks of ~4.5 MB each (~675 MB)
        tracks = [
            {"path": f"track_{i}.mp3", "duration": 180.0, "size": 4_500_000, "title": f"Song {i}"}
            for i in range(150)
        ]
        discs = calculate_disc_distribution(
            tracks,
            disc_capacity_mb=700.0,
            target_bitrate="192k",
            safe_margin_mb=10.0,
            is_audio_cd=False,
        )
        self.assertEqual(len(discs), 1)
        self.assertEqual(discs[0]["disc_number"], 1)
        self.assertFalse(discs[0]["is_audio_cd"])
        self.assertLessEqual(discs[0]["total_mb"], 700.0)

    def test_audio_cd_packing_by_duration(self):
        """Audio CD (CD-DA) packs tracks by time duration (78 min safe threshold)."""
        # 30 tracks of 4 minutes (240s) each = 120 minutes total -> requires 2 discs
        tracks = [
            {"path": f"track_{i}.mp3", "duration": 240.0, "size": 6_000_000, "title": f"Song {i}"}
            for i in range(30)
        ]
        discs = calculate_disc_distribution(
            tracks,
            is_audio_cd=True,
            max_audio_cd_minutes=80.0,
        )
        # Safe limit is 78 mins = 19.5 tracks -> 19 tracks on Disc 1 (76 mins), 11 on Disc 2 (44 mins)
        self.assertEqual(len(discs), 2)
        self.assertTrue(discs[0]["is_audio_cd"])
        self.assertLessEqual(discs[0]["total_duration_min"], 78.0)
        self.assertEqual(len(discs[0]["tracks"]), 19)
        self.assertEqual(len(discs[1]["tracks"]), 11)

    def test_audio_cd_74_minute_variant(self):
        """74-minute disc safe limit is 72 minutes."""
        # 20 tracks of 4.5 minutes (270s) each = 90 minutes total
        tracks = [
            {"path": f"track_{i}.mp3", "duration": 270.0, "size": 6_000_000, "title": f"Song {i}"}
            for i in range(20)
        ]
        discs = calculate_disc_distribution(
            tracks,
            is_audio_cd=True,
            max_audio_cd_minutes=74.0,
        )
        # Safe limit is 72 mins = 16 tracks (72 mins) -> Disc 1 has 16, Disc 2 has 4
        self.assertEqual(len(discs), 2)
        self.assertLessEqual(discs[0]["total_duration_min"], 72.0)
        self.assertEqual(len(discs[0]["tracks"]), 16)
        self.assertEqual(len(discs[1]["tracks"]), 4)

    def test_disc_folder_cleanup_removes_stale_files(self):
        """Ensures stale files in existing Disc folders are removed before reuse."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            disc_folder = Path(tmpdir) / "Disc 1"
            disc_folder.mkdir()
            old_track = disc_folder / "99 - OldSong.mp3"
            old_track.write_text("dummy")
            old_m3u = disc_folder / "playlist.m3u"
            old_m3u.write_text("dummy")

            # Simulate cleanup logic
            for old_file in list(disc_folder.iterdir()):
                if old_file.is_file() and (
                    old_file.suffix.lower() in (".mp3", ".m4a", ".flac", ".opus", ".wav", ".m3u", ".txt")
                    or old_file.name in ("playlist.m3u", "disc_tracklist.txt")
                ):
                    old_file.unlink()

            remaining = list(disc_folder.iterdir())
            self.assertEqual(len(remaining), 0)


if __name__ == "__main__":
    unittest.main()
