# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.2.2] - 2026-11-15

### Added
- **Multi-Factor Album Clustering & Collision Protection**:
  - Re-architected `fix_library_album_tags` to group tracks by directory path, album title, release identity, and artist family.
  - Distinct albums sharing identical titles (such as Queen's *Greatest Hits* versus ABBA's *Greatest Hits*) in nested or flat directories are isolated into independent clusters and protected from metadata cross-contamination.
  - Multi-disc sets organized in `CD1`, `CD2`, `Disc 1`, or `Disc 2` subfolders automatically collapse to the album parent directory.
- **Recursive Directory Traversal**:
  - Scans nested library folder hierarchies (`Artist/Album/track.ext`) recursively by default, with an optional `--no-recursive` flag for flat scans.
- **Dry-Run Preview Simulation**:
  - Added `--dry-run` CLI flag and interactive **Preview Changes** button in the GUI dialog to simulate metadata updates and inspect planned groupings without writing to disk.
- **Automated Safety Tag Backup & Restoration**:
  - Generates a timestamped `.redspindle_tag_backup_<timestamp>.json` snapshot recording original tag states prior to modifying any file.
  - Added `--restore-tags <backup.json>` CLI command to revert tag modifications back to their exact previous state.
- **Data CD (MP3 CD) vs. Audio CD (CD-DA) Distinction & Sizing**:
  - Added dedicated disc targets in CD Burn Prep for **80-minute** and **74-minute** Red Book Audio CDs alongside 700 MB Data / MP3 CDs.
  - Audio CD mode packs tracks by duration (up to 78 minutes safe limit, ~18–20 tracks), while Data CD mode packs by byte size (up to 690 MB, ~120–180 tracks).
  - UI export prompts, manifests, tracklists, and documentation explicitly explain the technical differences and player requirements for burning Data vs. Audio CDs.

### Changed
- **Neutralized Split Album Dialog Copy**:
  - Updated dialog window title, header, and subtitles to reflect universal `Album Artist` (`TPE2` / `aART` / `albumartist`) tag harmonization across Windows Media Player, Apple Music, VLC, and mobile players.

---

## [2.2.1] - 2026-11-15

### Changed
- **Neutralized Metadata & Tagging Terminology**:
  - Rephrased split-album repair around the universal `Album Artist` (`TPE2` / `aART` / `albumartist`) standard rather than Apple-specific framing, explaining grouping behavior across Windows Media Player, Android players (Poweramp/Musicolet), VLC, and Apple Music.
  - Clarified open-standard `.lrc` companion files for universal players alongside embedded container tags (`USLT` / `©lyr` / `lyrics`) for closed players.
  - Reframed artwork embedding to hardware-compatible baseline JPEG 640&times;640 across vintage DAPs, click-wheel iPods, and in-car systems.
- **UI & CLI Copy Updates**:
  - Main window subtitle updated to *"High-fidelity music downloader, metadata harmonizer & CD burn studio"*.
  - Dialog checkboxes explicitly state *"Fetch lyrics (.lrc file & embedded tags)"* and *"Fetch lyrics (standard .lrc file & embedded tags)"*.
  - CLI banner and help flags generalized to media library tag repair.
- **Multi-Platform Release Packaging**:
  - Standardized release executable names to `RedSpindle-Windows.exe`, `RedSpindle-Linux`, and `RedSpindle-macOS.zip` (while retaining `Spotify-Downloader-*` compatibility aliases).

---

## [2.2.0] - 2026-11-14

### Added
- **CD & Grid Art Studio**:
  - Full-featured artwork and disc label generator with interactive live preview.
  - **Style 1: Curved Polar Fan Mosaic (CD Disc)**: 100% full-bleed annular wedges curving along disc radius that dynamically scale from center spindle to outer perimeter.
  - **Style 2: Floating Concentric Tiles (CD Disc)**: Tangentially rotated crisp square album covers arranged in concentric circular rings over a sleek vinyl backdrop.
  - **Style 3: Any-by-Any Grid (Jewel Case Inserts and Posters)**: Auto-optimum or custom Rows &times; Columns grids with presets for CD Jewel Case Front Insert (120&times;120 mm), Back Tray Insert (150&times;118 mm), Desktop Wallpaper (16:9), and Poster (3:4).
  - Configurable tile spacing (gap) and corner rounding sliders.
- **Intelligent Album Cover Deduplication**:
  - Automatically identifies songs from the same album or identical embedded artwork.
  - Places each unique album cover on the disc/grid exactly once, eliminating repetitive clutter.
  - Includes a live toggle switch (`Deduplicate Albums`) in the UI that dynamically updates the preview and adapts the grid.
