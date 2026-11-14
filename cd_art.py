"""
CD & Grid Art Studio (Sticker & Cover Generator)
Allows generating high-resolution printable CD label stickers and artwork grids
from song collections / album covers:
1. Style 1: Curved Polar Fan Mosaic (Annular Wedges curving along disc radius, 100% full-bleed)
2. Style 2: Floating Concentric Tiles (Tangentially rotated crisp square covers scaling radially)
3. Style 3: Any-by-Any Grid (Auto-Optimum grid, custom Rows x Cols, CD Jewel Case Inserts)

Supports live interactive preview, center hub custom typography, spindle hole sizing,
cutting guides, printable A4 sheets (1:1 physical scale at 300 DPI), and Windows clipboard copy.
"""

import os
import sys
import math
import time
import io
import glob
import ctypes
import queue
import hashlib
import threading
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any

from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageFilter, ImageOps
import customtkinter as ctk
from tkinter import filedialog, messagebox

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    cv2 = None
    np = None

try:
    import mutagen
    from mutagen.id3 import ID3
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False


# ──────────────────────────────────────────────────────────────────────────────
# Windows Clipboard Image Helper
# ──────────────────────────────────────────────────────────────────────────────

def copy_image_to_clipboard(pil_img: Image.Image) -> bool:
    """Copies a PIL Image to Windows clipboard using standard CF_DIB format."""
    if sys.platform != "win32":
        return False
    try:
        output = io.BytesIO()
        converted = pil_img.convert("RGB")
        converted.save(output, "BMP")
        data = output.getvalue()[14:]  # Strip 14-byte BMP file header
        output.close()

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

        GMEM_MOVEABLE = 0x0002
        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h_mem:
            return False
        mem_ptr = kernel32.GlobalLock(h_mem)
        if not mem_ptr:
            return False
        ctypes.memmove(mem_ptr, data, len(data))
        kernel32.GlobalUnlock(h_mem)

        if user32.OpenClipboard(None):
            user32.EmptyClipboard()
            user32.SetClipboardData(8, h_mem)  # CF_DIB = 8
            user32.CloseClipboard()
            return True
        return False
    except Exception as e:
        print(f"[CDArt] Clipboard copy failed: {e}")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Album Cover Extraction & Fallback Placeholders
# ──────────────────────────────────────────────────────────────────────────────

