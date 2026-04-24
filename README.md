<h1 align="center"> # FFmpex — The Clean FFmpeg GUI </h1>

<p align="center"><em>Stop memorizing flags...</em></p>

FFmpex gives FFmpeg a polished dark-themed interface — convert, compress, trim, and batch-process video & audio in seconds, with hardware acceleration and 30+ platform presets built in.

<p align="center">
  <a href="https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html">
    <img src="https://img.shields.io/badge/License-GPL_v2-orange.svg" />
  </a>
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/Python-3.9%2B-blue.svg" />
  </a>
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg" />
</p>
<p align="center">
<img width="100%" alt="image" src="https://github.com/user-attachments/assets/b253e2f0-f0d8-401b-b988-ade65492a3e8" />
</p>



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
- 📐 **Resolution Scaling** — 240p to 8K with smart padding to preserve aspect ratio

---
<p align="center">
<img width="100%" alt="image" src="https://github.com/user-attachments/assets/a68a8d22-16b1-45fc-97f8-d326d5ef3e79" />
</p>

<p align="center">
<img width="100%" alt="Untitled-3 copy" src="https://github.com/user-attachments/assets/13375bf2-a8ea-471f-8ab5-a62452377aaa" />
</p>

## Format Support

**Video Containers:** MP4, MKV, AVI, MOV, WebM, FLV, WMV, M4V, TS, 3GP, MXF, VOB, DIVX, MPG, MPEG, F4V

**Audio Formats:** MP3, AAC, FLAC, OGG, WAV, M4A, Opus, WMA, AC3, DTS, ALAC, AIFF, AMR

**Video Codecs:** H.264/AVC, H.265/HEVC, AV1 (libaom), AV1 (SVT-AV1), VP9, VP8, ProRes 422, DNxHD/DNxHR, MPEG-2, Theora, Stream Copy

---

<p align="center">
<img width="1280" height="687" alt="GIF" src="https://github.com/user-attachments/assets/a88302da-286c-4602-b400-2ed36c32b0f5" />
</p>


## Hardware Acceleration

| Vendor | Encoder | Supported Codecs |
|--------|---------|-----------------|
| NVIDIA | NVENC | H.264, H.265, AV1 (RTX 40+) |
| AMD | AMF | H.264, H.265, AV1 (RX 7000+) |
| Intel | Quick Sync (QSV) | H.264, H.265, AV1 (Arc) |
| Apple | VideoToolbox | H.264, H.265 |
| Linux | VAAPI | H.264, H.265, AV1 |


---

<p align="center">
<img width="1596" height="1003" alt="image" src="https://github.com/user-attachments/assets/fa8a827c-f4ce-4d58-98a9-74ca30376725" />
</p>

---

## Themes

> 3 of 21 available themes — switch instantly from Settings.

<p align="center">
<img width="32%" alt="image" src="https://github.com/user-attachments/assets/6682afd9-d1df-4861-aa67-de7b6abf0317" />
<img width="32%" alt="image" src="https://github.com/user-attachments/assets/2295dcc3-d326-498f-9c19-22cf884ad5aa" />
<img width="32%" alt="image" src="https://github.com/user-attachments/assets/82adbb19-4849-4197-b4e5-169886cd031b" />




</p>
<p align="center">
  <em>Gruvbox Dark &nbsp;·&nbsp; Light Sepia &nbsp;·&nbsp; Synthwave '84 Cyan</em>
</p>



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
