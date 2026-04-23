# FFMPEX — The Clean FFmpeg GUI

> Stop memorizing flags. FFmpex gives FFmpeg a polished dark-themed interface — convert, compress, trim, and batch-process video & audio in seconds, with hardware acceleration and 30+ platform presets built in.

[![License: GPL v2](https://img.shields.io/badge/License-GPL_v2-orange.svg)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

---

## Features

- 🎬 **Video Conversion** — MP4, MKV, AVI, MOV, WebM, and 10+ more containers with smart per-container codec defaults
- 🎵 **Audio Conversion** — MP3, AAC, FLAC, Opus, WAV, ALAC and more. Full bitrate control from 32k to 512k
- 📦 **Smart Compression** — Target-size presets for Discord, WhatsApp, Telegram. CRF slider from 14 (archive) to 35 (smallest)
- ⚡ **Hardware Acceleration** — NVIDIA NVENC, AMD AMF, Intel QSV, Apple VideoToolbox, Linux VAAPI — auto-detected
- 🎯 **30+ Platform Presets** — YouTube, TikTok, Instagram, Twitter, Plex, PS5, Xbox, Steam Deck, and more
- 🗂 **Job Queue** — Queue multiple jobs with live ETA tracking and desktop notifications on completion
- 🖱 **Drag & Drop** — Drop files directly onto the window (requires optional `tkinterdnd2`)
- 🎨 **Custom Themes** — Dracula, Nord, and more via CustomTkinter's theming engine
- 📐 **Resolution Scaling** — 240p to 8K with smart `-2` padding to preserve aspect ratio

---

## Format Support

**Video Containers:** MP4, MKV, AVI, MOV, WebM, FLV, WMV, M4V, TS, 3GP, MXF, VOB, DIVX, MPG, MPEG, F4V

**Audio Formats:** MP3, AAC, FLAC, OGG, WAV, M4A, Opus, WMA, AC3, DTS, ALAC, AIFF, AMR

**Video Codecs:** H.264/AVC, H.265/HEVC, AV1 (libaom), AV1 (SVT-AV1), VP9, VP8, ProRes 422, DNxHD/DNxHR, MPEG-2, Theora, Stream Copy

---

## Hardware Acceleration

| Vendor | Encoder | Supported Codecs |
|--------|---------|-----------------|
| NVIDIA | NVENC | H.264, H.265, AV1 (RTX 40+) |
| AMD | AMF | H.264, H.265, AV1 (RX 7000+) |
| Intel | Quick Sync (QSV) | H.264, H.265, AV1 (Arc) |
| Apple | VideoToolbox | H.264, H.265 |
| Linux | VAAPI | H.264, H.265, AV1 |

---

## Installation

**Requirements:** Python 3.9+ and FFmpeg installed on your system.

```bash
# 1. Install FFmpeg if you haven't already
#    Windows: winget install ffmpeg
#    macOS:   brew install ffmpeg
#    Linux:   sudo apt install ffmpeg

# 2. Required dependencies
pip install customtkinter pillow

# 3. Optional extras
pip install tkinterdnd2   # drag-and-drop
pip install pystray       # system tray icon
pip install plyer         # desktop notifications

# 4. Run
python ffmpex_v2.py

# Override FFmpeg path at launch
python ffmpex_v2.py --ffmpeg /custom/path/ffmpeg
```

---

## License

Licensed under the [GNU General Public License v2.0](LICENSE).
