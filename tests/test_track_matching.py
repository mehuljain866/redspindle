import unittest

from track_matching import rank_youtube_candidates, score_youtube_candidate


class TrackMatchingTests(unittest.TestCase):
    def setUp(self):
        self.track = {
            "title": "Blinding Lights",
            "artist": "The Weeknd",
            "duration_ms": 200_000,
            "is_explicit": False,
        }

    def candidate(self, **overrides):
        value = {
            "id": "abc123",
            "title": "The Weeknd - Blinding Lights (Official Audio)",
            "uploader": "The Weeknd - Topic",
            "duration": 200,
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
        }
        value.update(overrides)
        return value

    def test_accepts_exact_artist_title_and_duration_match(self):
        result = score_youtube_candidate(self.track, self.candidate())
        self.assertTrue(result["accepted"], result["reason"])
        self.assertGreaterEqual(result["score"], 0.90)

    def test_rejects_live_recording_when_studio_version_requested(self):
        candidate = self.candidate(title="The Weeknd - Blinding Lights (Live in Concert)", duration=238)
        result = score_youtube_candidate(self.track, candidate)
        self.assertFalse(result["accepted"])
        self.assertIn("live", result["reason"])

    def test_rejects_large_duration_mismatch(self):
        result = score_youtube_candidate(self.track, self.candidate(duration=245))
        self.assertFalse(result["accepted"])
        self.assertIn("duration differs", result["reason"])

    def test_rejects_wrong_artist_even_when_title_matches(self):
        candidate = self.candidate(
            title="Blinding Lights",
            uploader="Random Cover Channel",
        )
        result = score_youtube_candidate(self.track, candidate)
        self.assertFalse(result["accepted"])

    def test_clean_mode_requires_clean_label_for_explicit_source_track(self):
        explicit_track = dict(self.track, is_explicit=True)
        ordinary = self.candidate()
        result = score_youtube_candidate(explicit_track, ordinary, explicit_mode="clean")
        self.assertFalse(result["accepted"])
        self.assertIn("not clearly labelled", result["reason"])

    def test_accepts_and_marks_labelled_clean_version(self):
        explicit_track = dict(self.track, is_explicit=True)
        candidate = self.candidate(title="The Weeknd - Blinding Lights (Clean Radio Edit)")
        result = score_youtube_candidate(explicit_track, candidate, explicit_mode="clean")
        self.assertTrue(result["accepted"], result["reason"])
        self.assertEqual(result["version_status"], "clean")
        self.assertTrue(result["version_verified"])

    def test_rejects_explicit_candidate_for_non_explicit_spotify_track(self):
        candidate = self.candidate(title="The Weeknd - Blinding Lights (Explicit Audio)")
        result = score_youtube_candidate(self.track, candidate)
        self.assertFalse(result["accepted"])
        self.assertIn("Spotify marks the track non-explicit", result["reason"])

    def test_explicit_candidate_is_marked_verified(self):
        explicit_track = dict(self.track, is_explicit=True)
        candidate = self.candidate(title="The Weeknd - Blinding Lights (Explicit Version)")
        result = score_youtube_candidate(explicit_track, candidate)
        self.assertTrue(result["accepted"], result["reason"])
        self.assertEqual(result["version_status"], "explicit")
        self.assertTrue(result["version_verified"])

    def test_ranks_accepted_candidate_ahead_of_rejected_candidates(self):
        wrong = self.candidate(title="The Weeknd - Blinding Lights Live", duration=240)
        exact = self.candidate()
        ranked = rank_youtube_candidates(self.track, [wrong, exact])
        self.assertTrue(ranked[0]["accepted"])
        self.assertEqual(ranked[0]["candidate"]["id"], "abc123")
        self.assertFalse(ranked[1]["accepted"])


if __name__ == "__main__":
    unittest.main()
