"""Conservative matching of Spotify track metadata to YouTube search results.

This module intentionally uses only the Python standard library so it can be
unit-tested independently of yt-dlp and bundled easily with Red Spindle.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional


ALTERNATE_VERSION_PATTERNS = {
    "live": r"\b(live|concert|at the .*?arena|live session)\b",
    "cover": r"\b(cover|covered by|tribute)\b",
    "karaoke": r"\bkaraoke\b",
    "instrumental": r"\b(instrumental|backing track|no vocals)\b",
    "remix": r"\b(remix|rework|bootleg|mash[ -]?up)\b",
    "slowed": r"\b(slowed|slower version|slowed down)\b",
    "sped_up": r"\b(sped[ -]?up|speed[ -]?up|faster version)\b",
    "acoustic": r"\b(acoustic|unplugged)\b",
    "extended": r"\b(extended mix|extended version|long version)\b",
    "nightcore": r"\bnightcore\b",
    "8d": r"\b8d audio\b",
}

CLEAN_PATTERNS = (
    r"\bclean version\b",
    r"\bclean edit\b",
    r"\bradio edit\b",
    r"\bradio version\b",
    r"\bcensored version\b",
    r"\bcensored\b",
    r"\bclean audio\b",
)
EXPLICIT_PATTERNS = (
    r"\bexplicit version\b",
    r"\bexplicit audio\b",
    r"\bexplicit\b",
    r"\buncensored\b",
    r"\bparental advisory\b",
)

_TRAILING_NOISE = re.compile(
    r"\s*(?:[-|–—:]\s*)?(?:official\s+(?:audio|video)|audio|lyrics?|lyric\s+video|visualizer|hd|4k|topic)\s*$",
    re.I,
)
_ARTIST_SPLIT = re.compile(r"\s*,\s*|\s+feat(?:uring)?\.?\s+|\s+ft\.?\s+", re.I)


def normalize_match_text(value: Any) -> str:
    """Normalize text for language-aware, punctuation-insensitive comparison."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("&", " and ")
    return re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).strip()


def _patterns_found(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, flags=re.I) for pattern in patterns)


def _artist_names(artist: str) -> List[str]:
    names = [artist.strip()]
    names.extend(part.strip() for part in _ARTIST_SPLIT.split(artist) if part.strip())
    # Keep longer names first; remove duplicates after normalization.
    seen = set()
    output = []
    for name in sorted(names, key=len, reverse=True):
        normalized = normalize_match_text(name)
        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(name)
    return output


def _strip_artist_from_title(candidate_title: str, artist: str) -> str:
    # Strip only trailing platform labels. Removing these words globally would
    # break legitimate titles such as "Video Killed the Radio Star".
    candidate_title = re.sub(r"\s*[\(\[][^\)\]]*(?:official|audio|video|lyrics?|visualizer|hd|4k|topic)[^\)\]]*[\)\]]\s*$", " ", candidate_title, flags=re.I)
    candidate_title = _TRAILING_NOISE.sub("", candidate_title)
    normalized_title = normalize_match_text(candidate_title)
    for name in _artist_names(artist):
        normalized_artist = normalize_match_text(name)
        if not normalized_artist:
            continue
        if normalized_title.startswith(normalized_artist + " "):
            normalized_title = normalized_title[len(normalized_artist):].strip()
        if normalized_title.endswith(" " + normalized_artist):
            normalized_title = normalized_title[:-len(normalized_artist)].strip()
    return re.sub(r"\s+", " ", normalized_title).strip()


def _title_similarity(expected_title: str, candidate_title: str, artist: str) -> float:
    expected = normalize_match_text(expected_title)
    candidate = _strip_artist_from_title(candidate_title, artist)
    if not expected or not candidate:
        return 0.0
    expected_tokens = expected.split()
    candidate_tokens = candidate.split()
    overlap = len(set(expected_tokens) & set(candidate_tokens)) / max(1, len(set(expected_tokens)))
    sequence = difflib.SequenceMatcher(None, expected, candidate).ratio()
    # Token coverage tolerates labels such as "Official Audio"; sequence
    # similarity still penalizes unrelated words and badly mismatched titles.
    return max(0.0, min(1.0, 0.72 * overlap + 0.28 * sequence))


def _artist_similarity(artist: str, candidate: Dict[str, Any]) -> float:
    if not artist or normalize_match_text(artist) in {"unknown", "various artists"}:
        return 0.5  # No useful artist metadata: neutral, not a free pass.

    identity = " ".join(
        str(candidate.get(key) or "")
        for key in ("channel", "uploader", "creator", "artist")
    )
    title = str(candidate.get("title") or "")
    identity_norm = normalize_match_text(identity)
    title_norm = normalize_match_text(title)
    best = 0.0

    for name in _artist_names(artist):
        normalized = normalize_match_text(name)
        tokens = set(normalized.split())
        if not tokens:
            continue
        if normalized and normalized in identity_norm:
            return 1.0
        if normalized and normalized in title_norm:
            best = max(best, 0.95)
            continue
        identity_coverage = len(tokens & set(identity_norm.split())) / len(tokens)
        title_coverage = len(tokens & set(title_norm.split())) / len(tokens)
        best = max(best, 0.82 * identity_coverage, 0.76 * title_coverage)

    return max(0.0, min(1.0, best))


def _candidate_duration(candidate: Dict[str, Any]) -> Optional[float]:
    value = candidate.get("duration")
    if value is None and candidate.get("duration_ms") is not None:
        try:
            value = float(candidate["duration_ms"]) / 1000.0
        except (TypeError, ValueError):
            return None
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    return duration if duration > 0 else None


