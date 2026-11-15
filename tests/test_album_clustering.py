import unittest
from pathlib import Path
import tempfile
import json
import shutil

from spotify_dl import (
    _cluster_album_tracks,
    _extract_lead_artist,
    fix_library_album_tags,
    restore_tags_from_backup,
)


class AlbumClusteringTests(unittest.TestCase):
    def test_lead_artist_extraction(self):
        self.assertEqual(_extract_lead_artist("Gorillaz feat. Snoop Dogg"), "Gorillaz")
        self.assertEqual(_extract_lead_artist("Daft Punk ft. Pharrell Williams"), "Daft Punk")
        self.assertEqual(_extract_lead_artist("Queen & David Bowie"), "Queen")
        self.assertEqual(_extract_lead_artist("Kendrick Lamar with SZA"), "Kendrick Lamar")
        self.assertEqual(_extract_lead_artist("Solo Artist"), "Solo Artist")

    def test_prevents_greatest_hits_collision(self):
        """Identical generic album titles by different artists must not be merged."""
        tracks = [
            {"album": "Greatest Hits", "artist": "Queen", "album_artist": "", "title": "Bohemian Rhapsody"},
            {"album": "Greatest Hits", "artist": "Queen & David Bowie", "album_artist": "", "title": "Under Pressure"},
            {"album": "Greatest Hits", "artist": "ABBA", "album_artist": "", "title": "Dancing Queen"},
            {"album": "Greatest Hits", "artist": "ABBA", "album_artist": "", "title": "Mamma Mia"},
        ]
        clusters = list(_cluster_album_tracks(tracks))
        self.assertEqual(len(clusters), 2)
        album_artists = {c[1] for c in clusters}
        self.assertEqual(album_artists, {"Queen", "ABBA"})

    def test_groups_featured_artists_to_lead_artist(self):
        """Album tracks featuring different guest artists should resolve to the primary artist."""
        tracks = [
            {"album": "Demon Days", "artist": "Gorillaz", "album_artist": "", "title": "Intro"},
            {"album": "Demon Days", "artist": "Gorillaz feat. Snoop Dogg", "album_artist": "", "title": "Welcome to the World"},
            {"album": "Demon Days", "artist": "Gorillaz feat. De La Soul", "album_artist": "", "title": "Feel Good Inc."},
        ]
        clusters = list(_cluster_album_tracks(tracks))
        self.assertEqual(len(clusters), 1)
        alb_name, album_artist, is_comp, sub_tracks = clusters[0]
        self.assertEqual(album_artist, "Gorillaz")
        self.assertFalse(is_comp)
        self.assertEqual(len(sub_tracks), 3)

    def test_identifies_soundtracks_as_various_artists(self):
        """Soundtrack albums should be marked as Various Artists compilations."""
        tracks = [
            {"album": "Pulp Fiction (Music From The Motion Picture)", "artist": "Dick Dale", "album_artist": ""},
            {"album": "Pulp Fiction (Music From The Motion Picture)", "artist": "Kool & The Gang", "album_artist": ""},
            {"album": "Pulp Fiction (Music From The Motion Picture)", "artist": "Dusty Springfield", "album_artist": ""},
        ]
        clusters = list(_cluster_album_tracks(tracks))
        self.assertEqual(len(clusters), 1)
        alb_name, album_artist, is_comp, sub_tracks = clusters[0]
        self.assertEqual(album_artist, "Various Artists")
        self.assertTrue(is_comp)

    def test_backup_and_restore_data_structure(self):
        """Verifies JSON backup snapshot serialization and tag restoration logic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_file = Path(tmpdir) / "test_backup.json"
            sample_backup = {
                "created_at": "2026-11-15T12:00:00",
                "files": {
                    str(Path(tmpdir) / "nonexistent.mp3"): {
                        "title": "Test Title",
                        "artist": "Test Artist",
                        "album": "Test Album",
                        "album_artist": "Original Artist",
                        "compilation": False,
                    }
                }
            }
            backup_file.write_text(json.dumps(sample_backup), encoding="utf-8")

            # Restore handles missing file gracefully without crashing
            res = restore_tags_from_backup(backup_file)
            self.assertEqual(res.get("total_in_backup"), 1)
            self.assertEqual(res.get("restored_files"), 0)


if __name__ == "__main__":
    unittest.main()
