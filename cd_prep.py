"""
CD Burn Prep & Song Curator
Allows interactive 'Tinder-style' song curation using keyboard arrow keys
(Up = Select/Keep, Down = Reject/Skip, Right = +5s/+10s, Left = -5s/-10s, Space = Pause/Play),
smart disc packing for 700 MB CD-Rs (Moser Baer), session JSON persistence,
and multi-threaded disc folder generation with optional audio compression.
"""

import os
import sys
import re
import json
import time
import shutil
import ctypes
import threading
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Callable
from collections import deque
import io

from PIL import Image, ImageTk, ImageDraw
import customtkinter as ctk
from tkinter import filedialog, messagebox

# Import transcoding and metadata helpers from spotify_dl
try:
    from spotify_dl import transcode_audio_file, get_ffmpeg_executable
except ImportError:
    transcode_audio_file = None
    get_ffmpeg_executable = None

try:
    import mutagen
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3
except ImportError:
    mutagen = None
    MP3 = None
    ID3 = None


# ──────────────────────────────────────────────────────────────────────────────
# Native Windows MCI Audio Player with Seek & Position Tracking
# ──────────────────────────────────────────────────────────────────────────────

class MCIAudioPlayer:
    """
    Native Windows MCI audio player for low-latency playback, pause, and seeking.
    Requires zero external audio libraries.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._alias = "cd_curator_mci"
        self._mci = ctypes.windll.winmm.mciSendStringW
        self._current_file: Optional[str] = None
        self._is_playing: bool = False
        self._length_ms: int = 0

    def load_track(self, file_path: str) -> bool:
        with self._lock:
            self._close_internal()
            if not file_path or not os.path.exists(file_path):
                return False
            cmd = f'open "{file_path}" type mpegvideo alias {self._alias}'
            r = self._mci(cmd, None, 0, None)
            if r != 0:
                return False
            self._mci(f'set {self._alias} time format milliseconds', None, 0, None)
            self._current_file = file_path
            self._is_playing = False

            buf = ctypes.create_unicode_buffer(128)
            self._mci(f'status {self._alias} length', buf, 128, None)
            val = buf.value.strip()
            self._length_ms = int(val) if val.isdigit() else 0
            return True

    def play(self, from_ms: Optional[int] = None) -> bool:
        with self._lock:
            if not self._current_file:
                return False
            if from_ms is not None:
                cmd = f'play {self._alias} from {max(0, from_ms)}'
            else:
                cmd = f'play {self._alias}'
            r = self._mci(cmd, None, 0, None)
            self._is_playing = (r == 0)
            return self._is_playing

    def pause(self) -> bool:
        with self._lock:
            if not self._current_file:
                return False
            r = self._mci(f'pause {self._alias}', None, 0, None)
            self._is_playing = False
            return r == 0

    def toggle_play_pause(self) -> bool:
        if self.is_playing():
            self.pause()
            return False
        else:
            pos = self.get_position_ms()
            self.play(from_ms=pos)
            return True

    def seek_relative(self, delta_ms: int) -> int:
        with self._lock:
            if not self._current_file:
                return 0
            buf = ctypes.create_unicode_buffer(128)
            self._mci(f'status {self._alias} position', buf, 128, None)
            val = buf.value.strip()
            current_ms = int(val) if val.isdigit() else 0
            target_ms = max(0, current_ms + delta_ms)
            if self._length_ms > 0:
                target_ms = min(target_ms, max(0, self._length_ms - 500))

            if self._is_playing:
                self._mci(f'play {self._alias} from {target_ms}', None, 0, None)
            else:
                self._mci(f'seek {self._alias} to {target_ms}', None, 0, None)
            return target_ms

    def seek_to(self, pos_ms: int):
        with self._lock:
            if not self._current_file:
                return
            target_ms = max(0, pos_ms)
            if self._length_ms > 0:
                target_ms = min(target_ms, max(0, self._length_ms - 500))
            if self._is_playing:
                self._mci(f'play {self._alias} from {target_ms}', None, 0, None)
            else:
                self._mci(f'seek {self._alias} to {target_ms}', None, 0, None)

    def get_position_ms(self) -> int:
        with self._lock:
            if not self._current_file:
                return 0
            buf = ctypes.create_unicode_buffer(128)
            self._mci(f'status {self._alias} position', buf, 128, None)
            val = buf.value.strip()
            return int(val) if val.isdigit() else 0

    def get_length_ms(self) -> int:
        return self._length_ms

    def is_playing(self) -> bool:
        with self._lock:
            if not self._current_file:
                return False
            buf = ctypes.create_unicode_buffer(128)
            self._mci(f'status {self._alias} mode', buf, 128, None)
            mode = buf.value.lower().strip()
            self._is_playing = (mode == "playing")
            return self._is_playing

    def stop(self):
        with self._lock:
            self._close_internal()

    def _close_internal(self):
        try:
            self._mci(f'stop {self._alias}', None, 0, None)
            self._mci(f'close {self._alias}', None, 0, None)
        except Exception:
            pass
        self._current_file = None
        self._is_playing = False
        self._length_ms = 0


# ──────────────────────────────────────────────────────────────────────────────
# Disc Packing & Sizing Algorithms
# ──────────────────────────────────────────────────────────────────────────────

def estimate_track_size_bytes(duration_s: float, current_size: int, target_bitrate: str) -> int:
    """
    Estimates the file size of a track after transcoding to target bitrate.
    Includes ~85KB padding for ID3 tags, lyrics, and embedded album art.
    """
    tb = target_bitrate.lower().strip()
    if tb in ("original", "as-is", "none", "keep as-is"):
        return current_size

    m = re.search(r"\d+", tb)
    if not m:
        return current_size
    kbps = int(m.group())

    # Raw audio bytes = kbps * 1000 / 8 * seconds
    raw_audio_bytes = int((kbps * 1000 / 8) * max(1.0, duration_s))
    padded_bytes = raw_audio_bytes + 85_000

    return min(current_size, padded_bytes) if current_size > 0 else padded_bytes


def calculate_disc_distribution(
    selected_tracks: List[Dict],
    disc_capacity_mb: float = 700.0,
    target_bitrate: str = "192k",
    safe_margin_mb: float = 10.0,
) -> List[Dict]:
    """
    Distributes selected tracks into disc buckets (Disc 1, Disc 2, ...)
    ensuring each disc does not exceed (disc_capacity_mb - safe_margin_mb).
    """
    safe_capacity_bytes = int(max(50.0, disc_capacity_mb - safe_margin_mb) * 1024 * 1024)
    discs = []
    current_tracks = []
    current_bytes = 0
    current_duration = 0.0

    for track in selected_tracks:
        est_size = estimate_track_size_bytes(track.get("duration", 0), track.get("size", 0), target_bitrate)
        if current_bytes + est_size > safe_capacity_bytes and current_tracks:
            discs.append({
                "disc_number": len(discs) + 1,
                "tracks": current_tracks,
                "total_bytes": current_bytes,
                "total_mb": current_bytes / (1024 * 1024),
                "total_duration_s": current_duration,
                "capacity_mb": disc_capacity_mb,
                "percent_full": (current_bytes / (disc_capacity_mb * 1024 * 1024)) * 100.0,
            })
            current_tracks = []
            current_bytes = 0
            current_duration = 0.0

        current_tracks.append({**track, "est_size": est_size})
        current_bytes += est_size
        current_duration += track.get("duration", 0)

    if current_tracks:
        discs.append({
            "disc_number": len(discs) + 1,
            "tracks": current_tracks,
            "total_bytes": current_bytes,
            "total_mb": current_bytes / (1024 * 1024),
            "total_duration_s": current_duration,
            "capacity_mb": disc_capacity_mb,
            "percent_full": (current_bytes / (disc_capacity_mb * 1024 * 1024)) * 100.0,
        })

    return discs


def generate_fallback_album_art(size: Tuple[int, int] = (240, 240)) -> Image.Image:
    """Generates a stylish dark vinyl record placeholder image if album art is missing."""
    img = Image.new("RGBA", size, (25, 25, 28, 255))
    draw = ImageDraw.Draw(img)
    w, h = size
    # Draw vinyl disc
    pad = 12
    draw.ellipse([pad, pad, w - pad, h - pad], fill=(12, 12, 15), outline=(50, 50, 60), width=2)
    # Grooves
    for r in range(pad + 25, w // 2 - 20, 14):
        draw.ellipse([r, r, w - r, h - r], outline=(30, 32, 40), width=1)
    # Center label
    center_r = 45
    cx, cy = w // 2, h // 2
    draw.ellipse([cx - center_r, cy - center_r, cx + center_r, cy + center_r], fill=(29, 185, 84))
    # Center hole
    hole_r = 12
    draw.ellipse([cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r], fill=(12, 12, 15))
    return img


# ──────────────────────────────────────────────────────────────────────────────
# Interactive Curation & Disc Burn Prep Dialog
# ──────────────────────────────────────────────────────────────────────────────

class CDBurnPrepDialog(ctk.CTkToplevel):
    """
    Full-featured interactive CD burning curation & disc preparation tool.
    - Arrow keys: Up/Right = Keep (Select), Down/Left = Skip (Reject)
    - Spacebar: Play/Pause. Single tap seek +5s, Double-tap seek +10s
    - Real-time disc packing for 700 MB CD-Rs (Moser Baer)
    - Auto-saves session JSON so no curation progress is ever lost
    - Multi-threaded batch exporter with optional audio compression
    """
    def __init__(self, parent: ctk.CTk, default_folder: Path):
        super().__init__(parent)

        self.title("CD Burn Prep & Song Curator")
        self.geometry("780x850")
        self.minsize(740, 750)
        self.transient(parent)

        # Set window icon if available
        icon_path = Path(__file__).parent / "icon.ico"
        if icon_path.exists():
            try:
                self.iconbitmap(str(icon_path))
            except Exception:
                pass

        self.source_folder = default_folder if default_folder.exists() else Path.home() / "Music" / "Spotify Downloads"
        self.output_folder = Path.home() / "Music" / "CD Burn Discs"
        self.session_file = self.source_folder / "cd_curation_session.json"

        # Curation Data State
        self.all_tracks: List[Dict] = []
        self.filtered_indices: List[int] = []
        self.current_idx: int = 0
        self.selections: Dict[str, str] = {}  # path -> "selected" | "rejected"
        self.history: List[Tuple[str, str]] = []  # for undo stack

        # Settings
        self.disc_size_mb: float = 700.0
        self.target_bitrate: str = "192k"
        self.auto_play: bool = True

        # Player
        self.player = MCIAudioPlayer()
        self._is_seeking = False
        self._last_right_press = 0.0
        self._pending_right_timer = None
        self._last_left_press = 0.0
        self._pending_left_timer = None
        self._hud_clear_timer = None

        # Threading & status
        self._closed = False
        self._is_exporting = False
        self._cancel_export = False

        self._create_widgets()
        self._bind_keys()
        self._load_session_and_scan()

        # Start periodic audio progress tracker
        self._poll_audio_progress()

    def _create_widgets(self):
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=18, pady=14)

        # ── Header Bar ───────────────────────────────────────────────────────
        header_frame = ctk.CTkFrame(container, fg_color="#1E1E1E", corner_radius=10)
        header_frame.pack(fill="x", pady=(0, 10))

        h_inner = ctk.CTkFrame(header_frame, fg_color="transparent")
        h_inner.pack(fill="x", padx=14, pady=10)

        # Title & Subtitle
        t_row = ctk.CTkFrame(h_inner, fg_color="transparent")
        t_row.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            t_row,
            text="CD Burn Prep & Song Curator",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#F48FB1",
        ).pack(side="left")

        # Shortcuts reminder pill
        shortcut_pill = ctk.CTkFrame(t_row, fg_color="#2A2228", corner_radius=6)
        shortcut_pill.pack(side="right")
        ctk.CTkLabel(
            shortcut_pill,
            text="Up: Select  |  Down: Reject  |  Right: +5s/+10s  |  Left: -5s/-10s  |  Space: Pause",
            font=ctk.CTkFont(size=11),
            text_color="#CE93D8",
            padx=10,
            pady=3,
        ).pack()

        # Settings Row 1: Source & Output Folders
        f_row = ctk.CTkFrame(h_inner, fg_color="transparent")
        f_row.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(f_row, text="Music Source:", font=ctk.CTkFont(size=11, weight="bold"), text_color="gray85").pack(side="left", padx=(0, 6))
        self.src_entry = ctk.CTkEntry(f_row, font=ctk.CTkFont(size=11), height=28)
        self.src_entry.insert(0, str(self.source_folder))
        self.src_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        src_browse_btn = ctk.CTkButton(
            f_row, text="Browse...", width=70, height=28, fg_color="#333333", hover_color="#444444", command=self._browse_src
        )
        src_browse_btn.pack(side="left", padx=(0, 14))

        ctk.CTkLabel(f_row, text="Burn Output:", font=ctk.CTkFont(size=11, weight="bold"), text_color="gray85").pack(side="left", padx=(0, 6))
        self.out_entry = ctk.CTkEntry(f_row, font=ctk.CTkFont(size=11), height=28)
        self.out_entry.insert(0, str(self.output_folder))
        self.out_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        out_browse_btn = ctk.CTkButton(
            f_row, text="Browse...", width=70, height=28, fg_color="#333333", hover_color="#444444", command=self._browse_out
        )
        out_browse_btn.pack(side="left")

        # Settings Row 2: Disc Size & Bitrate Compression
        s_row = ctk.CTkFrame(h_inner, fg_color="transparent")
        s_row.pack(fill="x")

        ctk.CTkLabel(s_row, text="Disc Size:", font=ctk.CTkFont(size=11, weight="bold"), text_color="gray85").pack(side="left", padx=(0, 6))
        self.disc_size_var = ctk.StringVar(value="700 MB (Moser Baer CD-R)")
        self.disc_size_menu = ctk.CTkOptionMenu(
            s_row,
            values=[
                "700 MB (Moser Baer CD-R)",
                "650 MB (74-Min CD-R)",
                "800 MB (90-Min CD-R)",
                "4.7 GB (Standard DVD-R)",
            ],
            variable=self.disc_size_var,
            command=self._on_settings_change,
            width=185,
            height=28,
            fg_color="#2A2A2A",
            button_color="#333333",
            button_hover_color="#444444",
        )
        self.disc_size_menu.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(s_row, text="Target Quality:", font=ctk.CTkFont(size=11, weight="bold"), text_color="gray85").pack(side="left", padx=(0, 6))
        self.bitrate_var = ctk.StringVar(value="192 kbps (Recommended)")
        self.bitrate_menu = ctk.CTkOptionMenu(
            s_row,
            values=[
                "192 kbps (Recommended)",
                "128 kbps (Max Capacity)",
                "160 kbps (Balanced)",
                "256 kbps (High Fidelity)",
                "320 kbps (Pristine)",
                "Original (No Re-encoding)",
            ],
            variable=self.bitrate_var,
            command=self._on_settings_change,
            width=190,
            height=28,
            fg_color="#2A2A2A",
            button_color="#333333",
            button_hover_color="#444444",
        )
        self.bitrate_menu.pack(side="left", padx=(0, 16))

        # Auto-play checkbox
        self.auto_play_var = ctk.BooleanVar(value=True)
        self.auto_play_cb = ctk.CTkCheckBox(
            s_row,
            text="Auto-play preview",
            variable=self.auto_play_var,
            font=ctk.CTkFont(size=11),
            checkmark_color="#000000",
            fg_color="#1DB954",
            hover_color="#1AA34A",
            height=26,
        )
        self.auto_play_cb.pack(side="left")

        # ── Live Disc Allocation & Packing Bar ────────────────────────────────
        self.disc_bar_frame = ctk.CTkFrame(container, fg_color="#18181B", corner_radius=8)
        self.disc_bar_frame.pack(fill="x", pady=(0, 10))

        bar_inner = ctk.CTkFrame(self.disc_bar_frame, fg_color="transparent")
        bar_inner.pack(fill="x", padx=12, pady=8)

        self.disc_summary_label = ctk.CTkLabel(
            bar_inner,
            text="Selected: 0 songs (0 MB)  |  Discs Needed: 0 Discs",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#81C784",
        )
        self.disc_summary_label.pack(side="left")

        self.disc_detail_label = ctk.CTkLabel(
            bar_inner,
            text="Disc 1: 0 MB / 690 MB (0% full)",
            font=ctk.CTkFont(size=11),
            text_color="gray70",
        )
        self.disc_detail_label.pack(side="right")

        # ── Interactive Song Curation Card ────────────────────────────────────
        self.card_frame = ctk.CTkFrame(container, fg_color="#1E1E1E", corner_radius=12)
        self.card_frame.pack(fill="both", expand=True, pady=(0, 10))

        card_inner = ctk.CTkFrame(self.card_frame, fg_color="transparent")
        card_inner.pack(fill="both", expand=True, padx=16, pady=12)

        # Top row inside card: Filter & Track Progress Counter
        top_filter_row = ctk.CTkFrame(card_inner, fg_color="transparent")
        top_filter_row.pack(fill="x", pady=(0, 8))

        self.track_counter_label = ctk.CTkLabel(
            top_filter_row,
            text="Track 0 of 0",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="gray85",
        )
        self.track_counter_label.pack(side="left")

        # Filter dropdown
        self.filter_var = ctk.StringVar(value="All Songs (Reviewing)")
        self.filter_menu = ctk.CTkOptionMenu(
            top_filter_row,
            values=[
                "All Songs (Reviewing)",
                "Unreviewed Only",
                "Selected Songs Only",
                "Skipped Songs Only",
            ],
            variable=self.filter_var,
            command=self._on_filter_change,
            width=170,
            height=26,
            fg_color="#2A2A2A",
            button_color="#333333",
            button_hover_color="#444444",
        )
        self.filter_menu.pack(side="right")
        ctk.CTkLabel(top_filter_row, text="View:", font=ctk.CTkFont(size=11), text_color="gray60").pack(side="right", padx=(0, 6))

        # Main Center Area: Album Cover Art & Song Metadata
        center_area = ctk.CTkFrame(card_inner, fg_color="transparent")
        center_area.pack(fill="both", expand=True, pady=(0, 8))

        # Album Cover Box (220x220)
        self.art_box = ctk.CTkFrame(center_area, width=220, height=220, fg_color="#121214", corner_radius=10)
        self.art_box.pack(pady=(0, 10))
        self.art_box.pack_propagate(False)

        self.art_label = ctk.CTkLabel(self.art_box, text="")
        self.art_label.pack(expand=True, fill="both")

        # HUD feedback overlay label (shows +5s, +10s, Selected, etc.)
        self.hud_label = ctk.CTkLabel(
            self.art_box,
            text="",
            font=ctk.CTkFont(size=18, weight="bold"),
            fg_color="#000000",
            text_color="#FFFFFF",
            corner_radius=6,
        )

        # Track Title
        self.title_label = ctk.CTkLabel(
            center_area,
            text="Song Title",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#FFFFFF",
            wraplength=640,
        )
        self.title_label.pack(pady=(0, 2))

        # Artist & Album
        self.artist_label = ctk.CTkLabel(
            center_area,
            text="Artist Name",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#1DB954",
        )
        self.artist_label.pack(pady=(0, 2))

        self.album_label = ctk.CTkLabel(
            center_area,
            text="Album • 2024",
            font=ctk.CTkFont(size=12),
            text_color="gray70",
        )
        self.album_label.pack(pady=(0, 6))

        # Tech Details: Duration, Original Size, Compressed Size, Assigned Disc
        self.tech_details_label = ctk.CTkLabel(
            center_area,
            text="Duration: 0:00  |  Original: 0 MB  |  At 192k: ~0 MB  |  Target: Disc 1",
            font=ctk.CTkFont(size=11),
            text_color="gray60",
        )
        self.tech_details_label.pack(pady=(0, 10))

        # Audio Player Scrubber & Buttons
        player_frame = ctk.CTkFrame(center_area, fg_color="#161618", corner_radius=8)
        player_frame.pack(fill="x", padx=20, pady=(0, 10))

        p_inner = ctk.CTkFrame(player_frame, fg_color="transparent")
        p_inner.pack(fill="x", padx=12, pady=8)

        # Play / Pause & Seek Buttons
        ctrl_row = ctk.CTkFrame(p_inner, fg_color="transparent")
        ctrl_row.pack(fill="x", pady=(0, 4))

        self.rewind_btn = ctk.CTkButton(
            ctrl_row,
            text="⏪ -5s / -10s (← Left)",
            width=110,
            height=28,
            fg_color="#2A2A2A",
            hover_color="#3A3A3A",
            text_color="gray85",
            command=self._on_rewind_click,
        )
        self.rewind_btn.pack(side="left", padx=(0, 8))

        self.play_pause_btn = ctk.CTkButton(
            ctrl_row,
            text="⏸ Pause / ▶ Play (Space)",
            width=165,
            height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1DB954",
            hover_color="#1AA34A",
            text_color="#000000",
            command=self._toggle_playback,
        )
        self.play_pause_btn.pack(side="left", padx=(0, 8))

        self.forward_btn = ctk.CTkButton(
            ctrl_row,
            text="⏩ +5s / +10s (→ Right)",
            width=110,
            height=28,
            fg_color="#2A2A2A",
            hover_color="#3A3A3A",
            text_color="gray85",
            command=self._on_forward_click,
        )
        self.forward_btn.pack(side="left")

        # Time counter
        self.time_label = ctk.CTkLabel(
            ctrl_row,
            text="0:00 / 0:00",
            font=ctk.CTkFont(size=11),
            text_color="gray70",
        )
        self.time_label.pack(side="right")

        # Audio Slider
        self.audio_slider = ctk.CTkSlider(
            p_inner,
            from_=0,
            to=100,
            number_of_steps=100,
            height=14,
            progress_color="#1DB954",
            button_color="#1DB954",
            button_hover_color="#1AA34A",
            command=self._on_slider_seek,
        )
        self.audio_slider.set(0)
        self.audio_slider.pack(fill="x")

        # ── Curation Action Buttons ───────────────────────────────────────────
        btn_action_row = ctk.CTkFrame(card_inner, fg_color="transparent")
        btn_action_row.pack(fill="x", pady=(4, 0))

        # Reject / Skip Button
        self.reject_btn = ctk.CTkButton(
            btn_action_row,
            text="❌ Skip / Reject (↓ Down Arrow)",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=42,
            fg_color="#3D1A1E",
            hover_color="#5C262C",
            text_color="#EF9A9A",
            command=self._on_reject,
        )
        self.reject_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Undo Button
        self.undo_btn = ctk.CTkButton(
            btn_action_row,
            text="↩ Undo (Backspace)",
            font=ctk.CTkFont(size=12),
            width=130,
            height=42,
            fg_color="#2A2A2A",
            hover_color="#383838",
            text_color="gray85",
            command=self._on_undo,
        )
        self.undo_btn.pack(side="left", padx=(0, 8))

        # Keep / Select Button
        self.select_btn = ctk.CTkButton(
            btn_action_row,
            text="✅ Keep / Select (↑ Up Arrow)",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=42,
            fg_color="#163820",
            hover_color="#225430",
            text_color="#A5D6A7",
            command=self._on_select,
        )
        self.select_btn.pack(side="left", fill="x", expand=True)

        # ── Bottom Action Footer ─────────────────────────────────────────────
        footer = ctk.CTkFrame(container, fg_color="transparent")
        footer.pack(fill="x")

        self.save_json_btn = ctk.CTkButton(
            footer,
            text="💾 Save Session JSON",
            font=ctk.CTkFont(size=12),
            height=36,
            fg_color="#2A2A2A",
            hover_color="#383838",
            command=self._save_session_manual,
        )
        self.save_json_btn.pack(side="left", padx=(0, 8))

        self.open_out_btn = ctk.CTkButton(
            footer,
            text="📂 Open Output Folder",
            font=ctk.CTkFont(size=12),
            height=36,
            fg_color="#2A2A2A",
            hover_color="#383838",
            command=self._open_output_folder,
        )
        self.open_out_btn.pack(side="left", padx=(0, 8))

        self.export_btn = ctk.CTkButton(
            footer,
            text="🔥 Export Disc Folders",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=36,
            fg_color="#E65100",
            hover_color="#F57C00",
            text_color="#FFFFFF",
            command=self._on_export_click,
        )
        self.export_btn.pack(side="right")

    # ──────────────────────────────────────────────────────────────────────────
    # Key Binding & Interactive Controls
    # ──────────────────────────────────────────────────────────────────────────

    def _bind_keys(self):
        # Up = Select/Keep, Down = Reject/Skip
        self.bind("<Up>", lambda e: self._on_select())
        self.bind("<Down>", lambda e: self._on_reject())

        # Right = Forward (+5s single-tap, +10s double-tap)
        self.bind("<Right>", self._on_right_key)

        # Left = Rewind (-5s single-tap, -10s double-tap)
        self.bind("<Left>", self._on_left_key)

        # Spacebar = Play/Pause toggle only
        self.bind("<space>", self._on_space_key)

        # Undo Key
        self.bind("<BackSpace>", lambda e: self._on_undo())
        self.bind("<Control-z>", lambda e: self._on_undo())
        self.bind("z", lambda e: self._on_undo() if not self._is_entry_focused() else None)
        self.bind("Z", lambda e: self._on_undo() if not self._is_entry_focused() else None)

        # Quick Play/Pause Keys
        self.bind("p", lambda e: self._toggle_playback() if not self._is_entry_focused() else None)
        self.bind("P", lambda e: self._toggle_playback() if not self._is_entry_focused() else None)

        self.protocol("WM_DELETE_WINDOW", self._close)

    def _is_entry_focused(self) -> bool:
        focus = self.focus_get()
        return isinstance(focus, (ctk.CTkEntry, ctk.windows.widgets.core_widget_classes.CTkBaseClass)) and "entry" in str(focus).lower()

    def _on_space_key(self, event=None):
        if self._is_entry_focused():
            return
        self._toggle_playback()
        return "break"

    def _on_right_key(self, event=None):
        if self._is_entry_focused():
            return
        now = time.time()
        time_diff = now - self._last_right_press
        self._last_right_press = now

        # Double-tap detected (< 320ms): cancel single-tap and seek forward 10 seconds!
        if time_diff < 0.32 and self._pending_right_timer:
            self.after_cancel(self._pending_right_timer)
            self._pending_right_timer = None
            self._seek_relative(10000)
            self._flash_hud("+10s ⏩⏩", "#FF9800")
            return "break"

        # Schedule single tap (+5s)
        if self._pending_right_timer:
            self.after_cancel(self._pending_right_timer)
        self._pending_right_timer = self.after(320, self._handle_single_right_tap)
        return "break"

    def _handle_single_right_tap(self):
        self._pending_right_timer = None
        self._seek_relative(5000)
        self._flash_hud("+5s ⏩", "#4CAF50")

    def _on_left_key(self, event=None):
        if self._is_entry_focused():
            return
        now = time.time()
        time_diff = now - self._last_left_press
        self._last_left_press = now

        # Double-tap detected (< 320ms): cancel single-tap and seek backward 10 seconds!
        if time_diff < 0.32 and self._pending_left_timer:
            self.after_cancel(self._pending_left_timer)
            self._pending_left_timer = None
            self._seek_relative(-10000)
            self._flash_hud("-10s ⏪⏪", "#FF9800")
            return "break"

        # Schedule single tap (-5s)
        if self._pending_left_timer:
            self.after_cancel(self._pending_left_timer)
        self._pending_left_timer = self.after(320, self._handle_single_left_tap)
        return "break"

    def _handle_single_left_tap(self):
        self._pending_left_timer = None
        self._seek_relative(-5000)
        self._flash_hud("-5s ⏪", "#64B5F6")

    def _on_forward_click(self):
        self._on_right_key()

    def _on_rewind_click(self):
        self._on_left_key()

    def _seek_forward(self, seconds: int):
        self._seek_relative(seconds * 1000)

    def _seek_relative(self, delta_ms: int):
        self.player.seek_relative(delta_ms)
        pos_ms = self.player.get_position_ms()
        dur_ms = self.player.get_length_ms()
        if dur_ms > 0:
            pct = min(100.0, max(0.0, (pos_ms / dur_ms) * 100.0))
            self.audio_slider.set(pct)
            cur_m, cur_s = divmod(pos_ms // 1000, 60)
            tot_m, tot_s = divmod(dur_ms // 1000, 60)
            self.time_label.configure(text=f"{cur_m}:{cur_s:02d} / {tot_m}:{tot_s:02d}")

    def _flash_hud(self, text: str, color: str = "#FFFFFF"):
        try:
            self.hud_label.configure(text=text, text_color=color)
            self.hud_label.place(relx=0.5, rely=0.5, anchor="center")
            if self._hud_clear_timer:
                self.after_cancel(self._hud_clear_timer)
            self._hud_clear_timer = self.after(850, lambda: self.hud_label.place_forget())
        except Exception:
            pass

    def _toggle_playback(self):
        playing = self.player.toggle_play_pause()
        if playing:
            self.play_pause_btn.configure(text="⏸ Pause (Space)", fg_color="#FFA726", hover_color="#FB8C00")
            self._flash_hud("▶ Playing", "#81C784")
        else:
            self.play_pause_btn.configure(text="▶ Play (Space)", fg_color="#1DB954", hover_color="#1AA34A")
            self._flash_hud("⏸ Paused", "gray70")

    def _on_slider_seek(self, value):
        duration_ms = self.player.get_length_ms()
        if duration_ms > 0:
            target_ms = int((value / 100.0) * duration_ms)
            self.player.seek_to(target_ms)

    def _poll_audio_progress(self):
        if self._closed:
            return

        try:
            if self.player.is_playing():
                pos_ms = self.player.get_position_ms()
                dur_ms = self.player.get_length_ms()
                if dur_ms > 0:
                    pct = min(100.0, max(0.0, (pos_ms / dur_ms) * 100.0))
                    self.audio_slider.set(pct)
                    cur_m, cur_s = divmod(pos_ms // 1000, 60)
                    tot_m, tot_s = divmod(dur_ms // 1000, 60)
                    self.time_label.configure(text=f"{cur_m}:{cur_s:02d} / {tot_m}:{tot_s:02d}")
                    self.play_pause_btn.configure(text="⏸ Pause (Space)", fg_color="#FFA726")
            else:
                self.play_pause_btn.configure(text="▶ Play (Space)", fg_color="#1DB954")
        except Exception:
            pass

        self.after(250, self._poll_audio_progress)

    # ──────────────────────────────────────────────────────────────────────────
    # Library Scanning & Session Persistence
    # ──────────────────────────────────────────────────────────────────────────

    def _load_session_and_scan(self):
        self.session_file = self.source_folder / "cd_curation_session.json"
        saved_selections = {}
        if self.session_file.exists():
            try:
                with open(self.session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    saved_selections = data.get("selections", {})
                    self.disc_size_mb = data.get("disc_size_mb", 700.0)
                    self.target_bitrate = data.get("target_bitrate", "192k")
            except Exception:
                pass

        self.selections = saved_selections

        # Scan folder for audio files
        audio_files = sorted([
            f for f in self.source_folder.iterdir()
            if f.is_file() and f.suffix.lower() in (".mp3", ".m4a", ".flac") and f.stat().st_size > 50000
        ], key=lambda x: x.name.lower())

        self.all_tracks = []
        for f in audio_files:
            size = f.stat().st_size
            title = f.stem
            artist = "Unknown Artist"
            album = "Unknown Album"
            duration = 210.0

            if mutagen and f.suffix.lower() == ".mp3":
                try:
                    audio = MP3(str(f))
                    duration = audio.info.length if audio.info else 210.0
                    tags = ID3(str(f))
                    if "TIT2" in tags:
                        title = str(tags["TIT2"])
                    if "TPE1" in tags:
                        artist = str(tags["TPE1"])
                    if "TALB" in tags:
                        album = str(tags["TALB"])
                except Exception:
                    pass

            self.all_tracks.append({
                "path": str(f),
                "filename": f.name,
                "title": title,
                "artist": artist,
                "album": album,
                "duration": duration,
                "size": size,
            })

        self._apply_filter()
        self._update_disc_packing_banner()
        self._show_current_track()

    def _save_session(self):
        try:
            payload = {
                "source_folder": str(self.source_folder),
                "output_folder": str(self.output_folder),
                "disc_size_mb": self._get_selected_disc_mb(),
                "target_bitrate": self._get_selected_bitrate(),
                "selections": self.selections,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            pass

    def _save_session_manual(self):
        self._save_session()
        self._flash_hud("Session Saved! 💾", "#81C784")

    # ──────────────────────────────────────────────────────────────────────────
    # Filtering, Navigation, and Display
    # ──────────────────────────────────────────────────────────────────────────

    def _apply_filter(self):
        f_mode = self.filter_var.get()
        new_indices = []
        for i, t in enumerate(self.all_tracks):
            p = t["path"]
            status = self.selections.get(p)
            if f_mode == "All Songs (Reviewing)":
                new_indices.append(i)
            elif f_mode == "Unreviewed Only" and not status:
                new_indices.append(i)
            elif f_mode == "Selected Songs Only" and status == "selected":
                new_indices.append(i)
            elif f_mode == "Skipped Songs Only" and status == "rejected":
                new_indices.append(i)

        self.filtered_indices = new_indices
        if self.current_idx >= len(self.filtered_indices):
            self.current_idx = max(0, len(self.filtered_indices) - 1)

    def _on_filter_change(self, val):
        self._apply_filter()
        self._show_current_track()

    def _show_current_track(self):
        if not self.all_tracks or not self.filtered_indices:
            self.title_label.configure(text="No tracks in current filter view")
            self.artist_label.configure(text="Select 'All Songs' or choose another music folder")
            self.album_label.configure(text="")
            self.tech_details_label.configure(text="")
            self.track_counter_label.configure(text="0 of 0")
            self.player.stop()
            return

        track_idx = self.filtered_indices[self.current_idx]
        track = self.all_tracks[track_idx]
        file_path = track["path"]

        # Track counter
        reviewed_cnt = len(self.selections)
        selected_cnt = sum(1 for v in self.selections.values() if v == "selected")
        skipped_cnt = sum(1 for v in self.selections.values() if v == "rejected")
        total_cnt = len(self.all_tracks)
        self.track_counter_label.configure(
            text=f"Track {self.current_idx + 1} of {len(self.filtered_indices)}  |  Total: {total_cnt} (Selected: {selected_cnt} | Skipped: {skipped_cnt} | Unreviewed: {total_cnt - reviewed_cnt})"
        )

        # Labels
        self.title_label.configure(text=track["title"])
        self.artist_label.configure(text=track["artist"])
        self.album_label.configure(text=track["album"])

        # Format details
        dur_m, dur_s = divmod(int(track["duration"]), 60)
        orig_mb = track["size"] / (1024 * 1024)
        target_br = self._get_selected_bitrate()
        est_bytes = estimate_track_size_bytes(track["duration"], track["size"], target_br)
        est_mb = est_bytes / (1024 * 1024)

        # Status badge / disc assignment
        current_status = self.selections.get(file_path)
        status_text = ""
        if current_status == "selected":
            status_text = " [STATUS: ✅ SELECTED]"
        elif current_status == "rejected":
            status_text = " [STATUS: ❌ SKIPPED]"

        disc_target = self._get_track_disc_target(track)
        self.tech_details_label.configure(
            text=f"Duration: {dur_m}:{dur_s:02d}  |  Original: {orig_mb:.1f} MB  |  At {target_br}: ~{est_mb:.1f} MB  |  {disc_target}{status_text}"
        )

        # Highlight buttons based on current state
        if current_status == "selected":
            self.select_btn.configure(fg_color="#2E7D32", text="✅ Currently Selected (↑ Up)")
            self.reject_btn.configure(fg_color="#3D1A1E", text="❌ Skip / Reject (↓ Down)")
        elif current_status == "rejected":
            self.select_btn.configure(fg_color="#163820", text="✅ Keep / Select (↑ Up)")
            self.reject_btn.configure(fg_color="#C62828", text="❌ Currently Skipped (↓ Down)")
        else:
            self.select_btn.configure(fg_color="#163820", text="✅ Keep / Select (↑ Up)")
            self.reject_btn.configure(fg_color="#3D1A1E", text="❌ Skip / Reject (↓ Down)")

        # Load Album Art
        self._load_art_image(file_path)

        # Audio Load & Auto-play
        self.player.load_track(file_path)
        self.audio_slider.set(0)
        self.time_label.configure(text=f"0:00 / {dur_m}:{dur_s:02d}")
        if self.auto_play_var.get():
            self.player.play()
            self.play_pause_btn.configure(text="⏸ Pause (Space)", fg_color="#FFA726")

    def _load_art_image(self, file_path: str):
        pil_img = None
        if mutagen and file_path.lower().endswith(".mp3"):
            try:
                tags = ID3(file_path)
                for k in tags.keys():
                    if k.startswith("APIC"):
                        raw_bytes = tags[k].data
                        pil_img = Image.open(io.BytesIO(raw_bytes))
                        break
            except Exception:
                pass

        if not pil_img:
            pil_img = generate_fallback_album_art((220, 220))

        pil_img = pil_img.resize((220, 220), Image.Resampling.LANCZOS)
        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(220, 220))
        self.art_label.configure(image=ctk_img)
        self.art_label.image = ctk_img

    # ──────────────────────────────────────────────────────────────────────────
    # User Curation Actions (Select, Reject, Undo)
    # ──────────────────────────────────────────────────────────────────────────

    def _on_select(self):
        if not self.filtered_indices:
            return
        track = self.all_tracks[self.filtered_indices[self.current_idx]]
        p = track["path"]
        prev_status = self.selections.get(p)
        self.selections[p] = "selected"
        self.history.append((p, prev_status))
        self._flash_hud("KEPT! ✅", "#81C784")
        self._save_session()
        self._update_disc_packing_banner()
        self._advance_next()

    def _on_reject(self):
        if not self.filtered_indices:
            return
        track = self.all_tracks[self.filtered_indices[self.current_idx]]
        p = track["path"]
        prev_status = self.selections.get(p)
        self.selections[p] = "rejected"
        self.history.append((p, prev_status))
        self._flash_hud("SKIPPED ❌", "#EF9A9A")
        self._save_session()
        self._update_disc_packing_banner()
        self._advance_next()

    def _on_undo(self):
        if not self.history:
            self._flash_hud("Nothing to Undo", "gray60")
            return
        p, prev_status = self.history.pop()
        if prev_status is None:
            self.selections.pop(p, None)
        else:
            self.selections[p] = prev_status

        self._flash_hud("Undone ↩", "#FFB74D")
        self._save_session()
        self._update_disc_packing_banner()

        # Step back to that track
        for i, idx in enumerate(self.filtered_indices):
            if self.all_tracks[idx]["path"] == p:
                self.current_idx = i
                break
        self._show_current_track()

    def _advance_next(self):
        if self.current_idx < len(self.filtered_indices) - 1:
            self.current_idx += 1
            self._show_current_track()
        else:
            # Reached end of current filter list
            self._show_current_track()
            messagebox.showinfo("Curation Complete", "You have reviewed all songs in this filter view!\nYou can export your disc folders or review your choices.")

    # ──────────────────────────────────────────────────────────────────────────
    # Disc Calculation & Packing Status
    # ──────────────────────────────────────────────────────────────────────────

    def _get_selected_disc_mb(self) -> float:
        val = self.disc_size_var.get()
        m = re.search(r"(\d+(?:\.\d+)?)", val)
        if not m:
            return 700.0
        num = float(m.group(1))
        if "gb" in val.lower():
            return num * 1024.0
        return num

    def _get_selected_bitrate(self) -> str:
        val = self.bitrate_var.get().lower()
        if "original" in val:
            return "original"
        m = re.search(r"\d+", val)
        return f"{m.group()}k" if m else "192k"

    def _on_settings_change(self, *args):
        self._update_disc_packing_banner()
        self._show_current_track()

    def _update_disc_packing_banner(self):
        selected_tracks = [t for t in self.all_tracks if self.selections.get(t["path"]) == "selected"]
        disc_mb = self._get_selected_disc_mb()
        bitrate = self._get_selected_bitrate()

        discs = calculate_disc_distribution(selected_tracks, disc_mb, bitrate, safe_margin_mb=10.0)
        total_songs = len(selected_tracks)
        total_bytes = sum(d["total_bytes"] for d in discs)
        total_mb = total_bytes / (1024 * 1024)
        num_discs = len(discs)

        self.disc_summary_label.configure(
            text=f"Selected: {total_songs} songs ({total_mb:.1f} MB)  |  Discs Needed: {num_discs} {'Disc' if num_discs == 1 else 'Discs'}"
        )

        if not discs:
            self.disc_detail_label.configure(text=f"Disc 1: 0 MB / {disc_mb-10:.0f} MB (0% full)")
        else:
            latest_disc = discs[-1]
            status = "[FULL]" if latest_disc["percent_full"] >= 98 else "[IN PROGRESS]"
            self.disc_detail_label.configure(
                text=f"Disc {latest_disc['disc_number']}: {len(latest_disc['tracks'])} songs ({latest_disc['total_mb']:.1f} MB / {disc_mb-10:.0f} MB) {status}"
            )

    def _get_track_disc_target(self, track: Dict) -> str:
        selected_tracks = [t for t in self.all_tracks if self.selections.get(t["path"]) == "selected"]
        disc_mb = self._get_selected_disc_mb()
        bitrate = self._get_selected_bitrate()

        is_already_selected = self.selections.get(track["path"]) == "selected"
        if not is_already_selected:
            selected_tracks.append(track)

        discs = calculate_disc_distribution(selected_tracks, disc_mb, bitrate, safe_margin_mb=10.0)
        if not discs:
            return "Target: Disc 1"

        # Find which disc this track landed in
        for d in discs:
            for t in d["tracks"]:
                if t["path"] == track["path"]:
                    return f"Target: Disc {d['disc_number']} (Track #{len(d['tracks'])})"

        return f"Target: Disc {len(discs)}"

    # ──────────────────────────────────────────────────────────────────────────
    # Export Engine: Build Disc 1, Disc 2, Disc 3 Folders
    # ──────────────────────────────────────────────────────────────────────────

    def _on_export_click(self):
        selected_tracks = [t for t in self.all_tracks if self.selections.get(t["path"]) == "selected"]
        if not selected_tracks:
            messagebox.showwarning("No Songs Selected", "You have not selected any songs yet.\nUse Right/Up arrow to select songs before exporting.")
            return

        disc_mb = self._get_selected_disc_mb()
        bitrate = self._get_selected_bitrate()
        discs = calculate_disc_distribution(selected_tracks, disc_mb, bitrate, safe_margin_mb=10.0)

        out_dir = Path(self.out_entry.get().strip()).expanduser().resolve()
        confirm_msg = (
            f"Ready to export {len(selected_tracks)} songs across {len(discs)} Disc folders:\n\n"
            f"Destination: {out_dir}\n"
            f"Target Quality: {self.bitrate_var.get()}\n"
            f"Disc Capacity: {disc_mb:.0f} MB (Moser Baer CD-R)\n\n"
        )
        for d in discs:
            confirm_msg += f"• Disc {d['disc_number']}: {len(d['tracks'])} songs ({d['total_mb']:.1f} MB)\n"

        confirm_msg += "\nProceed with disc creation?"
        if not messagebox.askyesno("Confirm Disc Export", confirm_msg):
            return

        self._start_export_process(discs, out_dir, bitrate)

    def _start_export_process(self, discs: List[Dict], out_dir: Path, bitrate: str):
        # Progress Dialog
        p_win = ctk.CTkToplevel(self)
        p_win.title("Exporting Disc Folders")
        p_win.geometry("520x240")
        p_win.transient(self)

        ctk.CTkLabel(p_win, text="Preparing Disc Folders for CD Burning...", font=ctk.CTkFont(size=14, weight="bold"), text_color="#F48FB1").pack(pady=(16, 6))
        status_lbl = ctk.CTkLabel(p_win, text="Starting export...", font=ctk.CTkFont(size=12), text_color="gray85")
        status_lbl.pack(pady=(0, 10))

        prog_bar = ctk.CTkProgressBar(p_win, height=16, progress_color="#E65100")
        prog_bar.set(0.0)
        prog_bar.pack(fill="x", padx=30, pady=(0, 16))

        cancel_btn = ctk.CTkButton(p_win, text="Cancel", width=90, fg_color="#333333", hover_color="#444444")
        cancel_btn.pack()

        self._is_exporting = True
        self._cancel_export = False

        def _do_cancel():
            self._cancel_export = True
            cancel_btn.configure(state="disabled", text="Stopping...")

        cancel_btn.configure(command=_do_cancel)

        def _worker():
            total_songs = sum(len(d["tracks"]) for d in discs)
            processed_count = 0

            try:
                out_dir.mkdir(parents=True, exist_ok=True)
                for disc in discs:
                    if self._cancel_export:
                        break
                    disc_num = disc["disc_number"]
                    disc_folder = out_dir / f"Disc {disc_num}"
                    disc_folder.mkdir(parents=True, exist_ok=True)

                    m3u_lines = ["#EXTM3U\n"]
                    tracklist_lines = [
                        f"==================================================",
                        f"  Spotify Downloader - Disc {disc_num}",
                        f"  Total Tracks: {len(disc['tracks'])}",
                        f"  Total Size  : {disc['total_mb']:.1f} MB / {disc['capacity_mb']:.0f} MB",
                        f"==================================================\n",
                    ]

                    for t_idx, track in enumerate(disc["tracks"], 1):
                        if self._cancel_export:
                            break

                        src_p = Path(track["path"])
                        # Prefix with 2-digit track number so CD players play in curated order
                        clean_stem = re.sub(r"^\d+\s*[-_.]\s*", "", src_p.stem)
                        dest_filename = f"{t_idx:02d} - {clean_stem}{src_p.suffix.lower()}"
                        dest_p = disc_folder / dest_filename

                        # Update UI
                        pct = processed_count / max(1, total_songs)
                        msg = f"Disc {disc_num} [{t_idx}/{len(disc['tracks'])}]: {track['title']} - {track['artist']}"
                        p_win.after(0, lambda m=msg, p=pct: (status_lbl.configure(text=m), prog_bar.set(p)))

                        # Transcode or Copy
                        if bitrate.lower() in ("original", "keep as-is", "none") or not transcode_audio_file:
                            shutil.copy2(src_p, dest_p)
                        else:
                            ok = transcode_audio_file(src_p, dest_p, target_bitrate=bitrate)
                            if not ok or not dest_p.exists():
                                shutil.copy2(src_p, dest_p)

                        m3u_lines.append(f"#EXTINF:{int(track['duration'])},{track['artist']} - {track['title']}\n{dest_filename}\n")
                        dur_m, dur_s = divmod(int(track["duration"]), 60)
                        tracklist_lines.append(f"{t_idx:02d}. {track['artist']} - {track['title']} ({dur_m}:{dur_s:02d})")

                        processed_count += 1

                    # Write playlist and summary in disc folder
                    (disc_folder / "playlist.m3u").write_text("".join(m3u_lines), encoding="utf-8")
                    (disc_folder / "disc_tracklist.txt").write_text("\n".join(tracklist_lines), encoding="utf-8")

                # Write master manifest in root
                manifest = {
                    "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "total_tracks": total_songs,
                    "target_bitrate": bitrate,
                    "disc_size_mb": disc["capacity_mb"],
                    "discs": [
                        {
                            "disc_number": d["disc_number"],
                            "songs": len(d["tracks"]),
                            "total_mb": round(d["total_mb"], 1),
                        }
                        for d in discs
                    ]
                }
                (out_dir / "cd_burn_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

                def _on_finish():
                    p_win.destroy()
                    self._is_exporting = False
                    if not self._cancel_export:
                        messagebox.showinfo(
                            "Discs Ready to Burn!",
                            f"Successfully created {len(discs)} Disc folders in:\n{out_dir}\n\n"
                            f"Each folder contains a playlist.m3u and tracklist.txt and fits cleanly onto 700 MB CD-Rs!"
                        )
                        self._open_output_folder()

                p_win.after(0, _on_finish)

            except Exception as e:
                p_win.after(0, lambda err=str(e): (p_win.destroy(), messagebox.showerror("Export Error", f"Failed to export discs: {err}")))

        threading.Thread(target=_worker, daemon=True).start()

    def _browse_src(self):
        f = filedialog.askdirectory(initialdir=str(self.source_folder), title="Select Music Source Folder")
        if f:
            self.source_folder = Path(f)
            self.src_entry.delete(0, "end")
            self.src_entry.insert(0, str(self.source_folder))
            self._load_session_and_scan()

    def _browse_out(self):
        f = filedialog.askdirectory(initialdir=str(self.output_folder), title="Select Disc Output Folder")
        if f:
            self.output_folder = Path(f)
            self.out_entry.delete(0, "end")
            self.out_entry.insert(0, str(self.output_folder))

    def _open_output_folder(self):
        p = Path(self.out_entry.get().strip()).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(p))

    def _close(self):
        self._closed = True
        if self._pending_right_timer:
            try:
                self.after_cancel(self._pending_right_timer)
            except Exception:
                pass
            self._pending_right_timer = None
        if self._pending_left_timer:
            try:
                self.after_cancel(self._pending_left_timer)
            except Exception:
                pass
            self._pending_left_timer = None
        if self._hud_clear_timer:
            try:
                self.after_cancel(self._hud_clear_timer)
            except Exception:
                pass
            self._hud_clear_timer = None
        self.player.stop()
        self._save_session()
        self.destroy()