def _duration_similarity(target_seconds: Optional[float], candidate_seconds: Optional[float]) -> Optional[float]:
    if target_seconds is None or target_seconds <= 0 or candidate_seconds is None:
        return None
    delta = abs(target_seconds - candidate_seconds)
    if delta <= 2:
        return 1.0
    if delta <= 5:
        return 0.90
    if delta <= 10:
        return 0.78
    if delta <= 15:
        return 0.62
    return 0.25


def _alternate_versions(expected_title: str, candidate_title: str) -> List[str]:
    expected = normalize_match_text(expected_title)
    candidate = normalize_match_text(candidate_title)
    expected_flags = {
        name for name, pattern in ALTERNATE_VERSION_PATTERNS.items()
        if re.search(pattern, expected, flags=re.I)
    }
    candidate_flags = {
        name for name, pattern in ALTERNATE_VERSION_PATTERNS.items()
        if re.search(pattern, candidate, flags=re.I)
    }
    return sorted(candidate_flags - expected_flags)


def _version_markers(candidate_title: str) -> Dict[str, bool]:
    text = normalize_match_text(candidate_title)
    return {
        "clean": _patterns_found(text, CLEAN_PATTERNS),
        "explicit": _patterns_found(text, EXPLICIT_PATTERNS),
    }


def score_youtube_candidate(
    track: Dict[str, Any],
    candidate: Dict[str, Any],
    explicit_mode: str = "explicit",
    min_score: float = 0.72,
) -> Dict[str, Any]:
    """Score a single YouTube candidate and explain whether it is acceptable."""
    title = str(track.get("title") or "")
    artist = str(track.get("artist") or "")
    candidate_title = str(candidate.get("title") or "")
    reasons: List[str] = []

    title_score = _title_similarity(title, candidate_title, artist)
    artist_score = _artist_similarity(artist, candidate)

    target_ms = track.get("duration_ms")
    try:
        target_seconds = float(target_ms) / 1000.0 if target_ms else None
    except (TypeError, ValueError):
        target_seconds = None
    found_seconds = _candidate_duration(candidate)
    duration_score = _duration_similarity(target_seconds, found_seconds)
    duration_delta = (
        abs(target_seconds - found_seconds)
        if target_seconds is not None and found_seconds is not None else None
    )

    if duration_score is None:
        score = 0.68 * title_score + 0.32 * artist_score
    else:
        score = 0.55 * title_score + 0.30 * artist_score + 0.15 * duration_score

    accepted = True
    if not candidate_title:
        accepted = False
        reasons.append("YouTube result has no title")

    alternate = _alternate_versions(title, candidate_title)
    if alternate:
        accepted = False
        reasons.append("different recording style: " + ", ".join(alternate))

    if title_score < 0.70:
        accepted = False
        reasons.append("title match is too weak")
    if artist_score < 0.42 and artist and normalize_match_text(artist) != "unknown":
        accepted = False
        reasons.append("artist could not be matched confidently")

    if duration_delta is not None and target_seconds:
        tolerance = max(8.0, min(20.0, target_seconds * 0.08))
        if duration_delta > tolerance:
            accepted = False
            reasons.append(
                f"duration differs by {duration_delta:.1f}s (allowed {tolerance:.1f}s)"
            )

    markers = _version_markers(candidate_title)
    source_explicit = bool(track.get("is_explicit", False))
    clean_mode = explicit_mode.casefold() == "clean"
    version_status = "unverified"
    version_verified = False

    if markers["clean"] and markers["explicit"]:
        accepted = False
        reasons.append("candidate has conflicting clean and explicit labels")
    elif source_explicit and clean_mode:
        if markers["explicit"]:
            accepted = False
            reasons.append("candidate is labelled explicit, but clean audio was requested")
        elif not markers["clean"]:
            accepted = False
            reasons.append("clean/radio-edit version is not clearly labelled")
        else:
            version_status = "clean"
            version_verified = True
    elif source_explicit:
        if markers["clean"]:
            accepted = False
            reasons.append("candidate is labelled clean, but the Spotify track is explicit")
        elif markers["explicit"]:
            version_status = "explicit"
            version_verified = True
        else:
            # A search result without a version label cannot prove that the
            # recording is explicit. It may still be the correct recording.
            version_status = "unverified"
    else:
        if markers["explicit"]:
            accepted = False
            reasons.append("candidate is labelled explicit, but Spotify marks the track non-explicit")
        elif markers["clean"]:
            version_status = "clean"
            version_verified = True

    if score < min_score:
        accepted = False
        reasons.append(f"overall match score {score:.0%} is below {min_score:.0%}")

    if accepted and not reasons:
        reasons.append("title, artist and duration checks passed")

    return {
        "candidate": candidate,
        "score": round(score, 4),
        "title_score": round(title_score, 4),
        "artist_score": round(artist_score, 4),
        "duration_score": round(duration_score, 4) if duration_score is not None else None,
        "duration_delta": round(duration_delta, 2) if duration_delta is not None else None,
        "accepted": accepted,
        "reason": "; ".join(reasons),
        "version_status": version_status,
        "version_verified": version_verified,
    }


def rank_youtube_candidates(
    track: Dict[str, Any],
    candidates: Iterable[Dict[str, Any]],
    explicit_mode: str = "explicit",
    min_score: float = 0.72,
) -> List[Dict[str, Any]]:
    """Return candidates sorted by match score, best first."""
    ranked = [
        score_youtube_candidate(track, candidate, explicit_mode, min_score)
        for candidate in candidates
        if isinstance(candidate, dict)
    ]
    return sorted(ranked, key=lambda item: (item["accepted"], item["score"]), reverse=True)
