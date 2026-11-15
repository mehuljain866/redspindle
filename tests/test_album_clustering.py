import unittest
from pathlib import Path
import tempfile
import json
import shutil
from mutagen.id3 import ID3, TALB, TCMP, TPE1, TPE2

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
        self.assertEqual(_extract_lead_artist("Queen & David Bowie"), "Queen & David Bowie")
        self.assertEqual(_extract_lead_artist("Kendrick Lamar with SZA"), "Kendrick Lamar with SZA")
        self.assertEqual(_extract_lead_artist("AC/DC"), "AC/DC")
        self.assertEqual(_extract_lead_artist("Earth, Wind & Fire"), "Earth, Wind & Fire")
        self.assertEqual(_extract_lead_artist("Simon & Garfunkel"), "Simon & Garfunkel")
        self.assertEqual(_extract_lead_artist("Solo Artist"), "Solo Artist")

    def test_prevents_greatest_hits_collision(self):
        """Identical generic album titles by different artists must not be merged."""
        tracks = [
            {"album": "Greatest Hits", "artist": "Queen", "album_artist": "", "title": "Bohemian Rhapsody"},
            {"album": "Greatest Hits", "artist": "Queen feat. David Bowie", "album_artist": "", "title": "Under Pressure"},
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

    def test_soundtrack_detection_does_not_match_ordinary_album_title(self):
        tracks = [
            {"album": "The Score", "artist": "Fugees", "album_artist": "", "title": "Ready or Not"},
            {"album": "The Score", "artist": "Fugees", "album_artist": "", "title": "Fu-Gee-La"},
        ]
        clusters = list(_cluster_album_tracks(tracks))
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0][1], "Fugees")
        self.assertFalse(clusters[0][2])

    def test_backup_restore_restores_all_modified_mp3_tags(self):
        """The snapshot must restore track artist, album, album artist and compilation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "sample.mp3"
            current = ID3()
            current.add(TPE1(encoding=3, text="Changed Artist"))
            current.add(TALB(encoding=3, text="Changed Album"))
            current.add(TPE2(encoding=3, text="Changed Album Artist"))
            current.add(TCMP(encoding=3, text="1"))
            current.save(audio_path, v2_version=3)

            backup_file = Path(tmpdir) / "backup.json"
            backup_file.write_text(json.dumps({"files": {str(audio_path): {
                "ext": ".mp3", "artist": "Original Artist", "album": "Original Album",
                "album_artist": "Original Album Artist", "compilation": False,
            }}}), encoding="utf-8")

            result = restore_tags_from_backup(backup_file)
            restored = ID3(str(audio_path))
            self.assertEqual(result["restored_files"], 1)
            self.assertEqual(str(restored["TPE1"]), "Original Artist")
            self.assertEqual(str(restored["TALB"]), "Original Album")
            self.assertEqual(str(restored["TPE2"]), "Original Album Artist")
            self.assertNotIn("TCMP", restored)

    def test_legacy_backup_without_artist_or_album_keeps_those_fields(self):
        """Old snapshots must not erase fields they never recorded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "legacy.mp3"
            current = ID3()
            current.add(TPE1(encoding=3, text="Keep Artist"))
            current.add(TALB(encoding=3, text="Keep Album"))
            current.save(audio_path, v2_version=3)
            backup_file = Path(tmpdir) / "legacy-backup.json"
            backup_file.write_text(json.dumps({"files": {str(audio_path): {
                "ext": ".mp3", "album_artist": "Old Album Artist", "compilation": False,
            }}}), encoding="utf-8")

            restore_tags_from_backup(backup_file)
            restored = ID3(str(audio_path))
            self.assertEqual(str(restored["TPE1"]), "Keep Artist")
            self.assertEqual(str(restored["TALB"]), "Keep Album")


if __name__ == "__main__":
    unittest.main()