def create_placeholder_cover(title: str, artist: str, size: int = 300) -> Image.Image:
    """Generates a stylish gradient album cover placeholder if audio file has no embedded art."""
    img = Image.new("RGB", (size, size), (25, 27, 34))
    draw = ImageDraw.Draw(img)

    # Subtle diagonal background tint based on title hash
    h = abs(hash(title + artist))
    r = 30 + (h % 50)
    g = 35 + ((h >> 3) % 50)
    b = 45 + ((h >> 6) % 60)
    for y in range(size):
        factor = y / size
        line_color = (
            int(r * (1 - factor * 0.4)),
            int(g * (1 - factor * 0.4)),
            int(b * (1 - factor * 0.4))
        )
        draw.line([(0, y), (size, y)], fill=line_color)

    # Stylized vinyl / music note icon in center
    cx, cy = size // 2, size // 2 - 20
    draw.ellipse((cx - 45, cy - 45, cx + 45, cy + 45), outline=(120, 130, 160), width=3)
    draw.ellipse((cx - 15, cy - 15, cx + 15, cy + 15), fill=(80, 90, 120))

    try:
        font_t = ImageFont.truetype("segoeuib.ttf", max(11, size // 20))
        font_a = ImageFont.truetype("segoeui.ttf", max(9, size // 25))
    except Exception:
        font_t = font_a = ImageFont.load_default()

    t_clean = (title[:22] + "...") if len(title) > 25 else title
    a_clean = (artist[:25] + "...") if len(artist) > 28 else artist

    draw.text((size // 2, size - 55), t_clean or "Unknown Track", fill=(240, 240, 245), anchor="mm", font=font_t)
    draw.text((size // 2, size - 32), a_clean or "Unknown Artist", fill=(170, 175, 190), anchor="mm", font=font_a)

    return img


def extract_track_cover_and_metadata(file_path: Path) -> Tuple[Optional[Image.Image], str, str, str, Optional[str]]:
    """
    Extracts embedded cover art, track title, artist, album, and MD5 image hash.
    Returns: (cover_image, title, artist, album, md5_hash)
    """
    title = file_path.stem
    artist = ""
    album = ""
    img_data = None
    ext = file_path.suffix.lower()

    if HAS_MUTAGEN:
        try:
            if ext == ".mp3":
                tag = ID3(file_path)
                t = tag.get("TIT2")
                if t and t.text:
                    title = str(t.text[0]).strip()
                a = tag.get("TPE1") or tag.get("TPE2")
                if a and a.text:
                    artist = str(a.text[0]).strip()
                alb = tag.get("TALB")
                if alb and alb.text:
                    album = str(alb.text[0]).strip()
                for k in tag.keys():
                    if k.startswith("APIC"):
                        img_data = tag[k].data
                        break
            elif ext == ".flac":
                audio = FLAC(file_path)
                title = audio.get("title", [title])[0]
                artist = audio.get("artist", [""])[0]
                album = audio.get("album", [""])[0]
                if audio.pictures:
                    img_data = audio.pictures[0].data
            elif ext in (".m4a", ".mp4"):
                audio = MP4(file_path)
                title = audio.get("©nam", [title])[0]
                artist = audio.get("©ART", audio.get("aART", [""]))[0]
                album = audio.get("©alb", [""])[0]
                if "covr" in audio and audio["covr"]:
                    img_data = bytes(audio["covr"][0])
        except Exception:
            pass

    cover_im = None
    img_hash = None

    if img_data:
        try:
            cover_im = Image.open(io.BytesIO(img_data)).convert("RGB")
            img_hash = hashlib.md5(img_data).hexdigest()
        except Exception:
            pass

    # Check for external cover file in same directory
    if not cover_im:
        for name in ("cover.jpg", "cover.png", "folder.jpg", "album.jpg", "front.jpg"):
            candidate = file_path.parent / name
            if candidate.exists():
                try:
                    c_data = candidate.read_bytes()
                    cover_im = Image.open(io.BytesIO(c_data)).convert("RGB")
                    img_hash = hashlib.md5(c_data).hexdigest()
                    break
                except Exception:
                    pass

    return cover_im, title, artist, album, img_hash


def extract_cover_from_file(file_path: Path) -> Optional[Image.Image]:
    """Compatibility wrapper: extracts cover image from file."""
    cov, _, _, _, _ = extract_track_cover_and_metadata(file_path)
    return cov


# ──────────────────────────────────────────────────────────────────────────────
# Math & Ring Partitioning Algorithms
# ──────────────────────────────────────────────────────────────────────────────

def calculate_ring_distribution(num_items: int) -> Tuple[List[int], List[float]]:
    """
    Dynamically partitions N items into concentric rings such that:
    - Ring thickness and cell arc length both scale proportionally with radius r.
    - Each ring gets an appropriate item count n_k summing exactly to N.
    """
    if num_items <= 1:
        return [max(1, num_items)], [1.0]

    # Select optimal number of concentric rings
    if num_items <= 8:
        k = 1
    elif num_items <= 20:
        k = 2
    elif num_items <= 45:
        k = 3
    elif num_items <= 80:
        k = 4
    elif num_items <= 140:
        k = 5
    elif num_items <= 220:
        k = 6
    else:
        k = min(8, max(5, int(math.sqrt(num_items) * 0.55)))

    # Weights scale with radius: inner weight 1.0, outer weight ~2.2
    weights = [1.0 + (1.2 * i / max(1, k - 1)) for i in range(k)]
    total_w = sum(weights)

    counts = [max(1, int(round(num_items * (w / total_w)))) for w in weights]

    # Adjust rounding discrepancy on largest outer ring so sum(counts) == num_items
    diff = num_items - sum(counts)
    counts[-1] += diff

    # Ensure all rings have at least 1 item
    while counts[-1] < 1 and k > 1:
        k -= 1
        return calculate_ring_distribution(num_items)

    norm_weights = [w / total_w for w in weights]
    return counts, norm_weights


def calculate_optimal_grid(num_items: int, target_aspect: float = 1.0) -> Tuple[int, int]:
    """Calculates optimal (rows, cols) for N items to fit target aspect ratio (default square 1:1)."""
    if num_items <= 0:
        return 1, 1

    best_r, best_c = 1, num_items
    best_score = float("inf")

    max_r = max(2, int(math.isqrt(num_items)) + 4)
    for r in range(1, max_r + 1):
        c = math.ceil(num_items / r)
        empty = (r * c) - num_items
        aspect = c / max(1, r)
        score = (empty * 3.5) + (abs(aspect - target_aspect) * 12.0)
        if score < best_score:
            best_score = score
            best_r, best_c = r, c

    return best_r, best_c


# ──────────────────────────────────────────────────────────────────────────────
# Rendering Engines
# ──────────────────────────────────────────────────────────────────────────────

def render_curved_polar_fan(
    covers: List[Image.Image],
    canvas_size: int = 2400,
    r_outer: int = 1140,
    r_inner: int = 280,
    r_spindle: int = 150,
    hub_title: str = "SPOTIFY DISC MIX",
    hub_subtitle: str = "",
    hub_info: str = "MOSER BAER 700 MB CD-R",
    show_cutlines: bool = True,
    cell_border_px: int = 2,
) -> Image.Image:
    """
    Renders Style 1: Curved Polar Fan Mosaic.
    Wedges curve along the disc radius and arc, expanding from center hub to outer edge.
    100% full-bleed coverage.
    """
    if not HAS_CV2 or not covers:
        # Fallback to concentric tiles if OpenCV is unavailable
        return render_concentric_tiles(
            covers, canvas_size, r_outer, r_inner, r_spindle,
            hub_title, hub_subtitle, hub_info, show_cutlines
        )

    D = canvas_size
    center = D // 2
    num_songs = len(covers)

    ring_counts, ring_weights = calculate_ring_distribution(num_songs)
    k = len(ring_counts)

    # Polar canvas parameters:
    # W_pol corresponds to radius [0, r_outer]
    # H_pol corresponds to angle [0, 2*pi]
    W_pol = r_outer
    H_pol = int(round(2 * math.pi * r_outer))

    polar_canvas = np.zeros((H_pol, W_pol, 3), dtype=np.uint8)

    # Compute radial bounds for each ring
    radii = [r_inner]
    curr = r_inner
    for w in ring_weights:
        curr += w * (r_outer - r_inner)
        radii.append(int(round(curr)))

    # Populate polar strip
    cover_idx = 0
    for ring_idx, count in enumerate(ring_counts):
        r_start = radii[ring_idx]
        r_end = radii[ring_idx + 1]
        ring_w = max(4, r_end - r_start)
        cell_h = H_pol / max(1, count)

        for i in range(count):
            pil_img = covers[cover_idx % len(covers)]
            cover_idx += 1

            # Convert PIL to BGR OpenCV array
            bgr_cv = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

            y_start = int(round(i * cell_h))
            y_end = int(round((i + 1) * cell_h))
            cur_h = max(4, y_end - y_start)

            # Rotate 90 degrees clockwise so original TOP faces outwards to r_end
            img_rot = cv2.rotate(bgr_cv, cv2.ROTATE_90_CLOCKWISE)
            resized = cv2.resize(img_rot, (ring_w, cur_h), interpolation=cv2.INTER_AREA)

            # Cell borders in polar space
            if cell_border_px > 0:
                b = cell_border_px
                resized[:b, :] = 20
                resized[-b:, :] = 20
                resized[:, :b] = 20
                resized[:, -b:] = 20

            polar_canvas[y_start:y_end, r_start:r_end] = resized

    # Warp polar canvas to Cartesian circular disc
    disc_bgr = cv2.warpPolar(
        polar_canvas,
        (D, D),
        (center, center),
        r_outer,
        cv2.WARP_POLAR_LINEAR + cv2.WARP_INVERSE_MAP + cv2.INTER_CUBIC
    )
    disc_pil = Image.fromarray(cv2.cvtColor(disc_bgr, cv2.COLOR_BGR2RGB))

    # Apply disc mask, center hub, spindle hole, and typography
    return _apply_cd_chassis(
        disc_pil, canvas_size, r_outer, r_inner, r_spindle,
        hub_title, hub_subtitle or f"{num_songs} TRACKS • 700 MB CD-R", hub_info,
        show_cutlines, is_full_bleed=True
    )


def render_concentric_tiles(
    covers: List[Image.Image],
    canvas_size: int = 2400,
    r_outer: int = 1140,
    r_inner: int = 280,
    r_spindle: int = 150,
    hub_title: str = "SPOTIFY DISC MIX",
    hub_subtitle: str = "",
    hub_info: str = "MOSER BAER 700 MB CD-R",
    show_cutlines: bool = True,
    bg_color: Tuple[int, int, int] = (16, 17, 20),
    corner_radius_pct: float = 0.08,
) -> Image.Image:
    """
    Renders Style 2: Floating Concentric Tiles.
    Keeps each album cover as an unwarped crisp square, rotated tangentially in concentric rings.
    Tile size grows radially from inner hub to outer rim.
    """
    D = canvas_size
    center = D // 2
    num_songs = len(covers)

    ring_counts, ring_weights = calculate_ring_distribution(num_songs)
    k = len(ring_counts)

    canvas = Image.new("RGB", (D, D), bg_color)

    # Compute ring center radii and tile sizes
    radii_centers = []
    tile_sizes = []
    curr = r_inner
    for i, w in enumerate(ring_weights):
        span = w * (r_outer - r_inner)
        rc = curr + span * 0.5
        radii_centers.append(rc)
        # Tile size proportional to ring width and circumference
        circum_share = (2 * math.pi * rc) / max(1, ring_counts[i])
        ts = int(min(span * 0.88, circum_share * 0.85))
        tile_sizes.append(max(24, ts))
        curr += span

    cover_idx = 0
    for ring_idx, count in enumerate(ring_counts):
        r = radii_centers[ring_idx]
        size = tile_sizes[ring_idx]

        for i in range(count):
            pil_img = covers[cover_idx % len(covers)]
            cover_idx += 1

            img_resized = pil_img.resize((size, size), Image.Resampling.LANCZOS)

            # Circular / tangential positioning
            angle_rad = 2 * math.pi * i / max(1, count)
            angle_deg = math.degrees(angle_rad)
            cx = center + r * math.cos(angle_rad)
            cy = center + r * math.sin(angle_rad)

            # Rounded corner mask
            mask = Image.new("L", (size, size), 0)
            mdraw = ImageDraw.Draw(mask)
            rad = max(3, int(size * corner_radius_pct))
            mdraw.rounded_rectangle((0, 0, size, size), radius=rad, fill=255)

            # Rotate so top faces radially outward
            rot_img = img_resized.rotate(-angle_deg + 90, expand=True, resample=Image.Resampling.BICUBIC)
            rot_mask = mask.rotate(-angle_deg + 90, expand=True, resample=Image.Resampling.BICUBIC)

            px = int(round(cx - rot_img.width / 2))
            py = int(round(cy - rot_img.height / 2))
            canvas.paste(rot_img, (px, py), rot_mask)

    return _apply_cd_chassis(
        canvas, canvas_size, r_outer, r_inner, r_spindle,
        hub_title, hub_subtitle or f"{num_songs} TRACKS • 700 MB CD-R", hub_info,
        show_cutlines, is_full_bleed=False
    )


def render_rectangular_grid(
    covers: List[Image.Image],
    rows: int,
    cols: int,
    target_width: int = 2400,
    target_height: int = 2400,
    gap: int = 6,
    corner_radius: int = 4,
    bg_color: Tuple[int, int, int] = (18, 19, 23),
) -> Image.Image:
    """
    Renders Style 3: Any-by-Any Grid (Optimal or Custom Dimensions).
    Lays out covers into an R x C grid, perfect for CD Jewel Case Front Covers (120x120mm),
    Back Tray Inserts (150x118mm), posters, and wallpapers.
    """
    if rows <= 0 or cols <= 0 or not covers:
        return Image.new("RGB", (target_width, target_height), bg_color)

    canvas = Image.new("RGB", (target_width, target_height), bg_color)

    # Compute cell dimensions
    avail_w = target_width - (gap * (cols + 1))
    avail_h = target_height - (gap * (rows + 1))
    cell_w = max(4, int(avail_w / cols))
    cell_h = max(4, int(avail_h / rows))

    # Centering offsets
    total_content_w = cols * cell_w + (cols - 1) * gap
    total_content_h = rows * cell_h + (rows - 1) * gap
    start_x = max(gap, (target_width - total_content_w) // 2)
    start_y = max(gap, (target_height - total_content_h) // 2)

    # Create mask if corner radius requested
    mask = None
    if corner_radius > 0:
        mask = Image.new("L", (cell_w, cell_h), 0)
        mdraw = ImageDraw.Draw(mask)
        mdraw.rounded_rectangle((0, 0, cell_w, cell_h), radius=corner_radius, fill=255)

    idx = 0
    total_cells = rows * cols
    for r in range(rows):
        for c in range(cols):
            x = start_x + c * (cell_w + gap)
            y = start_y + r * (cell_h + gap)

            if idx < len(covers):
                cover = covers[idx]
                idx += 1
            else:
                # Loop or fill
                cover = covers[idx % len(covers)]
                idx += 1

            resized = cover.resize((cell_w, cell_h), Image.Resampling.LANCZOS)
            if mask:
                canvas.paste(resized, (x, y), mask)
            else:
                canvas.paste(resized, (x, y))

    return canvas


def _apply_cd_chassis(
    base_img: Image.Image,
    canvas_size: int,
    r_outer: int,
    r_inner: int,
    r_spindle: int,
    hub_title: str,
    hub_subtitle: str,
    hub_info: str,
    show_cutlines: bool,
    is_full_bleed: bool,
) -> Image.Image:
    """Applies the physical CD disc circular mask, center hub, spindle hole, and typography."""
    D = canvas_size
    center = D // 2

    # Transparent canvas for output sticker
    out = Image.new("RGBA", (D, D), (0, 0, 0, 0))

    # Outer disc circular mask
    mask = Image.new("L", (D, D), 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.ellipse((center - r_outer, center - r_outer, center + r_outer, center + r_outer), fill=255)
    mdraw.ellipse((center - r_inner, center - r_inner, center + r_inner, center + r_inner), fill=0)

    out.paste(base_img.convert("RGBA"), (0, 0), mask)
    draw = ImageDraw.Draw(out)

    # Inner hub sticker circle
    draw.ellipse((center - r_inner, center - r_inner, center + r_inner, center + r_inner), fill=(22, 24, 29, 255))

    # Spindle hole cutout (15mm standard)
    draw.ellipse(
        (center - r_spindle, center - r_spindle, center + r_spindle, center + r_spindle),
        fill=(10, 11, 14, 255),
        outline=(170, 175, 190, 255) if show_cutlines else None,
        width=4 if show_cutlines else 0
    )
    # Inner plastic ring
    draw.ellipse((center - 65, center - 65, center + 65, center + 65), fill=(5, 6, 8, 255))

    # Guide cutlines
    if show_cutlines:
        # Outer disc edge (120mm)
        draw.ellipse((center - r_outer, center - r_outer, center + r_outer, center + r_outer), outline=(120, 125, 145, 230), width=4)
        # Inner hub edge
        draw.ellipse((center - r_inner, center - r_inner, center + r_inner, center + r_inner), outline=(130, 135, 155, 240), width=4)

    # Typography in center hub
    try:
        font_title = ImageFont.truetype("segoeuib.ttf", max(18, int(D * 0.016)))
        font_sub = ImageFont.truetype("segoeui.ttf", max(12, int(D * 0.0105)))
        font_info = ImageFont.truetype("segoeui.ttf", max(10, int(D * 0.009)))
    except Exception:
        font_title = font_sub = font_info = ImageFont.load_default()

    y_top = center - int(r_inner * 0.65)
    y_sub_top = center - int(r_inner * 0.45)
    y_bot = center + int(r_inner * 0.52)
    y_bot_sub = center + int(r_inner * 0.72)

    if hub_title:
        draw.text((center, y_top), hub_title.upper(), fill=(255, 255, 255), anchor="mm", font=font_title)
    if hub_subtitle:
        draw.text((center, y_sub_top), hub_subtitle, fill=(120, 220, 150), anchor="mm", font=font_sub)
    if hub_info:
        draw.text((center, y_bot), hub_info, fill=(200, 205, 220), anchor="mm", font=font_info)
        draw.text((center, y_bot_sub), "CD LABEL STICKER (120 MM)", fill=(140, 145, 160), anchor="mm", font=font_info)

    return out


def generate_printable_a4_sheet(
    artwork: Image.Image,
    is_disc: bool = True,
    dpi: int = 300,
) -> Image.Image:
    """
    Places the CD sticker or grid onto an A4 page (210 x 297 mm) at EXACT 1:1 scale (300 DPI)
    with cutting crosshairs, ready for standard home printer sticker sheets.
    """
    w_px = int(round(210 / 25.4 * dpi))  # ~2480 px
    h_px = int(round(297 / 25.4 * dpi))  # ~3508 px

    page = Image.new("RGB", (w_px, h_px), (255, 255, 255))
    draw = ImageDraw.Draw(page)

    # 120 mm physical CD diameter at target DPI
    target_d = int(round(120 / 25.4 * dpi))  # ~1417 px

    if is_disc:
        art_resized = artwork.resize((target_d, target_d), Image.Resampling.LANCZOS)
        cx = w_px // 2
        cy = h_px // 2 - 100

        # Paste sticker
        page.paste(art_resized, (cx - target_d // 2, cy - target_d // 2), art_resized if art_resized.mode == "RGBA" else None)

        # Draw cutting crosshairs
        ch_len = 40
        ch_color = (160, 160, 160)
        # Top, Bottom, Left, Right crosshairs
        draw.line([(cx, cy - target_d // 2 - ch_len), (cx, cy - target_d // 2 - 5)], fill=ch_color, width=2)
        draw.line([(cx, cy + target_d // 2 + 5), (cx, cy + target_d // 2 + ch_len)], fill=ch_color, width=2)
        draw.line([(cx - target_d // 2 - ch_len, cy), (cx - target_d // 2 - 5, cy)], fill=ch_color, width=2)
        draw.line([(cx + target_d // 2 + 5, cy), (cx + target_d // 2 + ch_len, cy)], fill=ch_color, width=2)

        # Header / instructions
        try:
            font_head = ImageFont.truetype("segoeuib.ttf", 36)
            font_sub = ImageFont.truetype("segoeui.ttf", 24)
        except Exception:
            font_head = font_sub = ImageFont.load_default()

        draw.text((w_px // 2, 140), "Printable CD Label Sticker (120 mm)", fill=(40, 40, 40), anchor="mm", font=font_head)
        draw.text(
            (w_px // 2, 190),
            "Print setting: Scale 100% (Actual Size) • Cut along outer 120 mm circle & 15 mm center hole",
            fill=(100, 100, 100), anchor="mm", font=font_sub
        )
    else:
        # Rectangular / Square Grid (Fit nicely centered on page)
        max_w = w_px - 240
        max_h = h_px - 400
        ratio = min(max_w / artwork.width, max_h / artwork.height, 1.0)
        disp_w = int(artwork.width * ratio)
        disp_h = int(artwork.height * ratio)

        art_resized = artwork.resize((disp_w, disp_h), Image.Resampling.LANCZOS)
        cx = w_px // 2
        cy = h_px // 2

        page.paste(art_resized, (cx - disp_w // 2, cy - disp_h // 2))
        draw.rectangle((cx - disp_w // 2, cy - disp_h // 2, cx + disp_w // 2, cy + disp_h // 2), outline=(180, 180, 180), width=2)

    return page


# ──────────────────────────────────────────────────────────────────────────────
# Interactive Studio Dialog (UI)
# ──────────────────────────────────────────────────────────────────────────────

class CDArtStudioDialog(ctk.CTkToplevel):
    """
    Modern full-featured CD & Grid Art Studio Dialog.
    Provides live interactive previews, custom grid dimensions, CD disc typography,
    and 300 DPI high-resolution export.
    """
    def __init__(self, parent, initial_folder: Optional[Path] = None):
        super().__init__(parent)

        self.title("CD & Grid Art Studio — Label & Collage Generator")
        self.geometry("1240x840")
        self.minsize(1080, 720)
        self.transient(parent)

        self.source_folder: Path = initial_folder or Path.home() / "Music" / "CD Burn Discs"
        if not self.source_folder.exists():
            self.source_folder = Path.home() / "Music"

        self.output_folder: Path = Path.home() / "Music" / "CD Art Exports"
        self.output_folder.mkdir(parents=True, exist_ok=True)

        # Loaded song/cover data
        self.all_items: List[Dict[str, Any]] = []
        self.unique_items: List[Dict[str, Any]] = []
        self.cached_covers: List[Image.Image] = []
        self.cached_thumbnails: List[Image.Image] = []

        # Current state
        self._current_style = "Style 1: Curved Polar Fan (Disc)"
        self._render_lock = threading.Lock()
        self._pending_render = False
        self._last_rendered_master: Optional[Image.Image] = None
        self._preview_photo_image = None
        self._scan_queue: queue.Queue = queue.Queue()

        self._build_ui()
        self._scan_folder_async()

    def _build_ui(self):
        # Master 2-column layout: Left Controls (width ~420), Right Preview Canvas
        self.grid_columnconfigure(0, weight=0, minsize=420)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Left Control Sidebar ─────────────────────────────────────────────
        self.left_panel = ctk.CTkScrollableFrame(self, width=420, corner_radius=0, fg_color="#18191C")
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        # Title Banner
        ctk.CTkLabel(
            self.left_panel,
            text="CD & Grid Art Studio",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#80CBC4",
        ).pack(anchor="w", padx=16, pady=(16, 2))

        ctk.CTkLabel(
            self.left_panel,
            text="Generate printable CD stickers & album art grids",
            font=ctk.CTkFont(size=12),
            text_color="gray70",
        ).pack(anchor="w", padx=16, pady=(0, 14))

        # 1. Source Folder Section
        folder_card = ctk.CTkFrame(self.left_panel, fg_color="#222328", corner_radius=8)
        folder_card.pack(fill="x", padx=14, pady=(0, 12))

        ctk.CTkLabel(
            folder_card,
            text="Music Source Folder:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="gray90"
        ).pack(anchor="w", padx=12, pady=(10, 4))

        src_row = ctk.CTkFrame(folder_card, fg_color="transparent")
        src_row.pack(fill="x", padx=12, pady=(0, 8))

        self.src_entry = ctk.CTkEntry(src_row, height=32, font=ctk.CTkFont(size=11))
        self.src_entry.insert(0, str(self.source_folder))
        self.src_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            src_row,
            text="Browse...",
            width=70,
            height=32,
            fg_color="#333333",
            hover_color="#444444",
            command=self._browse_folder
        ).pack(side="left")

        # Deduplication toggle switch (1 cover per album)
        self.dedup_switch = ctk.CTkSwitch(
            folder_card,
            text="Deduplicate Albums (1 cover per album)",
            command=self._on_dedup_toggled,
            progress_color="#00897B",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.dedup_switch.select()
        self.dedup_switch.pack(anchor="w", padx=12, pady=(4, 4))

        self.status_badge = ctk.CTkLabel(
            folder_card,
            text="Scanning folder for album art...",
            font=ctk.CTkFont(size=11),
            text_color="#80CBC4"
        )
        self.status_badge.pack(anchor="w", padx=12, pady=(0, 8))

        # 2. Style Selector Section
        style_card = ctk.CTkFrame(self.left_panel, fg_color="#222328", corner_radius=8)
        style_card.pack(fill="x", padx=14, pady=(0, 12))

        ctk.CTkLabel(
            style_card,
            text="Artwork Style:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="gray90"
        ).pack(anchor="w", padx=12, pady=(10, 6))

        self.style_segmented = ctk.CTkSegmentedButton(
            style_card,
            values=["Style 1 (Curved)", "Style 2 (Tiles)", "Style 3 (Grid)"],
            command=self._on_style_changed,
            selected_color="#00897B",
            selected_hover_color="#00796B",
        )
        self.style_segmented.set("Style 1 (Curved)")
        self.style_segmented.pack(fill="x", padx=12, pady=(0, 10))

        self.style_desc_lbl = ctk.CTkLabel(
            style_card,
            text="Wedge tiles curved along CD radius • 100% full-bleed coverage",
            font=ctk.CTkFont(size=11),
            text_color="gray70",
            wraplength=380,
            justify="left"
        )
        self.style_desc_lbl.pack(anchor="w", padx=12, pady=(0, 10))

        # 3. Dynamic Controls Container
        self.options_container = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.options_container.pack(fill="x", padx=0, pady=0)

        # Build Disc Options Frame
        self._build_disc_options_panel()

        # Build Grid Options Frame
        self._build_grid_options_panel()

        # 4. Export & Action Buttons Card
        action_card = ctk.CTkFrame(self.left_panel, fg_color="#222328", corner_radius=8)
        action_card.pack(fill="x", padx=14, pady=(12, 16))

        ctk.CTkLabel(
            action_card,
            text="Export & Print:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="gray90"
        ).pack(anchor="w", padx=12, pady=(10, 6))

        # Primary export button
        self.btn_export_png = ctk.CTkButton(
            action_card,
            text="💾  Export High-Res Image (300 DPI)...",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=36,
            fg_color="#00897B",
            hover_color="#00796B",
            command=self._export_high_res
        )
        self.btn_export_png.pack(fill="x", padx=12, pady=(0, 6))

        # Printable sheet button
        self.btn_export_a4 = ctk.CTkButton(
            action_card,
            text="🖨️  Generate Printable A4 Sheet...",
            font=ctk.CTkFont(size=12),
            height=34,
            fg_color="#2E3B4E",
            hover_color="#3D4E67",
            text_color="#90CAF9",
            command=self._export_printable_a4
        )
        self.btn_export_a4.pack(fill="x", padx=12, pady=(0, 6))

        # Quick action row (Copy to clipboard & Open folder)
        quick_row = ctk.CTkFrame(action_card, fg_color="transparent")
        quick_row.pack(fill="x", padx=12, pady=(0, 10))

        self.btn_copy = ctk.CTkButton(
            quick_row,
            text="📋 Copy to Clipboard",
            height=32,
            fg_color="#333333",
            hover_color="#444444",
            command=self._copy_to_clipboard
        )
        self.btn_copy.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_open_out = ctk.CTkButton(
            quick_row,
            text="📁 Open Folder",
            height=32,
            fg_color="#333333",
            hover_color="#444444",
            command=self._open_output_folder
        )
        self.btn_open_out.pack(side="left", fill="x", expand=True)

        # ── Right Preview Panel ──────────────────────────────────────────────
        self.right_panel = ctk.CTkFrame(self, fg_color="#121316", corner_radius=0)
        self.right_panel.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self.right_panel.grid_rowconfigure(1, weight=1)
        self.right_panel.grid_columnconfigure(0, weight=1)

        # Preview Top Bar
        preview_top = ctk.CTkFrame(self.right_panel, height=44, fg_color="#1B1C20", corner_radius=0)
        preview_top.grid(row=0, column=0, sticky="ew", padx=0, pady=0)

        self.preview_title_lbl = ctk.CTkLabel(
            preview_top,
            text="Interactive Live Preview — 120 mm Disc (100% Physical Aspect)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="gray85"
        )
        self.preview_title_lbl.pack(side="left", padx=16, pady=8)

        self.preview_render_time_lbl = ctk.CTkLabel(
            preview_top,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="#80CBC4"
        )
        self.preview_render_time_lbl.pack(side="right", padx=16, pady=8)

        # Preview Canvas Container
        self.canvas_container = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        self.canvas_container.grid(row=1, column=0, sticky="nsew", padx=20, pady=20)
        self.canvas_container.grid_rowconfigure(0, weight=1)
        self.canvas_container.grid_columnconfigure(0, weight=1)

        self.preview_canvas_lbl = ctk.CTkLabel(
            self.canvas_container,
            text="Loading preview...",
            fg_color="#141518",
            corner_radius=8
        )
        self.preview_canvas_lbl.grid(row=0, column=0, sticky="nsew")
        self.canvas_container.bind("<Configure>", self._on_preview_resize)

        # Show initial options panel
        self._update_options_panel_visibility()

    def _build_disc_options_panel(self):
        """Constructs settings specific to CD circular disc stickers (Style 1 & 2)."""
        self.disc_options_frame = ctk.CTkFrame(self.options_container, fg_color="#222328", corner_radius=8)

        ctk.CTkLabel(
            self.disc_options_frame,
            text="CD Disc & Typography Settings:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="gray90"
        ).pack(anchor="w", padx=12, pady=(10, 6))

        # Disc Title
        ctk.CTkLabel(self.disc_options_frame, text="Disc Title (Center Hub):", font=ctk.CTkFont(size=11), text_color="gray80").pack(anchor="w", padx=12, pady=(4, 2))
        self.hub_title_entry = ctk.CTkEntry(self.disc_options_frame, height=30, font=ctk.CTkFont(size=11))
        self.hub_title_entry.insert(0, "SPOTIFY DISC MIX")
        self.hub_title_entry.pack(fill="x", padx=12, pady=(0, 6))
        self.hub_title_entry.bind("<KeyRelease>", lambda e: self._request_preview_render())

        # Subtitle
        ctk.CTkLabel(self.disc_options_frame, text="Subtitle / Track Info:", font=ctk.CTkFont(size=11), text_color="gray80").pack(anchor="w", padx=12, pady=(2, 2))
        self.hub_sub_entry = ctk.CTkEntry(self.disc_options_frame, height=30, font=ctk.CTkFont(size=11))
        self.hub_sub_entry.insert(0, "AUTO: {N} TRACKS • 700 MB CD-R")
        self.hub_sub_entry.pack(fill="x", padx=12, pady=(0, 6))
        self.hub_sub_entry.bind("<KeyRelease>", lambda e: self._request_preview_render())

        # Footer Disc Note
        ctk.CTkLabel(self.disc_options_frame, text="Disc Brand / Date Note:", font=ctk.CTkFont(size=11), text_color="gray80").pack(anchor="w", padx=12, pady=(2, 2))
        self.hub_info_entry = ctk.CTkEntry(self.disc_options_frame, height=30, font=ctk.CTkFont(size=11))
        self.hub_info_entry.insert(0, "MOSER BAER DATA DISC")
        self.hub_info_entry.pack(fill="x", padx=12, pady=(0, 8))
        self.hub_info_entry.bind("<KeyRelease>", lambda e: self._request_preview_render())

        # Spindle Cutout Size
        ctk.CTkLabel(self.disc_options_frame, text="Spindle Hole Size:", font=ctk.CTkFont(size=11), text_color="gray80").pack(anchor="w", padx=12, pady=(2, 2))
        self.spindle_menu = ctk.CTkOptionMenu(
            self.disc_options_frame,
            values=["Small Spindle (15-20 mm • Full Coverage)", "Standard Hub (40 mm • Clear Ring)"],
            command=lambda v: self._request_preview_render(),
            fg_color="#333333",
            button_color="#444444",
            height=30
        )
        self.spindle_menu.pack(fill="x", padx=12, pady=(0, 8))

        # Cutlines toggle
        self.cutlines_switch = ctk.CTkSwitch(
            self.disc_options_frame,
            text="Show 120 mm Outer & Center Cutlines",
            command=self._request_preview_render,
            progress_color="#00897B",
            font=ctk.CTkFont(size=11)
        )
        self.cutlines_switch.select()
        self.cutlines_switch.pack(anchor="w", padx=12, pady=(4, 12))

    def _build_grid_options_panel(self):
        """Constructs settings specific to Any-by-Any Rectangular / Square Grids (Style 3)."""
        self.grid_options_frame = ctk.CTkFrame(self.options_container, fg_color="#222328", corner_radius=8)

        ctk.CTkLabel(
            self.grid_options_frame,
            text="Grid Dimensions & Preset Options:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="gray90"
        ).pack(anchor="w", padx=12, pady=(10, 6))

        # Presets dropdown
        ctk.CTkLabel(self.grid_options_frame, text="Grid Layout Preset:", font=ctk.CTkFont(size=11), text_color="gray80").pack(anchor="w", padx=12, pady=(2, 2))
        self.preset_menu = ctk.CTkOptionMenu(
            self.grid_options_frame,
            values=[
                "Auto-Optimum Grid (Square 1:1)",
                "CD Jewel Case Front (120x120 mm)",
                "CD Jewel Case Back Tray (150x118 mm)",
                "Poster / Print (3:4 Aspect)",
                "Desktop Wallpaper (16:9 Aspect)",
                "Custom Dimensions (Enter Below)",
            ],
            command=self._on_preset_selected,
            fg_color="#333333",
            button_color="#444444",
            height=30
        )
        self.preset_menu.pack(fill="x", padx=12, pady=(0, 8))

        # Custom Rows & Columns inputs
        dim_row = ctk.CTkFrame(self.grid_options_frame, fg_color="transparent")
        dim_row.pack(fill="x", padx=12, pady=(0, 8))

        r_col = ctk.CTkFrame(dim_row, fg_color="transparent")
        r_col.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkLabel(r_col, text="Rows:", font=ctk.CTkFont(size=11), text_color="gray80").pack(anchor="w")
        self.rows_entry = ctk.CTkEntry(r_col, height=30, font=ctk.CTkFont(size=11))
        self.rows_entry.insert(0, "10")
        self.rows_entry.pack(fill="x")
        self.rows_entry.bind("<KeyRelease>", lambda e: self._request_preview_render())

        c_col = ctk.CTkFrame(dim_row, fg_color="transparent")
        c_col.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(c_col, text="Columns:", font=ctk.CTkFont(size=11), text_color="gray80").pack(anchor="w")
        self.cols_entry = ctk.CTkEntry(c_col, height=30, font=ctk.CTkFont(size=11))
        self.cols_entry.insert(0, "10")
        self.cols_entry.pack(fill="x")
        self.cols_entry.bind("<KeyRelease>", lambda e: self._request_preview_render())

        # Tile Spacing Slider
        ctk.CTkLabel(self.grid_options_frame, text="Tile Spacing (Gap):", font=ctk.CTkFont(size=11), text_color="gray80").pack(anchor="w", padx=12, pady=(4, 2))
        self.gap_slider = ctk.CTkSlider(self.grid_options_frame, from_=0, to=20, number_of_steps=20, command=lambda v: self._request_preview_render())
        self.gap_slider.set(6)
        self.gap_slider.pack(fill="x", padx=12, pady=(0, 6))

        # Corner Radius Slider
        ctk.CTkLabel(self.grid_options_frame, text="Corner Rounding:", font=ctk.CTkFont(size=11), text_color="gray80").pack(anchor="w", padx=12, pady=(4, 2))
        self.radius_slider = ctk.CTkSlider(self.grid_options_frame, from_=0, to=24, number_of_steps=24, command=lambda v: self._request_preview_render())
        self.radius_slider.set(4)
        self.radius_slider.pack(fill="x", padx=12, pady=(0, 12))

    def _update_options_panel_visibility(self):
        """Swaps the controls shown in the left sidebar based on selected style."""
        style = self.style_segmented.get()
        self.disc_options_frame.pack_forget()
        self.grid_options_frame.pack_forget()

        if "Style 3" in style:
            self.grid_options_frame.pack(fill="x", padx=14, pady=(0, 12))
            self.style_desc_lbl.configure(text="Custom Rows × Columns grid • Jewel case front/back inserts & poster collage")
            if hasattr(self, "preview_title_lbl"):
                self.preview_title_lbl.configure(text="Interactive Live Preview — Album Art Grid / Collage")
        elif "Style 2" in style:
            self.disc_options_frame.pack(fill="x", padx=14, pady=(0, 12))
            self.style_desc_lbl.configure(text="Unwarped square covers arranged in concentric rings • Tangential rotation")
            if hasattr(self, "preview_title_lbl"):
                self.preview_title_lbl.configure(text="Interactive Live Preview — 120 mm Disc (Floating Concentric Tiles)")
        else:
            self.disc_options_frame.pack(fill="x", padx=14, pady=(0, 12))
            self.style_desc_lbl.configure(text="Wedge tiles curved along CD radius • 100% full-bleed coverage")
            if hasattr(self, "preview_title_lbl"):
                self.preview_title_lbl.configure(text="Interactive Live Preview — 120 mm Disc (Curved Polar Fan)")

    def _on_style_changed(self, value):
        self._update_options_panel_visibility()
        self._request_preview_render()

    def _on_preset_selected(self, preset: str):
        num_items = len(self.cached_covers) or 100
        if "Auto-Optimum" in preset:
            r, c = calculate_optimal_grid(num_items, target_aspect=1.0)
            self._set_grid_entries(r, c)
        elif "CD Jewel Case Front" in preset:
            r, c = calculate_optimal_grid(num_items, target_aspect=1.0)
            self._set_grid_entries(r, c)
        elif "CD Jewel Case Back" in preset:
            r, c = calculate_optimal_grid(num_items, target_aspect=150 / 118)
            self._set_grid_entries(r, c)
        elif "Poster" in preset:
            r, c = calculate_optimal_grid(num_items, target_aspect=3 / 4)
            self._set_grid_entries(r, c)
        elif "Wallpaper" in preset:
            r, c = calculate_optimal_grid(num_items, target_aspect=16 / 9)
            self._set_grid_entries(r, c)

        self._request_preview_render()

    def _set_grid_entries(self, r: int, c: int):
        self.rows_entry.delete(0, "end")
        self.rows_entry.insert(0, str(r))
        self.cols_entry.delete(0, "end")
        self.cols_entry.insert(0, str(c))

    # ── Folder Scanning & Asset Loading ──────────────────────────────────────

    def _browse_folder(self):
        f = filedialog.askdirectory(initialdir=str(self.source_folder), title="Select Music Source Folder")
        if f:
            self.source_folder = Path(f)
            self.src_entry.delete(0, "end")
            self.src_entry.insert(0, str(self.source_folder))
            self._scan_folder_async()

    def _scan_folder_async(self):
        self.status_badge.configure(text="Scanning folder for audio files & album covers...", text_color="#80CBC4")
        self.btn_export_png.configure(state="disabled")

        def _worker():
            try:
                files = []
                for ext in ("*.mp3", "*.flac", "*.m4a", "*.mp4"):
                    files.extend(list(self.source_folder.glob(ext)))
                    files.extend(list(self.source_folder.glob(f"**/{ext}")))
                # Deduplicate path references and sort
                files = sorted(list({p.resolve() for p in files}))

                all_items = []
                unique_items = []
                seen_albums = set()
                seen_hashes = set()

                for f in files:
                    cov, title, artist, album, img_hash = extract_track_cover_and_metadata(f)
                    if not cov:
                        cov = create_placeholder_cover(title, artist)
                        img_hash = hashlib.md5(f"{title}-{artist}".encode()).hexdigest()

                    thumb = cov.copy()
                    thumb.thumbnail((120, 120), Image.Resampling.LANCZOS)

                    item = {
                        "path": f,
                        "title": title,
                        "artist": artist,
                        "album": album,
                        "cover": cov,
                        "thumb": thumb,
                        "hash": img_hash
                    }
                    all_items.append(item)

                    # Deduplication check: only one cover per unique album or identical cover art
                    is_dup = False
                    norm_album = album.strip().lower()
                    norm_artist = artist.strip().lower()

                    if norm_album and norm_album not in ("single", "unknown", ""):
                        album_key = (norm_album, norm_artist)
                        if album_key in seen_albums:
                            is_dup = True
                        else:
                            seen_albums.add(album_key)

                    if not is_dup and img_hash:
                        if img_hash in seen_hashes:
                            is_dup = True
                        else:
                            seen_hashes.add(img_hash)

                    if not is_dup:
                        unique_items.append(item)

                self._scan_queue.put(("DONE", all_items, unique_items))
            except Exception as e:
                self._scan_queue.put(("ERROR", str(e)))

        threading.Thread(target=_worker, daemon=True).start()
        self._check_scan_queue()

    def _update_active_covers(self):
        """Updates cached covers and thumbnails based on the deduplication toggle."""
        use_dedup = self.dedup_switch.get() if hasattr(self, "dedup_switch") else True
        items = self.unique_items if (use_dedup and self.unique_items) else self.all_items

        self.cached_covers = [x["cover"] for x in items]
        self.cached_thumbnails = [x["thumb"] for x in items]

        if hasattr(self, "status_badge") and self.all_items:
            dup_count = len(self.all_items) - len(self.unique_items)
            if use_dedup and dup_count > 0:
                self.status_badge.configure(
                    text=f"Loaded {len(self.all_items)} songs • {len(self.unique_items)} unique albums ({dup_count} duplicates skipped)",
                    text_color="#80CBC4"
                )
            else:
                self.status_badge.configure(
                    text=f"Loaded {len(self.all_items)} songs (all covers included)",
                    text_color="#80CBC4"
                )

    def _on_dedup_toggled(self):
        """Triggered when the user flips the deduplication toggle."""
        self._update_active_covers()
        if "Auto-Optimum" in self.preset_menu.get():
            r, c = calculate_optimal_grid(len(self.cached_covers), target_aspect=1.0)
            self._set_grid_entries(r, c)

        label = "ALBUMS" if self.dedup_switch.get() else "TRACKS"
        if "{N}" in self.hub_sub_entry.get() or "TRACKS" in self.hub_sub_entry.get() or "ALBUMS" in self.hub_sub_entry.get():
            self.hub_sub_entry.delete(0, "end")
            self.hub_sub_entry.insert(0, f"{len(self.cached_covers)} {label} • 700 MB CD-R")

        self._request_preview_render()

    def _check_scan_queue(self):
        try:
            msg = self._scan_queue.get_nowait()
            status = msg[0]
            if status == "DONE":
                _, all_items, unique_items = msg
                self.all_items = all_items
                self.unique_items = unique_items
                self.btn_export_png.configure(state="normal" if all_items else "disabled")
                self._update_active_covers()

                # Auto update grid dimensions if on Auto-Optimum
                if "Auto-Optimum" in self.preset_menu.get():
                    r, c = calculate_optimal_grid(len(self.cached_covers), target_aspect=1.0)
                    self._set_grid_entries(r, c)

                # Update default hub subtitle with album/track count
                label = "ALBUMS" if (hasattr(self, "dedup_switch") and self.dedup_switch.get()) else "TRACKS"
                if "{N}" in self.hub_sub_entry.get() or "TRACKS" in self.hub_sub_entry.get() or "ALBUMS" in self.hub_sub_entry.get():
                    self.hub_sub_entry.delete(0, "end")
                    self.hub_sub_entry.insert(0, f"{len(self.cached_covers)} {label} • 700 MB CD-R")

                self._request_preview_render()
            elif status == "ERROR":
                err = msg[1]
                self.status_badge.configure(text=f"Scan error: {err}", text_color="#E57373")
        except queue.Empty:
            self.after(50, self._check_scan_queue)

    # ── Live Preview Rendering ───────────────────────────────────────────────

    def _request_preview_render(self):
        """Debounced preview request so slider movement stays smooth and responsive."""
        with self._render_lock:
            if self._pending_render:
                return
            self._pending_render = True

        self.after(40, self._execute_preview_render)

    def _execute_preview_render(self):
        with self._render_lock:
            self._pending_render = False

        if not self.cached_thumbnails:
            return

        t0 = time.time()
        style = self.style_segmented.get()
        covers = self.cached_thumbnails

        # Render preview at moderate resolution for 60 FPS UI speed (~900px)
        preview_dim = 960

        try:
            if "Style 3" in style:
                # Grid
                try:
                    r = max(1, int(self.rows_entry.get().strip()))
                    c = max(1, int(self.cols_entry.get().strip()))
                except ValueError:
                    r, c = calculate_optimal_grid(len(covers))

                gap = max(0, int(self.gap_slider.get()))
                radius = max(0, int(self.radius_slider.get()))

                # Determine aspect ratio based on preset
                preset = self.preset_menu.get()
                if "Back Tray" in preset:
                    tw, th = 960, int(960 * 118 / 150)
                elif "Poster" in preset:
                    tw, th = 720, 960
                elif "Wallpaper" in preset:
                    tw, th = 960, 540
                else:
                    tw, th = 960, 960

                rendered = render_rectangular_grid(
                    covers, r, c,
                    target_width=tw,
                    target_height=th,
                    gap=gap,
                    corner_radius=radius,
                    bg_color=(18, 19, 23)
                )

            elif "Style 2" in style:
                # Concentric Tiles
                r_out = int(preview_dim * 0.475)
                r_in = int(preview_dim * 0.16) if "Small" in self.spindle_menu.get() else int(preview_dim * 0.22)
                r_sp = int(preview_dim * 0.065)

                hub_sub = self.hub_sub_entry.get().replace("{N}", str(len(self.cached_covers)))

                rendered = render_concentric_tiles(
                    covers,
                    canvas_size=preview_dim,
                    r_outer=r_out,
                    r_inner=r_in,
                    r_spindle=r_sp,
                    hub_title=self.hub_title_entry.get().strip(),
                    hub_subtitle=hub_sub,
                    hub_info=self.hub_info_entry.get().strip(),
                    show_cutlines=self.cutlines_switch.get(),
                    bg_color=(16, 17, 20)
                )
            else:
                # Style 1: Curved Polar Fan
                r_out = int(preview_dim * 0.475)
                r_in = int(preview_dim * 0.16) if "Small" in self.spindle_menu.get() else int(preview_dim * 0.22)
                r_sp = int(preview_dim * 0.065)

                hub_sub = self.hub_sub_entry.get().replace("{N}", str(len(self.cached_covers)))

                rendered = render_curved_polar_fan(
                    covers,
                    canvas_size=preview_dim,
                    r_outer=r_out,
                    r_inner=r_in,
                    r_spindle=r_sp,
                    hub_title=self.hub_title_entry.get().strip(),
                    hub_subtitle=hub_sub,
                    hub_info=self.hub_info_entry.get().strip(),
                    show_cutlines=self.cutlines_switch.get(),
                    cell_border_px=1
                )

            self._last_rendered_master = rendered
            self._display_preview_image(rendered)

            dt = (time.time() - t0) * 1000
            self.preview_render_time_lbl.configure(text=f"Rendered in {int(dt)}ms")

        except Exception as e:
            print(f"[CDArt] Preview render error: {e}")

    def _display_preview_image(self, img: Image.Image):
        """Scales rendered image to fit current container while maintaining aspect ratio."""
        cw = max(200, self.canvas_container.winfo_width() - 20)
        ch = max(200, self.canvas_container.winfo_height() - 20)

        ratio = min(cw / img.width, ch / img.height, 1.0)
        dw = max(10, int(img.width * ratio))
        dh = max(10, int(img.height * ratio))

        disp = img.resize((dw, dh), Image.Resampling.BILINEAR)

        # Convert transparency to dark background for display
        if disp.mode == "RGBA":
            bg = Image.new("RGBA", (dw, dh), (20, 21, 24, 255))
            disp = Image.alpha_composite(bg, disp).convert("RGB")

        ctk_img = ctk.CTkImage(light_image=disp, dark_image=disp, size=(dw, dh))
        self._preview_photo_image = ctk_img
        self.preview_canvas_lbl.configure(image=ctk_img, text="")

    def _on_preview_resize(self, event):
        if self._last_rendered_master:
            self._display_preview_image(self._last_rendered_master)

    # ── Master Full-Resolution Export ────────────────────────────────────────

    def _render_master_image(self) -> Image.Image:
        """Renders the master print-ready image at 300 DPI (~2400 x 2400 px)."""
        covers = self.cached_covers
        if not covers:
            raise RuntimeError("No album covers available to render.")

        style = self.style_segmented.get()
        D = 2400

        if "Style 3" in style:
            try:
                r = max(1, int(self.rows_entry.get().strip()))
                c = max(1, int(self.cols_entry.get().strip()))
            except ValueError:
                r, c = calculate_optimal_grid(len(covers))

            gap = max(0, int(self.gap_slider.get() * 2.5))
            radius = max(0, int(self.radius_slider.get() * 2.5))

            preset = self.preset_menu.get()
            if "Back Tray" in preset:
                tw, th = 2400, int(2400 * 118 / 150)
            elif "Poster" in preset:
                tw, th = 1800, 2400
            elif "Wallpaper" in preset:
                tw, th = 2560, 1440
            else:
                tw, th = 2400, 2400

            return render_rectangular_grid(
                covers, r, c,
                target_width=tw, target_height=th,
                gap=gap, corner_radius=radius,
                bg_color=(18, 19, 23)
            )

        elif "Style 2" in style:
            r_out = 1140
            r_in = 280 if "Small" in self.spindle_menu.get() else 420
            r_sp = 150
            hub_sub = self.hub_sub_entry.get().replace("{N}", str(len(covers)))

            return render_concentric_tiles(
                covers,
                canvas_size=D,
                r_outer=r_out,
                r_inner=r_in,
                r_spindle=r_sp,
                hub_title=self.hub_title_entry.get().strip(),
                hub_subtitle=hub_sub,
                hub_info=self.hub_info_entry.get().strip(),
                show_cutlines=self.cutlines_switch.get(),
                bg_color=(16, 17, 20)
            )
        else:
            r_out = 1140
            r_in = 280 if "Small" in self.spindle_menu.get() else 420
            r_sp = 150
            hub_sub = self.hub_sub_entry.get().replace("{N}", str(len(covers)))

            return render_curved_polar_fan(
                covers,
                canvas_size=D,
                r_outer=r_out,
                r_inner=r_in,
                r_spindle=r_sp,
                hub_title=self.hub_title_entry.get().strip(),
                hub_subtitle=hub_sub,
                hub_info=self.hub_info_entry.get().strip(),
                show_cutlines=self.cutlines_switch.get(),
                cell_border_px=2
            )

    def _export_high_res(self):
        try:
            default_name = f"CD_Art_{int(time.time())}.png"
            dest = filedialog.asksaveasfilename(
                initialdir=str(self.output_folder),
                initialfile=default_name,
                defaultextension=".png",
                filetypes=[("PNG Image (Transparent/Lossless)", "*.png"), ("JPEG Image", "*.jpg")],
                title="Save High-Res Artwork"
            )
            if not dest:
                return

            master = self._render_master_image()
            if dest.lower().endswith(".jpg") or dest.lower().endswith(".jpeg"):
                # Convert RGBA to RGB for JPEG
                rgb = Image.new("RGB", master.size, (255, 255, 255))
                if master.mode == "RGBA":
                    rgb.paste(master, (0, 0), master)
                else:
                    rgb.paste(master, (0, 0))
                rgb.save(dest, "JPEG", quality=95, dpi=(300, 300))
            else:
                master.save(dest, "PNG", dpi=(300, 300))

            messagebox.showinfo("Export Complete", f"Successfully exported 300 DPI artwork to:\n{dest}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not export artwork: {e}")

    def _export_printable_a4(self):
        try:
            default_name = f"CD_Printable_A4_{int(time.time())}.png"
            dest = filedialog.asksaveasfilename(
                initialdir=str(self.output_folder),
                initialfile=default_name,
                defaultextension=".png",
                filetypes=[("PNG Image", "*.png"), ("PDF Document", "*.pdf")],
                title="Save Printable A4 Sheet"
            )
            if not dest:
                return

            master = self._render_master_image()
            is_disc = "Style 3" not in self.style_segmented.get()
            a4_page = generate_printable_a4_sheet(master, is_disc=is_disc, dpi=300)

            if dest.lower().endswith(".pdf"):
                a4_page.save(dest, "PDF", resolution=300.0)
            else:
                a4_page.save(dest, "PNG", dpi=(300, 300))

            messagebox.showinfo(
                "Printable Sheet Saved",
                f"Successfully generated 1:1 scale printable sheet!\n\nLocation: {dest}\n\n"
                f"Tip: When printing, select '100% / Actual Size' (do not choose 'Fit to Page') "
                f"so it matches standard 120 mm CD stickers exactly."
            )
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not generate printable sheet: {e}")

    def _copy_to_clipboard(self):
        try:
            if not self._last_rendered_master:
                self._last_rendered_master = self._render_master_image()
            ok = copy_image_to_clipboard(self._last_rendered_master)
            if ok:
                messagebox.showinfo("Copied!", "Artwork copied to clipboard! You can paste it into Word, Photoshop, or Paint.")
            else:
                messagebox.showwarning("Clipboard Warning", "Could not copy to clipboard directly. Try using 'Save Image'.")
        except Exception as e:
            messagebox.showerror("Error", f"Clipboard copy failed: {e}")

    def _open_output_folder(self):
        self.output_folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(self.output_folder))