- **True 1:1 Scale Printable A4 Sheets**:
  - High-resolution (300 DPI) print-ready A4 export with 120 mm circular cutlines, center spindle hole, and alignment crosshairs.
  - Saves as high-resolution PNG or PDF for direct printing on standard sticker paper.
- **Windows Clipboard Integration**:
  - 1-click clipboard copy (`CF_DIB` 64-bit format) to paste generated artwork directly into Word, Paint, Photoshop, or printer software.
- **Center Hub Custom Typography**:
  - Customizable Disc Title, Subtitle, and extra metadata notes with Small Spindle (15–20 mm) and Standard Hub (40 mm) cutouts.
- **Multi-Threaded CD Disc Export**:
  - Parallelized disc folder generation (`ThreadPoolExecutor`) in CD Burn Prep, reducing export times for 100–200 tracks by up to 5x.

### Changed
- **Project Rebrand**: Rebranded project to **Red Spindle** (a tribute to the 1980 Philips/Sony Red Book CD-DA audio standard and physical disc spindles) to reflect its evolution into a full-featured music curation, iPod synchronization, and physical disc studio.
- Reorganized main window toolbar into dedicated rows for General Audio Maintenance and CD / Artwork Tools.
- Clarified audio pipeline in documentation: accurately states that high-fidelity audio streams are fetched via YouTube / YouTube Music matched against official Spotify metadata.

---

## [2.1.0] - 2026-11-13

### Added
- **Interactive CD Burn Prep & Song Curator**:
  - "Tinder-style" curation tool with instant keyboard navigation (Up = Keep, Down = Skip, Space = Play/Pause, Right = +5s/+10s seek, Left = -5s/-10s seek, Backspace/Z = Undo).
  - High-fidelity PyGame SDL2 audio playback engine with WASAPI and DirectSound support, bypassing Windows MCI limits on large ID3 tags.
  - Smart capacity disc packing: automatically distributes curated tracks into `Disc 1/`, `Disc 2/`, `Disc 3/` folders fitting standard 700 MB CD-Rs (Moser Baer).
  - Session JSON persistence (`cd_curation_session.json`): safely auto-saves progress so curation can be resumed anytime.
  - Auto-generated playlists (`playlist.m3u`) and track summaries (`disc_tracklist.txt`) in each disc folder.

---

## [2.0.0] - 2026-11-03

### Added
- **Universal Library & Device Tag Optimization**:
  - Automated `Album Artist` (`TPE2` / `aART`) tag unification to eliminate fragmented / split albums across Windows Media Player, Apple Music, and mobile libraries.
  - Standalone lossless repair tool (**Fix Split Albums...** / `--fix-tags`) to harmonize existing libraries without re-compressing audio.
  - Content advisory ratings: tags songs with standard `[E]` (Explicit) or `[Clean]` metadata.
  - Standardized 640&times;640 baseline JPEG artwork embedding for compatibility with vintage click-wheel iPods, car stereos, and portable players.

---

## [1.3.0] - 2026-10-28

### Added
- **Synchronized Lyrics for Apple Music and iOS**:
  - Direct integration with LRCLIB to embed synchronized lyrics into ID3 tags (`USLT` for MP3, `©lyr` for M4A).
  - Enables iOS tap-to-view lyrics on iPhone and iPod touch lock screen and player interfaces.
  - Companion `.lrc` timestamped files generated alongside each track.
- **Multilingual Hinglish Transliteration**:
  - Automatic transliteration engine for Bollywood and Hindi songs, converting Devanagari lyrics to Romanized Hinglish for singing along.
  - Three configurable script modes: Hinglish, native Devanagari, or raw database original.

---

## [1.2.0] - 2026-10-27

### Added
- **Audio Downsizing and Storage Optimizer**:
  - Downsize existing music collections to 128k, 160k, or 192k bitrates using FFmpeg.
  - Intelligent bitrate filter: only proposes bitrates lower than the current file's actual bitrate.
  - Preserves 100% of ID3 metadata, album covers, and lyrics tags without quality loss on tags.
  - Supports both in-place replacement and dedicated output subfolders.

---

## [1.1.0] - 2026-10-26

### Added
- **Parallel Download Engine**:
  - Concurrent multi-worker downloading (4–6 songs at once) for up to 5x faster downloads.
- **Clean vs Explicit Audio Modes**:
  - Choose between original uncensored explicit releases or official clean radio edits.
- **Smart Incremental Sync**:
  - Avoids re-downloading previously fetched tracks in existing folders.

---

## [1.0.0] - 2026-10-25

### Added
- Initial public release of Spotify Downloader.
- Modern dark-mode CustomTkinter desktop GUI and full-featured CLI.
- Spotify playlist, album, and track metadata scraping via `spotapi`.
- High-resolution audio stream matching via YouTube / YouTube Music using `yt-dlp`.
- Standalone single-file PyInstaller executables and single-command install scripts.
