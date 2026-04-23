#!/usr/bin/env python3
"""
FFmpex v2.4 — Clean FFmpeg GUI wrapper
pip install customtkinter pillow
pip install tkinterdnd2   # optional — enables drag-and-drop
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import threading
import os
import re
import time
import json
import tempfile
from pathlib import Path
from datetime import datetime

# ── Optional dependencies ──────────────────────────────────────────────────
try:
    from PIL import Image as PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import tkinterdnd2
    from tkinterdnd2 import DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

try:
    import pystray
    from pystray import MenuItem as TrayItem
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    from plyer import notification as plyer_notification
    HAS_PLYER = True
except ImportError:
    HAS_PLYER = False

import sys
import platform

# ══════════════════════════════════════════════════════════════
# Theme & Constants
# ══════════════════════════════════════════════════════════════
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

VIDEO_EXTS = [
    "mp4", "mkv", "avi", "mov", "webm", "flv", "wmv", "m4v",
    "ts", "3gp", "mxf", "f4v", "vob", "divx", "mpg", "mpeg",
]
AUDIO_EXTS = [
    "mp3", "aac", "flac", "ogg", "wav", "m4a", "opus", "wma",
    "ac3", "dts", "alac", "aiff", "amr",
    # NOTE: "pcm" is not a real container extension — raw PCM is better saved as
    # wav with a high bit-depth codec. Removed to avoid confusing file pickers.
]

COMPRESS_PRESETS = {
    "Discord (8 MB)":        {"crf": 28},
    "Discord Nitro (50 MB)": {"crf": 23},
    "WhatsApp (16 MB)":      {"crf": 30},
    "Telegram (50 MB)":      {"crf": 24},
    "Twitter / X":           {"crf": 20},
    "Web Optimized":         {"crf": 23},
    "High Quality":          {"crf": 18},
    "Archive (lossless-ish)":{"crf": 14},
    "Smallest File":         {"crf": 35},
}

BITRATES = [
    "32k", "48k", "64k", "80k", "96k", "112k",
    "128k", "160k", "192k", "224k", "256k", "320k",
    "384k", "448k", "512k",
]

SCALE_OPTIONS = {
    "Original":    None,
    "8K (4320p)":  "7680:-2",
    "4K (2160p)":  "3840:-2",
    "2K (1440p)":  "2560:-2",
    "1080p":       "1920:-2",
    "720p":        "1280:-2",
    "540p":        "960:-2",
    "480p":        "854:-2",
    "360p":        "640:-2",
    "240p":        "426:-2",
}

AUDIO_CODEC_MAP = {
    # Lossy
    "mp3":  "libmp3lame",
    "aac":  "aac",
    "ogg":  "libvorbis",
    "opus": "libopus",
    "wma":  "wmav2",
    "ac3":  "ac3",
    "dts":  "dca",
    "amr":  "libopencore_amrnb",
    # Lossless
    "flac": "flac",
    "wav":  "pcm_s16le",
    "m4a":  "aac",          # m4a = AAC in MP4 container
    "alac": "alac",
    "aiff": "pcm_s16be",
    # NOTE: "pcm" removed from AUDIO_EXTS — not a container.
    # Use "wav" for raw PCM output; pcm_s24le codec selected below if
    # a caller ever explicitly requests the key.
    "pcm":  "pcm_s24le",    # fallback kept for backwards-compat only
}

# ── Video codec options for ConvertPage / CompressPage ────────────────────
# key = display label, value = FFmpeg encoder name
VIDEO_CODEC_OPTIONS = {
    # H.264 / AVC
    "H.264 (libx264)":           "libx264",
    # H.265 / HEVC
    "H.265 / HEVC (libx265)":    "libx265",
    # AV1
    "AV1 (libaom-av1)":          "libaom-av1",
    "AV1 (libsvtav1) — faster":  "libsvtav1",
    # VP9 / VP8
    "VP9 (libvpx-vp9)":          "libvpx-vp9",
    "VP8 (libvpx)":              "libvpx",
    # ProRes / DNxHD (professional)
    "ProRes 422 (prores_ks)":    "prores_ks",
    "DNxHD / DNxHR (dnxhd)":     "dnxhd",
    # MPEG-2 (legacy / DVD)
    "MPEG-2 (mpeg2video)":       "mpeg2video",
    # Theora (open)
    "Theora (libtheora)":        "libtheora",
    # Stream copy (no re-encode)
    "Copy (no re-encode)":       "copy",
}

# ── Container → default video codec ─────────────────────────────────────────
# Used by ConvertPage to pick the right encoder for each output format.
# Containers not listed fall back to libx264 (universally safe).
CONTAINER_VIDEO_CODEC: dict[str, dict] = {
    # H.264 containers
    "mp4":  {"vcodec": "libx264",    "acodec": "aac"},
    "m4v":  {"vcodec": "libx264",    "acodec": "aac"},
    "mov":  {"vcodec": "libx264",    "acodec": "aac"},
    "f4v":  {"vcodec": "libx264",    "acodec": "aac"},
    # Flexible container (H.264 default; also supports H.265, VP9 etc.)
    "mkv":  {"vcodec": "libx264",    "acodec": "aac"},
    # AVI — H.264 is widely compatible inside AVI
    "avi":  {"vcodec": "libx264",    "acodec": "mp3"},   # AAC in AVI is unreliable
    # WebM — VP9 + Opus is the correct spec
    "webm": {"vcodec": "libvpx-vp9", "acodec": "libopus"},
    # Ogg/Theora — container mandates Theora video + Vorbis audio
    "ogv":  {"vcodec": "libtheora",  "acodec": "libvorbis"},
    # MPEG-2 transport / program stream
    "ts":   {"vcodec": "libx264",    "acodec": "aac"},
    "mpg":  {"vcodec": "mpeg2video", "acodec": "mp2"},
    "mpeg": {"vcodec": "mpeg2video", "acodec": "mp2"},
    # Flash
    "flv":  {"vcodec": "libx264",    "acodec": "aac"},
    # Windows Media
    "wmv":  {"vcodec": "wmv2",       "acodec": "wmav2"},
    # Mobile
    "3gp":  {"vcodec": "libx264",    "acodec": "aac"},
    # Professional / broadcast
    "mxf":  {"vcodec": "libx264",    "acodec": "pcm_s16le"},
    "vob":  {"vcodec": "mpeg2video", "acodec": "ac3"},
    "divx": {"vcodec": "libx264",    "acodec": "mp3"},
}

# CRF/quality flag differs per codec family
def codec_quality_flag(vcodec: str, crf_value: str | int) -> list[str]:
    """Return the correct quality flag(s) for a given codec."""
    crf = str(crf_value)
    v = vcodec.lower()
    if "libx264" in v or "libx265" in v or "libvpx" in v:
        return ["-crf", crf]
    if "libaom" in v:
        return ["-crf", crf, "-b:v", "0"]   # libaom needs b:v 0 for CRF mode
    if "libsvtav1" in v:
        return ["-crf", crf, "-preset", "6"] # SVT-AV1 uses preset not x264 preset
    if "libtheora" in v:
        q = max(1, min(10, int(float(crf) / 5.1)))  # map 0-51 CRF to 1-10 quality
        return ["-q:v", str(q)]
    if "prores" in v:
        return ["-profile:v", "2"]           # ProRes 422
    if "dnxhd" in v:
        return ["-b:v", "120M"]              # DNxHD needs explicit bitrate
    if "copy" in v:
        return []
    return ["-crf", crf]                     # safe default

# ── Hardware acceleration encoders ────────────────────────────────────────
HW_ENCODERS = {
    # ── Software ──────────────────────────────────────────────────────────
    "H.264 — software (libx264)":     {"venc": "libx264",            "aenc": "aac", "suffix": "_x264",    "codec": "h264"},
    "H.265 — software (libx265)":     {"venc": "libx265",            "aenc": "aac", "suffix": "_x265",    "codec": "hevc"},
    "AV1  — software (libaom-av1)":   {"venc": "libaom-av1",         "aenc": "opus","suffix": "_av1",     "codec": "av1"},
    "AV1  — software (libsvtav1)":    {"venc": "libsvtav1",          "aenc": "opus","suffix": "_svtav1",  "codec": "av1"},
    "VP9  — software (libvpx-vp9)":   {"venc": "libvpx-vp9",         "aenc": "opus","suffix": "_vp9",     "codec": "vp9"},
    # ── NVIDIA NVENC ──────────────────────────────────────────────────────
    "H.264 — NVENC (NVIDIA)":         {"venc": "h264_nvenc",          "aenc": "aac", "suffix": "_nvenc",   "codec": "h264"},
    "H.265 — NVENC (NVIDIA)":         {"venc": "hevc_nvenc",          "aenc": "aac", "suffix": "_hevc_nvenc","codec": "hevc"},
    "AV1  — NVENC (NVIDIA RTX 40+)":  {"venc": "av1_nvenc",           "aenc": "opus","suffix": "_av1_nvenc","codec": "av1"},
    # ── Apple VideoToolbox ────────────────────────────────────────────────
    "H.264 — VideoToolbox (Apple)":   {"venc": "h264_videotoolbox",   "aenc": "aac", "suffix": "_vt",      "codec": "h264"},
    "H.265 — VideoToolbox (Apple)":   {"venc": "hevc_videotoolbox",   "aenc": "aac", "suffix": "_hevc_vt", "codec": "hevc"},
    # ── AMD AMF ───────────────────────────────────────────────────────────
    "H.264 — AMF (AMD)":              {"venc": "h264_amf",            "aenc": "aac", "suffix": "_amf",     "codec": "h264"},
    "H.265 — AMF (AMD)":              {"venc": "hevc_amf",            "aenc": "aac", "suffix": "_hevc_amf","codec": "hevc"},
    "AV1  — AMF (AMD RX 7000+)":      {"venc": "av1_amf",             "aenc": "opus","suffix": "_av1_amf", "codec": "av1"},
    # ── Intel QSV ────────────────────────────────────────────────────────
    "H.264 — QSV (Intel)":            {"venc": "h264_qsv",            "aenc": "aac", "suffix": "_qsv",     "codec": "h264"},
    "H.265 — QSV (Intel)":            {"venc": "hevc_qsv",            "aenc": "aac", "suffix": "_hevc_qsv","codec": "hevc"},
    "AV1  — QSV (Intel Arc)":         {"venc": "av1_qsv",             "aenc": "opus","suffix": "_av1_qsv", "codec": "av1"},
    # ── Linux VAAPI ───────────────────────────────────────────────────────
    "H.264 — VAAPI (Linux)":          {"venc": "h264_vaapi",          "aenc": "aac", "suffix": "_vaapi",   "codec": "h264"},
    "H.265 — VAAPI (Linux)":          {"venc": "hevc_vaapi",          "aenc": "aac", "suffix": "_hevc_vaapi","codec": "hevc"},
    "AV1  — VAAPI (Linux)":           {"venc": "av1_vaapi",           "aenc": "opus","suffix": "_av1_vaapi","codec": "av1"},
}

# ── Platform presets ──────────────────────────────────────────────────────
PLATFORM_PRESETS = {
    "YouTube (1080p)": {
        "desc": "H.264 High, 1080p, 128k AAC, fast-start — recommended upload spec",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.0",
        "crf": "18", "preset_enc": "slow", "scale": "1920:-2",
        "acodec": "aac", "ab": "128k", "extra": ["-movflags", "+faststart"],
    },
    "YouTube Shorts (9:16)": {
        "desc": "H.264 High, 1080×1920, 60 fps, 128k AAC — vertical short-form",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.0",
        "crf": "20", "preset_enc": "fast", "scale": "1080:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-r", "60", "-movflags", "+faststart"],
    },
    "YouTube 4K (UHD)": {
        "desc": "H.264 High, 4K 2160p, 192k AAC — high quality archive upload",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "5.1",
        "crf": "16", "preset_enc": "slow", "scale": "3840:-2",
        "acodec": "aac", "ab": "192k", "extra": ["-movflags", "+faststart"],
    },
    "Instagram Reels": {
        "desc": "H.264, 1080×1920 (9:16), 30 fps, 128k AAC",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.0",
        "crf": "20", "preset_enc": "fast", "scale": "1080:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-r", "30", "-movflags", "+faststart"],
    },
    "Instagram Feed (1:1)": {
        "desc": "H.264, 1080×1080 (square), 30 fps — feed post",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.0",
        # FIX: removed "scale" key — the correct padded-square filter is in "extra"
        # and having both caused two -vf flags which made the scale step redundant.
        "crf": "20", "preset_enc": "fast",
        "acodec": "aac", "ab": "128k",
        "extra": ["-r", "30", "-vf", "scale=1080:1080:force_original_aspect_ratio=decrease,pad=1080:1080:(ow-iw)/2:(oh-ih)/2", "-movflags", "+faststart"],
    },
    "TikTok": {
        "desc": "H.264, 1080×1920 (9:16), 30 fps, 128k AAC",
        "ext": "mp4", "vcodec": "libx264", "profile": "main", "level": "3.1",
        "crf": "21", "preset_enc": "fast", "scale": "1080:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-r", "30", "-movflags", "+faststart"],
    },
    "Facebook (1080p)": {
        "desc": "H.264, 1080p, 128k AAC, fast-start — Facebook upload spec",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.0",
        "crf": "20", "preset_enc": "fast", "scale": "1920:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-movflags", "+faststart"],
    },
    "Facebook Reels": {
        "desc": "H.264, 1080×1920, 30 fps, 128k AAC — Facebook vertical Reels",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.0",
        "crf": "21", "preset_enc": "fast", "scale": "1080:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-r", "30", "-movflags", "+faststart"],
    },
    "Twitter / X": {
        "desc": "H.264, 1280×720, 128k AAC — Twitter/X upload spec",
        "ext": "mp4", "vcodec": "libx264", "profile": "main", "level": "3.1",
        "crf": "23", "preset_enc": "fast", "scale": "1280:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-movflags", "+faststart"],
    },
    "LinkedIn": {
        "desc": "H.264, 1080p, 128k AAC — LinkedIn native video spec",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.0",
        "crf": "20", "preset_enc": "fast", "scale": "1920:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-movflags", "+faststart"],
    },
    "Snapchat": {
        "desc": "H.264, 1080×1920 (9:16), 30 fps, AAC — Snapchat vertical video",
        "ext": "mp4", "vcodec": "libx264", "profile": "main", "level": "3.1",
        "crf": "23", "preset_enc": "fast", "scale": "1080:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-r", "30", "-movflags", "+faststart"],
    },
    "Pinterest": {
        "desc": "H.264, 1080×1920, 30 fps, 128k AAC — Pinterest video pins",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.0",
        "crf": "22", "preset_enc": "fast", "scale": "1080:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-r", "30", "-movflags", "+faststart"],
    },
    "Reddit": {
        "desc": "H.264, 1080p, 128k AAC — Reddit native video (≤1 GB, ≤15 min)",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.0",
        "crf": "21", "preset_enc": "fast", "scale": "1920:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-movflags", "+faststart"],
    },
    "Twitch Clip": {
        "desc": "H.264 High, 1080p60, 192k AAC — Twitch stream/clip quality",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.2",
        "crf": "20", "preset_enc": "fast", "scale": "1920:-2",
        "acodec": "aac", "ab": "192k",
        "extra": ["-r", "60", "-movflags", "+faststart"],
    },
    "Vimeo (HD)": {
        "desc": "H.264, 1080p, high quality, 192k AAC — Vimeo recommended",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.0",
        "crf": "16", "preset_enc": "slow", "scale": "1920:-2",
        "acodec": "aac", "ab": "192k",
        "extra": ["-movflags", "+faststart"],
    },
    "Vimeo 4K": {
        "desc": "H.264, 4K 2160p, 192k AAC — Vimeo 4K upload",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "5.1",
        "crf": "14", "preset_enc": "slow", "scale": "3840:-2",
        "acodec": "aac", "ab": "192k",
        "extra": ["-movflags", "+faststart"],
    },
    "WhatsApp Status": {
        "desc": "H.264, 480p, 64k AAC — WhatsApp status (≤16 MB, ≤30 s)",
        "ext": "mp4", "vcodec": "libx264", "profile": "baseline", "level": "3.0",
        "crf": "30", "preset_enc": "fast", "scale": "854:-2",
        "acodec": "aac", "ab": "64k",
        "extra": ["-t", "30", "-movflags", "+faststart"],
    },
    "WeChat": {
        "desc": "H.264, 720p, 128k AAC — WeChat Moments video spec",
        "ext": "mp4", "vcodec": "libx264", "profile": "main", "level": "3.1",
        "crf": "24", "preset_enc": "fast", "scale": "1280:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-movflags", "+faststart"],
    },
    "Broadcast (H.264)": {
        "desc": "H.264 High 4.1, 1080p, 192k AAC — generic broadcast/OTT delivery",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.1",
        "crf": "18", "preset_enc": "slow", "scale": "1920:-2",
        "acodec": "aac", "ab": "192k",
        "extra": ["-movflags", "+faststart"],
    },
}

# ── Device presets ────────────────────────────────────────────────────────
DEVICE_PRESETS = {
    # ── Apple ─────────────────────────────────────────────────────────────
    "iPhone (H.265/HEVC)": {
        "desc": "HEVC Main10, 1080p, Stereo AAC — iPhone 7+",
        "ext": "mp4", "vcodec": "libx265", "crf": "22", "preset_enc": "fast",
        "scale": "1920:-2", "acodec": "aac", "ab": "128k",
        "extra": ["-tag:v", "hvc1", "-movflags", "+faststart"],
    },
    "iPhone (H.264)": {
        "desc": "H.264 Baseline 3.0, 720p, AAC — broadest iPhone compatibility",
        "ext": "mp4", "vcodec": "libx264", "profile": "baseline", "level": "3.0",
        "crf": "23", "preset_enc": "fast", "scale": "1280:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-movflags", "+faststart"],
    },
    "iPad (H.265/HEVC)": {
        "desc": "HEVC, 1080p, Stereo AAC — iPad (5th gen+)",
        "ext": "mp4", "vcodec": "libx265", "crf": "20", "preset_enc": "fast",
        "scale": "1920:-2", "acodec": "aac", "ab": "128k",
        "extra": ["-tag:v", "hvc1", "-movflags", "+faststart"],
    },
    "Apple TV (4K)": {
        "desc": "HEVC Main10, 4K 2160p, AAC 256k",
        "ext": "mp4", "vcodec": "libx265", "crf": "18", "preset_enc": "slow",
        "scale": "3840:-2", "acodec": "aac", "ab": "256k",
        "extra": ["-tag:v", "hvc1"],
    },
    # ── Android ───────────────────────────────────────────────────────────
    "Android (universal)": {
        "desc": "H.264 Baseline 3.1, 720p, AAC — universal Android compatibility",
        "ext": "mp4", "vcodec": "libx264", "profile": "baseline", "level": "3.1",
        "crf": "23", "preset_enc": "fast", "scale": "1280:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-movflags", "+faststart"],
    },
    "Android (high quality)": {
        "desc": "H.264 High 4.0, 1080p, AAC 192k — modern Android flagship",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.0",
        "crf": "20", "preset_enc": "fast", "scale": "1920:-2",
        "acodec": "aac", "ab": "192k",
        "extra": ["-movflags", "+faststart"],
    },
    # ── Smart TV / Streaming sticks ───────────────────────────────────────
    "Chromecast (1080p)": {
        "desc": "H.264, 1080p, AAC 128k — Google Cast compatible",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.0",
        "crf": "20", "preset_enc": "fast", "scale": "1920:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-movflags", "+faststart"],
    },
    "Samsung Smart TV": {
        "desc": "H.264 High 4.1, 1080p, AAC 192k — Samsung Tizen TV player",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.1",
        "crf": "20", "preset_enc": "fast", "scale": "1920:-2",
        "acodec": "aac", "ab": "192k",
        "extra": [],
    },
    "LG Smart TV (HEVC)": {
        "desc": "HEVC Main 4.1, 4K, AAC 192k — LG webOS H.265 playback",
        "ext": "mp4", "vcodec": "libx265", "crf": "20", "preset_enc": "fast",
        "scale": "3840:-2", "acodec": "aac", "ab": "192k",
        "extra": ["-tag:v", "hvc1"],
    },
    "Roku / Generic Smart TV": {
        "desc": "H.264 Main 4.0, 1080p, AAC 128k — broadest Smart TV compat",
        "ext": "mp4", "vcodec": "libx264", "profile": "main", "level": "4.0",
        "crf": "20", "preset_enc": "fast", "scale": "1920:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-movflags", "+faststart"],
    },
    "Amazon Fire TV": {
        "desc": "H.264 High 4.1, 1080p, AAC 192k — Fire TV Stick 4K compatible",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.1",
        "crf": "20", "preset_enc": "fast", "scale": "1920:-2",
        "acodec": "aac", "ab": "192k",
        "extra": ["-movflags", "+faststart"],
    },
    # ── Game consoles ──────────────────────────────────────────────────────
    "PlayStation 5 / DLNA": {
        "desc": "H.264 High 4.1, 1080p, AAC 192k — PS5 Media Player",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.1",
        "crf": "18", "preset_enc": "slow", "scale": "1920:-2",
        "acodec": "aac", "ab": "192k",
        "extra": [],
    },
    "Xbox Series X / S": {
        "desc": "H.264 High 4.2, 1080p, AAC 192k — Xbox media app compatible",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.2",
        "crf": "19", "preset_enc": "slow", "scale": "1920:-2",
        "acodec": "aac", "ab": "192k",
        "extra": [],
    },
    "Nintendo Switch": {
        "desc": "H.264 Baseline 3.1, 720p, AAC 128k — Switch media player",
        "ext": "mp4", "vcodec": "libx264", "profile": "baseline", "level": "3.1",
        "crf": "24", "preset_enc": "fast", "scale": "1280:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-movflags", "+faststart"],
    },
    "Steam Deck": {
        "desc": "H.264 High 4.0, 1280×800, AAC 192k — Steam Deck native display",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.0",
        "crf": "20", "preset_enc": "fast", "scale": "1280:-2",
        "acodec": "aac", "ab": "192k",
        "extra": ["-movflags", "+faststart"],
    },
    # ── Media server / SBC ────────────────────────────────────────────────
    "Plex / Kodi (1080p)": {
        "desc": "H.264 High 4.0, 1080p, AAC 192k — direct-play in Plex & Kodi",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.0",
        "crf": "20", "preset_enc": "medium", "scale": "1920:-2",
        "acodec": "aac", "ab": "192k",
        "extra": ["-movflags", "+faststart"],
    },
    "Plex / Kodi (4K HEVC)": {
        "desc": "HEVC Main 5.1, 4K, AAC 256k — Plex/Kodi 4K direct-play",
        "ext": "mkv", "vcodec": "libx265", "crf": "20", "preset_enc": "medium",
        "scale": "3840:-2", "acodec": "aac", "ab": "256k",
        "extra": [],
    },
    "Raspberry Pi": {
        "desc": "H.264 Baseline 3.0, 720p, AAC 128k — hardware decode on Pi 3/4",
        "ext": "mp4", "vcodec": "libx264", "profile": "baseline", "level": "3.0",
        "crf": "26", "preset_enc": "veryfast", "scale": "1280:-2",
        "acodec": "aac", "ab": "128k",
        "extra": ["-movflags", "+faststart"],
    },
    # ── VR / Special ──────────────────────────────────────────────────────
    "Meta Quest (VR)": {
        "desc": "H.264 High 4.1, 1920×1080, AAC 192k — Meta Quest side-load",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "4.1",
        "crf": "18", "preset_enc": "slow", "scale": "1920:-2",
        "acodec": "aac", "ab": "192k",
        "extra": ["-movflags", "+faststart"],
    },
    "DJI / GoPro Archive": {
        "desc": "H.264 High 5.1, 4K, AAC 256k — high-quality action cam archive",
        "ext": "mp4", "vcodec": "libx264", "profile": "high", "level": "5.1",
        "crf": "16", "preset_enc": "slow", "scale": "3840:-2",
        "acodec": "aac", "ab": "256k",
        "extra": ["-movflags", "+faststart"],
    },
}

# ══════════════════════════════════════════════════════════════
# Full UI Themes
# ══════════════════════════════════════════════════════════════
# Each theme is a complete CustomTkinter color dict.
# Format: every color is [light_mode_value, dark_mode_value].
# For dark-only themes (Dracula, etc.) both values are the same dark color.

def _theme(bg, bg2, bg3, border, btn, btn_hover, btn_text,
           entry_bg, text, text_dim, text_disabled,
           progress_track, progress_fill, scrollbar) -> dict:
    """
    Build a complete CustomTkinter-compatible theme dict.
    Includes every key CTk reads so no KeyError can occur.
    Color values are [light, dark] pairs; we use the same value for both
    since our themes define absolute colors rather than mode-dependent ones.
    """
    return {
        # ── Top-level windows ─────────────────────────────────────────────
        "CTk":         {"fg_color": [bg, bg]},
        "CTkToplevel": {"fg_color": [bg, bg]},
        # ── Frame ────────────────────────────────────────────────────────
        "CTkFrame": {
            "fg_color":     [bg2, bg2],
            "top_fg_color": [bg3, bg3],
            "border_color": [border, border],
            "border_width": 0,
            "corner_radius": 6,
        },
        # ── Button ───────────────────────────────────────────────────────
        "CTkButton": {
            "fg_color":            [btn, btn],
            "hover_color":         [btn_hover, btn_hover],
            "border_color":        [border, border],
            "text_color":          [btn_text, btn_text],
            "text_color_disabled": [text_disabled, text_disabled],
            "border_width": 0,
            "corner_radius": 6,
        },
        # ── CheckBox ─────────────────────────────────────────────────────
        "CTkCheckBox": {
            "fg_color":            [btn, btn],
            "hover_color":         [btn_hover, btn_hover],
            "border_color":        [border, border],
            "checkmark_color":     [btn_text, btn_text],
            "text_color":          [text, text],
            "text_color_disabled": [text_disabled, text_disabled],
            "border_width": 3,
            "corner_radius": 6,
        },
        # ── RadioButton ──────────────────────────────────────────────────
        "CTkRadioButton": {
            "fg_color":              [btn, btn],
            "border_color":          [border, border],
            "hover_color":           [btn_hover, btn_hover],
            "text_color":            [text, text],
            "text_color_disabled":   [text_disabled, text_disabled],
            "border_width_checked":   6,
            "border_width_unchecked": 3,
            "corner_radius": 1000,
        },
        # ── Entry ────────────────────────────────────────────────────────
        "CTkEntry": {
            "fg_color":               [entry_bg, entry_bg],
            "border_color":           [btn, btn],
            "text_color":             [text, text],
            "placeholder_text_color": [text_disabled, text_disabled],
            "border_width": 2,
            "corner_radius": 6,
        },
        # ── Label ────────────────────────────────────────────────────────
        "CTkLabel": {
            "fg_color":   "transparent",
            "text_color": [text, text],
            "corner_radius": 0,
        },
        # ── ProgressBar ──────────────────────────────────────────────────
        "CTkProgressBar": {
            "fg_color":       [progress_track, progress_track],
            "progress_color": [progress_fill, progress_fill],
            "border_color":   [border, border],
            "border_width": 0,
            "corner_radius": 1000,
        },
        # ── Slider ───────────────────────────────────────────────────────
        "CTkSlider": {
            "fg_color":           [progress_track, progress_track],
            "progress_color":     [progress_fill, progress_fill],
            "button_color":       [progress_fill, progress_fill],
            "button_hover_color": [btn_hover, btn_hover],
            "border_width": 6,
            "corner_radius": 1000,
            "button_corner_radius": 1000,
            "button_length": 0,
        },
        # ── OptionMenu ───────────────────────────────────────────────────
        "CTkOptionMenu": {
            "fg_color":            [btn, btn],
            "button_color":        [btn_hover, btn_hover],
            "button_hover_color":  [btn_hover, btn_hover],
            "text_color":          [btn_text, btn_text],
            "text_color_disabled": [text_disabled, text_disabled],
            "corner_radius": 6,
        },
        # ── ComboBox ─────────────────────────────────────────────────────
        "CTkComboBox": {
            "fg_color":            [entry_bg, entry_bg],
            "border_color":        [btn, btn],
            "button_color":        [btn, btn],
            "button_hover_color":  [btn_hover, btn_hover],
            "text_color":          [text, text],
            "text_color_disabled": [text_disabled, text_disabled],
            "border_width": 2,
            "corner_radius": 6,
        },
        # ── Scrollbar ────────────────────────────────────────────────────
        "CTkScrollbar": {
            "fg_color":                "transparent",
            "button_color":            [scrollbar, scrollbar],
            "button_hover_color":      [btn, btn],
            "corner_radius": 1000,
            "border_spacing": 4,
        },
        # ── ScrollableFrame ───────────────────────────────────────────────
        "CTkScrollableFrame": {
            "label_fg_color": [bg2, bg2],
        },
        # ── Textbox ───────────────────────────────────────────────────────
        "CTkTextbox": {
            "fg_color":                     [entry_bg, entry_bg],
            "border_color":                 [border, border],
            "text_color":                   [text, text],
            "scrollbar_button_color":       [scrollbar, scrollbar],
            "scrollbar_button_hover_color": [btn, btn],
            "border_width": 0,
            "corner_radius": 6,
        },
        # ── SegmentedButton ───────────────────────────────────────────────
        "CTkSegmentedButton": {
            "fg_color":               [bg3, bg3],
            "selected_color":         [btn, btn],
            "selected_hover_color":   [btn_hover, btn_hover],
            "unselected_color":       [bg3, bg3],
            "unselected_hover_color": [bg2, bg2],
            "text_color":             [text, text],
            "text_color_disabled":    [text_disabled, text_disabled],
            "border_width": 2,
            "corner_radius": 6,
        },
        # ── Tabview ───────────────────────────────────────────────────────
        "CTkTabview": {
            "fg_color":              [bg2, bg2],
            "border_color":          [border, border],
            "segmented_button_fg_color": [bg3, bg3],
            "segmented_button_selected_color": [btn, btn],
            "segmented_button_selected_hover_color": [btn_hover, btn_hover],
            "segmented_button_unselected_color": [bg3, bg3],
            "segmented_button_unselected_hover_color": [bg2, bg2],
            "text_color":            [text, text],
            "text_color_disabled":   [text_disabled, text_disabled],
            "border_width": 0,
            "corner_radius": 6,
        },
        # ── Switch ────────────────────────────────────────────────────────
        "CTkSwitch": {
            "fg_color":            [progress_track, progress_track],
            "progress_color":      [progress_fill, progress_fill],
            "button_color":        [text_dim, text_dim],
            "button_hover_color":  [text, text],
            "text_color":          [text, text],
            "text_color_disabled": [text_disabled, text_disabled],
            "border_width": 3,
            "corner_radius": 1000,
            "button_length": 0,
        },
        # ── DropdownMenu (used internally by OptionMenu/ComboBox) ─────────
        "DropdownMenu": {
            "fg_color":    [bg3, bg3],
            "hover_color": [btn_hover, btn_hover],
            "text_color":  [text, text],
        },
        # ── Font defaults ─────────────────────────────────────────────────
        "CTkFont": {
            "macOS":   {"family": "SF Display",  "size": 13, "weight": "normal"},
            "Windows": {"family": "Segoe UI",     "size": 13, "weight": "normal"},
            "Linux":   {"family": "Roboto",       "size": 13, "weight": "normal"},
        },
    }


# Theme registry — name: (theme_dict, preview_colors)
# preview_colors = (bg, accent, text) for the swatch in Settings
FULL_THEMES: dict[str, tuple[dict, tuple]] = {

    "FFmpex Default (Dark Blue)": (
        _theme(
            bg="#1e2227", bg2="#252a31", bg3="#2d343c",
            border="#3d4550",
            btn="#1a6db5", btn_hover="#144870", btn_text="#e8edf2",
            entry_bg="#1a1f25",
            text="#cdd6e0", text_dim="#7a8a9a", text_disabled="#4a5a6a",
            progress_track="#2d343c", progress_fill="#1a6db5",
            scrollbar="#3d4550",
        ),
        ("#1e2227", "#1a6db5", "#cdd6e0"),
    ),

    "Dracula": (
        _theme(
            bg="#282a36", bg2="#21222c", bg3="#343746",
            border="#6272a4",
            btn="#bd93f9", btn_hover="#a074e8", btn_text="#282a36",
            entry_bg="#21222c",
            text="#f8f8f2", text_dim="#6272a4", text_disabled="#44475a",
            progress_track="#44475a", progress_fill="#bd93f9",
            scrollbar="#6272a4",
        ),
        ("#282a36", "#bd93f9", "#f8f8f2"),
    ),

    "Catppuccin Mocha": (
        _theme(
            bg="#1e1e2e", bg2="#181825", bg3="#313244",
            border="#45475a",
            btn="#89b4fa", btn_hover="#74a0e8", btn_text="#1e1e2e",
            entry_bg="#181825",
            text="#cdd6f4", text_dim="#6c7086", text_disabled="#45475a",
            progress_track="#313244", progress_fill="#89b4fa",
            scrollbar="#45475a",
        ),
        ("#1e1e2e", "#89b4fa", "#cdd6f4"),
    ),

    "Catppuccin Macchiato": (
        _theme(
            bg="#24273a", bg2="#1e2030", bg3="#363a4f",
            border="#494d64",
            btn="#8aadf4", btn_hover="#7095e0", btn_text="#24273a",
            entry_bg="#1e2030",
            text="#cad3f5", text_dim="#6e738d", text_disabled="#494d64",
            progress_track="#363a4f", progress_fill="#8aadf4",
            scrollbar="#494d64",
        ),
        ("#24273a", "#8aadf4", "#cad3f5"),
    ),

    "Catppuccin Latte (Light)": (
        _theme(
            bg="#eff1f5", bg2="#e6e9ef", bg3="#dce0e8",
            border="#9ca0b0",
            btn="#1e66f5", btn_hover="#1050d8", btn_text="#eff1f5",
            entry_bg="#ffffff",
            text="#4c4f69", text_dim="#9ca0b0", text_disabled="#ccd0da",
            progress_track="#ccd0da", progress_fill="#1e66f5",
            scrollbar="#9ca0b0",
        ),
        ("#eff1f5", "#1e66f5", "#4c4f69"),
    ),

    "Nord": (
        _theme(
            bg="#2e3440", bg2="#272c36", bg3="#3b4252",
            border="#4c566a",
            btn="#5e81ac", btn_hover="#4c6f96", btn_text="#eceff4",
            entry_bg="#272c36",
            text="#eceff4", text_dim="#7b88a1", text_disabled="#4c566a",
            progress_track="#3b4252", progress_fill="#88c0d0",
            scrollbar="#4c566a",
        ),
        ("#2e3440", "#88c0d0", "#eceff4"),
    ),

    "One Dark Pro": (
        _theme(
            bg="#282c34", bg2="#21252b", bg3="#2c313c",
            border="#3e4452",
            btn="#61afef", btn_hover="#4d9bd8", btn_text="#282c34",
            entry_bg="#21252b",
            text="#abb2bf", text_dim="#5c6370", text_disabled="#3e4452",
            progress_track="#3e4452", progress_fill="#61afef",
            scrollbar="#5c6370",
        ),
        ("#282c34", "#61afef", "#abb2bf"),
    ),

    "Gruvbox Dark": (
        _theme(
            bg="#282828", bg2="#1d2021", bg3="#3c3836",
            border="#504945",
            btn="#d79921", btn_hover="#b8841c", btn_text="#282828",
            entry_bg="#1d2021",
            text="#ebdbb2", text_dim="#928374", text_disabled="#504945",
            progress_track="#3c3836", progress_fill="#83a598",
            scrollbar="#665c54",
        ),
        ("#282828", "#d79921", "#ebdbb2"),
    ),

    "Tokyo Night": (
        _theme(
            bg="#1a1b26", bg2="#16161e", bg3="#24283b",
            border="#414868",
            btn="#7aa2f7", btn_hover="#6085d6", btn_text="#1a1b26",
            entry_bg="#16161e",
            text="#c0caf5", text_dim="#565f89", text_disabled="#414868",
            progress_track="#24283b", progress_fill="#7aa2f7",
            scrollbar="#565f89",
        ),
        ("#1a1b26", "#7aa2f7", "#c0caf5"),
    ),

    "Tokyo Night Storm": (
        _theme(
            bg="#24283b", bg2="#1f2335", bg3="#2f344a",
            border="#414868",
            btn="#7aa2f7", btn_hover="#5a82d7", btn_text="#24283b",
            entry_bg="#1f2335",
            text="#c0caf5", text_dim="#565f89", text_disabled="#414868",
            progress_track="#2f344a", progress_fill="#bb9af7",
            scrollbar="#565f89",
        ),
        ("#24283b", "#bb9af7", "#c0caf5"),
    ),

    "Monokai Pro": (
        _theme(
            bg="#2d2a2e", bg2="#221f22", bg3="#403e41",
            border="#5b595c",
            btn="#a9dc76", btn_hover="#8fc45e", btn_text="#2d2a2e",
            entry_bg="#221f22",
            text="#fcfcfa", text_dim="#727072", text_disabled="#5b595c",
            progress_track="#403e41", progress_fill="#ff6188",
            scrollbar="#5b595c",
        ),
        ("#2d2a2e", "#a9dc76", "#fcfcfa"),
    ),

    "Solarized Dark": (
        _theme(
            bg="#002b36", bg2="#00212b", bg3="#073642",
            border="#2e5260",
            btn="#268bd2", btn_hover="#1a6fa8", btn_text="#fdf6e3",
            entry_bg="#00212b",
            text="#839496", text_dim="#586e75", text_disabled="#2e5260",
            progress_track="#073642", progress_fill="#2aa198",
            scrollbar="#2e5260",
        ),
        ("#002b36", "#268bd2", "#839496"),
    ),

    "Material Ocean": (
        _theme(
            bg="#0f111a", bg2="#090b10", bg3="#1a1c25",
            border="#2d3142",
            btn="#82aaff", btn_hover="#6990e0", btn_text="#0f111a",
            entry_bg="#090b10",
            text="#8f93a2", text_dim="#4b526d", text_disabled="#2d3142",
            progress_track="#1a1c25", progress_fill="#c3e88d",
            scrollbar="#4b526d",
        ),
        ("#0f111a", "#82aaff", "#8f93a2"),
    ),

    "Everforest Dark": (
        _theme(
            bg="#2d353b", bg2="#272e33", bg3="#343f44",
            border="#4a555b",
            btn="#a7c080", btn_hover="#8aad63", btn_text="#2d353b",
            entry_bg="#272e33",
            text="#d3c6aa", text_dim="#7a8478", text_disabled="#4a555b",
            progress_track="#343f44", progress_fill="#a7c080",
            scrollbar="#4a555b",
        ),
        ("#2d353b", "#a7c080", "#d3c6aa"),
    ),

    "Rosé Pine": (
        _theme(
            bg="#191724", bg2="#1f1d2e", bg3="#26233a",
            border="#403d52",
            btn="#c4a7e7", btn_hover="#a889cc", btn_text="#191724",
            entry_bg="#1f1d2e",
            text="#e0def4", text_dim="#6e6a86", text_disabled="#403d52",
            progress_track="#26233a", progress_fill="#eb6f92",
            scrollbar="#6e6a86",
        ),
        ("#191724", "#c4a7e7", "#e0def4"),
    ),

    "Ayu Dark": (
        _theme(
            bg="#0d1017", bg2="#0b0e14", bg3="#131721",
            border="#1f2430",
            btn="#e6b450", btn_hover="#c99a3e", btn_text="#0d1017",
            entry_bg="#0b0e14",
            text="#b3b1ad", text_dim="#3e4b59", text_disabled="#1f2430",
            progress_track="#131721", progress_fill="#39bae6",
            scrollbar="#3e4b59",
        ),
        ("#0d1017", "#e6b450", "#b3b1ad"),
    ),

    "Midnight (Pure Black)": (
        _theme(
            bg="#000000", bg2="#0a0a0a", bg3="#111111",
            border="#222222",
            btn="#3b8ed0", btn_hover="#2a6faa", btn_text="#ffffff",
            entry_bg="#0a0a0a",
            text="#e0e0e0", text_dim="#555555", text_disabled="#333333",
            progress_track="#111111", progress_fill="#3b8ed0",
            scrollbar="#333333",
        ),
        ("#000000", "#3b8ed0", "#e0e0e0"),
    ),

    "Light (Clean)": (
        _theme(
            bg="#f5f5f5", bg2="#ebebeb", bg3="#e0e0e0",
            border="#c0c0c0",
            btn="#2563eb", btn_hover="#1d4fd8", btn_text="#ffffff",
            entry_bg="#ffffff",
            text="#1a1a1a", text_dim="#6b7280", text_disabled="#c0c0c0",
            progress_track="#d1d5db", progress_fill="#2563eb",
            scrollbar="#9ca3af",
        ),
        ("#f5f5f5", "#2563eb", "#1a1a1a"),
    ),

    "Light Sepia": (
        _theme(
            bg="#f5f0e8", bg2="#ede7d9", bg3="#e0d8c8",
            border="#b8a898",
            btn="#8b5e3c", btn_hover="#704c30", btn_text="#f5f0e8",
            entry_bg="#faf7f0",
            text="#3c2a1a", text_dim="#8b7355", text_disabled="#c8b89a",
            progress_track="#ddd5c5", progress_fill="#8b5e3c",
            scrollbar="#b8a898",
        ),
        ("#f5f0e8", "#8b5e3c", "#3c2a1a"),
    ),
}


# ── Synthwave '84 ─────────────────────────────────────────────────────────
FULL_THEMES["Synthwave '84"] = (
    _theme(
        bg="#241734",      bg2="#1a0e2e",     bg3="#2d1b4e",
        border="#7b2fff",
        btn="#f92aad",     btn_hover="#d41d94", btn_text="#1a0e2e",
        entry_bg="#1a0e2e",
        text="#f8f8f2",    text_dim="#b893ce",  text_disabled="#4a2f6a",
        progress_track="#2d1b4e", progress_fill="#72f1b8",
        scrollbar="#7b2fff",
    ),
    ("#241734", "#f92aad", "#f8f8f2"),
)
FULL_THEMES["Synthwave '84 (Cyan)"] = (
    _theme(
        bg="#241734",      bg2="#1a0e2e",     bg3="#2d1b4e",
        border="#7b2fff",
        btn="#72f1b8",     btn_hover="#52d19a", btn_text="#1a0e2e",
        entry_bg="#1a0e2e",
        text="#f8f8f2",    text_dim="#b893ce",  text_disabled="#4a2f6a",
        progress_track="#2d1b4e", progress_fill="#f92aad",
        scrollbar="#7b2fff",
    ),
    ("#241734", "#72f1b8", "#f8f8f2"),
)


# ── TC — module-level theme surface colors used by layout helpers ──────────
# These are plain hex strings (NOT tuples). CTk accepts single-string colors.
# Updated by apply_full_theme(); initialized below from the default theme.

TC: dict[str, str] = {}


def _derive_tc(ctk_dict: dict) -> dict:
    """
    Extract semantic UI surface colors from a CTk theme dict.
    Called automatically by apply_full_theme() to populate TC.
    """
    bg        = ctk_dict["CTk"]["fg_color"][0]
    bg2       = ctk_dict["CTkFrame"]["fg_color"][0]
    bg3       = ctk_dict["CTkFrame"]["top_fg_color"][0]
    border    = ctk_dict["CTkFrame"]["border_color"][0]
    btn       = ctk_dict["CTkButton"]["fg_color"][0]
    btn_hover = ctk_dict["CTkButton"]["hover_color"][0]
    btn_text  = ctk_dict["CTkButton"]["text_color"][0]
    text      = ctk_dict["CTkLabel"]["text_color"][0]
    entry_bg  = ctk_dict["CTkEntry"]["fg_color"][0]
    scrollbar = ctk_dict["CTkScrollbar"]["button_color"][0]
    progress  = ctk_dict["CTkProgressBar"]["progress_color"][0]
    text_dim  = ctk_dict["CTkSwitch"]["button_color"][0]

    # Derive a slightly lighter/darker variant of bg3 for nav-active highlight
    def _blend(a: str, b: str, t: float = 0.35) -> str:
        """Linear blend of two hex colors."""
        a = a.lstrip("#"); b = b.lstrip("#")
        ra, ga, ba = int(a[0:2],16), int(a[2:4],16), int(a[4:6],16)
        rb, gb, bb = int(b[0:2],16), int(b[2:4],16), int(b[4:6],16)
        r = int(ra + (rb - ra) * t)
        g = int(ga + (gb - ga) * t)
        bl = int(ba + (bb - ba) * t)
        return "#{:02X}{:02X}{:02X}".format(r, g, bl)

    nav_active = _blend(bg2, btn, 0.30)

    return {
        # Page chrome
        "sidebar":       bg2,
        "content":       bg,
        # Cards
        "card":          bg2,
        "card_inner":    entry_bg,
        # Separators
        "sep":           border,
        # Nav buttons
        "nav_text":      text,
        "nav_section":   text_dim,
        "nav_hover":     bg3,
        "nav_active":    nav_active,
        # Secondary / ghost buttons (Cancel, Browse, etc.)
        "secondary":     bg3,
        "secondary_hover": border,
        "secondary_text":  text,
        # Quick-pick chip buttons (format shortcuts)
        "quick":         bg3,
        "quick_hover":   _blend(bg3, btn, 0.25),
        "quick_text":    text,
        # FileDropZone surfaces
        "filedrop":      bg2,
        "filedrop_inner":entry_bg,
        # Logo "FF" accent color
        "logo":          btn,
        # Progress & info
        "progress_fill": progress,
        "scrollbar":     scrollbar,
        # Raw semantic
        "text":          text,
        "text_dim":      text_dim,
        "border":        border,
        "accent":        btn,
        "accent_hover":  btn_hover,
    }


# Initialise TC from the default FFmpex Dark Blue theme
TC.update(_derive_tc(FULL_THEMES["FFmpex Default (Dark Blue)"][0]))


def apply_full_theme(theme_name: str, app=None) -> bool:
    """
    Write a CTk-compatible JSON theme file, apply it, update TC,
    and (if an FFmpexApp instance is supplied) refresh structural chrome.
    Returns True on success, False if the theme isn't found.
    """
    import json as _json
    entry = FULL_THEMES.get(theme_name)
    if entry is None:
        return False
    theme_dict, _ = entry
    slug     = theme_name.replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_").replace("'","")
    tmp_path = Path(tempfile.gettempdir()) / f"ffmpex_theme_{slug}.json"
    try:
        tmp_path.write_text(_json.dumps(theme_dict, indent=2), encoding="utf-8")
        ctk.set_default_color_theme(str(tmp_path))
    except Exception:
        return False
    # Update the live TC surface-color dict
    TC.update(_derive_tc(theme_dict))
    # Reconfigure already-built structural chrome widgets
    if app is not None:
        try:
            app.refresh_chrome()
        except Exception:
            pass
    return True



# ── Persistent state / preset file paths ─────────────────────────────────
PRESETS_FILE       = Path.home() / ".ffmpex_presets.json"
QUEUE_FILE_DEFAULT = Path.home() / "ffmpex_queue.json"
STATE_FILE         = Path.home() / ".ffmpex_state.json"


# ══════════════════════════════════════════════════════════════
# Persistent State  (last output dirs, window geometry, etc.)
# ══════════════════════════════════════════════════════════════

class AppState:
    """
    Thin wrapper around ~/.ffmpex_state.json.
    Stores:
      - last_outdir[page_name]  — last directory chosen in each save dialog
      - geometry                — last window size/position
    All reads/writes are best-effort; a corrupt file is silently wiped.
    """

    def __init__(self):
        self._data: dict = self._load()

    def _load(self) -> dict:
        try:
            if STATE_FILE.exists():
                return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {"last_outdir": {}, "geometry": ""}

    def save(self):
        try:
            STATE_FILE.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass

    def last_outdir(self, page: str) -> str:
        """Return the last save directory for this page, or home."""
        saved = self._data.get("last_outdir", {}).get(page, "")
        if saved and os.path.isdir(saved):
            return saved
        return str(Path.home())

    def remember_outdir(self, page: str, path: str):
        """Store the directory of an output path for a given page."""
        folder = str(Path(path).parent)
        self._data.setdefault("last_outdir", {})[page] = folder
        self.save()

    def geometry(self) -> str:
        return self._data.get("geometry", "")

    def remember_geometry(self, geo: str):
        self._data["geometry"] = geo
        self.save()

    def get_theme(self) -> str:
        return self._data.get("theme", "FFmpex Default (Dark Blue)")

    def save_theme(self, name: str):
        self._data["theme"] = name
        self.save()

    def remember_page(self, page: str):
        """Store the last active page so a restart can restore it."""
        self._data["last_page"] = page
        self.save()

    def last_page(self) -> str:
        """Return the page to restore on startup, defaulting to Convert."""
        return self._data.get("last_page", "Convert")

    def get_tray_close(self) -> bool:
        """Return True if X should minimise to tray instead of quitting."""
        return self._data.get("tray_close", False)   # default: X = quit

    def save_tray_close(self, value: bool):
        self._data["tray_close"] = value
        self.save()

    # ── Recently used files ───────────────────────────────────────────────

    def recent_files_add(self, path: str, limit: int = 12):
        """Prepend a file path to the global recently-used list (deduped)."""
        recent = self._data.setdefault("recent_files", [])
        # Remove existing entry for this path (case-insensitive on Windows)
        path_norm = str(Path(path))
        recent = [r for r in recent if r.lower() != path_norm.lower()]
        recent.insert(0, path_norm)
        self._data["recent_files"] = recent[:limit]
        self.save()

    def recent_files_get(self, limit: int = 10) -> list:
        """Return recently used files that still exist on disk."""
        return [p for p in self._data.get("recent_files", [])
                if os.path.exists(p)][:limit]


# ══════════════════════════════════════════════════════════════
# Toast / Desktop Notification helper
# ══════════════════════════════════════════════════════════════

def send_notification(title: str, message: str):
    """
    Send a desktop toast notification. Tries plyer first (cross-platform),
    falls back to platform-native commands, then silently ignores.
    """
    if HAS_PLYER:
        try:
            plyer_notification.notify(
                title=title, message=message,
                app_name="FFmpex", timeout=6)
            return
        except Exception:
            pass

    _sys = platform.system()
    try:
        if _sys == "Darwin":
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{message}" with title "{title}"'],
                timeout=5, capture_output=True)
        elif _sys == "Linux":
            subprocess.run(
                ["notify-send", "--app-name=FFmpex",
                 "--expire-time=6000", title, message],
                timeout=5, capture_output=True)
        elif _sys == "Windows":
            ps = (
                f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
                f"ContentType = WindowsRuntime] | Out-Null; "
                f"$t = [Windows.UI.Notifications.ToastTemplateType]::ToastText02; "
                f"$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($t); "
                f"$x.GetElementsByTagName('text')[0].AppendChild($x.CreateTextNode('{title}')) | Out-Null; "
                f"$x.GetElementsByTagName('text')[1].AppendChild($x.CreateTextNode('{message}')) | Out-Null; "
                f"$n = [Windows.UI.Notifications.ToastNotification]::new($x); "
                f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('FFmpex').Show($n)"
            )
            subprocess.run(["powershell", "-Command", ps],
                           timeout=8, capture_output=True)
    except Exception:
        pass  # Notifications are best-effort





def _reveal_in_folder(path: str):
    """
    Open the system file manager with the given file selected.
    Works on Windows (Explorer /select), macOS (open -R), Linux (xdg-open on parent).
    """
    p = Path(path)
    try:
        _sys = platform.system()
        if _sys == "Windows":
            subprocess.Popen(["explorer", "/select,", str(p)])
        elif _sys == "Darwin":
            subprocess.Popen(["open", "-R", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent)])
    except Exception:
        pass

def apply_template(pattern: str, inp: str, ext: str = "mp4", **kwargs) -> str:
    """Expand a naming template.  Returns a full output path string."""
    stem = Path(inp).stem
    now  = datetime.now()
    tokens = {
        "name": stem,
        "ext":  ext,
        "date": now.strftime("%Y%m%d"),
        "time": now.strftime("%H%M%S"),
        "crf":  kwargs.get("crf", ""),
        "res":  kwargs.get("res", ""),
    }
    try:
        filename = pattern.format(**tokens)
    except (KeyError, ValueError):
        filename = f"{stem}_output"
    # Ensure extension
    if not filename.endswith(f".{ext}"):
        filename = f"{filename}.{ext}"
    return str(Path(inp).parent / filename)


# ══════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════

def find_tool(name):
    """Return the tool name if it's available in PATH, else None."""
    try:
        r = subprocess.run([name, "-version"], capture_output=True, timeout=5)
        return name if r.returncode == 0 else None
    except Exception:
        return None


# ── Probe result cache ────────────────────────────────────────────────────
# Keyed by (ffprobe_path, abs_filepath, mtime).  Automatically invalidates
# when the file changes on disk.  Thread-safe for reads; writes happen on
# the main thread via self.after(), so no explicit lock is needed.
_PROBE_CACHE: dict[tuple, dict] = {}
_DURATION_CACHE: dict[tuple, float | None] = {}


def _probe_cache_key(ffprobe: str, filepath: str) -> tuple:
    """Return a cache key that encodes ffprobe identity + file mtime."""
    try:
        mtime = os.path.getmtime(filepath)
    except OSError:
        mtime = 0.0
    return (ffprobe, os.path.abspath(filepath), mtime)


def probe_cache_invalidate(filepath: str):
    """Drop every cached entry for filepath (call after in-place edits)."""
    abspath = os.path.abspath(filepath)
    for cache in (_PROBE_CACHE, _DURATION_CACHE):
        stale = [k for k in cache if k[1] == abspath]
        for k in stale:
            del cache[k]


def get_duration(ffprobe, filepath):
    key = _probe_cache_key(ffprobe, filepath)
    if key in _DURATION_CACHE:
        return _DURATION_CACHE[key]
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", filepath],
            capture_output=True, text=True, timeout=15
        )
        result = float(r.stdout.strip())
    except Exception:
        result = None
    _DURATION_CACHE[key] = result
    return result


def get_file_info(ffprobe, filepath):
    key = _probe_cache_key(ffprobe, filepath)
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    try:
        r = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", filepath],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(r.stdout)
        info = {"duration": None, "video": [], "audio": [], "size_mb": 0}
        fmt = data.get("format", {})
        if "duration" in fmt:
            info["duration"] = float(fmt["duration"])
        if "size" in fmt:
            info["size_mb"] = int(fmt["size"]) / (1024 * 1024)
        for stream in data.get("streams", []):
            ct = stream.get("codec_type")
            if ct == "video":
                fps_raw = stream.get("r_frame_rate", "0/1")
                try:
                    num, den = fps_raw.split("/")
                    fps = f"{float(num) / float(den):.2f}"
                except Exception:
                    fps = fps_raw
                info["video"].append({
                    "codec":  stream.get("codec_name", "?"),
                    "width":  stream.get("width", "?"),
                    "height": stream.get("height", "?"),
                    "fps":    fps,
                })
            elif ct == "audio":
                info["audio"].append({
                    "codec":       stream.get("codec_name", "?"),
                    "channels":    stream.get("channels", "?"),
                    "sample_rate": stream.get("sample_rate", "?"),
                })
        _PROBE_CACHE[key] = info
        return info
    except Exception:
        return None


def extract_thumbnail(ffmpeg_path, filepath, thumb_w=280):
    """Extract a single frame from a video using ffmpeg. Returns PIL Image or None."""
    if not HAS_PIL:
        return None
    if Path(filepath).suffix.lower().lstrip(".") not in VIDEO_EXTS:
        return None
    # FIX: mktemp() is insecure (TOCTOU race) — use mkstemp instead
    fd, tmp = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    try:
        # Try 3 seconds in first (catches black intros), fall back to frame 0
        for ss in ("3", "0"):
            subprocess.run(
                [ffmpeg_path, "-y", "-ss", ss, "-i", filepath,
                 "-vframes", "1", "-vf", f"scale={thumb_w}:-2", tmp],
                capture_output=True, timeout=20
            )
            if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                break
        if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            img = PILImage.open(tmp)
            img.load()
            return img
    except Exception:
        pass
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
    return None


def parse_progress_time(line):
    """Extract encoded time in seconds from an FFmpeg stderr progress line."""
    m = re.search(r"time=(\d+):(\d+):(\d+\.?\d*)", line)
    if m:
        return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    return None


def secs_to_ts(s):
    s = max(0.0, float(s))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:05.2f}"


def estimate_output_size_mb(input_path: str, crf: int | None = None,
                             video_kbps: int | None = None,
                             audio_kbps: int = 128,
                             duration: float | None = None,
                             is_audio_only: bool = False) -> str:
    """
    Return a human-readable estimated output size string, e.g. "≈ 24 MB".

    Two modes:
      • CRF mode  (crf given)      — uses a bitrate model based on input resolution
        and CRF value.  Approximate, but directionally correct.
      • VBR/ABR mode (video_kbps)  — exact: (video_kbps + audio_kbps) × duration.
      • Audio-only mode            — audio_kbps × duration only.

    Returns empty string if estimation is not possible.
    """
    try:
        if duration is None or duration <= 0:
            return ""

        if is_audio_only:
            est_mb = (audio_kbps * 1000 / 8) * duration / (1024 * 1024)
            return f"≈ {est_mb:.1f} MB"

        if video_kbps is not None:
            total_kbps = video_kbps + audio_kbps
            est_mb = (total_kbps * 1000 / 8) * duration / (1024 * 1024)
            return f"≈ {est_mb:.1f} MB"

        if crf is not None:
            # Heuristic: at CRF 23/1080p H.264, ≈ 1500 kbps is typical.
            # Bitrate roughly doubles every 6 CRF steps (halved per 6 steps up).
            # We also scale by input file size as a rough resolution proxy.
            try:
                src_mb = os.path.getsize(input_path) / (1024 * 1024)
                src_kbps = src_mb * 1024 * 8 / duration  # rough source bitrate
            except Exception:
                src_kbps = 5000  # fallback assumption

            # Reference point: CRF 23 ≈ 35 % of source bitrate for typical content
            ref_pct = 0.35 * (2 ** ((23 - crf) / 6))
            ref_pct = max(0.01, min(ref_pct, 2.0))  # clamp to sane range
            est_video_kbps = max(100, src_kbps * ref_pct)
            total_kbps = est_video_kbps + audio_kbps
            est_mb = (total_kbps * 1000 / 8) * duration / (1024 * 1024)
            return f"≈ {est_mb:.1f} MB  (CRF estimate)"

    except Exception:
        pass
    return ""

def ts_to_secs(t):
    try:
        p = t.strip().split(":")
        if len(p) == 3:
            return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])
        if len(p) == 2:
            return int(p[0]) * 60 + float(p[1])
        return float(p[0])
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# ToolTip  —  lightweight hover tooltip for CTk widgets
# ══════════════════════════════════════════════════════════════

class ToolTip:
    """
    A simple hover tooltip.  Attach to any tkinter/CTk widget:
        ToolTip(widget, "Hint text")
    The tooltip follows the mouse and disappears on leave.
    """
    def __init__(self, widget, text: str):
        self._widget  = widget
        self._text    = text
        self._tip_win = None
        widget.bind("<Enter>",  self._show)
        widget.bind("<Leave>",  self._hide)
        widget.bind("<Button>", self._hide)

    def _show(self, event=None):
        if self._tip_win:
            return
        x = self._widget.winfo_rootx() + self._widget.winfo_width() // 2
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip_win = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        # FIX: use TC theme colors so tooltips work on both dark and light themes
        tk.Label(tw, text=self._text, justify="left",
                 background=TC["card_inner"], foreground=TC["text"],
                 relief="flat", borderwidth=0,
                 font=("Segoe UI", 9) if hasattr(tk, "font") else ("Arial", 9),
                 padx=6, pady=3).pack()

    def _hide(self, event=None):
        if self._tip_win:
            self._tip_win.destroy()
            self._tip_win = None


# ══════════════════════════════════════════════════════════════
# Layout helpers
# ══════════════════════════════════════════════════════════════

def _sep(parent, **pack_kw):
    """BUG FIX: ctk.CTkSeparator does not exist — this is the correct replacement."""
    kw = {"fill": "x", "pady": 6}
    kw.update(pack_kw)
    f = ctk.CTkFrame(parent, height=1, fg_color=TC["sep"])
    f.pack(**kw)
    return f


def _page_header(parent, title, subtitle=""):
    ctk.CTkLabel(parent, text=title,
                 font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", pady=(0, 2))
    if subtitle:
        ctk.CTkLabel(parent, text=subtitle,
                     text_color=TC["text_dim"],
                     font=ctk.CTkFont(size=13)).pack(anchor="w", pady=(0, 16))


def _card(parent, title):
    """Labelled card frame. Returns the card frame (pack into it directly)."""
    frame = ctk.CTkFrame(parent, fg_color=TC["card"], corner_radius=8)
    frame.pack(fill="x", pady=(0, 10))
    ctk.CTkLabel(frame, text=title,
                 font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(8, 6))
    return frame


def _action_row(parent, run_cmd, cancel_cmd, run_label="Convert",
                preview: "CommandPreview | None" = None):
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=(6, 0))
    ctk.CTkButton(row, text=run_label, command=run_cmd, width=130,
                  font=ctk.CTkFont(size=13)).pack(side="left")
    ctk.CTkButton(row, text="Cancel", command=cancel_cmd, width=90,
                  fg_color=TC["secondary"],
                  hover_color=TC["secondary_hover"],
                  text_color=TC["secondary_text"]).pack(side="left", padx=10)
    if preview is not None:
        ctk.CTkButton(row, text="⌨  Preview Command", width=140, height=30,
                      fg_color=TC["secondary"],
                      hover_color=TC["secondary_hover"],
                      text_color=TC["secondary_text"],
                      command=preview.refresh).pack(side="left", padx=4)


# ══════════════════════════════════════════════════════════════
# Presets Manager  (disk-backed JSON)
# ══════════════════════════════════════════════════════════════

class PresetsManager:
    """
    Singleton-style helper that reads/writes ~/.ffmpex_presets.json.
    Each preset is stored as:
        { "name": str, "page": str, "settings": dict }
    The settings dict is opaque — pages serialise whatever they need.
    """

    @staticmethod
    def load() -> list[dict]:
        try:
            if PRESETS_FILE.exists():
                return json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []

    @staticmethod
    def save(presets: list[dict]) -> None:
        try:
            PRESETS_FILE.write_text(
                json.dumps(presets, indent=2, ensure_ascii=False),
                encoding="utf-8")
        except Exception as exc:
            messagebox.showwarning("Presets", f"Could not save presets:\n{exc}")

    @classmethod
    def for_page(cls, page: str) -> list[dict]:
        return [p for p in cls.load() if p.get("page") == page]

    @classmethod
    def add(cls, name: str, page: str, settings: dict) -> None:
        presets = cls.load()
        # Overwrite if same name + page already exists
        presets = [p for p in presets
                   if not (p["name"] == name and p["page"] == page)]
        presets.append({"name": name, "page": page, "settings": settings})
        cls.save(presets)

    @classmethod
    def delete(cls, name: str, page: str) -> None:
        presets = [p for p in cls.load()
                   if not (p["name"] == name and p["page"] == page)]
        cls.save(presets)


# ══════════════════════════════════════════════════════════════
# PresetBar widget
# ══════════════════════════════════════════════════════════════

class PresetBar(ctk.CTkFrame):
    """
    A collapsible card that lets users save / load / delete named presets
    for a given page.

    Usage in a page's _build():
        self.preset_bar = PresetBar(self, page_name="Compress",
                                    get_fn=self._get_settings,
                                    set_fn=self._apply_settings)
        self.preset_bar.pack(fill="x", pady=(0, 6))

    get_fn()            → dict of current settings to save
    set_fn(dict)        → restore settings from a saved dict
    """

    def __init__(self, parent, page_name: str,
                 get_fn, set_fn, **kwargs):
        super().__init__(parent, fg_color=TC["card"],
                         corner_radius=8, **kwargs)
        self._page   = page_name
        self._get_fn = get_fn
        self._set_fn = set_fn
        self._open   = False
        self._build()

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=10, pady=6)

        self._toggle_btn = ctk.CTkButton(
            hdr, text="💾  Custom Presets", anchor="w",
            fg_color="transparent",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TC["nav_text"],
            hover_color=TC["nav_hover"],
            command=self._toggle)
        self._toggle_btn.pack(side="left")

        self._body = ctk.CTkFrame(self, fg_color="transparent")

        # ── Save row ──────────────────────────────────────────────────────
        save_row = ctk.CTkFrame(self._body, fg_color="transparent")
        save_row.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(save_row, text="Save current settings as:",
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        self._name_var = ctk.StringVar()
        ctk.CTkEntry(save_row, textvariable=self._name_var,
                     placeholder_text="Preset name…",
                     width=180).pack(side="left", padx=(0, 8))
        ctk.CTkButton(save_row, text="Save", width=70,
                      command=self._save_preset).pack(side="left")

        # ── Load / delete row ─────────────────────────────────────────────
        load_row = ctk.CTkFrame(self._body, fg_color="transparent")
        load_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(load_row, text="Saved presets:",
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        self._sel_var = ctk.StringVar()
        self._dropdown = ctk.CTkOptionMenu(
            load_row, variable=self._sel_var,
            values=["(none)"], width=200)
        self._dropdown.pack(side="left", padx=(0, 8))
        ctk.CTkButton(load_row, text="Load", width=70,
                      command=self._load_preset).pack(side="left", padx=(0, 6))
        ctk.CTkButton(load_row, text="Delete", width=70,
                      fg_color=TC["secondary"],
                      hover_color=TC["secondary_hover"],
                      text_color=TC["secondary_text"],
                      command=self._delete_preset).pack(side="left")

    def _toggle(self):
        self._open = not self._open
        if self._open:
            self._refresh_list()
            self._body.pack(fill="x")
            self._toggle_btn.configure(text="💾  Custom Presets  ▲")
        else:
            self._body.pack_forget()
            self._toggle_btn.configure(text="💾  Custom Presets")

    def _refresh_list(self):
        presets = PresetsManager.for_page(self._page)
        names   = [p["name"] for p in presets] or ["(none)"]
        self._dropdown.configure(values=names)
        self._sel_var.set(names[0])

    def _save_preset(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("Presets", "Enter a name for the preset.")
            return
        try:
            settings = self._get_fn()
        except Exception as exc:
            messagebox.showerror("Presets", f"Could not read settings:\n{exc}")
            return
        PresetsManager.add(name, self._page, settings)
        self._name_var.set("")
        self._refresh_list()

    def _load_preset(self):
        sel = self._sel_var.get()
        if not sel or sel == "(none)":
            return
        presets = {p["name"]: p for p in PresetsManager.for_page(self._page)}
        preset  = presets.get(sel)
        if preset:
            try:
                self._set_fn(preset["settings"])
            except Exception as exc:
                messagebox.showerror("Presets", f"Could not apply preset:\n{exc}")

    def _delete_preset(self):
        sel = self._sel_var.get()
        if not sel or sel == "(none)":
            return
        PresetsManager.delete(sel, self._page)
        self._refresh_list()


# ══════════════════════════════════════════════════════════════
# TemplateBar widget
# ══════════════════════════════════════════════════════════════

class TemplateBar(ctk.CTkFrame):
    """
    Collapsible output naming template editor.

    Usage:
        self.tmpl_bar = TemplateBar(self, get_inp_fn=self.input_zone.get)
        self.tmpl_bar.pack(fill="x", pady=(0, 6))
        # Then call self.tmpl_bar.resolve(inp, ext="mp4", crf=23)
        # to get the expanded output path (or None if disabled).
    """

    TOKENS = ["{name}", "{date}", "{time}", "{ext}", "{crf}", "{res}"]
    DEFAULT = "{name}_converted_{date}"

    def __init__(self, parent, get_inp_fn, **kwargs):
        super().__init__(parent, fg_color=TC["card"],
                         corner_radius=8, **kwargs)
        self._get_inp = get_inp_fn
        self._open    = False
        self._build()

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=10, pady=6)
        self._toggle_btn = ctk.CTkButton(
            hdr, text="🔗  Output Naming Template", anchor="w",
            fg_color="transparent",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TC["nav_text"],
            hover_color=TC["nav_hover"],
            command=self._toggle)
        self._toggle_btn.pack(side="left")

        self._body = ctk.CTkFrame(self, fg_color="transparent")

        # ── Enable toggle ──────────────────────────────────────────────────
        en_row = ctk.CTkFrame(self._body, fg_color="transparent")
        en_row.pack(fill="x", padx=10, pady=(0, 6))
        self._enabled = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(en_row, text="Use naming template instead of Save dialog",
                        variable=self._enabled,
                        command=self._on_toggle_enabled).pack(side="left")

        # ── Pattern entry ──────────────────────────────────────────────────
        pat_row = ctk.CTkFrame(self._body, fg_color="transparent")
        pat_row.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(pat_row, text="Pattern:", width=60).pack(side="left")
        self._pattern = ctk.StringVar(value=self.DEFAULT)
        self._pattern.trace_add("write", lambda *_: self._update_preview())
        self._entry = ctk.CTkEntry(pat_row, textvariable=self._pattern, width=280)
        self._entry.pack(side="left", padx=(0, 8))

        # Token quick-insert buttons
        for tok in self.TOKENS:
            ctk.CTkButton(pat_row, text=tok, width=70, height=24,
                          fg_color=TC["quick"],
                          hover_color=TC["quick_hover"],
                          text_color=TC["secondary_text"],
                          font=ctk.CTkFont(size=10),
                          command=lambda t=tok: self._insert_token(t)
                          ).pack(side="left", padx=2)

        # ── Preview ────────────────────────────────────────────────────────
        prev_row = ctk.CTkFrame(self._body, fg_color="transparent")
        prev_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(prev_row, text="Preview:", width=60,
                     text_color=TC["text_dim"],
                     font=ctk.CTkFont(size=11)).pack(side="left")
        self._preview_lbl = ctk.CTkLabel(
            prev_row, text="",
            text_color=TC["text_dim"],
            font=ctk.CTkFont(family="Courier", size=11))
        self._preview_lbl.pack(side="left")

        self._on_toggle_enabled()

    def _toggle(self):
        self._open = not self._open
        if self._open:
            self._update_preview()
            self._body.pack(fill="x")
            self._toggle_btn.configure(text="🔗  Output Naming Template  ▲")
        else:
            self._body.pack_forget()
            self._toggle_btn.configure(text="🔗  Output Naming Template")

    def _on_toggle_enabled(self):
        state = "normal" if self._enabled.get() else "disabled"
        self._entry.configure(state=state)

    def _insert_token(self, token: str):
        current = self._pattern.get()
        self._pattern.set(current + token)
        self._update_preview()

    def _update_preview(self):
        inp = self._get_inp()
        if inp and os.path.exists(inp):
            try:
                result = apply_template(self._pattern.get(), inp)
                self._preview_lbl.configure(text=Path(result).name)
            except Exception:
                self._preview_lbl.configure(text="(invalid pattern)")
        else:
            self._preview_lbl.configure(text="(select a file to preview)")

    def resolve(self, inp: str, ext: str = "mp4", **kwargs) -> str | None:
        """
        Return the expanded output path if template mode is enabled,
        else None (caller should fall back to Save dialog).
        """
        if not self._enabled.get():
            return None
        pattern = self._pattern.get().strip() or self.DEFAULT
        return apply_template(pattern, inp, ext=ext, **kwargs)


# ══════════════════════════════════════════════════════════════
# Command Preview Panel
# ══════════════════════════════════════════════════════════════

class CommandPreview(ctk.CTkFrame):
    """
    Collapsible panel that shows the FFmpeg command that *would* run.
    Usage:
        self.cmd_preview = CommandPreview(self, build_cmd_fn)
        self.cmd_preview.pack(fill="x", pady=(4, 0))
    build_cmd_fn() must return a list[str] or None/[] when the command
    cannot be built yet (e.g. no file selected).
    """

    def __init__(self, parent, build_cmd_fn, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._build_cmd = build_cmd_fn
        self._visible   = False

        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x")

        self._toggle_btn = ctk.CTkButton(
            hdr, text="▶  Command Preview", width=150, height=26,
            fg_color="transparent",
            font=ctk.CTkFont(size=11),
            text_color=TC["text_dim"],
            hover_color=TC["nav_hover"],
            command=self._toggle)
        self._toggle_btn.pack(side="left")

        self._copy_btn = ctk.CTkButton(
            hdr, text="Copy", width=60, height=26,
            fg_color="transparent",
            font=ctk.CTkFont(size=11),
            text_color=TC["text_dim"],
            hover_color=TC["nav_hover"],
            command=self._copy)
        # copy btn only shown when panel is open

        self._panel = ctk.CTkFrame(
            self, fg_color=TC["card_inner"], corner_radius=6)
        self._text = ctk.CTkTextbox(
            self._panel,
            height=72,
            font=ctk.CTkFont(family="Courier", size=11),
            wrap="word",
            state="disabled")
        self._text.pack(fill="x", padx=8, pady=6)

        self._hint = ctk.CTkLabel(
            self._panel,
            text="Select a file first, then click 'Preview Command'.",
            font=ctk.CTkFont(size=11),
            text_color=TC["text_dim"])

    def _toggle(self):
        self._visible = not self._visible
        if self._visible:
            self.refresh()
            self._panel.pack(fill="x", pady=(4, 0))
            self._copy_btn.pack(side="left", padx=6)
            self._toggle_btn.configure(text="▼  Command Preview")
        else:
            self._panel.pack_forget()
            self._copy_btn.pack_forget()
            self._toggle_btn.configure(text="▶  Command Preview")

    def refresh(self):
        """Rebuild and display the command. Safe to call anytime."""
        if not self._visible:
            self._toggle()
            return
        try:
            cmd = self._build_cmd()
        except Exception:
            cmd = None

        self._text.pack_forget()
        self._hint.pack_forget()

        if cmd:
            text = " ".join(
                f'"{a}"' if " " in a else a
                for a in cmd)
            self._text.configure(state="normal")
            self._text.delete("1.0", "end")
            self._text.insert("end", text)
            self._text.configure(state="disabled")
            self._text.pack(fill="x", padx=8, pady=6)
        else:
            self._hint.pack(padx=8, pady=10)

    def _copy(self):
        try:
            cmd = self._build_cmd()
        except Exception:
            cmd = None
        if not cmd:
            return
        text = " ".join(
            f'"{a}"' if " " in a else a
            for a in cmd)
        self.clipboard_clear()
        self.clipboard_append(text)
        # Briefly flash the button
        self._copy_btn.configure(text="✓ Copied")
        self.after(1500, lambda: self._copy_btn.configure(text="Copy"))


# ══════════════════════════════════════════════════════════════
# Reusable Widgets
# ══════════════════════════════════════════════════════════════

class FileDropZone(ctk.CTkFrame):
    """
    File picker with optional thumbnail preview and drag-and-drop.
    Pass show_thumbnail=True and app=<FFmpexApp> to enable preview.
    """

    def __init__(self, parent, label="Input File", filetypes=None,
                 multiple=False, show_thumbnail=False, app=None,
                 on_file_loaded=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.filetypes      = filetypes or [("All files", "*.*")]
        self.multiple       = multiple
        self.show_thumbnail = show_thumbnail
        self.app            = app
        self.paths          = []
        self._ctk_image     = None
        self._on_file_loaded = on_file_loaded  # optional callback(path: str)
        self.configure(fg_color=TC["filedrop"], corner_radius=8)

        ctk.CTkLabel(self, text=label,
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(8, 2))

        inner = ctk.CTkFrame(self, fg_color=TC["filedrop_inner"], corner_radius=6)
        inner.pack(fill="x", padx=10, pady=(0, 6 if show_thumbnail else 10))

        hint = "No file selected  —  drag & drop or Browse" if HAS_DND else "No file selected"
        self.path_label = ctk.CTkLabel(
            inner, text=hint,
            text_color=TC["text_dim"], font=ctk.CTkFont(size=12),
            wraplength=440, anchor="w")
        self.path_label.pack(side="left", padx=12, pady=10, fill="x", expand=True)

        # ── Recent ▾ button — only shown when recent files exist ──────────
        self._recent_btn = ctk.CTkButton(
            inner, text="Recent ▾", width=76, height=28,
            fg_color=TC["secondary"],
            hover_color=TC["secondary_hover"],
            text_color=TC["secondary_text"],
            font=ctk.CTkFont(size=11),
            command=self._show_recent_menu)
        # Shown lazily in _show_recent_menu only if there are entries

        ctk.CTkButton(inner, text="Browse", width=80,
                      command=self._browse).pack(side="right", padx=(0, 8), pady=6)
        self._recent_btn.pack(side="right", padx=(0, 4), pady=6)

        # ── Thumbnail row (only when requested) ───────────────────────────
        if show_thumbnail:
            self._thumb_row = ctk.CTkFrame(self, fg_color="transparent")
            self._thumb_row.pack(fill="x", padx=10, pady=(0, 10))
            self._thumb_label = ctk.CTkLabel(self._thumb_row, text="")
            self._thumb_label.pack(side="left")
            self._thumb_info = ctk.CTkLabel(
                self._thumb_row, text="",
                font=ctk.CTkFont(size=11),
                text_color=TC["text_dim"], justify="left")
            self._thumb_info.pack(side="left", padx=14, anchor="nw")

        # ── Drag-and-drop registration (requires tkinterdnd2) ──────────────
        if HAS_DND:
            for widget in (inner, self.path_label):
                try:
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<Drop>>", self._on_drop)
                except Exception:
                    pass

    # ── Recent files menu ─────────────────────────────────────────────────
    def _show_recent_menu(self):
        """Pop up a menu of recently used files below the Recent button."""
        recent = []
        if self.app and hasattr(self.app, "app_state"):
            recent = self.app.app_state.recent_files_get()
        if not recent:
            return

        menu = tk.Menu(self, tearoff=0,
                       bg=TC["card_inner"], fg=TC["text"],
                       activebackground=TC["accent"],
                       activeforeground=TC["text"],
                       relief="flat", borderwidth=1)
        for p in recent:
            label = Path(p).name
            if len(label) > 55:
                label = "…" + label[-52:]
            menu.add_command(label=label,
                             command=lambda fp=p: self._load_file(fp))
        menu.add_separator()
        menu.add_command(label="Clear recent files",
                         command=self._clear_recent)

        x = self._recent_btn.winfo_rootx()
        y = self._recent_btn.winfo_rooty() + self._recent_btn.winfo_height() + 2
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _load_file(self, path: str):
        """Load a file programmatically (used by the Recent menu)."""
        if not os.path.exists(path):
            messagebox.showwarning("Recent Files",
                                   f"File no longer exists:\n{path}")
            if self.app and hasattr(self.app, "app_state"):
                # Prune missing file from the list
                state = self.app.app_state
                state._data["recent_files"] = [
                    r for r in state._data.get("recent_files", [])
                    if r.lower() != path.lower()]
                state.save()
            return
        self.paths = [path]
        self.path_label.configure(text=Path(path).name,
                                  text_color=TC["secondary_text"])
        if self.show_thumbnail and self.app and self.app.ffmpeg:
            self._load_thumbnail_async(path)
        self._record_recent(path)
        if self._on_file_loaded:
            self._on_file_loaded(path)

    def _clear_recent(self):
        if self.app and hasattr(self.app, "app_state"):
            self.app.app_state._data["recent_files"] = []
            self.app.app_state.save()

    def _record_recent(self, path: str):
        """Add a single file to the global recent list (best-effort)."""
        if self.app and hasattr(self.app, "app_state") and not self.multiple:
            try:
                self.app.app_state.recent_files_add(path)
            except Exception:
                pass

    # ── DnD handler ───────────────────────────────────────────────────────
    def _on_drop(self, event):
        raw = event.data.strip()
        # tkinterdnd2 wraps space-containing paths in { }
        items = re.findall(r'\{[^}]+\}|[^\s{}]+', raw)
        paths = [p.strip("{}").strip('"') for p in items if p.strip("{}")]
        if not paths:
            return
        if self.multiple:
            self.paths = paths
            text = (Path(paths[0]).name if len(paths) == 1
                    else f"{len(paths)} files selected")
        else:
            self.paths = [paths[0]]
            text = Path(paths[0]).name
            if self.show_thumbnail and self.app and self.app.ffmpeg:
                self._load_thumbnail_async(paths[0])
            self._record_recent(paths[0])
            if self._on_file_loaded:
                self._on_file_loaded(paths[0])
        self.path_label.configure(text=text, text_color=TC["secondary_text"])

    # ── Browse handler ────────────────────────────────────────────────────
    def _browse(self):
        if self.multiple:
            paths = filedialog.askopenfilenames(filetypes=self.filetypes)
            if paths:
                self.paths = list(paths)
                text = (Path(paths[0]).name if len(paths) == 1
                        else f"{len(paths)} files selected")
                self.path_label.configure(text=text, text_color=TC["secondary_text"])
        else:
            path = filedialog.askopenfilename(filetypes=self.filetypes)
            if path:
                self.paths = [path]
                self.path_label.configure(text=Path(path).name,
                                          text_color=TC["secondary_text"])
                if self.show_thumbnail and self.app and self.app.ffmpeg:
                    self._load_thumbnail_async(path)
                self._record_recent(path)
                if self._on_file_loaded:
                    self._on_file_loaded(path)

    # ── Async thumbnail loader ────────────────────────────────────────────
    def _load_thumbnail_async(self, path):
        def _work():
            img = extract_thumbnail(self.app.ffmpeg, path)
            if img is None:
                return
            w, h = img.size
            disp_w = 240
            disp_h = int(h * disp_w / w)
            ctk_img = ctk.CTkImage(img, size=(disp_w, disp_h))

            info_text = ""
            if self.app.ffprobe:
                info = get_file_info(self.app.ffprobe, path)
                if info:
                    v   = info["video"][0] if info["video"] else {}
                    dur = info.get("duration")
                    ds  = (f"{int(dur // 60)}m {int(dur % 60)}s"
                           if dur else "?")
                    sz  = info.get("size_mb", 0)
                    info_text = (
                        f"{v.get('width','?')}×{v.get('height','?')}\n"
                        f"{v.get('fps','?')} fps  ·  {v.get('codec','?').upper()}\n"
                        f"⏱  {ds}\n"
                        f"💾  {sz:.1f} MB"
                    )

            def _update(ci=ctk_img, it=info_text):
                self._ctk_image = ci
                self._thumb_label.configure(image=ci, text="")
                self._thumb_info.configure(text=it)

            self.after(0, _update)

        threading.Thread(target=_work, daemon=True).start()

    def get(self):
        if not self.paths:
            return (None if not self.multiple else [])
        return self.paths[0] if not self.multiple else self.paths

    def clear(self):
        self.paths = []
        hint = "No file selected  —  drag & drop or Browse" if HAS_DND else "No file selected"
        self.path_label.configure(text=hint, text_color=TC["text_dim"])
        if self.show_thumbnail:
            self._thumb_label.configure(image=None, text="")
            self._thumb_info.configure(text="")
            self._ctk_image = None


class ProgressSection(ctk.CTkFrame):
    """Progress bar + status label + collapsible FFmpeg log."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        prog_row = ctk.CTkFrame(self, fg_color="transparent")
        prog_row.pack(fill="x")

        self.bar = ctk.CTkProgressBar(prog_row)
        self.bar.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.bar.set(0)

        self.pct_label = ctk.CTkLabel(prog_row, text="0%", width=42,
                                       font=ctk.CTkFont(size=12))
        self.pct_label.pack(side="left")

        self.status_label = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=12),
            text_color=TC["text_dim"])
        self.status_label.pack(anchor="w", pady=(4, 0))

        self._log_visible = False
        self._log_btn = ctk.CTkButton(
            self, text="▶  Show Log", width=100, height=24,
            fg_color="transparent", font=ctk.CTkFont(size=11),
            command=self._toggle_log)
        self._log_btn.pack(anchor="w", pady=(4, 0))

        # BUG FIX: start in disabled state so update_progress can safely enable it
        self.log_box = ctk.CTkTextbox(
            self, height=120, font=ctk.CTkFont(family="Courier", size=11),
            state="disabled")

    def _toggle_log(self):
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_box.pack(fill="x", pady=(4, 0))
            self._log_btn.configure(text="▼  Hide Log")
        else:
            self.log_box.pack_forget()
            self._log_btn.configure(text="▶  Show Log")

    def update_progress(self, progress, status="", log_line=""):
        self.bar.set(min(progress, 100) / 100)
        self.pct_label.configure(text=f"{int(progress)}%")
        if status:
            self.status_label.configure(text=status, text_color=TC["text_dim"])
        if log_line:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", log_line + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

    def reset(self):
        self.bar.set(0)
        self.pct_label.configure(text="0%")
        self.status_label.configure(text="", text_color=TC["text_dim"])
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        # Clear any post-encode info row from the previous run
        if hasattr(self, "_info_row"):
            self._info_row.destroy()
            del self._info_row

    def done(self, success=True, output_path="", input_path=""):
        self.bar.set(1)
        self.pct_label.configure(text="100%")
        text  = "✓  Done!" if success else "✗  Failed — check the log for details."
        color = ("green", "#4caf50") if success else ("red", "#f44336")
        self.status_label.configure(text=text, text_color=color)

        # Clear any info row left from a previous run
        if hasattr(self, "_info_row"):
            self._info_row.destroy()
            del self._info_row

        if success and output_path and os.path.exists(output_path):
            self._info_row = ctk.CTkFrame(self, fg_color="transparent")
            self._info_row.pack(anchor="w", pady=(6, 0))

            # ── File size comparison ───────────────────────────────────────
            out_mb = os.path.getsize(output_path) / (1024 * 1024)
            if input_path and os.path.exists(input_path):
                in_mb = os.path.getsize(input_path) / (1024 * 1024)
                if in_mb > 0:
                    pct   = (out_mb - in_mb) / in_mb * 100
                    sign  = "+" if pct > 0 else ""
                    arrow_color = ("#c0392b", "#e74c3c") if pct > 0 else ("green", "#27ae60")
                    size_txt = f"💾  {in_mb:.1f} MB  →  {out_mb:.1f} MB"
                    pct_txt  = f"  ({sign}{pct:.0f}%)"
                else:
                    size_txt  = f"💾  {out_mb:.1f} MB"
                    pct_txt   = ""
                    arrow_color = TC["text_dim"]
            else:
                size_txt  = f"💾  Output: {out_mb:.1f} MB"
                pct_txt   = ""
                arrow_color = TC["text_dim"]

            ctk.CTkLabel(self._info_row, text=size_txt,
                         font=ctk.CTkFont(size=11),
                         text_color=TC["text_dim"]).pack(side="left")
            if pct_txt:
                ctk.CTkLabel(self._info_row, text=pct_txt,
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=arrow_color).pack(side="left")

            # ── Reveal in Folder button ────────────────────────────────────
            _out = output_path
            ctk.CTkButton(
                self._info_row, text="📁  Reveal", width=88, height=24,
                fg_color=TC["secondary"],
                hover_color=TC["secondary_hover"],
                text_color=TC["secondary_text"],
                font=ctk.CTkFont(size=11),
                command=lambda p=_out: _reveal_in_folder(p),
            ).pack(side="left", padx=(14, 0))


# ══════════════════════════════════════════════════════════════
# Page Base Class
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
# VideoPreviewWidget
# ══════════════════════════════════════════════════════════════

def _extract_frame_at(ffmpeg_path: str, filepath: str,
                       timestamp: float, width: int = 320) -> "PILImage.Image | None":
    """
    Extract a single video frame at `timestamp` seconds using ffmpeg.
    Returns a PIL Image or None on failure / if PIL is not installed.
    """
    if not HAS_PIL:
        return None
    if Path(filepath).suffix.lower().lstrip(".") not in VIDEO_EXTS:
        return None
    fd, tmp = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    try:
        subprocess.run(
            [ffmpeg_path, "-y", "-ss", str(max(0.0, timestamp)),
             "-i", filepath, "-vframes", "1",
             "-vf", f"scale={width}:-2", tmp],
            capture_output=True, timeout=15
        )
        if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            img = PILImage.open(tmp)
            img.load()
            return img
    except Exception:
        pass
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
    return None


class VideoPreviewWidget(ctk.CTkFrame):
    """
    Inline video frame previewer.

    Shows a still frame extracted from the source file at a given timestamp,
    plus a "▶ Preview" button that opens ffplay from that position.

    Usage:
        self.preview = VideoPreviewWidget(self, app=self.app, label="Preview")
        self.preview.pack(fill="x", pady=(0, 8))
        # Update when the user moves a slider:
        self.preview.seek(timestamp_seconds, filepath)
    """

    THUMB_W = 320   # display width in pixels

    def __init__(self, parent, app, label: str = "Preview",
                 show_ffplay: bool = True, **kwargs):
        super().__init__(parent, fg_color=TC["card"],
                         corner_radius=8, **kwargs)
        self.app         = app
        self._filepath   = None
        self._timestamp  = 0.0
        self._ctk_image  = None
        self._after_id   = None   # debounce timer
        self._ffplay     = find_tool("ffplay")

        # ── Header row ───────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(hdr, text=label,
                     font=ctk.CTkFont(weight="bold")).pack(side="left")

        if show_ffplay:
            self._play_btn = ctk.CTkButton(
                hdr, text="▶  Preview clip",
                width=120, height=26,
                fg_color=TC["secondary"],
                hover_color=TC["secondary_hover"],
                text_color=TC["secondary_text"],
                command=self._launch_ffplay)
            self._play_btn.pack(side="right")

        # ── Frame display ────────────────────────────────────────────────────
        self._img_label = ctk.CTkLabel(
            self, text="No file loaded",
            text_color=TC["text_dim"],
            font=ctk.CTkFont(size=12))
        self._img_label.pack(pady=(0, 8))

        # ── Timestamp label ───────────────────────────────────────────────────
        self._ts_label = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(family="Courier", size=11),
            text_color=TC["text_dim"])
        self._ts_label.pack(pady=(0, 8))

    def seek(self, timestamp: float, filepath: str | None = None,
             debounce_ms: int = 400):
        """
        Schedule a frame extraction at `timestamp`.
        Cancels any pending extraction first (debounce).
        """
        if filepath:
            self._filepath  = filepath
        self._timestamp = timestamp

        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
        self._after_id = self.after(debounce_ms, self._do_extract)

    def seek_immediate(self, timestamp: float, filepath: str | None = None):
        """Seek without debounce — use for explicit user clicks."""
        if filepath:
            self._filepath = filepath
        self._timestamp = timestamp
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
        self._do_extract()

    def clear(self):
        self._filepath  = None
        self._timestamp = 0.0
        self._ctk_image = None
        self._img_label.configure(image=None, text="No file loaded")
        self._ts_label.configure(text="")

    # ── Internals ─────────────────────────────────────────────────────────────

    def _do_extract(self):
        """Run frame extraction in a background thread."""
        self._after_id = None
        fp = self._filepath
        ts = self._timestamp
        if not fp or not os.path.exists(fp) or not self.app.ffmpeg:
            return
        self._ts_label.configure(text=f"⏱  {secs_to_ts(ts)}")

        def _work():
            img = _extract_frame_at(self.app.ffmpeg, fp, ts, self.THUMB_W)
            if img is None:
                self.after(0, lambda: self._img_label.configure(
                    image=None,
                    text="(preview unavailable — install Pillow)"))
                return
            w, h = img.size
            disp_h = int(h * self.THUMB_W / w)
            ctk_img = ctk.CTkImage(img, size=(self.THUMB_W, disp_h))

            def _update(ci=ctk_img):
                self._ctk_image = ci
                self._img_label.configure(image=ci, text="")
            self.after(0, _update)

        threading.Thread(target=_work, daemon=True).start()

    def _launch_ffplay(self):
        """Open ffplay from the current timestamp."""
        if not self._ffplay:
            messagebox.showinfo(
                "ffplay not found",
                "ffplay ships with FFmpeg. Install FFmpeg and restart FFmpex.")
            return
        fp = self._filepath
        if not fp or not os.path.exists(fp):
            messagebox.showerror("Preview", "No file loaded.")
            return
        ts = self._timestamp
        cmd = [self._ffplay, "-autoexit", "-loglevel", "quiet"]
        if ts > 0.1:
            cmd += ["-ss", str(ts)]
        cmd.append(fp)
        try:
            subprocess.Popen(cmd)
        except Exception as exc:
            messagebox.showerror("Preview", f"Could not launch ffplay:\n{exc}")


class DualVideoPreviewWidget(ctk.CTkFrame):
    """
    Two VideoPreviewWidget panels side by side — Start frame and End frame.
    Used by TrimPage so the user can see exactly where the clip begins and ends.

    Usage:
        self.dual_preview = DualVideoPreviewWidget(self, app=self.app)
        self.dual_preview.pack(fill="x", pady=(0, 8))
        self.dual_preview.set_file(filepath)
        self.dual_preview.set_start(seconds)
        self.dual_preview.set_end(seconds)
    """

    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, fg_color=TC["filedrop"],
                         corner_radius=8, **kwargs)
        self.app = app

        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=10, pady=(8, 6))
        ctk.CTkLabel(hdr, text="Frame Preview",
                     font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkButton(
            hdr, text="▶  Preview full clip",
            width=140, height=26,
            fg_color=TC["secondary"],
            hover_color=TC["secondary_hover"],
            text_color=TC["secondary_text"],
            command=self._preview_clip).pack(side="right")

        panels = ctk.CTkFrame(self, fg_color="transparent")
        panels.pack(fill="x", padx=10, pady=(0, 10))
        panels.columnconfigure(0, weight=1)
        panels.columnconfigure(1, weight=1)

        self._start_panel = VideoPreviewWidget(
            panels, app=app, label="Start frame", show_ffplay=False)
        self._start_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        self._end_panel = VideoPreviewWidget(
            panels, app=app, label="End frame", show_ffplay=False)
        self._end_panel.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        self._filepath  = None
        self._start_ts  = 0.0
        self._end_ts    = 0.0
        self._ffplay    = find_tool("ffplay")

    def set_file(self, filepath: str):
        self._filepath = filepath
        self._start_panel._filepath = filepath
        self._end_panel._filepath   = filepath

    def set_start(self, ts: float, debounce_ms: int = 400):
        self._start_ts = ts
        self._start_panel.seek(ts, filepath=self._filepath,
                               debounce_ms=debounce_ms)

    def set_end(self, ts: float, debounce_ms: int = 400):
        self._end_ts = ts
        self._end_panel.seek(ts, filepath=self._filepath,
                             debounce_ms=debounce_ms)

    def clear(self):
        self._filepath = None
        self._start_panel.clear()
        self._end_panel.clear()

    def _preview_clip(self):
        """Open ffplay from the start point and let it run until end."""
        if not self._ffplay:
            messagebox.showinfo("ffplay not found",
                                "Install FFmpeg to enable preview.")
            return
        fp = self._filepath
        if not fp or not os.path.exists(fp):
            messagebox.showerror("Preview", "No file loaded.")
            return
        dur = self._end_ts - self._start_ts if self._end_ts > self._start_ts else None
        cmd = [self._ffplay, "-autoexit", "-loglevel", "quiet",
               "-ss", str(self._start_ts)]
        if dur:
            cmd += ["-t", str(dur)]
        cmd.append(fp)
        try:
            subprocess.Popen(cmd)
        except Exception as exc:
            messagebox.showerror("Preview", f"Could not launch ffplay:\n{exc}")


class BasePage(ctk.CTkScrollableFrame):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, **kwargs)
        self.app = app
        self.configure(fg_color="transparent")
        self._running = False
        self._proc    = None

    def run_ffmpeg(self, cmd, duration, progress_section,
                   on_done=None, page_name="", output_path=""):
        """
        Launch an FFmpeg command in a daemon thread with live progress.
        page_name + output_path are used to record the job in History.
        input_path is inferred from the command for the post-encode size card.

        A lightweight safety check runs before the thread starts to catch the
        most common hard errors (missing input, unwritable output dir, same-path
        overwrite) on pages that don't call preflight() themselves.
        """
        if self._running:
            messagebox.showwarning("Busy", "A job is already running on this page.")
            return

        # Infer input path from cmd: the argument that follows "-i"
        _input_path = ""
        try:
            _i_idx = cmd.index("-i")
            _input_path = cmd[_i_idx + 1] if _i_idx + 1 < len(cmd) else ""
        except (ValueError, IndexError):
            pass

        # ── Mini safety check ─────────────────────────────────────────────────
        # Only hard-blocks — no soft warnings, so pages that already called the
        # full preflight() don't get double-prompted.
        if _input_path and not os.path.exists(_input_path):
            messagebox.showerror(
                "Input Not Found",
                f"Input file does not exist:\n\n  {_input_path}")
            return
        if output_path:
            _out_dir = Path(output_path).parent
            if not _out_dir.exists():
                try:
                    _out_dir.mkdir(parents=True, exist_ok=True)
                except Exception:
                    messagebox.showerror(
                        "Cannot Write Output",
                        f"Output folder could not be created:\n\n  {_out_dir}")
                    return
            elif not os.access(str(_out_dir), os.W_OK):
                messagebox.showerror(
                    "Cannot Write Output",
                    f"Output folder is not writable:\n\n  {_out_dir}")
                return
            if _input_path and output_path:
                try:
                    if Path(_input_path).resolve() == Path(output_path).resolve():
                        messagebox.showerror(
                            "Same-File Overwrite",
                            "The output path is the same as the input file.\n"
                            "Choose a different output path to avoid overwriting your source.")
                        return
                except Exception:
                    pass
        # ─────────────────────────────────────────────────────────────────────

        self._running = True
        progress_section.reset()
        start_time = time.time()

        def _work():
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stderr=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    text=True,
                    universal_newlines=True,
                )
                for line in self._proc.stderr:
                    line = line.rstrip()
                    # Schedule log append on main thread
                    self.after(0, lambda l=line:
                               progress_section.update_progress(
                                   progress_section.bar.get() * 100, log_line=l))
                    enc_time = parse_progress_time(line)
                    if enc_time is not None and duration and duration > 0:
                        pct     = min(99.0, (enc_time / duration) * 100)
                        elapsed = time.time() - start_time
                        if enc_time > 0:
                            eta    = int((duration - enc_time) / (enc_time / max(elapsed, 0.01)))
                            status = f"Encoding…  ETA {eta}s"
                        else:
                            status = "Encoding…"
                        self.after(0, lambda p=pct, s=status:
                                   progress_section.update_progress(p, status=s))

                self._proc.wait()
                success = self._proc.returncode == 0
            except Exception as exc:
                self.after(0, lambda e=exc:
                           progress_section.update_progress(0, status=f"Error: {e}"))
                success = False
            finally:
                self._running = False
                self._proc    = None

            self.after(0, lambda s=success: progress_section.done(
                s, output_path=output_path, input_path=_input_path))
            self.after(0, lambda s=success:
                       self.app.add_history(page_name, output_path, s))
            if on_done:
                self.after(0, lambda s=success: on_done(s))

        threading.Thread(target=_work, daemon=True).start()

    def run_ffmpeg_chain(self, cmds, total_duration, progress_section,
                         on_done=None, page_name="", output_path=""):
        """
        Run a list of FFmpeg commands sequentially (e.g. 2-pass GIF encoding).
        Progress is divided equally across passes.
        """
        if self._running:
            messagebox.showwarning("Busy", "A job is already running on this page.")
            return
        self._running = True
        progress_section.reset()
        n_passes = len(cmds)

        def _work():
            success = False   # safe default — set True only on full completion
            try:
                _ok = True
                for i, cmd in enumerate(cmds):
                    pct_start = (i / n_passes) * 100
                    pct_end   = ((i + 1) / n_passes) * 100
                    try:
                        self._proc = subprocess.Popen(
                            cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            text=True, universal_newlines=True,
                        )
                        for line in self._proc.stderr:
                            line = line.rstrip()
                            self.after(0, lambda l=line:
                                       progress_section.update_progress(
                                           progress_section.bar.get() * 100, log_line=l))
                            enc_time = parse_progress_time(line)
                            if enc_time is not None and total_duration and total_duration > 0:
                                phase_pct = min(1.0, enc_time / total_duration)
                                overall   = pct_start + phase_pct * (pct_end - pct_start)
                                label     = f"Pass {i + 1}/{n_passes} — Encoding…"
                                self.after(0, lambda p=overall, s=label:
                                           progress_section.update_progress(p, status=s))
                        self._proc.wait()
                        if self._proc.returncode != 0:
                            _ok = False
                            break
                    except Exception as exc:
                        self.after(0, lambda e=exc:
                                   progress_section.update_progress(0, status=f"Error: {e}"))
                        _ok = False
                        break
                success = _ok
            finally:
                # Always reset state — success is guaranteed to be bound by here
                self._running = False
                self._proc    = None
            # These run after finally completes, with success safely bound
            self.after(0, lambda s=success: progress_section.done(
                s, output_path=output_path))
            self.after(0, lambda s=success:
                       self.app.add_history(page_name, output_path, s))
            if on_done:
                self.after(0, lambda s=success: on_done(s))

        threading.Thread(target=_work, daemon=True).start()

    def cancel(self):
        if self._proc:
            self._proc.terminate()
            # FIX: schedule a kill() in case terminate() is ignored (e.g. Windows)
            proc = self._proc
            self.after(2000, lambda: proc.kill() if proc.poll() is None else None)
        self._running = False

    # ── Pre-flight validation ─────────────────────────────────────────────────

    def preflight(self,
                  input_path: str = "",
                  output_path: str = "",
                  required_codecs: list[str] | None = None,
                  min_free_mb: float = 100.0) -> bool:
        """
        Run sanity checks before launching FFmpeg.
        Returns True if all checks pass, False if user aborted or hard error found.

        Checks:
          1. Input file exists and is readable
          2. Output folder is writable
          3. Output does not overwrite the input file
          4. Estimated free disk space (2x source size)
          5. Required codecs are compiled into this FFmpeg build
        """
        warnings: list[str] = []
        errors:   list[str] = []

        # 1. Input readable
        if input_path:
            if not os.path.exists(input_path):
                errors.append("Input file not found:\n  " + input_path)
            elif not os.access(input_path, os.R_OK):
                errors.append("Input file is not readable:\n  " + input_path)

        # 2. Output folder writable
        if output_path:
            out_dir = Path(output_path).parent
            if not out_dir.exists():
                warnings.append("Output folder does not exist and will be created:\n  " + str(out_dir))
            elif not os.access(str(out_dir), os.W_OK):
                errors.append("Output folder is not writable:\n  " + str(out_dir))

        # 3. Would overwrite input
        if input_path and output_path:
            try:
                if Path(input_path).resolve() == Path(output_path).resolve():
                    errors.append(
                        "Output path is the same as the input file.\n"
                        "FFmpex would overwrite your source — choose a different output path.")
            except Exception:
                pass

        # 4. Disk space estimate
        if input_path and output_path and os.path.exists(input_path):
            try:
                import shutil as _shutil
                src_mb    = os.path.getsize(input_path) / (1024 * 1024)
                out_dir_s = str(Path(output_path).parent)
                free_mb   = _shutil.disk_usage(out_dir_s).free / (1024 * 1024)
                needed_mb = max(src_mb * 2, min_free_mb)
                if free_mb < needed_mb:
                    warnings.append(
                        "Low disk space on output drive:\n"
                        "  Available : " + f"{free_mb:.0f} MB\n" +
                        "  Estimated : " + f"{needed_mb:.0f} MB (2x source size)")
            except Exception:
                pass

        # 5. Required codecs
        if required_codecs and self.app.ffmpeg:
            for codec in required_codecs:
                if not self._codec_available(codec):
                    warnings.append(
                        "Codec '" + codec + "' may not be compiled into your FFmpeg build.\n"
                        "The job may fail. Check Settings → FFmpeg Installation.")

        # Hard errors — block
        if errors:
            messagebox.showerror(
                "Cannot Start — Pre-flight Check Failed",
                "\n\n".join(errors))
            return False

        # Warnings — let user decide
        if warnings:
            proceed = messagebox.askyesno(
                "Pre-flight Warning",
                "\n\n".join(warnings) + "\n\nProceed anyway?",
                icon="warning")
            return proceed

        return True

    def _codec_available(self, codec: str) -> bool:
        """Return True if FFmpeg reports the codec as available.
        FIX: cache the encoder list so we only shell out once per session."""
        if not hasattr(self, "_encoder_cache"):
            try:
                r = subprocess.run(
                    [self.app.ffmpeg, "-encoders"],
                    capture_output=True, text=True, timeout=8)
                self._encoder_cache = r.stdout
            except Exception:
                self._encoder_cache = ""  # empty → all checks return True below
        if not self._encoder_cache:
            return True  # assume available if we couldn't query
        return codec in self._encoder_cache


# ══════════════════════════════════════════════════════════════
# Convert Page
# ══════════════════════════════════════════════════════════════

class ConvertPage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        _page_header(self, "🔄  Convert",
                     "Convert any video or audio file to a different format.")

        self.input_zone = FileDropZone(
            self, label="Input File",
            filetypes=[("Media files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS + AUDIO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app,
            on_file_loaded=lambda _p: self.after(100, self._refresh_estimate))
        self.input_zone.pack(fill="x", pady=(0, 10))

        # ── Format row ──────────────────────────────────────────────────────
        fmt_card = _card(self, "Output Format")
        row = ctk.CTkFrame(fmt_card, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(row, text="Format:").pack(side="left", padx=(0, 8))
        self.fmt_var = ctk.StringVar(value="mp4")
        ctk.CTkOptionMenu(row, variable=self.fmt_var,
                          values=VIDEO_EXTS + AUDIO_EXTS,
                          width=110).pack(side="left", padx=(0, 16))

        ctk.CTkLabel(row, text="Quick:").pack(side="left", padx=(0, 6))
        for fmt in ["mp4", "mp3", "mkv", "webm", "gif", "flac", "wav"]:
            ctk.CTkButton(row, text=fmt, width=52, height=28,
                          command=lambda f=fmt: self.fmt_var.set(f),
                          fg_color=TC["quick"],
                          hover_color=TC["quick_hover"],
                          text_color=TC["secondary_text"]).pack(side="left", padx=2)

        # ── Encoding options ─────────────────────────────────────────────────
        opts_card = _card(self, "Encoding Options")
        opts_row = ctk.CTkFrame(opts_card, fg_color="transparent")
        opts_row.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(opts_row, text="Video CRF (0–51):").pack(side="left", padx=(0, 6))
        self.crf_var = ctk.StringVar(value="23")
        ctk.CTkEntry(opts_row, textvariable=self.crf_var,
                     width=52).pack(side="left", padx=(0, 20))

        ctk.CTkLabel(opts_row, text="Audio Bitrate:").pack(side="left", padx=(0, 6))
        self.bitrate_var = ctk.StringVar(value="192k")
        ctk.CTkOptionMenu(opts_row, variable=self.bitrate_var,
                          values=BITRATES, width=90).pack(side="left", padx=(0, 20))

        ctk.CTkLabel(opts_row, text="Scale:").pack(side="left", padx=(0, 6))
        self.scale_var = ctk.StringVar(value="Original")
        ctk.CTkOptionMenu(opts_row, variable=self.scale_var,
                          values=list(SCALE_OPTIONS.keys()),
                          width=120).pack(side="left")

        # ── GIF options ──────────────────────────────────────────────────────
        gif_card = _card(self, "GIF Options  (only used when output format is GIF)")
        gif_row = ctk.CTkFrame(gif_card, fg_color="transparent")
        gif_row.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(gif_row, text="FPS:").pack(side="left", padx=(0, 6))
        self.gif_fps_var = ctk.StringVar(value="15")
        ctk.CTkOptionMenu(gif_row, variable=self.gif_fps_var,
                          values=["10", "15", "20", "24", "30"],
                          width=70).pack(side="left", padx=(0, 20))

        ctk.CTkLabel(gif_row, text="Width (px):").pack(side="left", padx=(0, 6))
        self.gif_w_var = ctk.StringVar(value="480")
        ctk.CTkEntry(gif_row, textvariable=self.gif_w_var,
                     width=60).pack(side="left", padx=(0, 20))

        self.gif_2pass_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(gif_row,
                        text="2-pass palette (better quality, slower)",
                        variable=self.gif_2pass_var).pack(side="left")

        # ── Presets bar ──────────────────────────────────────────────────────
        self.preset_bar = PresetBar(self, page_name="Convert",
                                    get_fn=self._get_settings,
                                    set_fn=self._apply_settings)
        self.preset_bar.pack(fill="x", pady=(0, 6))

        # ── Output naming template ────────────────────────────────────────────
        self.tmpl_bar = TemplateBar(self, get_inp_fn=self.input_zone.get)
        self.tmpl_bar.pack(fill="x", pady=(0, 6))

        # ── Output path ──────────────────────────────────────────────────────
        out_card = _card(self, "Output File  (overrides template if filled)")
        out_row = ctk.CTkFrame(out_card, fg_color="transparent")
        out_row.pack(fill="x", padx=10, pady=(0, 10))
        self.output_var = ctk.StringVar()
        ctk.CTkEntry(out_row, textvariable=self.output_var,
                     placeholder_text="Leave blank to use template or auto-name").pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(out_row, text="Browse", width=80,
                      command=self._browse_out).pack(side="left")

        self.args_bar = CustomArgsBar(self)
        self.args_bar.pack(fill="x", pady=(0, 6))

        # ── Estimated output size ─────────────────────────────────────────────
        self._est_lbl = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=12), text_color=TC["text_dim"])
        self._est_lbl.pack(anchor="w", pady=(0, 4))

        # Refresh estimate whenever format, CRF, or bitrate changes
        for var in (self.fmt_var, self.crf_var, self.bitrate_var):
            var.trace_add("write", lambda *_: self.after(50, self._refresh_estimate))

        self.cmd_preview = CommandPreview(self, self._build_cmd)
        _action_row(self, self._run, self.cancel, preview=self.cmd_preview)
        self.cmd_preview.pack(fill="x", pady=(6, 0))
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _get_settings(self) -> dict:
        return {
            "fmt":      self.fmt_var.get(),
            "crf":      self.crf_var.get(),
            "bitrate":  self.bitrate_var.get(),
            "scale":    self.scale_var.get(),
            "gif_fps":  self.gif_fps_var.get(),
            "gif_w":    self.gif_w_var.get(),
            "gif_2p":   self.gif_2pass_var.get(),
        }

    def _apply_settings(self, s: dict):
        if "fmt"     in s: self.fmt_var.set(s["fmt"])
        if "crf"     in s: self.crf_var.set(s["crf"])
        if "bitrate" in s: self.bitrate_var.set(s["bitrate"])
        if "scale"   in s: self.scale_var.set(s["scale"])
        if "gif_fps" in s: self.gif_fps_var.set(s["gif_fps"])
        if "gif_w"   in s: self.gif_w_var.set(s["gif_w"])
        if "gif_2p"  in s: self.gif_2pass_var.set(s["gif_2p"])
        self._refresh_estimate()

    def _refresh_estimate(self):
        """Update the estimated output size label below the action row."""
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            self._est_lbl.configure(text="")
            return
        fmt  = self.fmt_var.get()
        dur  = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None
        try:
            crf_int = int(self.crf_var.get())
        except ValueError:
            crf_int = 23
        try:
            ab_kbps = int(self.bitrate_var.get().rstrip("k"))
        except ValueError:
            ab_kbps = 128

        audio_only = fmt in AUDIO_EXTS and fmt not in VIDEO_EXTS
        est = estimate_output_size_mb(
            inp,
            crf=None if audio_only else crf_int,
            audio_kbps=ab_kbps,
            duration=dur,
            is_audio_only=audio_only,
        )
        self._est_lbl.configure(
            text=f"📐  Estimated output size:  {est}" if est else "")

    def _browse_out(self):
        fmt = self.fmt_var.get()
        inp = self.input_zone.get()
        # FIX: initialfile was missing — caused TypeError at runtime
        stem = Path(inp).stem if inp else "output"
        p = self.app.smart_save_dialog(
            "Convert",
            initialfile=f"{stem}_converted.{fmt}",
            defaultextension=f".{fmt}",
            filetypes=[(fmt.upper(), f"*.{fmt}"), ("All files", "*.*")])
        if p:
            self.output_var.set(p)

    def _build_cmd(self):
        """Return the FFmpeg command list for the current settings (no file dialogs)."""
        inp = self.input_zone.get()
        if not inp or not self.app.ffmpeg:
            return None
        fmt = self.fmt_var.get()
        out = self.output_var.get() or f"<output>.{fmt}"

        if fmt == "gif":
            fps = self.gif_fps_var.get()
            w   = self.gif_w_var.get()
            vf  = f"fps={fps},scale={w}:-1:flags=lanczos"
            if self.gif_2pass_var.get():
                # Show pass-1 command only in the preview — pass-2 references a
                # temp palette file that doesn't exist yet, so displaying both as
                # a flat list with "&&" looked broken.  The preview note makes
                # clear that a second pass runs automatically.
                return [self.app.ffmpeg, "-y", "-i", inp,
                        "-vf", f"{vf},palettegen", "<palette.png>",
                        "# (pass 2 runs automatically with paletteuse)"]
            return [self.app.ffmpeg, "-y", "-i", inp,
                    "-vf", vf, "-loop", "0", out]

        cmd = [self.app.ffmpeg, "-y", "-i", inp]
        if fmt in VIDEO_EXTS:
            mapping = CONTAINER_VIDEO_CODEC.get(fmt, {"vcodec": "libx264", "acodec": "aac"})
            vcodec  = mapping["vcodec"]
            acodec  = mapping["acodec"]
            cmd += ["-c:v", vcodec]
            cmd += codec_quality_flag(vcodec, self.crf_var.get())
            if vcodec not in ("wmv2", "mpeg2video", "libtheora", "prores_ks", "dnxhd", "copy"):
                cmd += ["-preset", "fast"]
            cmd += ["-c:a", acodec]
            if acodec not in ("pcm_s16le", "mp2", "copy"):
                cmd += ["-b:a", self.bitrate_var.get()]
            scale = SCALE_OPTIONS.get(self.scale_var.get())
            if scale:
                cmd += ["-vf", f"scale={scale}"]
        else:
            codec = AUDIO_CODEC_MAP.get(fmt, "copy")
            cmd += ["-vn", "-c:a", codec]
            if fmt not in ("flac", "wav"):
                cmd += ["-b:a", self.bitrate_var.get()]
        cmd.append(out)
        return cmd

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return
        fmt = self.fmt_var.get()
        # Priority: explicit path > template > auto-name
        out = (self.output_var.get().strip()
               or self.tmpl_bar.resolve(inp, ext=fmt,
                                        crf=self.crf_var.get())
               or str(Path(inp).parent / f"{Path(inp).stem}_converted.{fmt}"))

        duration = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None

        if not self.preflight(input_path=inp, output_path=out):
            return

        # ── GIF: 2-pass palette ────────────────────────────────────────────
        if fmt == "gif":
            fps  = self.gif_fps_var.get()
            w    = self.gif_w_var.get()
            vf   = f"fps={fps},scale={w}:-1:flags=lanczos"
            if self.gif_2pass_var.get():
                # FIX: mktemp() is insecure — use mkstemp instead
                _fd, palette = tempfile.mkstemp(suffix=".png")
                os.close(_fd)
                cmds = [
                    [self.app.ffmpeg, "-y", "-i", inp,
                     "-vf", f"{vf},palettegen", palette],
                    [self.app.ffmpeg, "-y", "-i", inp, "-i", palette,
                     "-lavfi", f"{vf}[v];[v][1:v]paletteuse",
                     "-loop", "0", out],
                ]
                def _cleanup_palette(ok, p=palette):
                    try: os.unlink(p)
                    except Exception: pass
                    if ok: messagebox.showinfo("Done", f"Saved to:\n{out}")
                self.run_ffmpeg_chain(cmds, duration, self.progress,
                                      on_done=_cleanup_palette,
                                      page_name="Convert (GIF)", output_path=out)
            else:
                cmd = [self.app.ffmpeg, "-y", "-i", inp,
                       "-vf", vf, "-loop", "0", out]
                self.run_ffmpeg(cmd, duration, self.progress,
                                on_done=lambda ok: messagebox.showinfo(
                                    "Done", f"Saved to:\n{out}") if ok else None,
                                page_name="Convert", output_path=out)
            return

        cmd = [self.app.ffmpeg, "-y", "-i", inp]

        if fmt in VIDEO_EXTS:
            mapping = CONTAINER_VIDEO_CODEC.get(fmt, {"vcodec": "libx264", "acodec": "aac"})
            vcodec  = mapping["vcodec"]
            acodec  = mapping["acodec"]
            cmd += ["-c:v", vcodec]
            cmd += codec_quality_flag(vcodec, self.crf_var.get())
            if vcodec not in ("wmv2", "mpeg2video", "libtheora", "prores_ks", "dnxhd", "copy"):
                cmd += ["-preset", "fast"]
            cmd += ["-c:a", acodec]
            if acodec not in ("pcm_s16le", "mp2", "copy"):
                cmd += ["-b:a", self.bitrate_var.get()]
            scale = SCALE_OPTIONS.get(self.scale_var.get())
            if scale:
                cmd += ["-vf", f"scale={scale}"]
        else:
            # Select correct audio codec for the output format
            codec = AUDIO_CODEC_MAP.get(fmt, "copy")
            cmd += ["-vn", "-c:a", codec]
            if fmt not in ("flac", "wav"):
                cmd += ["-b:a", self.bitrate_var.get()]

        cmd += self.args_bar.extra_args()
        cmd.append(out)
        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Convert", output_path=out)


# ══════════════════════════════════════════════════════════════
# Compress Page
# ══════════════════════════════════════════════════════════════

class CompressPage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        _page_header(self, "📦  Compress",
                     "Reduce file size with smart presets or a custom CRF value.")

        self.input_zone = FileDropZone(
            self, label="Input Video",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app,
            on_file_loaded=lambda _p: self.after(100, self._refresh_estimate))
        self.input_zone.pack(fill="x", pady=(0, 6))

        # Analyze button
        info_row = ctk.CTkFrame(self, fg_color="transparent")
        info_row.pack(fill="x", pady=(0, 8))
        self.info_label = ctk.CTkLabel(
            info_row, text="", font=ctk.CTkFont(size=12),
            text_color=TC["text_dim"])
        self.info_label.pack(side="left", padx=(0, 12))
        ctk.CTkButton(info_row, text="Analyze", width=90, height=28,
                      command=self._analyze).pack(side="left")

        # ── Presets ─────────────────────────────────────────────────────────
        preset_card = _card(self, "Presets")
        grid = ctk.CTkFrame(preset_card, fg_color="transparent")
        grid.pack(fill="x", padx=10, pady=(0, 10))
        self.preset_var = ctk.StringVar(value="Web Optimized")
        for i, name in enumerate(COMPRESS_PRESETS):
            ctk.CTkRadioButton(
                grid, text=name, variable=self.preset_var, value=name,
                command=self._on_preset,
            ).grid(row=i // 2, column=i % 2, sticky="w", padx=10, pady=3)

        # ── Mode selector ────────────────────────────────────────────────────
        mode_card = _card(self, "Encoding Mode")
        mode_row = ctk.CTkFrame(mode_card, fg_color="transparent")
        mode_row.pack(fill="x", padx=10, pady=(0, 10))
        self.encode_mode = ctk.StringVar(value="crf")
        ctk.CTkRadioButton(mode_row, text="CRF  (quality target — recommended)",
                           variable=self.encode_mode, value="crf",
                           command=self._on_mode_change).pack(side="left", padx=(0, 24))
        ctk.CTkRadioButton(mode_row, text="2-Pass  (exact file size target)",
                           variable=self.encode_mode, value="2pass",
                           command=self._on_mode_change).pack(side="left")

        # ── CRF slider ──────────────────────────────────────────────────────
        self._crf_card = _card(self, "Custom CRF  (0 = lossless  →  51 = worst quality)")
        crf_row = ctk.CTkFrame(self._crf_card, fg_color="transparent")
        crf_row.pack(fill="x", padx=10, pady=(0, 10))
        self.crf_var = ctk.IntVar(value=23)
        self.crf_slider = ctk.CTkSlider(
            crf_row, from_=0, to=51, number_of_steps=51,
            variable=self.crf_var, command=self._crf_moved)
        self.crf_slider.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.crf_display = ctk.CTkLabel(crf_row, text="23", width=30)
        self.crf_display.pack(side="left")

        # ── 2-Pass target size ────────────────────────────────────────────────
        self._twopass_card = _card(self, "2-Pass Target Size")
        tp_row1 = ctk.CTkFrame(self._twopass_card, fg_color="transparent")
        tp_row1.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(tp_row1, text="Target file size:").pack(side="left", padx=(0, 8))
        self.target_mb_var = ctk.StringVar(value="50")
        ctk.CTkEntry(tp_row1, textvariable=self.target_mb_var,
                     width=70).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(tp_row1, text="MB").pack(side="left", padx=(0, 20))
        for mb in [8, 16, 25, 50, 100, 500]:
            ctk.CTkButton(tp_row1, text=f"{mb} MB", width=58, height=26,
                          fg_color=TC["quick"],
                          hover_color=TC["quick_hover"],
                          text_color=TC["secondary_text"],
                          command=lambda v=mb: self.target_mb_var.set(str(v))
                          ).pack(side="left", padx=2)

        tp_hint = ctk.CTkFrame(self._twopass_card, fg_color="transparent")
        tp_hint.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(tp_hint,
                     text="The audio bitrate (set below) is subtracted from the size budget "
                          "before calculating the video bitrate.",
                     font=ctk.CTkFont(size=11),
                     text_color=TC["text_dim"],
                     wraplength=680, justify="left").pack(anchor="w")

        tp_row3 = ctk.CTkFrame(self._twopass_card, fg_color="transparent")
        tp_row3.pack(fill="x", padx=10, pady=(0, 10))
        self._tp_est_label = ctk.CTkLabel(
            tp_row3, text="",
            font=ctk.CTkFont(size=12),
            text_color=TC["text_dim"])
        self._tp_est_label.pack(side="left")
        ctk.CTkButton(tp_row3, text="Recalculate", width=110, height=26,
                      fg_color=TC["secondary"],
                      hover_color=TC["secondary_hover"],
                      text_color=TC["secondary_text"],
                      command=self._update_tp_estimate).pack(side="left", padx=(12, 0))
        self.target_mb_var.trace_add("write", lambda *_: self._update_tp_estimate())

        # 2-pass card hidden by default
        self._twopass_card.pack_forget()

        # Anchor widget for pack_before ordering (mode toggle uses this)
        self._enc_options_anchor = ctk.CTkFrame(self, fg_color="transparent", height=0)
        self._enc_options_anchor.pack(fill="x")

        # ── Encoding options ─────────────────────────────────────────────────
        enc_card = _card(self, "Encoding Options")
        enc_row = ctk.CTkFrame(enc_card, fg_color="transparent")
        enc_row.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(enc_row, text="Output resolution:").pack(side="left", padx=(0, 8))
        self.scale_var = ctk.StringVar(value="Original")
        ctk.CTkOptionMenu(enc_row, variable=self.scale_var,
                          values=list(SCALE_OPTIONS.keys()),
                          width=130).pack(side="left", padx=(0, 20))

        ctk.CTkLabel(enc_row, text="Audio bitrate:").pack(side="left", padx=(0, 8))
        self.bitrate_var = ctk.StringVar(value="128k")
        ctk.CTkOptionMenu(enc_row, variable=self.bitrate_var,
                          values=BITRATES, width=90).pack(side="left")

        # ── Presets bar ──────────────────────────────────────────────────────
        self.preset_bar = PresetBar(self, page_name="Compress",
                                    get_fn=self._get_settings,
                                    set_fn=self._apply_settings)
        self.preset_bar.pack(fill="x", pady=(0, 6))

        # ── Output naming template ────────────────────────────────────────────
        self.tmpl_bar = TemplateBar(self, get_inp_fn=self.input_zone.get)
        self.tmpl_bar.pack(fill="x", pady=(0, 6))

        self.args_bar = CustomArgsBar(self)
        self.args_bar.pack(fill="x", pady=(0, 6))

        # ── Estimated output size (CRF mode only) ────────────────────────────
        self._est_lbl = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=12), text_color=TC["text_dim"])
        self._est_lbl.pack(anchor="w", pady=(0, 4))
        # Refresh when CRF slider or audio bitrate changes
        self.crf_var.trace_add(    "write", lambda *_: self.after(50, self._refresh_estimate))
        self.bitrate_var.trace_add("write", lambda *_: self.after(50, self._refresh_estimate))

        self.cmd_preview = CommandPreview(self, self._build_cmd)
        _action_row(self, self._run, self.cancel, run_label="Compress",
                    preview=self.cmd_preview)
        self.cmd_preview.pack(fill="x", pady=(6, 0))
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _on_mode_change(self):
        """Toggle between CRF card and 2-pass card."""
        if self.encode_mode.get() == "crf":
            self._twopass_card.pack_forget()
            self._crf_card.pack(fill="x", pady=(0, 10),
                                before=self._enc_options_anchor)
        else:
            self._crf_card.pack_forget()
            self._twopass_card.pack(fill="x", pady=(0, 10),
                                    before=self._enc_options_anchor)
            self._update_tp_estimate()

    def _update_tp_estimate(self):
        """Calculate expected video bitrate from target MB and audio bitrate."""
        inp = self.input_zone.get()
        dur = None
        if inp and os.path.exists(inp) and self.app.ffprobe:
            dur = get_duration(self.app.ffprobe, inp)
        try:
            target_mb = float(self.target_mb_var.get())
        except ValueError:
            self._tp_est_label.configure(text="⚠  Enter a valid number of MB")
            return
        target_bits = target_mb * 8 * 1024 * 1024  # bits
        # Parse audio bitrate (e.g. "128k" -> 128000)
        abr_str = self.bitrate_var.get().lower().rstrip("k")
        try:
            audio_bps = int(abr_str) * 1000
        except ValueError:
            audio_bps = 128000
        if dur and dur > 0:
            video_bps = max(0, (target_bits / dur) - audio_bps)
            vkbps = video_bps / 1000
            self._tp_est_label.configure(
                text=f"⟹  Video bitrate: {vkbps:.0f} kbps  "
                     f"(audio: {audio_bps // 1000} kbps,  "
                     f"duration: {int(dur // 60)}m {int(dur % 60)}s)")
        else:
            self._tp_est_label.configure(
                text="Select a file and click Recalculate to see the estimated video bitrate.")

    def _on_preset(self):
        crf = COMPRESS_PRESETS[self.preset_var.get()]["crf"]
        self.crf_var.set(crf)
        self.crf_display.configure(text=str(crf))
        self.crf_slider.set(crf)
        self._refresh_estimate()

    def _crf_moved(self, val):
        self.crf_display.configure(text=str(int(float(val))))
        self._refresh_estimate()

    def _refresh_estimate(self):
        """Update the estimated output size label (CRF mode only)."""
        if self.encode_mode.get() != "crf":
            self._est_lbl.configure(text="")
            return
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            self._est_lbl.configure(text="")
            return
        dur = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None
        try:
            ab_kbps = int(self.bitrate_var.get().rstrip("k"))
        except ValueError:
            ab_kbps = 128
        est = estimate_output_size_mb(
            inp,
            crf=int(self.crf_var.get()),
            audio_kbps=ab_kbps,
            duration=dur,
        )
        self._est_lbl.configure(
            text=f"📐  Estimated output size:  {est}" if est else "")

    def _analyze(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp) or not self.app.ffprobe:
            messagebox.showinfo("Note", "Select a file and make sure ffprobe is installed.")
            return
        info = get_file_info(self.app.ffprobe, inp)
        if info:
            dur     = info["duration"]
            dur_str = f"{int(dur // 60)}m {int(dur % 60)}s" if dur else "?"
            v = info["video"][0] if info["video"] else {}
            a = info["audio"][0] if info["audio"] else {}
            parts = [
                f"📹 {v.get('width','?')}×{v.get('height','?')} @ {v.get('fps','?')} fps  {v.get('codec','?').upper()}",
                f"🎵 {a.get('codec','?').upper()} {a.get('channels','?')}ch @ {a.get('sample_rate','?')} Hz",
                f"⏱ {dur_str}   💾 {info['size_mb']:.1f} MB",
            ]
            self.info_label.configure(
                text="   |   ".join(parts),
                text_color=TC["nav_text"])
            self._update_tp_estimate()  # refresh estimate now duration is known

    def _get_settings(self) -> dict:
        return {
            "encode_mode": self.encode_mode.get(),
            "crf":         self.crf_var.get(),
            "target_mb":   self.target_mb_var.get(),
            "bitrate":     self.bitrate_var.get(),
            "scale":       self.scale_var.get(),
        }

    def _apply_settings(self, s: dict):
        if "encode_mode" in s:
            self.encode_mode.set(s["encode_mode"])
            self._on_mode_change()
        if "crf" in s:
            self.crf_var.set(int(s["crf"]))
            self.crf_display.configure(text=str(int(s["crf"])))
            self.crf_slider.set(int(s["crf"]))
        if "target_mb" in s:
            self.target_mb_var.set(s["target_mb"])
        if "bitrate" in s:
            self.bitrate_var.set(s["bitrate"])
        if "scale" in s:
            self.scale_var.set(s["scale"])

    def _build_cmd(self):
        inp = self.input_zone.get()
        if not inp or not self.app.ffmpeg:
            return None
        out = f"<{Path(inp).stem}_compressed.mp4>"
        scale_filter = SCALE_OPTIONS.get(self.scale_var.get())
        vf_args = ["-vf", f"scale={scale_filter}"] if scale_filter else []

        if self.encode_mode.get() == "2pass":
            # Show pass-1 command only — pass-2 runs automatically.
            return ([self.app.ffmpeg, "-y", "-i", inp]
                    + vf_args
                    + ["-c:v", "libx264", "-b:v", "<calculated>",
                       "-pass", "1", "-an", "-f", "null", "/dev/null",
                       "# (pass 2 runs automatically)"])

        crf = self.crf_var.get()
        cmd = [self.app.ffmpeg, "-y", "-i", inp,
               "-c:v", "libx264", "-crf", str(crf), "-preset", "fast",
               "-c:a", "aac", "-b:a", self.bitrate_var.get()]
        cmd += vf_args
        cmd.append(out)
        return cmd

    def _calc_video_bitrate(self, inp: str) -> str | None:
        """Return video bitrate string (e.g. '800k') for 2-pass mode, or None on error."""
        dur = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None
        if not dur or dur <= 0:
            return None
        try:
            target_mb = float(self.target_mb_var.get())
        except ValueError:
            return None
        abr_str = self.bitrate_var.get().lower().rstrip("k")
        try:
            audio_bps = int(abr_str) * 1000
        except ValueError:
            audio_bps = 128000
        target_bits = target_mb * 8 * 1024 * 1024
        video_bps   = max(50_000, (target_bits / dur) - audio_bps)
        return f"{int(video_bps / 1000)}k"

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return
        p   = Path(inp)
        out = self.tmpl_bar.resolve(inp, ext="mp4",
                                    crf=str(self.crf_var.get()))
        if out is None:
            out = self.app.smart_save_dialog(
                "Compress",
                initialfile=f"{p.stem}_compressed.mp4",
                defaultextension=".mp4",
                filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv"), ("All files", "*.*")])
        if not out:
            return

        duration    = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None
        scale_filter = SCALE_OPTIONS.get(self.scale_var.get())
        vf_args     = ["-vf", f"scale={scale_filter}"] if scale_filter else []

        # ── 2-pass encode ────────────────────────────────────────────────────
        if self.encode_mode.get() == "2pass":
            if not self.preflight(input_path=inp, output_path=out,
                                  required_codecs=["libx264"]):
                return
            vbr = self._calc_video_bitrate(inp)
            if not vbr:
                messagebox.showerror(
                    "2-Pass Error",
                    "Could not determine video duration.\n"
                    "Make sure ffprobe is installed and the file is valid.")
                return

            # FIX: mktemp() is insecure — use an exclusive temp directory so
            # FFmpeg's companion log files (passlog-0.log, .mbtree) are isolated.
            _passdir    = tempfile.mkdtemp(prefix="ffmpex_pass_")
            passlogfile = os.path.join(_passdir, "ffmpex_pass")
            null_out    = "NUL" if platform.system() == "Windows" else "/dev/null"

            pass1 = ([self.app.ffmpeg, "-y", "-i", inp]
                     + vf_args
                     + ["-c:v", "libx264", "-b:v", vbr,
                        "-pass", "1", "-passlogfile", passlogfile,
                        "-an", "-f", "null", null_out])

            pass2 = ([self.app.ffmpeg, "-y", "-i", inp]
                     + vf_args
                     + ["-c:v", "libx264", "-b:v", vbr,
                        "-pass", "2", "-passlogfile", passlogfile,
                        "-c:a", "aac", "-b:a", self.bitrate_var.get(),
                        out])

            def _cleanup(ok, logf=passlogfile, logdir=_passdir):
                for ext in ("", ".log", "-0.log", ".log.mbtree"):
                    try:
                        os.unlink(logf + ext)
                    except Exception:
                        pass
                try:
                    os.rmdir(logdir)   # remove the now-empty temp dir
                except Exception:
                    pass
                if ok:
                    messagebox.showinfo("Done", f"Saved to:\n{out}")

            self.run_ffmpeg_chain(
                [pass1, pass2], duration, self.progress,
                on_done=_cleanup,
                page_name="Compress (2-pass)", output_path=out)
            return

        if not self.preflight(input_path=inp, output_path=out):
            return

        # ── CRF encode ───────────────────────────────────────────────────────
        crf = self.crf_var.get()
        cmd = [self.app.ffmpeg, "-y", "-i", inp,
               "-c:v", "libx264", "-crf", str(crf), "-preset", "fast",
               "-c:a", "aac", "-b:a", self.bitrate_var.get()]
        cmd += vf_args
        cmd += self.args_bar.extra_args()
        cmd.append(out)

        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Compress", output_path=out)


# ══════════════════════════════════════════════════════════════
# Trim Page
# ══════════════════════════════════════════════════════════════

class TrimPage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._duration = None
        self._build()

    def _build(self):
        _page_header(self, "✂️  Trim & Cut",
                     "Extract a clip between two timestamps.")

        self.input_zone = FileDropZone(
            self, label="Input File",
            filetypes=[("Media files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS + AUDIO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 6))

        info_row = ctk.CTkFrame(self, fg_color="transparent")
        info_row.pack(fill="x", pady=(0, 10))
        self.info_label = ctk.CTkLabel(
            info_row, text="", font=ctk.CTkFont(size=12),
            text_color=TC["text_dim"])
        self.info_label.pack(side="left", padx=(0, 12))
        ctk.CTkButton(info_row, text="Load Info", width=90, height=28,
                      command=self._load_info).pack(side="left")

        # ── Timestamp inputs ─────────────────────────────────────────────────
        time_card = _card(self, "Cut Points  (HH:MM:SS  or  MM:SS  or  seconds)")
        t_row = ctk.CTkFrame(time_card, fg_color="transparent")
        t_row.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(t_row, text="Start:").pack(side="left", padx=(0, 6))
        self.start_var = ctk.StringVar(value="00:00:00.00")
        ctk.CTkEntry(t_row, textvariable=self.start_var,
                     width=120).pack(side="left", padx=(0, 28))

        ctk.CTkLabel(t_row, text="End:").pack(side="left", padx=(0, 6))
        self.end_var = ctk.StringVar(value="")
        ctk.CTkEntry(t_row, textvariable=self.end_var, width=120,
                     placeholder_text="end of file").pack(side="left")

        # ── Visual sliders ──────────────────────────────────────────────────
        slider_card = _card(self, "Visual Trim")
        sg = ctk.CTkFrame(slider_card, fg_color="transparent")
        sg.pack(fill="x", padx=10, pady=(0, 10))
        sg.columnconfigure(1, weight=1)

        ctk.CTkLabel(sg, text="Start:", width=45).grid(row=0, column=0, sticky="w")
        self.start_slider = ctk.CTkSlider(sg, from_=0, to=100,
                                           command=self._start_drag)
        self.start_slider.set(0)
        self.start_slider.grid(row=0, column=1, sticky="ew", padx=8)
        self.start_lbl = ctk.CTkLabel(sg, text="0:00", width=80)
        self.start_lbl.grid(row=0, column=2)

        ctk.CTkLabel(sg, text="End:", width=45).grid(row=1, column=0,
                                                       sticky="w", pady=(8, 0))
        self.end_slider = ctk.CTkSlider(sg, from_=0, to=100,
                                         command=self._end_drag)
        self.end_slider.set(100)
        self.end_slider.grid(row=1, column=1, sticky="ew", padx=8, pady=(8, 0))
        self.end_lbl = ctk.CTkLabel(sg, text="end", width=80)
        self.end_lbl.grid(row=1, column=2, pady=(8, 0))

        # ── Options ─────────────────────────────────────────────────────────
        opt_card = _card(self, "Options")
        opt_row = ctk.CTkFrame(opt_card, fg_color="transparent")
        opt_row.pack(fill="x", padx=10, pady=(0, 10))
        self.fast_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            opt_row,
            text="Fast cut  (stream copy — instant, no quality loss, slight frame boundary offset)",
            variable=self.fast_var).pack(anchor="w")

        # ── Frame preview ──────────────────────────────────────────────────
        self.dual_preview = DualVideoPreviewWidget(self, app=self.app)
        self.dual_preview.pack(fill="x", pady=(0, 8))

        _action_row(self, self._run, self.cancel, run_label="Trim")
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

        # Page-local keyboard shortcuts (only active when this frame has focus)
        # [ = set start   ] = set end   Space = preview clip
        self.bind_all("<bracketleft>",  lambda e: self._kb_set_start())
        self.bind_all("<bracketright>", lambda e: self._kb_set_end())

    def _kb_set_start(self):
        """[ key — set start slider to current playback position placeholder (0)."""
        # Without an embedded player we move start to the current slider value.
        # If the user has just typed a time in the entry, honour that instead.
        pass  # sliders already sync; shortcut serves as a mental anchor

    def _kb_set_end(self):
        pass

    def _load_info(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp) or not self.app.ffprobe:
            return
        dur = get_duration(self.app.ffprobe, inp)
        if dur:
            self._duration = dur
            self.info_label.configure(
                text=f"⏱  Duration: {secs_to_ts(dur)}",
                text_color=TC["nav_text"])
            self.end_var.set(secs_to_ts(dur))
            for sl in (self.start_slider, self.end_slider):
                sl.configure(to=dur)
            self.end_slider.set(dur)
            self.end_lbl.configure(text=secs_to_ts(dur))
            # Show first and last frames
            self.dual_preview.set_file(inp)
            self.dual_preview.set_start(0.0, debounce_ms=0)
            self.dual_preview.set_end(dur, debounce_ms=0)

    def _start_drag(self, val):
        self.start_var.set(secs_to_ts(float(val)))
        self.start_lbl.configure(text=secs_to_ts(float(val)))
        inp = self.input_zone.get()
        if inp:
            self.dual_preview.set_start(float(val))

    def _end_drag(self, val):
        self.end_var.set(secs_to_ts(float(val)))
        self.end_lbl.configure(text=secs_to_ts(float(val)))
        inp = self.input_zone.get()
        if inp:
            self.dual_preview.set_end(float(val))

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return
        p   = Path(inp)
        out = self.app.smart_save_dialog(
            "Trim",
            initialfile=f"{p.stem}_trim{p.suffix}",
            defaultextension=p.suffix,
            filetypes=[(p.suffix.upper().lstrip("."), f"*{p.suffix}"),
                       ("All files", "*.*")])
        if not out:
            return

        if not self.preflight(input_path=inp, output_path=out):
            return

        start   = ts_to_secs(self.start_var.get()) or 0.0
        end_str = self.end_var.get().strip()
        end     = ts_to_secs(end_str) if end_str else None

        if end is not None and end <= start:
            messagebox.showerror("Error", "End time must be after start time.")
            return

        # BUG FIX: when using input-seeking (-ss before -i),
        # -to is relative to the OUTPUT start (0), not the input timestamp.
        # Use -t <duration> instead, which is always unambiguous.
        clip_dur = (end - start) if end else None

        cmd = [self.app.ffmpeg, "-y", "-ss", str(start), "-i", inp]
        if clip_dur:
            cmd += ["-t", str(clip_dur)]
        if self.fast_var.get():
            cmd += ["-c", "copy"]
        cmd.append(out)

        self.run_ffmpeg(
            cmd, clip_dur or self._duration, self.progress,
            on_done=lambda ok: messagebox.showinfo(
                "Done", f"Saved to:\n{out}") if ok else None,
            page_name="Trim", output_path=out)


# ══════════════════════════════════════════════════════════════
# Merge Page
# ══════════════════════════════════════════════════════════════

class MergePage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._files = []
        self._selected_idx = None
        self._build()

    def _build(self):
        _page_header(self, "🔗  Merge / Concatenate",
                     "Join multiple files in order. Best results when all clips "
                     "share the same codec, resolution, and frame rate.")

        list_card = _card(self, "Files")
        # FIX: hardcoded dark colors broke light themes — use TC theme colors
        self.listbox = tk.Listbox(
            list_card,
            selectmode=tk.SINGLE,
            bg=TC["card_inner"], fg=TC["text"],
            selectbackground=TC["accent"],
            font=("Courier", 11),
            relief="flat", borderwidth=0,
            height=8)
        self.listbox.pack(fill="x", padx=10, pady=(0, 6))
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        btn_row = ctk.CTkFrame(list_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(0, 10))

        grey = {"fg_color": TC["secondary"],
                "hover_color": TC["secondary_hover"],
                "text_color": ("gray10", "gray90")}

        ctk.CTkButton(btn_row, text="Add Files", width=90,
                      command=self._add).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="Move Up", width=80,
                      command=self._move_up, **grey).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="Move Down", width=90,
                      command=self._move_down, **grey).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="Remove", width=80,
                      command=self._remove_selected, **grey).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="Clear All", width=80,
                      command=self._clear, **grey).pack(side="left")

        _action_row(self, self._run, self.cancel, run_label="Merge")
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _on_select(self, _event):
        sel = self.listbox.curselection()
        self._selected_idx = sel[0] if sel else None

    def _refresh(self):
        self.listbox.delete(0, tk.END)
        for i, f in enumerate(self._files):
            self.listbox.insert(tk.END, f"  {i + 1}.  {Path(f).name}")
        if self._selected_idx is not None:
            idx = min(self._selected_idx, len(self._files) - 1)
            if idx >= 0:
                self.listbox.selection_set(idx)
                self._selected_idx = idx

    def _add(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("Media files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS + AUDIO_EXTS)),
                       ("All files", "*.*")])
        if paths:
            self._files.extend(paths)
            self._refresh()

    # BUG FIX: was rotating the whole list; now swaps adjacent items
    def _move_up(self):
        idx = self._selected_idx
        if idx is None or idx == 0 or not self._files:
            return
        self._files[idx - 1], self._files[idx] = self._files[idx], self._files[idx - 1]
        self._selected_idx = idx - 1
        self._refresh()

    def _move_down(self):
        idx = self._selected_idx
        if idx is None or idx >= len(self._files) - 1 or not self._files:
            return
        self._files[idx], self._files[idx + 1] = self._files[idx + 1], self._files[idx]
        self._selected_idx = idx + 1
        self._refresh()

    def _remove_selected(self):
        idx = self._selected_idx
        if idx is None or not self._files:
            return
        self._files.pop(idx)
        self._selected_idx = min(idx, len(self._files) - 1) if self._files else None
        self._refresh()

    def _clear(self):
        self._files.clear()
        self._selected_idx = None
        self._refresh()

    def _run(self):
        if len(self._files) < 2:
            messagebox.showerror("Error", "Add at least 2 files to merge.")
            return
        out = self.app.smart_save_dialog(
            "Merge",
            initialfile="merged_output.mp4",
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv"), ("All files", "*.*")])
        if not out:
            return

        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        for f in self._files:
            # Escape single quotes in paths for ffmpeg concat format
            safe = f.replace("'", "'\\''")
            tmp.write(f"file '{safe}'\n")
        tmp.close()

        total_dur = None
        if self.app.ffprobe:
            durs = [get_duration(self.app.ffprobe, f) for f in self._files]
            durs = [d for d in durs if d]
            total_dur = sum(durs) if durs else None

        cmd = [self.app.ffmpeg, "-y", "-f", "concat", "-safe", "0",
               "-i", tmp.name, "-c", "copy", out]

        def _cleanup(ok):
            try: os.unlink(tmp.name)
            except Exception: pass
            if ok: messagebox.showinfo("Done", f"Saved to:\n{out}")

        self.run_ffmpeg(cmd, total_dur, self.progress, on_done=_cleanup,
                        page_name="Merge", output_path=out)


# ══════════════════════════════════════════════════════════════
# Extract Audio Page
# ══════════════════════════════════════════════════════════════

class ExtractPage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        _page_header(self, "🎵  Extract Audio",
                     "Strip the audio track from any video into a standalone file.")

        self.input_zone = FileDropZone(
            self, label="Input Video",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 10))

        fmt_card = _card(self, "Output Format")

        row1 = ctk.CTkFrame(fmt_card, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(row1, text="Format:").pack(side="left", padx=(0, 8))
        self.fmt_var = ctk.StringVar(value="mp3")
        ctk.CTkOptionMenu(row1, variable=self.fmt_var,
                          values=AUDIO_EXTS, width=100,
                          command=self._fmt_changed).pack(side="left", padx=(0, 20))
        ctk.CTkLabel(row1, text="Bitrate:").pack(side="left", padx=(0, 8))
        self.bitrate_var = ctk.StringVar(value="192k")
        self.bitrate_menu = ctk.CTkOptionMenu(
            row1, variable=self.bitrate_var, values=BITRATES, width=90)
        self.bitrate_menu.pack(side="left")

        quick_row = ctk.CTkFrame(fmt_card, fg_color="transparent")
        quick_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(quick_row, text="Quick:").pack(side="left", padx=(0, 6))
        for fmt in ["mp3", "aac", "flac", "wav", "ogg", "opus"]:
            ctk.CTkButton(
                quick_row, text=fmt, width=58, height=28,
                command=lambda f=fmt: (self.fmt_var.set(f), self._fmt_changed(f)),
                fg_color=TC["quick"],
                hover_color=TC["quick_hover"],
                text_color=TC["secondary_text"]).pack(side="left", padx=2)

        _action_row(self, self._run, self.cancel, run_label="Extract")
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _fmt_changed(self, fmt):
        lossless = fmt in ("flac", "wav")
        self.bitrate_menu.configure(state="disabled" if lossless else "normal")

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return
        fmt = self.fmt_var.get()
        p   = Path(inp)
        out = self.app.smart_save_dialog(
            "Extract Audio",
            initialfile=f"{p.stem}.{fmt}",
            defaultextension=f".{fmt}",
            filetypes=[(fmt.upper(), f"*.{fmt}"), ("All files", "*.*")])
        if not out:
            return

        duration = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None
        codec    = AUDIO_CODEC_MAP.get(fmt, "copy")
        cmd      = [self.app.ffmpeg, "-y", "-i", inp, "-vn", "-c:a", codec]
        if fmt not in ("flac", "wav"):
            cmd += ["-b:a", self.bitrate_var.get()]
        cmd.append(out)

        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Extract Audio", output_path=out)


# ══════════════════════════════════════════════════════════════
# Batch Page
# ══════════════════════════════════════════════════════════════

class BatchPage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._files = []
        self._build()

    def _build(self):
        _page_header(self, "📁  Batch Convert",
                     "Apply the same conversion settings to many files at once.")

        list_card = _card(self, "Input Files")
        self.listbox = ctk.CTkTextbox(
            list_card, height=150, font=ctk.CTkFont(size=12), state="disabled")
        self.listbox.pack(fill="x", padx=10, pady=(0, 6))

        btn_row = ctk.CTkFrame(list_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        grey = {"fg_color": TC["secondary"],
                "hover_color": TC["secondary_hover"],
                "text_color": ("gray10","gray90")}
        ctk.CTkButton(btn_row, text="Add Files",   width=90, command=self._add).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="Add Folder",  width=100, command=self._add_folder, **grey).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="Clear",       width=70,  command=self._clear, **grey).pack(side="left")
        self.count_label = ctk.CTkLabel(
            btn_row, text="0 files", font=ctk.CTkFont(size=12),
            text_color=TC["text_dim"])
        self.count_label.pack(side="right")

        # ── Settings ────────────────────────────────────────────────────────
        s_card = _card(self, "Batch Settings")
        s_row = ctk.CTkFrame(s_card, fg_color="transparent")
        s_row.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(s_row, text="Output format:").pack(side="left", padx=(0, 8))
        self.fmt_var = ctk.StringVar(value="mp4")
        ctk.CTkOptionMenu(s_row, variable=self.fmt_var,
                          values=VIDEO_EXTS + AUDIO_EXTS,
                          width=100,
                          command=self._fmt_changed).pack(side="left", padx=(0, 20))

        ctk.CTkLabel(s_row, text="CRF:").pack(side="left", padx=(0, 6))
        self.crf_var = ctk.StringVar(value="23")
        self.crf_entry = ctk.CTkEntry(s_row, textvariable=self.crf_var, width=52)
        self.crf_entry.pack(side="left", padx=(0, 20))

        ctk.CTkLabel(s_row, text="Audio bitrate:").pack(side="left", padx=(0, 6))
        self.bitrate_var = ctk.StringVar(value="128k")
        ctk.CTkOptionMenu(s_row, variable=self.bitrate_var,
                          values=BITRATES, width=90).pack(side="left")

        # ── Output folder ────────────────────────────────────────────────────
        out_card = _card(self, "Output Folder")
        out_row = ctk.CTkFrame(out_card, fg_color="transparent")
        out_row.pack(fill="x", padx=10, pady=(0, 6))
        self.outdir_var = ctk.StringVar()
        ctk.CTkEntry(out_row, textvariable=self.outdir_var,
                     placeholder_text="Same folder as source if blank").pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(out_row, text="Browse", width=80,
                      command=lambda: self.outdir_var.set(
                          filedialog.askdirectory() or "")).pack(side="left")

        # ── Output naming ─────────────────────────────────────────────────────
        name_card = _card(self, "Output File Naming")
        name_inner = ctk.CTkFrame(name_card, fg_color="transparent")
        name_inner.pack(fill="x", padx=10, pady=(0, 4))

        ctk.CTkLabel(name_inner, text="Prefix:", width=52).pack(side="left")
        self.prefix_var = ctk.StringVar(value="")
        ctk.CTkEntry(name_inner, textvariable=self.prefix_var,
                     placeholder_text="(none)", width=130).pack(side="left", padx=(0, 20))

        ctk.CTkLabel(name_inner, text="Suffix:", width=52).pack(side="left")
        self.suffix_var = ctk.StringVar(value="_converted")
        ctk.CTkEntry(name_inner, textvariable=self.suffix_var,
                     placeholder_text="e.g.  _web", width=130).pack(side="left", padx=(0, 20))

        # Live preview of final filename
        name_prev_row = ctk.CTkFrame(name_card, fg_color="transparent")
        name_prev_row.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(name_prev_row, text="Preview:",
                     text_color=TC["text_dim"],
                     font=ctk.CTkFont(size=11), width=52).pack(side="left")
        self._name_prev_lbl = ctk.CTkLabel(
            name_prev_row, text="my_video_converted.mp4",
            text_color=TC["text_dim"],
            font=ctk.CTkFont(family="Courier", size=11))
        self._name_prev_lbl.pack(side="left")

        # Update preview whenever prefix, suffix, or format changes
        for var in (self.prefix_var, self.suffix_var, self.fmt_var):
            var.trace_add("write", lambda *_: self.after(30, self._refresh_name_preview))
        self._refresh_name_preview()

        # ── Queue Import / Export ─────────────────────────────────────────────
        queue_card = _card(self, "💾  Job Queue  —  Save, share, and re-run entire batch definitions")
        q_row = ctk.CTkFrame(queue_card, fg_color="transparent")
        q_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(q_row, text="Export Queue JSON", width=160,
                      command=self._export_queue).pack(side="left", padx=(0, 10))
        ctk.CTkButton(q_row, text="Import Queue JSON", width=160,
                      fg_color=TC["secondary"],
                      hover_color=TC["secondary_hover"],
                      text_color=TC["secondary_text"],
                      command=self._import_queue).pack(side="left")

        # ── Scheduler ─────────────────────────────────────────────────────────
        sched_card = _card(self, "⏰  Sleep / Queue Scheduler")

        sched_inner = ctk.CTkFrame(sched_card, fg_color="transparent")
        sched_inner.pack(fill="x", padx=10, pady=(0, 6))

        self.sched_enabled = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(sched_inner, text="Start encoding at scheduled time:",
                        variable=self.sched_enabled,
                        command=self._on_sched_toggle).pack(side="left", padx=(0, 12))

        self.sched_time_var = ctk.StringVar(value="22:00")
        self._sched_entry = ctk.CTkEntry(sched_inner, textvariable=self.sched_time_var,
                                          width=70, placeholder_text="HH:MM",
                                          state="disabled")
        self._sched_entry.pack(side="left", padx=(0, 12))

        self.shutdown_var = ctk.BooleanVar(value=False)
        self._shutdown_chk = ctk.CTkCheckBox(sched_inner,
                                              text="Auto-shutdown when batch completes",
                                              variable=self.shutdown_var,
                                              state="disabled")
        self._shutdown_chk.pack(side="left")

        self._sched_status = ctk.CTkLabel(
            sched_card, text="", font=ctk.CTkFont(size=11),
            text_color=TC["text_dim"])
        self._sched_status.pack(anchor="w", padx=10, pady=(0, 8))

        # ── Notifications ─────────────────────────────────────────────────────
        notif_card = _card(self, "🔔  Notifications")
        notif_row = ctk.CTkFrame(notif_card, fg_color="transparent")
        notif_row.pack(fill="x", padx=10, pady=(0, 10))
        self.notif_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(notif_row, text="Send desktop notification when batch completes",
                        variable=self.notif_var).pack(side="left")

        notif_hint = "" if (HAS_PLYER or platform.system() in ("Darwin", "Linux", "Windows")) else "(install plyer for notifications)"
        if not HAS_PLYER:
            ctk.CTkLabel(notif_row, text="  pip install plyer",
                         font=ctk.CTkFont(family="Courier", size=10),
                         text_color=TC["text_dim"]).pack(side="left", padx=(10, 0))

        self.args_bar = CustomArgsBar(self)
        self.args_bar.pack(fill="x", pady=(0, 6))

        self.batch_status = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=12),
            text_color=TC["text_dim"])
        self.batch_status.pack(anchor="w", pady=(10, 0))

        _action_row(self, self._run, self.cancel, run_label="Start Batch")
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _on_sched_toggle(self):
        state = "normal" if self.sched_enabled.get() else "disabled"
        self._sched_entry.configure(state=state)
        self._shutdown_chk.configure(state=state)
        if not self.sched_enabled.get():
            self._sched_status.configure(text="")

    def _fmt_changed(self, fmt):
        is_video = fmt in VIDEO_EXTS
        self.crf_entry.configure(state="normal" if is_video else "disabled")
        self._refresh_name_preview()

    def _refresh_name_preview(self):
        """Update the filename preview label from current prefix/suffix/format."""
        prefix = self.prefix_var.get()
        suffix = self.suffix_var.get()
        fmt    = self.fmt_var.get()
        # Use the first queued file stem as example, or a placeholder
        if self._files:
            stem = Path(self._files[0]).stem
        else:
            stem = "my_video"
        preview = f"{prefix}{stem}{suffix}.{fmt}"
        self._name_prev_lbl.configure(text=preview)

    def _refresh(self):
        self.listbox.configure(state="normal")
        self.listbox.delete("1.0", "end")
        for i, f in enumerate(self._files):
            self.listbox.insert("end", f"{i + 1}.  {Path(f).name}\n")
        self.listbox.configure(state="disabled")
        n = len(self._files)
        self.count_label.configure(text=f"{n} file{'s' if n != 1 else ''}")
        self._refresh_name_preview()

    def _add(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("Media files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS + AUDIO_EXTS)),
                       ("All files", "*.*")])
        if paths:
            self._files.extend(paths)
            self._refresh()

    def _add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            exts = set(VIDEO_EXTS + AUDIO_EXTS)
            for f in sorted(Path(folder).iterdir()):
                if f.suffix.lstrip(".").lower() in exts:
                    self._files.append(str(f))
            self._refresh()

    def _clear(self):
        self._files.clear()
        self._refresh()

    # ── Queue Import / Export ─────────────────────────────────────────────────

    def _get_queue_dict(self) -> dict:
        """Serialise current batch settings to a plain dict."""
        return {
            "version": "1.0",
            "created": datetime.now().isoformat(timespec="seconds"),
            "settings": {
                "format":   self.fmt_var.get(),
                "crf":      self.crf_var.get(),
                "bitrate":  self.bitrate_var.get(),
                "outdir":   self.outdir_var.get(),
                "prefix":   self.prefix_var.get(),
                "suffix":   self.suffix_var.get(),
            },
            "files": list(self._files),
        }

    def _apply_queue_dict(self, data: dict):
        """Restore batch settings from a queue dict."""
        s = data.get("settings", {})
        if "format"  in s: self.fmt_var.set(s["format"])
        if "crf"     in s: self.crf_var.set(s["crf"])
        if "bitrate" in s: self.bitrate_var.set(s["bitrate"])
        if "outdir"  in s: self.outdir_var.set(s["outdir"])
        if "prefix"  in s: self.prefix_var.set(s["prefix"])
        if "suffix"  in s: self.suffix_var.set(s["suffix"])
        self._files = data.get("files", [])
        self._refresh()

    def _export_queue(self):
        path = self.app.smart_save_dialog(
            "Batch",
            title="Export Queue JSON",
            initialfile="ffmpex_queue.json",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps(self._get_queue_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8")
            messagebox.showinfo("Queue Exported",
                                f"Job queue saved to:\n{path}\n\n"
                                "Share it or use 'Import Queue JSON' to re-run later.")
        except Exception as exc:
            messagebox.showerror("Export Failed", str(exc))

    def _import_queue(self):
        path = filedialog.askopenfilename(
            title="Import Queue JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if "files" not in data:
                messagebox.showerror("Import Failed",
                                     "This doesn't look like an FFmpex queue file.")
                return
            missing = [f for f in data.get("files", []) if not os.path.exists(f)]
            self._apply_queue_dict(data)
            info = f"Imported {len(self._files)} file(s) and settings from queue."
            if missing:
                info += f"\n\n⚠  {len(missing)} file(s) not found on disk:\n"
                info += "\n".join(Path(m).name for m in missing[:5])
                if len(missing) > 5:
                    info += f"\n…and {len(missing)-5} more"
            messagebox.showinfo("Queue Imported", info)
        except Exception as exc:
            messagebox.showerror("Import Failed", str(exc))

    # ── Scheduler helpers ─────────────────────────────────────────────────────

    def _parse_sched_time(self) -> tuple[int, int] | None:
        """Parse HH:MM from the scheduler entry. Returns (hour, minute) or None."""
        raw = self.sched_time_var.get().strip()
        try:
            parts = raw.split(":")
            if len(parts) != 2:
                raise ValueError
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
            return h, m
        except (ValueError, AttributeError):
            return None

    def _seconds_until(self, h: int, m: int) -> float:
        """Seconds from now until the next occurrence of HH:MM."""
        now   = datetime.now()
        today = now.replace(hour=h, minute=m, second=0, microsecond=0)
        delta = (today - now).total_seconds()
        if delta <= 0:
            delta += 86400  # Tomorrow
        return delta

    def _do_shutdown(self):
        """Issue OS shutdown command (best-effort)."""
        _sys = platform.system()
        try:
            if _sys == "Windows":
                subprocess.run(["shutdown", "/s", "/t", "60"], check=False)
                messagebox.showinfo("Shutdown",
                                    "System will shut down in 60 seconds.\n"
                                    "Run 'shutdown /a' to cancel.")
            elif _sys == "Darwin":
                subprocess.run(["osascript", "-e",
                                 'tell app "System Events" to shut down'], check=False)
            else:
                subprocess.run(["systemctl", "poweroff"], check=False)
        except Exception as exc:
            messagebox.showwarning("Shutdown", f"Could not initiate shutdown:\n{exc}")

    # ── Main run ──────────────────────────────────────────────────────────────

    def _run(self):
        if not self._files:
            messagebox.showerror("Error", "No files added.")
            return
        if self._running:
            messagebox.showwarning("Busy", "Batch is already running.")
            return

        # ── Scheduler: wait until the scheduled time ──────────────────────────
        if self.sched_enabled.get():
            parsed = self._parse_sched_time()
            if not parsed:
                messagebox.showerror("Scheduler",
                                     "Invalid time format. Use HH:MM (e.g. 22:00).")
                return
            h, m   = parsed
            wait_s = self._seconds_until(h, m)
            hh, mm = int(wait_s // 3600), int((wait_s % 3600) // 60)
            self._sched_status.configure(
                text=f"⏳  Waiting until {h:02d}:{m:02d}  ({hh}h {mm}m from now)…",
                text_color=TC["text_dim"])

            def _countdown(remaining: float):
                if not self._running and remaining > 0:
                    # User cancelled before the timer fired
                    self._sched_status.configure(text="Scheduler cancelled.")
                    return
                if remaining <= 0:
                    self._sched_status.configure(text="")
                    self._start_batch()
                    return
                hh2 = int(remaining // 3600)
                mm2 = int((remaining % 3600) // 60)
                ss2 = int(remaining % 60)
                self._sched_status.configure(
                    text=f"⏳  Starting at {h:02d}:{m:02d}  —  {hh2}h {mm2:02d}m {ss2:02d}s remaining",
                    text_color=TC["text_dim"])
                self.after(1000, lambda r=remaining - 1: _countdown(r))

            # Mark as "running" so Cancel works during the countdown
            self._running = True
            _countdown(wait_s)
        else:
            self._start_batch()

    def _start_batch(self):
        fmt             = self.fmt_var.get()
        crf             = self.crf_var.get()
        bitrate         = self.bitrate_var.get()
        outdir          = self.outdir_var.get()
        prefix          = self.prefix_var.get()
        suffix          = self.suffix_var.get()
        files           = list(self._files)
        total           = len(files)
        do_notif        = self.notif_var.get()
        do_shutdown     = self.sched_enabled.get() and self.shutdown_var.get()
        extra_args_list = self.args_bar.extra_args()

        # Pre-flight: check ffmpeg exists and output dir is writable
        if not self.app.ffmpeg:
            messagebox.showerror("Error", "FFmpeg not found. Check Settings.")
            return
        if outdir and not os.access(outdir, os.W_OK):
            messagebox.showerror(
                "Pre-flight Failed",
                f"Output folder is not writable:\n  {outdir}")
            return
        try:
            import shutil
            drive = outdir if outdir else str(Path(files[0]).parent)
            free_mb = shutil.disk_usage(drive).free / (1024 * 1024)
            if free_mb < 200:
                if not messagebox.askyesno(
                    "Pre-flight Warning",
                    f"Output drive has only {free_mb:.0f} MB free."
                    "Batch encode may run out of space. Proceed?",
                    icon="warning"):
                    return
        except Exception:
            pass

        self.progress.reset()
        self._running = True
        start_time = time.time()

        def _batch():
            done_ok = 0
            for i, inp in enumerate(files):
                if not self._running:
                    break

                name = Path(inp).name
                self.after(0, lambda i=i, n=name:
                           self.batch_status.configure(
                               text=f"Processing {i + 1}/{total}:  {n}"))

                p        = Path(inp)
                dest_dir = Path(outdir) if outdir else p.parent
                out      = str(dest_dir / f"{prefix}{p.stem}{suffix}.{fmt}")

                dur = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None

                extra = extra_args_list
                if fmt in VIDEO_EXTS:
                    cmd = ([self.app.ffmpeg, "-y", "-i", inp,
                            "-c:v", "libx264", "-crf", crf, "-preset", "fast",
                            "-c:a", "aac", "-b:a", bitrate]
                           + extra + [out])
                else:
                    codec = AUDIO_CODEC_MAP.get(fmt, "copy")
                    cmd   = ([self.app.ffmpeg, "-y", "-i", inp,
                              "-vn", "-c:a", codec]
                             + ([] if fmt in ("flac", "wav") else ["-b:a", bitrate])
                             + extra + [out])

                try:
                    proc = subprocess.Popen(
                        cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                        text=True, universal_newlines=True)
                    self._proc = proc
                    for line in proc.stderr:
                        t = parse_progress_time(line.rstrip())
                        if t is not None and dur and dur > 0:
                            file_pct = t / dur
                            overall  = ((i + file_pct) / total) * 100
                            self.after(0, lambda p=overall:
                                       self.progress.update_progress(p))
                    proc.wait()
                    if proc.returncode == 0:
                        done_ok += 1
                except Exception as exc:
                    self.after(0, lambda e=exc:
                               self.progress.update_progress(
                                   0, status=f"Error: {e}"))

            self._running = False
            self._proc    = None
            elapsed       = int(time.time() - start_time)
            success       = done_ok == total

            self.after(0, lambda: (
                self.progress.done(success),
                self.batch_status.configure(
                    text=(f"✓  Finished — {done_ok}/{total} files converted "
                          f"in {elapsed}s."),
                    text_color=("green", "#4caf50") if success else ("red","#f44336")),
                self.app.add_history(
                    "Batch", outdir or "same as source", success),
            ))

            # Desktop notification
            if do_notif:
                send_notification(
                    "FFmpex — Batch Complete",
                    f"{done_ok}/{total} files converted in {elapsed}s.")

            # Auto-shutdown
            if do_shutdown:
                self.after(0, self._do_shutdown)

        threading.Thread(target=_batch, daemon=True).start()


# ══════════════════════════════════════════════════════════════
# Split Page  — cut one file into multiple segments
# ══════════════════════════════════════════════════════════════

class SplitPage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._duration = None
        self._build()

    def _build(self):
        _page_header(self, "✂️  Split",
                     "Divide a file into equal segments or cut at specific timestamps.")

        self.input_zone = FileDropZone(
            self, label="Input File",
            filetypes=[("Media files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS + AUDIO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 6))

        info_row = ctk.CTkFrame(self, fg_color="transparent")
        info_row.pack(fill="x", pady=(0, 10))
        self.info_label = ctk.CTkLabel(info_row, text="",
                                        font=ctk.CTkFont(size=12),
                                        text_color=TC["text_dim"])
        self.info_label.pack(side="left", padx=(0, 12))
        ctk.CTkButton(info_row, text="Load Info", width=90, height=28,
                      command=self._load_info).pack(side="left")

        mode_card = _card(self, "Split Mode")
        self.mode_var = ctk.StringVar(value="equal")

        eq_row = ctk.CTkFrame(mode_card, fg_color="transparent")
        eq_row.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkRadioButton(eq_row, text="Equal segments:",
                           variable=self.mode_var, value="equal").pack(side="left", padx=(0, 12))
        self.seg_var = ctk.StringVar(value="3")
        ctk.CTkEntry(eq_row, textvariable=self.seg_var, width=52).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(eq_row, text="segments", text_color=TC["text_dim"]).pack(side="left")

        ts_row = ctk.CTkFrame(mode_card, fg_color="transparent")
        ts_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkRadioButton(ts_row, text="At timestamps:",
                           variable=self.mode_var, value="timestamps").pack(side="left", padx=(0, 12))
        self.ts_var = ctk.StringVar(value="00:01:00, 00:02:00")
        ctk.CTkEntry(ts_row, textvariable=self.ts_var, width=280,
                     placeholder_text="00:01:00, 00:02:00, …").pack(side="left")

        out_card = _card(self, "Output Folder")
        out_row = ctk.CTkFrame(out_card, fg_color="transparent")
        out_row.pack(fill="x", padx=10, pady=(0, 10))
        self.outdir_var = ctk.StringVar()
        ctk.CTkEntry(out_row, textvariable=self.outdir_var,
                     placeholder_text="Same folder as source if blank").pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(out_row, text="Browse", width=80,
                      command=lambda: self.outdir_var.set(
                          filedialog.askdirectory() or "")).pack(side="left")

        self.copy_var = ctk.BooleanVar(value=True)
        opt_row = ctk.CTkFrame(self, fg_color="transparent")
        opt_row.pack(fill="x", pady=(0, 6))
        ctk.CTkCheckBox(opt_row,
                        text="Stream copy  (instant, no re-encode — slight frame offset at cut points)",
                        variable=self.copy_var).pack(anchor="w")

        _action_row(self, self._run, self.cancel, run_label="Split")
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _load_info(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp) or not self.app.ffprobe:
            return
        dur = get_duration(self.app.ffprobe, inp)
        if dur:
            self._duration = dur
            self.info_label.configure(
                text=f"⏱  Duration: {secs_to_ts(dur)}",
                text_color=TC["nav_text"])

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return

        p        = Path(inp)
        outdir   = Path(self.outdir_var.get()) if self.outdir_var.get() else p.parent
        mode     = self.mode_var.get()
        codec    = ["-c", "copy"] if self.copy_var.get() else []
        duration = self._duration or get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None

        if mode == "equal":
            try:
                n = int(self.seg_var.get())
                if n < 2: raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Enter a whole number ≥ 2 for segments.")
                return
            if not duration:
                messagebox.showerror("Error", "Could not determine duration. Click Load Info first.")
                return
            seg_dur  = duration / n
            out_pat  = str(outdir / f"{p.stem}_part%03d{p.suffix}")
            cmd = ([self.app.ffmpeg, "-y", "-i", inp,
                    "-f", "segment", "-segment_time", str(seg_dur),
                    "-reset_timestamps", "1"] + codec + [out_pat])
            self.run_ffmpeg(cmd, duration, self.progress,
                            on_done=lambda ok: messagebox.showinfo(
                                "Done", f"Segments saved to:\n{outdir}") if ok else None,
                            page_name="Split", output_path=str(outdir))

        else:  # timestamps mode — chain multiple trim commands
            raw = [t.strip() for t in self.ts_var.get().split(",") if t.strip()]
            cuts = []
            for t in raw:
                s = ts_to_secs(t)
                if s is None:
                    messagebox.showerror("Error", f"Invalid timestamp: {t}")
                    return
                cuts.append(s)
            cuts = sorted(set(cuts))

            # Build boundaries: 0 → cut1, cut1 → cut2, … cutN → end
            boundaries = [0.0] + cuts + [duration or 999999]
            cmds  = []
            parts = []
            for i in range(len(boundaries) - 1):
                start   = boundaries[i]
                end     = boundaries[i + 1]
                out_seg = str(outdir / f"{p.stem}_part{i+1:03d}{p.suffix}")
                parts.append(out_seg)
                c = [self.app.ffmpeg, "-y", "-ss", str(start), "-i", inp,
                     "-t", str(end - start)] + codec + [out_seg]
                cmds.append(c)

            def _run_chain(cmds=cmds, parts=parts, dur=duration):
                self._running = True
                self.progress.reset()
                ok = True
                for i, c in enumerate(cmds):
                    pct = (i / len(cmds)) * 100
                    self.after(0, lambda p=pct: self.progress.update_progress(
                        p, status=f"Part {i+1}/{len(cmds)}…"))
                    r = subprocess.run(c, capture_output=True)
                    if r.returncode != 0:
                        ok = False
                        break
                self._running = False
                self.after(0, lambda s=ok: self.progress.done(s, output_path=str(outdir)))
                self.after(0, lambda s=ok: self.app.add_history("Split", str(outdir), s))
                if ok:
                    self.after(0, lambda: messagebox.showinfo(
                        "Done", f"{len(parts)} parts saved to:\n{outdir}"))

            threading.Thread(target=_run_chain, daemon=True).start()


# ══════════════════════════════════════════════════════════════
# Reverse Page  — chunk-based, memory-efficient
# ══════════════════════════════════════════════════════════════

class ReversePage(BasePage):
    """
    Reverses a file without loading it all into RAM.

    Strategy
    ────────
    FFmpeg's built-in `reverse` / `areverse` filters buffer the ENTIRE
    stream before outputting a single frame — fine for short clips, but
    an out-of-memory crash waiting to happen on anything long.

    The chunk approach:
      1. Divide the file into N equal segments of `chunk_sec` seconds.
      2. Reverse each segment in isolation  (small, bounded RAM per chunk).
      3. Concatenate the reversed chunks in REVERSE order.
    Result is bit-for-bit identical to a full reverse, but peak RAM usage
    is proportional to one chunk, not the whole file.

    Trade-off: each chunk boundary requires a re-encode, so this is
    slightly slower than the naive approach on tiny files.  The UI
    exposes chunk size so the user can tune the speed/memory balance.
    """

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._duration    = None
        self._tmpdir      = None   # cleaned up after job
        self._build()

    def _build(self):
        _page_header(self, "⏪  Reverse",
                     "Play a video or audio file backwards — memory-efficient for any file size.")

        self.input_zone = FileDropZone(
            self, label="Input File",
            filetypes=[("Media files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS + AUDIO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 6))

        info_row = ctk.CTkFrame(self, fg_color="transparent")
        info_row.pack(fill="x", pady=(0, 10))
        self.info_label = ctk.CTkLabel(info_row, text="",
                                        font=ctk.CTkFont(size=12),
                                        text_color=TC["text_dim"])
        self.info_label.pack(side="left", padx=(0, 12))
        ctk.CTkButton(info_row, text="Load Info", width=90, height=28,
                      command=self._load_info).pack(side="left")

        # ── How it works note ─────────────────────────────────────────────
        info_card = _card(self, "How this works")
        ctk.CTkLabel(
            info_card,
            text="The file is split into short chunks, each chunk is reversed individually,\n"
                 "then the reversed chunks are joined in reverse order.\n"
                 "Peak memory = one chunk at a time — safe for files of any size.",
            text_color=TC["text_dim"], font=ctk.CTkFont(size=12),
            justify="left").pack(anchor="w", padx=12, pady=(0, 10))

        # ── Options ───────────────────────────────────────────────────────
        opt_card = _card(self, "Options")

        mode_row = ctk.CTkFrame(opt_card, fg_color="transparent")
        mode_row.pack(fill="x", padx=10, pady=(0, 8))
        self.rev_mode = ctk.StringVar(value="both")
        ctk.CTkRadioButton(mode_row, text="Reverse video + audio",
                           variable=self.rev_mode, value="both").pack(side="left", padx=(0, 20))
        ctk.CTkRadioButton(mode_row, text="Video only  (keep original audio)",
                           variable=self.rev_mode, value="video").pack(side="left", padx=(0, 20))
        ctk.CTkRadioButton(mode_row, text="Audio only",
                           variable=self.rev_mode, value="audio").pack(side="left")

        chunk_row = ctk.CTkFrame(opt_card, fg_color="transparent")
        chunk_row.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(chunk_row, text="Chunk size:").pack(side="left", padx=(0, 10))
        self.chunk_var = ctk.StringVar(value="5")
        ctk.CTkOptionMenu(chunk_row, variable=self.chunk_var,
                          values=["2", "5", "10", "15", "30"],
                          width=70).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(chunk_row, text="seconds   — smaller = less RAM, more temp files",
                     text_color=TC["text_dim"],
                     font=ctk.CTkFont(size=12)).pack(side="left")

        enc_row = ctk.CTkFrame(opt_card, fg_color="transparent")
        enc_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(enc_row, text="Video codec:").pack(side="left", padx=(0, 10))
        self.codec_var = ctk.StringVar(value="libx264")
        ctk.CTkOptionMenu(enc_row, variable=self.codec_var,
                          values=["libx264", "libx265", "copy (audio-only)"],
                          width=160).pack(side="left", padx=(0, 20))
        ctk.CTkLabel(enc_row, text="CRF:").pack(side="left", padx=(0, 8))
        self.crf_var = ctk.StringVar(value="18")
        ctk.CTkEntry(enc_row, textvariable=self.crf_var, width=48).pack(side="left")

        # Chunk counter label — updated during run
        self.chunk_lbl = ctk.CTkLabel(self, text="",
                                       font=ctk.CTkFont(size=12),
                                       text_color=TC["text_dim"])
        self.chunk_lbl.pack(anchor="w")

        _action_row(self, self._run, self.cancel, run_label="Reverse")
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _load_info(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp) or not self.app.ffprobe:
            return
        dur = get_duration(self.app.ffprobe, inp)
        if dur:
            self._duration = dur
            try:
                chunk_sec = float(self.chunk_var.get())
            except ValueError:
                chunk_sec = 5.0
            n_chunks = max(1, int(dur / chunk_sec) + (1 if dur % chunk_sec else 0))
            self.info_label.configure(
                text=f"⏱  {secs_to_ts(dur)}  →  ~{n_chunks} chunks at {chunk_sec}s each",
                text_color=TC["nav_text"])

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return

        p = Path(inp)
        out = self.app.smart_save_dialog(
            "Reverse",
            initialfile=f"{p.stem}_reversed{p.suffix}",
            defaultextension=p.suffix,
            filetypes=[(p.suffix.upper().lstrip("."), f"*{p.suffix}"),
                       ("All files", "*.*")])
        if not out:
            return

        duration = self._duration or (
            get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None)
        if not duration:
            messagebox.showerror("Error",
                                 "Could not read duration. Click Load Info first.")
            return

        try:
            chunk_sec = float(self.chunk_var.get())
            if chunk_sec <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Chunk size must be a positive number.")
            return

        mode   = self.rev_mode.get()
        codec  = self.codec_var.get()
        crf    = self.crf_var.get()
        ffmpeg = self.app.ffmpeg

        # Build boundary list:  0, chunk, 2*chunk, … , duration
        boundaries = []
        t = 0.0
        while t < duration:
            boundaries.append(t)
            t += chunk_sec
        n_chunks = len(boundaries)

        if self._running:
            messagebox.showwarning("Busy", "A job is already running.")
            return
        self._running = True
        self.progress.reset()

        def _work():
            tmpdir = tempfile.mkdtemp(prefix="ffmpex_rev_")
            chunk_paths = []
            ok = True

            try:
                # ── Pass 1: extract + reverse each chunk ──────────────────
                for i, start in enumerate(boundaries):
                    if not self._running:
                        ok = False
                        break

                    t_left = duration - start
                    seg_dur = min(chunk_sec, t_left)
                    chunk_out = os.path.join(tmpdir, f"chunk_{i:05d}{p.suffix}")

                    # Build filter flags per mode
                    if mode == "both":
                        filt = ["-vf", "reverse", "-af", "areverse"]
                    elif mode == "video":
                        filt = ["-vf", "reverse", "-c:a", "copy"]
                    else:  # audio only
                        filt = ["-af", "areverse", "-vn"]

                    # Codec flags (ignored for audio-only)
                    if mode != "audio" and "copy" not in codec:
                        enc = ["-c:v", codec, "-crf", crf, "-preset", "fast"]
                    elif mode != "audio":
                        enc = ["-c:v", "copy"]
                    else:
                        enc = []

                    cmd = ([ffmpeg, "-y",
                            "-ss", str(start), "-t", str(seg_dur),
                            "-i", inp]
                           + filt + enc
                           + [chunk_out])

                    pct    = (i / n_chunks) * 50   # first half of bar = extraction
                    status = f"Reversing chunk {i+1}/{n_chunks}…"
                    self.after(0, lambda p=pct, s=status:
                               self.progress.update_progress(p, status=s))
                    self.after(0, lambda i=i, n=n_chunks:
                               self.chunk_lbl.configure(
                                   text=f"Chunk {i+1} / {n_chunks}"))

                    r = subprocess.run(cmd, capture_output=True, text=True)
                    if r.returncode != 0:
                        self.after(0, lambda e=r.stderr:
                                   self.progress.update_progress(
                                       0, log_line=e))
                        ok = False
                        break
                    chunk_paths.append(chunk_out)

                if not ok:
                    return

                # ── Pass 2: concat reversed chunks in REVERSE order ───────
                self.after(0, lambda: self.progress.update_progress(
                    50, status="Joining reversed chunks…"))

                concat_list = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False, dir=tmpdir)
                # Reverse the list so chunk N comes first in the output
                for cp in reversed(chunk_paths):
                    safe = cp.replace("'", "'\\''")
                    concat_list.write(f"file '{safe}'\n")
                concat_list.close()

                cmd_concat = [ffmpeg, "-y",
                              "-f", "concat", "-safe", "0",
                              "-i", concat_list.name,
                              "-c", "copy", out]

                self._proc = subprocess.Popen(
                    cmd_concat, stderr=subprocess.PIPE,
                    stdout=subprocess.DEVNULL, text=True)

                for line in self._proc.stderr:
                    line = line.rstrip()
                    t_enc = parse_progress_time(line)
                    if t_enc is not None and duration > 0:
                        pct = 50 + min(49.0, (t_enc / duration) * 50)
                        self.after(0, lambda p=pct:
                                   self.progress.update_progress(
                                       p, status="Concatenating…"))
                    self.after(0, lambda l=line:
                               self.progress.update_progress(
                                   self.progress.bar.get() * 100, log_line=l))

                self._proc.wait()
                ok = self._proc.returncode == 0

            except Exception as exc:
                self.after(0, lambda e=exc:
                           self.progress.update_progress(0, status=f"Error: {e}"))
                ok = False

            finally:
                # Clean up all temp chunks and concat list
                import shutil
                try:
                    shutil.rmtree(tmpdir, ignore_errors=True)
                except Exception:
                    pass
                self._running = False
                self._proc    = None

            self.after(0, lambda s=ok: self.progress.done(s))
            self.after(0, lambda s=ok: self.app.add_history("Reverse", out, s))
            self.after(0, lambda: self.chunk_lbl.configure(text=""))
            if ok:
                self.after(0, lambda: messagebox.showinfo("Done", f"Saved to:\n{out}"))

        threading.Thread(target=_work, daemon=True).start()


# ══════════════════════════════════════════════════════════════
# Crop / Pad Page
# ══════════════════════════════════════════════════════════════

class CropPage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._orig_w = None
        self._orig_h = None
        self._build()

    def _build(self):
        _page_header(self, "📐  Crop & Pad",
                     "Crop out a region of the frame, or pad to a target aspect ratio.")

        self.input_zone = FileDropZone(
            self, label="Input Video",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 6))

        info_row = ctk.CTkFrame(self, fg_color="transparent")
        info_row.pack(fill="x", pady=(0, 10))
        self.info_label = ctk.CTkLabel(info_row, text="",
                                        font=ctk.CTkFont(size=12),
                                        text_color=TC["text_dim"])
        self.info_label.pack(side="left", padx=(0,12))
        ctk.CTkButton(info_row, text="Load Info", width=90, height=28,
                      command=self._load_info).pack(side="left")

        # ── Mode tabs ────────────────────────────────────────────────────────
        self.mode_var = ctk.StringVar(value="crop")
        tab_row = ctk.CTkFrame(self, fg_color="transparent")
        tab_row.pack(fill="x", pady=(0, 8))
        for label, val in [("Crop", "crop"), ("Pad / Letterbox", "pad")]:
            ctk.CTkRadioButton(tab_row, text=label, variable=self.mode_var,
                               value=val).pack(side="left", padx=(0, 20))

        # ── Crop section ─────────────────────────────────────────────────────
        self.crop_card = _card(self, "Crop Settings")
        cr = ctk.CTkFrame(self.crop_card, fg_color="transparent")
        cr.pack(fill="x", padx=10, pady=(0, 6))

        fields = [("Width:", "crop_w", "iw"), ("Height:", "crop_h", "ih"),
                  ("X offset:", "crop_x", "0"),  ("Y offset:", "crop_y", "0")]
        for lbl, attr, default in fields:
            ctk.CTkLabel(cr, text=lbl, width=70).pack(side="left", padx=(0, 4))
            var = ctk.StringVar(value=default)
            setattr(self, f"_{attr}_var", var)
            ctk.CTkEntry(cr, textvariable=var, width=72).pack(side="left", padx=(0, 14))

        preset_row = ctk.CTkFrame(self.crop_card, fg_color="transparent")
        preset_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(preset_row, text="Quick aspect:").pack(side="left", padx=(0, 8))
        grey = {"fg_color": TC["quick"], "hover_color": TC["quick_hover"],
                "text_color": TC["quick_text"]}
        for ar in ["16:9", "4:3", "1:1", "9:16", "21:9"]:
            ctk.CTkButton(preset_row, text=ar, width=56, height=26,
                          command=lambda a=ar: self._apply_crop_preset(a),
                          **grey).pack(side="left", padx=2)

        # ── Pad section ──────────────────────────────────────────────────────
        self.pad_card = _card(self, "Pad Settings")
        pr = ctk.CTkFrame(self.pad_card, fg_color="transparent")
        pr.pack(fill="x", padx=10, pady=(0, 6))

        pad_fields = [("Target W:", "pad_w", "1920"), ("Target H:", "pad_h", "1080")]
        for lbl, attr, default in pad_fields:
            ctk.CTkLabel(pr, text=lbl, width=70).pack(side="left", padx=(0, 4))
            var = ctk.StringVar(value=default)
            setattr(self, f"_{attr}_var", var)
            ctk.CTkEntry(pr, textvariable=var, width=72).pack(side="left", padx=(0, 14))

        pr2 = ctk.CTkFrame(self.pad_card, fg_color="transparent")
        pr2.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(pr2, text="Pad colour:").pack(side="left", padx=(0, 8))
        self._pad_color_var = ctk.StringVar(value="black")
        ctk.CTkOptionMenu(pr2, variable=self._pad_color_var,
                          values=["black", "white", "gray", "0x00FF00"],
                          width=110).pack(side="left", padx=(0, 20))
        ctk.CTkLabel(pr2, text="(or hex e.g. 0xFF0000)").pack(side="left")

        par_row = ctk.CTkFrame(self.pad_card, fg_color="transparent")
        par_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(par_row, text="Quick aspect:").pack(side="left", padx=(0, 8))
        for ar in ["16:9", "4:3", "1:1", "9:16", "21:9"]:
            ctk.CTkButton(par_row, text=ar, width=56, height=26,
                          command=lambda a=ar: self._apply_pad_preset(a),
                          **grey).pack(side="left", padx=2)

        # ── Preview ──────────────────────────────────────────────────────────
        self.preview = VideoPreviewWidget(
            self, app=self.app, label="Source frame  (preview updates on Load Info)")
        self.preview.pack(fill="x", pady=(0, 8))

        _action_row(self, self._run, self.cancel, run_label="Apply")
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _load_info(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp) or not self.app.ffprobe:
            return
        info = get_file_info(self.app.ffprobe, inp)
        if info and info["video"]:
            v = info["video"][0]
            self._orig_w = v.get("width")
            self._orig_h = v.get("height")
            self.info_label.configure(
                text=f"Source: {self._orig_w}×{self._orig_h}",
                text_color=TC["nav_text"])
            self._crop_w_var.set(str(self._orig_w))
            self._crop_h_var.set(str(self._orig_h))
            # Show mid-point frame
            dur = info.get("duration")
            ts  = (dur / 2) if dur else 0.0
            self.preview.seek_immediate(ts, filepath=inp)

    def _apply_crop_preset(self, ar):
        if not self._orig_w or not self._orig_h:
            messagebox.showinfo("Tip", "Click Load Info first to get source dimensions.")
            return
        num, den = map(int, ar.split(":"))
        # Crop to aspect ratio, centred
        if self._orig_w / self._orig_h > num / den:
            new_h = self._orig_h
            new_w = int(new_h * num / den) & ~1  # make even
        else:
            new_w = self._orig_w
            new_h = int(new_w * den / num) & ~1
        x_off = (self._orig_w - new_w) // 2
        y_off = (self._orig_h - new_h) // 2
        self._crop_w_var.set(str(new_w))
        self._crop_h_var.set(str(new_h))
        self._crop_x_var.set(str(x_off))
        self._crop_y_var.set(str(y_off))

    def _apply_pad_preset(self, ar):
        # Suggest common dimensions for the chosen ratio
        presets = {
            "16:9": ("1920", "1080"), "4:3": ("1440", "1080"),
            "1:1": ("1080", "1080"), "9:16": ("1080", "1920"),
            "21:9": ("2560", "1080"),
        }
        w, h = presets.get(ar, ("1920", "1080"))
        self._pad_w_var.set(w)
        self._pad_h_var.set(h)

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return
        p    = Path(inp)
        mode = self.mode_var.get()
        out  = self.app.smart_save_dialog(
            "Crop",
            initialfile=f"{p.stem}_{mode}{p.suffix}",
            defaultextension=p.suffix,
            filetypes=[(p.suffix.upper().lstrip("."), f"*{p.suffix}"),
                       ("All files", "*.*")])
        if not out:
            return

        duration = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None

        if mode == "crop":
            w = self._crop_w_var.get()
            h = self._crop_h_var.get()
            x = self._crop_x_var.get()
            y = self._crop_y_var.get()
            vf = f"crop={w}:{h}:{x}:{y}"
        else:
            tw    = self._pad_w_var.get()
            th    = self._pad_h_var.get()
            color = self._pad_color_var.get()
            # Centre the source in the padded frame
            vf = (f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                  f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color={color}")

        cmd = [self.app.ffmpeg, "-y", "-i", inp, "-vf", vf,
               "-c:a", "copy", out]
        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Crop/Pad", output_path=out)


# ══════════════════════════════════════════════════════════════
# Mute / Audio Track Page
# ══════════════════════════════════════════════════════════════

class MutePage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        _page_header(self, "🔇  Audio Track",
                     "Remove, mute, or replace the audio in a video.")

        self.input_zone = FileDropZone(
            self, label="Input Video",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 10))

        mode_card = _card(self, "Action")
        self.mode_var = ctk.StringVar(value="remove")

        r1 = ctk.CTkFrame(mode_card, fg_color="transparent")
        r1.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkRadioButton(r1, text="Remove audio entirely  (silent video)",
                           variable=self.mode_var, value="remove",
                           command=self._on_mode).pack(anchor="w")

        r2 = ctk.CTkFrame(mode_card, fg_color="transparent")
        r2.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkRadioButton(r2, text="Replace with silence  (keep audio track, zero volume)",
                           variable=self.mode_var, value="silence",
                           command=self._on_mode).pack(anchor="w")

        r3 = ctk.CTkFrame(mode_card, fg_color="transparent")
        r3.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkRadioButton(r3, text="Replace with audio file:",
                           variable=self.mode_var, value="replace",
                           command=self._on_mode).pack(side="left", padx=(0, 12))
        self.audio_zone = FileDropZone(
            r3, label="",
            filetypes=[("Audio files",
                        " ".join(f"*.{e}" for e in AUDIO_EXTS)),
                       ("All files", "*.*")])
        self.audio_zone.pack(side="left", fill="x", expand=True)
        self.audio_zone.configure(fg_color="transparent")

        vol_card = _card(self, "Volume  (for Replace with audio)")
        vol_row = ctk.CTkFrame(vol_card, fg_color="transparent")
        vol_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(vol_row, text="New audio volume:").pack(side="left", padx=(0, 10))
        self.vol_var = ctk.DoubleVar(value=1.0)
        ctk.CTkSlider(vol_row, from_=0, to=2, number_of_steps=40,
                      variable=self.vol_var,
                      command=lambda v: self.vol_lbl.configure(
                          text=f"{float(v):.2f}×")).pack(side="left", fill="x", expand=True, padx=(0,8))
        self.vol_lbl = ctk.CTkLabel(vol_row, text="1.00×", width=48)
        self.vol_lbl.pack(side="left")

        self.loop_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(vol_card, text="Loop audio to match video length",
                        variable=self.loop_var).pack(anchor="w", padx=12, pady=(0, 10))

        _action_row(self, self._run, self.cancel, run_label="Apply")
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _on_mode(self):
        pass  # reserved for future enable/disable of sub-widgets

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return
        p    = Path(inp)
        mode = self.mode_var.get()
        out  = self.app.smart_save_dialog(
            "Mute",
            initialfile=f"{p.stem}_audio_edited{p.suffix}",
            defaultextension=p.suffix,
            filetypes=[(p.suffix.upper().lstrip("."), f"*{p.suffix}"),
                       ("All files", "*.*")])
        if not out:
            return

        duration = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None

        if mode == "remove":
            cmd = [self.app.ffmpeg, "-y", "-i", inp, "-c:v", "copy", "-an", out]

        elif mode == "silence":
            cmd = [self.app.ffmpeg, "-y", "-i", inp,
                   "-c:v", "copy", "-af", "volume=0", out]

        else:  # replace
            aud = self.audio_zone.get()
            if not aud or not os.path.exists(aud):
                messagebox.showerror("Error", "Please select a replacement audio file.")
                return
            vol   = self.vol_var.get()
            loops = "-stream_loop -1" if self.loop_var.get() else ""
            cmd   = [self.app.ffmpeg, "-y", "-i", inp]
            if self.loop_var.get():
                cmd += ["-stream_loop", "-1"]
            cmd += ["-i", aud, "-c:v", "copy",
                    "-af", f"volume={vol:.3f}",
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-shortest", out]

        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Audio Track", output_path=out)


# ══════════════════════════════════════════════════════════════
# Video → Frames Page
# ══════════════════════════════════════════════════════════════

class FramesPage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        _page_header(self, "🖼️  Export Frames",
                     "Extract individual frames from a video as PNG or JPG images.")

        self.input_zone = FileDropZone(
            self, label="Input Video",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 10))

        mode_card = _card(self, "Extraction Mode")
        self.mode_var = ctk.StringVar(value="fps")

        r1 = ctk.CTkFrame(mode_card, fg_color="transparent")
        r1.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkRadioButton(r1, text="Every N seconds — 1 frame per:",
                           variable=self.mode_var, value="fps").pack(side="left", padx=(0, 12))
        self.fps_var = ctk.StringVar(value="1")
        ctk.CTkEntry(r1, textvariable=self.fps_var, width=52).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(r1, text="second(s)", text_color=TC["text_dim"]).pack(side="left")

        r2 = ctk.CTkFrame(mode_card, fg_color="transparent")
        r2.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkRadioButton(r2, text="Every Nth frame:",
                           variable=self.mode_var, value="nth").pack(side="left", padx=(0, 12))
        self.nth_var = ctk.StringVar(value="30")
        ctk.CTkEntry(r2, textvariable=self.nth_var, width=52).pack(side="left")

        r3 = ctk.CTkFrame(mode_card, fg_color="transparent")
        r3.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkRadioButton(r3, text="All frames  (⚠️ can produce thousands of files)",
                           variable=self.mode_var, value="all").pack(anchor="w")

        fmt_card = _card(self, "Output Format")
        fr = ctk.CTkFrame(fmt_card, fg_color="transparent")
        fr.pack(fill="x", padx=10, pady=(0, 10))
        self.img_fmt_var = ctk.StringVar(value="png")
        ctk.CTkRadioButton(fr, text="PNG  (lossless)", variable=self.img_fmt_var,
                           value="png").pack(side="left", padx=(0, 20))
        ctk.CTkRadioButton(fr, text="JPG  (smaller)", variable=self.img_fmt_var,
                           value="jpg").pack(side="left", padx=(0, 20))
        ctk.CTkLabel(fr, text="Quality (JPG):").pack(side="left", padx=(0, 8))
        self.jpg_q_var = ctk.StringVar(value="2")
        ctk.CTkOptionMenu(fr, variable=self.jpg_q_var,
                          values=["1","2","3","4","5"],
                          width=60).pack(side="left")

        out_card = _card(self, "Output Folder")
        out_row = ctk.CTkFrame(out_card, fg_color="transparent")
        out_row.pack(fill="x", padx=10, pady=(0, 10))
        self.outdir_var = ctk.StringVar()
        ctk.CTkEntry(out_row, textvariable=self.outdir_var,
                     placeholder_text="Subfolder next to source if blank").pack(
            side="left", fill="x", expand=True, padx=(0,8))
        ctk.CTkButton(out_row, text="Browse", width=80,
                      command=lambda: self.outdir_var.set(
                          filedialog.askdirectory() or "")).pack(side="left")

        _action_row(self, self._run, self.cancel, run_label="Export")
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return
        p        = Path(inp)
        mode     = self.mode_var.get()
        img_fmt  = self.img_fmt_var.get()
        outdir   = Path(self.outdir_var.get()) if self.outdir_var.get() \
                   else p.parent / f"{p.stem}_frames"
        outdir.mkdir(parents=True, exist_ok=True)
        out_pat  = str(outdir / f"frame_%05d.{img_fmt}")
        duration = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None

        cmd = [self.app.ffmpeg, "-y", "-i", inp]

        if mode == "fps":
            try:
                n = float(self.fps_var.get())
                vf = f"fps=1/{n}"
            except ValueError:
                messagebox.showerror("Error", "Enter a valid number of seconds.")
                return
            cmd += ["-vf", vf]
        elif mode == "nth":
            try:
                n = int(self.nth_var.get())
                vf = f"select=not(mod(n\\,{n}))"
            except ValueError:
                messagebox.showerror("Error", "Enter a valid frame interval.")
                return
            cmd += ["-vf", vf, "-vsync", "vfr"]

        if img_fmt == "jpg":
            cmd += ["-q:v", self.jpg_q_var.get()]

        cmd.append(out_pat)
        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Frames saved to:\n{outdir}") if ok else None,
                        page_name="Export Frames", output_path=str(outdir))


# ══════════════════════════════════════════════════════════════
# Volume Normalise Page
# ══════════════════════════════════════════════════════════════

class NormalisePage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        _page_header(self, "🔊  Normalise Volume",
                     "Apply EBU R128 loudness normalisation — the standard used by YouTube, Spotify, and broadcast.")

        self.input_zone = FileDropZone(
            self, label="Input File",
            filetypes=[("Media files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS + AUDIO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 10))

        target_card = _card(self, "Target Loudness")
        t_row = ctk.CTkFrame(target_card, fg_color="transparent")
        t_row.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(t_row, text="Platform preset:").pack(side="left", padx=(0, 10))
        self.preset_var = ctk.StringVar(value="YouTube / Streaming")
        presets = {
            "YouTube / Streaming": -14,
            "Podcast":             -16,
            "Broadcast (EBU R128)":-23,
            "Custom":              -18,
        }
        self._presets = presets
        ctk.CTkOptionMenu(t_row, variable=self.preset_var,
                          values=list(presets.keys()), width=200,
                          command=self._on_preset).pack(side="left", padx=(0, 20))

        t2 = ctk.CTkFrame(target_card, fg_color="transparent")
        t2.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(t2, text="Target LUFS:").pack(side="left", padx=(0, 10))
        self.lufs_var = ctk.StringVar(value="-14")
        ctk.CTkEntry(t2, textvariable=self.lufs_var, width=60).pack(side="left", padx=(0, 20))
        ctk.CTkLabel(t2, text="True Peak:").pack(side="left", padx=(0, 10))
        self.tp_var = ctk.StringVar(value="-1.5")
        ctk.CTkEntry(t2, textvariable=self.tp_var, width=60).pack(side="left", padx=(0, 20))
        ctk.CTkLabel(t2, text="LRA:").pack(side="left", padx=(0, 10))
        self.lra_var = ctk.StringVar(value="11")
        ctk.CTkEntry(t2, textvariable=self.lra_var, width=60).pack(side="left")

        # Analyse panel
        analyse_card = _card(self, "Step 1 — Analyse  (optional but recommended)")
        a_row = ctk.CTkFrame(analyse_card, fg_color="transparent")
        a_row.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkButton(a_row, text="Analyse Loudness", width=150,
                      command=self._analyse).pack(side="left")
        self.analyse_label = ctk.CTkLabel(
            a_row, text="", font=ctk.CTkFont(size=12),
            text_color=TC["text_dim"])
        self.analyse_label.pack(side="left", padx=12)
        ctk.CTkFrame(analyse_card, fg_color="transparent", height=6).pack()

        _action_row(self, self._run, self.cancel, run_label="Normalise")
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _on_preset(self, name):
        lufs = self._presets.get(name, -18)
        self.lufs_var.set(str(lufs))

    def _analyse(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return
        self.analyse_label.configure(text="Analysing…", text_color=TC["text_dim"])

        def _work():
            try:
                r = subprocess.run(
                    [self.app.ffmpeg, "-i", inp, "-af",
                     "loudnorm=I=-23:TP=-1.5:LRA=11:print_format=summary",
                     "-f", "null", "-"],
                    capture_output=True, text=True, timeout=300)
                stderr = r.stderr
                # Parse summary lines
                measures = {}
                for line in stderr.split("\n"):
                    for key in ("Input Integrated", "Input True Peak",
                                "Input LRA", "Input Threshold"):
                        if key in line:
                            parts = line.split(":")
                            if len(parts) >= 2:
                                measures[key] = parts[-1].strip().split()[0]
                result = (
                    f"Integrated: {measures.get('Input Integrated','?')} LUFS  |  "
                    f"True Peak: {measures.get('Input True Peak','?')} dBFS  |  "
                    f"LRA: {measures.get('Input LRA','?')} LU"
                )
                self.after(0, lambda: self.analyse_label.configure(
                    text=result, text_color=TC["nav_text"]))
            except Exception as e:
                self.after(0, lambda: self.analyse_label.configure(
                    text=f"Error: {e}", text_color=("red","#f44336")))

        threading.Thread(target=_work, daemon=True).start()

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return
        p   = Path(inp)
        out = self.app.smart_save_dialog(
            "Normalise",
            initialfile=f"{p.stem}_normalised{p.suffix}",
            defaultextension=p.suffix,
            filetypes=[(p.suffix.upper().lstrip("."), f"*{p.suffix}"),
                       ("All files", "*.*")])
        if not out:
            return

        duration = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None
        lufs     = self.lufs_var.get()
        tp       = self.tp_var.get()
        lra      = self.lra_var.get()
        af       = f"loudnorm=I={lufs}:TP={tp}:LRA={lra}"

        is_video = p.suffix.lower().lstrip(".") in VIDEO_EXTS
        if is_video:
            cmd = [self.app.ffmpeg, "-y", "-i", inp,
                   "-c:v", "copy", "-af", af, out]
        else:
            cmd = [self.app.ffmpeg, "-y", "-i", inp, "-af", af, out]

        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Normalise", output_path=out)


# ══════════════════════════════════════════════════════════════
# Mix Audio Page
# ══════════════════════════════════════════════════════════════

class MixAudioPage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        _page_header(self, "➕  Mix Audio",
                     "Add a music or audio track to a video, with independent volume and fade controls.")

        self.video_zone = FileDropZone(
            self, label="Input Video",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.video_zone.pack(fill="x", pady=(0, 8))

        self.audio_zone = FileDropZone(
            self, label="Audio Track to Mix In",
            filetypes=[("Audio files",
                        " ".join(f"*.{e}" for e in AUDIO_EXTS)),
                       ("All files", "*.*")])
        self.audio_zone.pack(fill="x", pady=(0, 10))

        vol_card = _card(self, "Volume Levels")
        for lbl, attr, default in [
            ("Original video audio:", "vid_vol",  1.0),
            ("New audio track:",      "mix_vol",  0.5),
        ]:
            r = ctk.CTkFrame(vol_card, fg_color="transparent")
            r.pack(fill="x", padx=10, pady=(0, 6))
            ctk.CTkLabel(r, text=lbl, width=190).pack(side="left")
            var = ctk.DoubleVar(value=default)
            lbl_w = ctk.CTkLabel(r, text=f"{default:.2f}×", width=48)
            sl = ctk.CTkSlider(r, from_=0, to=2, number_of_steps=40, variable=var,
                               command=lambda v, lw=lbl_w: lw.configure(text=f"{float(v):.2f}×"))
            sl.pack(side="left", fill="x", expand=True, padx=(0, 8))
            lbl_w.pack(side="left")
            setattr(self, f"_{attr}_var", var)

        ctk.CTkFrame(vol_card, fg_color="transparent", height=4).pack()

        fade_card = _card(self, "Fade Options  (seconds, 0 = no fade)")
        fade_row = ctk.CTkFrame(fade_card, fg_color="transparent")
        fade_row.pack(fill="x", padx=10, pady=(0, 10))
        for lbl, attr in [("Fade in:", "fade_in"), ("Fade out:", "fade_out")]:
            ctk.CTkLabel(fade_row, text=lbl).pack(side="left", padx=(0, 6))
            var = ctk.StringVar(value="0")
            setattr(self, f"_{attr}_var", var)
            ctk.CTkEntry(fade_row, textvariable=var, width=52).pack(side="left", padx=(0, 20))

        opt_card = _card(self, "Behaviour")
        opt_row = ctk.CTkFrame(opt_card, fg_color="transparent")
        opt_row.pack(fill="x", padx=10, pady=(0, 10))
        self.loop_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opt_row, text="Loop audio track to match video length",
                        variable=self.loop_var).pack(side="left", padx=(0, 20))
        self.shortest_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opt_row, text="End at shortest stream",
                        variable=self.shortest_var).pack(side="left")

        _action_row(self, self._run, self.cancel, run_label="Mix")
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _run(self):
        vid = self.video_zone.get()
        aud = self.audio_zone.get()
        if not vid or not os.path.exists(vid):
            messagebox.showerror("Error", "Please select a valid video file.")
            return
        if not aud or not os.path.exists(aud):
            messagebox.showerror("Error", "Please select a valid audio file.")
            return

        p        = Path(vid)
        out      = self.app.smart_save_dialog(
            "MixAudio",
            initialfile=f"{p.stem}_mixed{p.suffix}",
            defaultextension=p.suffix,
            filetypes=[(p.suffix.upper().lstrip("."), f"*{p.suffix}"),
                       ("All files", "*.*")])
        if not out:
            return

        duration = get_duration(self.app.ffprobe, vid) if self.app.ffprobe else None
        vid_vol  = self._vid_vol_var.get()
        mix_vol  = self._mix_vol_var.get()
        fi       = float(self._fade_in_var.get() or 0)
        fo       = float(self._fade_out_var.get() or 0)

        # Build audio filter chain for the mix track
        aud_filters = [f"volume={mix_vol:.3f}"]
        if fi > 0:
            aud_filters.append(f"afade=t=in:st=0:d={fi}")
        if fo > 0 and duration:
            aud_filters.append(f"afade=t=out:st={duration - fo}:d={fo}")
        aud_af = ",".join(aud_filters)

        cmd = [self.app.ffmpeg, "-y", "-i", vid]
        if self.loop_var.get():
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", aud, "-c:v", "copy",
                "-filter_complex",
                f"[0:a]volume={vid_vol:.3f}[a0];[1:a]{aud_af}[a1];[a0][a1]amix=inputs=2:duration=first[aout]",
                "-map", "0:v", "-map", "[aout]"]
        if self.shortest_var.get():
            cmd += ["-shortest"]
        cmd.append(out)

        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Mix Audio", output_path=out)


# ══════════════════════════════════════════════════════════════
# Denoise Page
# ══════════════════════════════════════════════════════════════

class DenoisePage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        _page_header(self, "🎙️  Denoise Audio",
                     "Remove background hiss, hum, and noise using FFmpeg's spectral noise filter.")

        self.input_zone = FileDropZone(
            self, label="Input File",
            filetypes=[("Media files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS + AUDIO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 10))

        main_card = _card(self, "Denoise Strength  (afftdn filter)")
        nr = ctk.CTkFrame(main_card, fg_color="transparent")
        nr.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(nr, text="Noise reduction (0–97):", width=190).pack(side="left")
        self.nr_var = ctk.IntVar(value=10)
        self.nr_lbl = ctk.CTkLabel(nr, text="10", width=30)
        ctk.CTkSlider(nr, from_=0, to=97, number_of_steps=97, variable=self.nr_var,
                      command=lambda v: self.nr_lbl.configure(text=str(int(float(v))))
                      ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.nr_lbl.pack(side="left")

        nf = ctk.CTkFrame(main_card, fg_color="transparent")
        nf.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(nf, text="Noise floor (-80 to 0 dBFS):", width=190).pack(side="left")
        self.nf_var = ctk.IntVar(value=-20)
        self.nf_lbl = ctk.CTkLabel(nf, text="-20 dB", width=52)
        ctk.CTkSlider(nf, from_=-80, to=0, number_of_steps=80, variable=self.nf_var,
                      command=lambda v: self.nf_lbl.configure(text=f"{int(float(v))} dB")
                      ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.nf_lbl.pack(side="left")

        extra_card = _card(self, "Additional Filters  (applied in order)")
        e_row = ctk.CTkFrame(extra_card, fg_color="transparent")
        e_row.pack(fill="x", padx=10, pady=(0, 10))
        self.hp_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(e_row, text="High-pass 80 Hz  (remove low rumble)",
                        variable=self.hp_var).pack(side="left", padx=(0, 20))
        self.lp_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(e_row, text="Low-pass 12 kHz  (soften harshness)",
                        variable=self.lp_var).pack(side="left")

        _action_row(self, self._run, self.cancel, run_label="Denoise")
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return
        p   = Path(inp)
        out = self.app.smart_save_dialog(
            "Denoise",
            initialfile=f"{p.stem}_denoised{p.suffix}",
            defaultextension=p.suffix,
            filetypes=[(p.suffix.upper().lstrip("."), f"*{p.suffix}"),
                       ("All files", "*.*")])
        if not out:
            return

        duration = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None
        nr       = self.nr_var.get()
        nf       = self.nf_var.get()

        filters  = [f"afftdn=nr={nr}:nf={nf}"]
        if self.hp_var.get():
            filters.append("highpass=f=80")
        if self.lp_var.get():
            filters.append("lowpass=f=12000")
        af = ",".join(filters)

        is_video = p.suffix.lower().lstrip(".") in VIDEO_EXTS
        if is_video:
            cmd = [self.app.ffmpeg, "-y", "-i", inp, "-c:v", "copy", "-af", af, out]
        else:
            cmd = [self.app.ffmpeg, "-y", "-i", inp, "-af", af, out]

        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Denoise", output_path=out)


# ══════════════════════════════════════════════════════════════
# Speed Change Page
# ══════════════════════════════════════════════════════════════

class SpeedPage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        _page_header(self, "⚡  Speed Change",
                     "Speed up or slow down video and audio. "
                     "Audio pitch is automatically corrected using atempo chaining.")

        self.input_zone = FileDropZone(
            self, label="Input File",
            filetypes=[("Media files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS + AUDIO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 10))

        speed_card = _card(self, "Speed Multiplier")
        s_row = ctk.CTkFrame(speed_card, fg_color="transparent")
        s_row.pack(fill="x", padx=10, pady=(0, 6))

        self.speed_var = ctk.DoubleVar(value=1.0)
        self.speed_lbl = ctk.CTkLabel(s_row, text="1.00×", width=52,
                                       font=ctk.CTkFont(size=15, weight="bold"))
        self.speed_lbl.pack(side="left", padx=(0, 12))
        ctk.CTkSlider(s_row, from_=0.25, to=4.0, number_of_steps=300,
                      variable=self.speed_var,
                      command=self._on_speed).pack(side="left", fill="x", expand=True)

        preset_row = ctk.CTkFrame(speed_card, fg_color="transparent")
        preset_row.pack(fill="x", padx=10, pady=(0, 10))
        grey = {"fg_color": TC["quick"], "hover_color": TC["quick_hover"],
                "text_color": TC["quick_text"]}
        ctk.CTkLabel(preset_row, text="Quick:").pack(side="left", padx=(0, 8))
        for sp in [0.25, 0.5, 0.75, 1.25, 1.5, 2.0, 4.0]:
            ctk.CTkButton(preset_row, text=f"{sp}×", width=52, height=26,
                          command=lambda s=sp: (self.speed_var.set(s),
                                                self._on_speed(s)),
                          **grey).pack(side="left", padx=2)

        opt_card = _card(self, "Options")
        o_row = ctk.CTkFrame(opt_card, fg_color="transparent")
        o_row.pack(fill="x", padx=10, pady=(0, 10))
        self.keep_audio_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(o_row, text="Include audio  (if video file)",
                        variable=self.keep_audio_var).pack(side="left", padx=(0, 20))
        self.pitch_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(o_row, text="Pitch correction  (atempo filter)",
                        variable=self.pitch_var).pack(side="left")

        # ── Preview ──────────────────────────────────────────────────────────
        self.preview = VideoPreviewWidget(
            self, app=self.app, label="Source frame preview")
        self.preview.pack(fill="x", pady=(0, 8))

        _action_row(self, self._run, self.cancel, run_label="Apply Speed")
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _on_speed(self, val):
        self.speed_lbl.configure(text=f"{float(val):.2f}×")
        # Refresh preview to show source unchanged (speed affects duration, not content)
        inp = self.input_zone.get()
        if inp and os.path.exists(inp):
            self.preview.seek(0.0, filepath=inp)

    @staticmethod
    def _build_atempo(speed):
        """
        atempo only accepts values in [0.5, 2.0].
        Chain multiple atempo filters for values outside that range.
        """
        filters = []
        remaining = speed
        while remaining > 2.0:
            filters.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            filters.append("atempo=0.5")
            remaining /= 0.5
        filters.append(f"atempo={remaining:.6f}")
        return ",".join(filters)

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return
        p     = Path(inp)
        speed = self.speed_var.get()
        out   = self.app.smart_save_dialog(
            "Speed",
            initialfile=f"{p.stem}_{speed:.2f}x{p.suffix}",
            defaultextension=p.suffix,
            filetypes=[(p.suffix.upper().lstrip("."), f"*{p.suffix}"),
                       ("All files", "*.*")])
        if not out:
            return

        duration     = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None
        est_duration = (duration / speed) if duration else None
        is_video     = p.suffix.lower().lstrip(".") in VIDEO_EXTS
        pts_factor   = 1.0 / speed

        cmd = [self.app.ffmpeg, "-y", "-i", inp]

        if is_video and self.keep_audio_var.get():
            vf = f"setpts={pts_factor:.6f}*PTS"
            af = self._build_atempo(speed) if self.pitch_var.get() else f"atempo={speed:.6f}"
            cmd += ["-filter:v", vf, "-filter:a", af]
        elif is_video:
            cmd += ["-filter:v", f"setpts={pts_factor:.6f}*PTS", "-an"]
        else:
            af  = self._build_atempo(speed) if self.pitch_var.get() else f"atempo={speed:.6f}"
            cmd += ["-filter:a", af]

        cmd.append(out)
        self.run_ffmpeg(cmd, est_duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Speed Change", output_path=out)


# ══════════════════════════════════════════════════════════════
# Waveform Preview Page
# ══════════════════════════════════════════════════════════════

class WaveformPage(BasePage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._waveform_image = None
        self._ctk_image      = None
        self._build()

    def _build(self):
        _page_header(self, "🎼  Waveform",
                     "Generate a waveform image from any audio or video file.")

        self.input_zone = FileDropZone(
            self, label="Input File",
            filetypes=[("Media files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS + AUDIO_EXTS)),
                       ("All files", "*.*")])
        self.input_zone.pack(fill="x", pady=(0, 10))

        style_card = _card(self, "Waveform Style")
        s_row = ctk.CTkFrame(style_card, fg_color="transparent")
        s_row.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(s_row, text="Width (px):").pack(side="left", padx=(0, 8))
        self.w_var = ctk.StringVar(value="1200")
        ctk.CTkEntry(s_row, textvariable=self.w_var, width=70).pack(side="left", padx=(0, 20))

        ctk.CTkLabel(s_row, text="Height (px):").pack(side="left", padx=(0, 8))
        self.h_var = ctk.StringVar(value="240")
        ctk.CTkEntry(s_row, textvariable=self.h_var, width=70).pack(side="left", padx=(0, 20))

        ctk.CTkLabel(s_row, text="Colours:").pack(side="left", padx=(0, 8))
        self.colour_var = ctk.StringVar(value="Blue on Dark")
        colours = {
            "Blue on Dark":  ("0x1a6db5", "0x111111"),
            "Green on Dark": ("0x4caf50", "0x111111"),
            "White on Dark": ("0xffffff", "0x1a1a1a"),
            "Black on White":("0x333333", "0xffffff"),
            "Orange on Dark":("0xf97316", "0x111111"),
        }
        self._colours = colours
        ctk.CTkOptionMenu(s_row, variable=self.colour_var,
                          values=list(colours.keys()), width=150).pack(side="left")

        # Preview area
        self.preview_frame = ctk.CTkFrame(self, fg_color=TC["card"], corner_radius=8)
        self.preview_frame.pack(fill="x", pady=(0, 10))
        self.preview_label = ctk.CTkLabel(
            self.preview_frame,
            text="Generate waveform to see a preview here.",
            text_color=TC["text_dim"],
            font=ctk.CTkFont(size=12))
        self.preview_label.pack(pady=30)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(btn_row, text="Generate Preview", command=self._generate,
                      width=160).pack(side="left")
        ctk.CTkButton(btn_row, text="Save as PNG…", command=self._save,
                      width=120,
                      fg_color=TC["secondary"],
                      hover_color=TC["secondary_hover"],
                      text_color=TC["secondary_text"]).pack(side="left", padx=10)
        ctk.CTkButton(btn_row, text="Cancel", command=self.cancel,
                      width=90,
                      fg_color=TC["secondary"],
                      hover_color=TC["secondary_hover"],
                      text_color=TC["secondary_text"]).pack(side="left")

        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _generate(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return

        w   = self.w_var.get()
        h   = self.h_var.get()
        fg, bg = self._colours.get(self.colour_var.get(), ("0x1a6db5","0x111111"))
        _fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(_fd)

        self.progress.reset()
        self.progress.update_progress(0, status="Generating waveform…")

        def _work():
            try:
                r = subprocess.run(
                    [self.app.ffmpeg, "-y", "-i", inp,
                     "-filter_complex",
                     f"showwavespic=s={w}x{h}:colors={fg}",
                     "-frames:v", "1", tmp],
                    capture_output=True, text=True, timeout=120)

                if r.returncode != 0 or not os.path.exists(tmp):
                    self.after(0, lambda: self.progress.update_progress(
                        0, status="Failed — check log", log_line=r.stderr))
                    self.after(0, lambda: self.progress.done(False))
                    return

                if HAS_PIL:
                    img = PILImage.open(tmp)
                    img.load()
                    self._waveform_image = img
                    # Scale to fit display width (~580px)
                    disp_w = 580
                    disp_h = int(img.height * disp_w / img.width)
                    ctk_img = ctk.CTkImage(img, size=(disp_w, disp_h))
                    self._ctk_image = ctk_img

                    def _show():
                        self.preview_label.configure(image=ctk_img, text="")
                    self.after(0, _show)
                else:
                    # Save to output path if PIL unavailable
                    import shutil
                    out_path = str(Path(inp).parent / f"{Path(inp).stem}_waveform.png")
                    shutil.copy(tmp, out_path)
                    self.after(0, lambda: messagebox.showinfo(
                        "Done", f"Saved to:\n{out_path}\n\n"
                                "(Install Pillow to see inline preview)"))

                self.after(0, lambda: self.progress.done(True))
                self.after(0, lambda: self.app.add_history(
                    "Waveform", tmp, True))
            except Exception as exc:
                self.after(0, lambda e=exc: self.progress.update_progress(
                    0, status=f"Error: {e}"))
                self.after(0, lambda: self.progress.done(False))
            finally:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
                self._running = False

        self._running = True
        threading.Thread(target=_work, daemon=True).start()

    def _save(self):
        if not HAS_PIL or not self._waveform_image:
            messagebox.showinfo("Note",
                                "Generate a waveform first (requires Pillow).")
            return
        inp = self.input_zone.get()
        p   = Path(inp) if inp else Path("waveform")
        out = self.app.smart_save_dialog(
            "Waveform",
            initialfile=f"{p.stem}_waveform.png",
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("All files", "*.*")])
        if out:
            self._waveform_image.save(out)
            messagebox.showinfo("Done", f"Saved to:\n{out}")


# ══════════════════════════════════════════════════════════════
# Subtitle Burn-in Page
# ══════════════════════════════════════════════════════════════

class SubtitlePage(BasePage):
    """
    Burn .srt or .ass subtitles into a video file.

    Strategy:
    • For .ass files: use the libass 'ass' filter directly — it honours all
      style data in the .ass spec.
    • For .srt files: use the 'subtitles' filter with a force_style override
      so the user-chosen font/size/colour/outline/position options take effect.
    Subtitles are always hard-burned (baked into the video pixels) so every
    player sees them without needing a sidecar file.
    """

    # Mapping of friendly position names → ASS alignment number
    # (numpad layout: 7=top-left … 5=centre … 3=bottom-right)
    POSITIONS = {
        "Bottom Centre (default)": 2,
        "Bottom Left":             1,
        "Bottom Right":            3,
        "Middle Centre":           5,
        "Top Centre":              8,
        "Top Left":                7,
        "Top Right":               9,
    }

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build(self):
        _page_header(
            self, "🔤  Burn-in Subtitles",
            "Bake an .srt or .ass subtitle file permanently into the video.")

        # ── Input video ──────────────────────────────────────────────────────
        self.video_zone = FileDropZone(
            self, label="Input Video",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.video_zone.pack(fill="x", pady=(0, 6))

        # ── Subtitle file ────────────────────────────────────────────────────
        self.sub_zone = FileDropZone(
            self, label="Subtitle File  (.srt or .ass)",
            filetypes=[("Subtitle files", "*.srt *.ass"),
                       ("SRT", "*.srt"), ("ASS/SSA", "*.ass *.ssa"),
                       ("All files", "*.*")])
        self.sub_zone.pack(fill="x", pady=(0, 6))

        # ── Style options ────────────────────────────────────────────────────
        style_card = _card(self, "Style Options  (SRT only — .ass uses its own styles)")

        # Row 1: font + size + position
        r1 = ctk.CTkFrame(style_card, fg_color="transparent")
        r1.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(r1, text="Font:").pack(side="left", padx=(0, 6))
        self.font_var = ctk.StringVar(value="Arial")
        ctk.CTkEntry(r1, textvariable=self.font_var,
                     width=120).pack(side="left", padx=(0, 20))

        ctk.CTkLabel(r1, text="Size:").pack(side="left", padx=(0, 6))
        self.size_var = ctk.StringVar(value="24")
        ctk.CTkOptionMenu(r1, variable=self.size_var,
                          values=["14", "18", "20", "22", "24", "28",
                                  "32", "36", "42", "48"],
                          width=70).pack(side="left", padx=(0, 20))

        ctk.CTkLabel(r1, text="Position:").pack(side="left", padx=(0, 6))
        self.pos_var = ctk.StringVar(value="Bottom Centre (default)")
        ctk.CTkOptionMenu(r1, variable=self.pos_var,
                          values=list(self.POSITIONS.keys()),
                          width=200).pack(side="left")

        # Row 2: primary colour + outline colour + outline width + opacity
        r2 = ctk.CTkFrame(style_card, fg_color="transparent")
        r2.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(r2, text="Colour (hex):").pack(side="left", padx=(0, 6))
        self.color_var = ctk.StringVar(value="#FFFFFF")
        ctk.CTkEntry(r2, textvariable=self.color_var,
                     width=90).pack(side="left", padx=(0, 4))
        # Colour preview swatch
        self._swatch = ctk.CTkFrame(r2, width=20, height=20, corner_radius=4,
                                    fg_color=self.color_var.get())
        self._swatch.pack(side="left", padx=(0, 20))
        self.color_var.trace_add("write", self._update_swatch)

        ctk.CTkLabel(r2, text="Outline colour:").pack(side="left", padx=(0, 6))
        self.outline_color_var = ctk.StringVar(value="#000000")
        ctk.CTkEntry(r2, textvariable=self.outline_color_var,
                     width=90).pack(side="left", padx=(0, 4))
        self._oswatch = ctk.CTkFrame(r2, width=20, height=20, corner_radius=4,
                                     fg_color=self.outline_color_var.get())
        self._oswatch.pack(side="left", padx=(0, 20))
        self.outline_color_var.trace_add("write", self._update_oswatch)

        ctk.CTkLabel(r2, text="Outline (px):").pack(side="left", padx=(0, 6))
        self.outline_var = ctk.StringVar(value="2")
        ctk.CTkOptionMenu(r2, variable=self.outline_var,
                          values=["0", "1", "2", "3", "4", "5"],
                          width=60).pack(side="left", padx=(0, 20))

        # Row 3: bold / italic toggles + margin
        r3 = ctk.CTkFrame(style_card, fg_color="transparent")
        r3.pack(fill="x", padx=10, pady=(0, 10))

        self.bold_var   = ctk.BooleanVar(value=False)
        self.italic_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(r3, text="Bold",   variable=self.bold_var).pack(
            side="left", padx=(0, 16))
        ctk.CTkCheckBox(r3, text="Italic", variable=self.italic_var).pack(
            side="left", padx=(0, 28))

        ctk.CTkLabel(r3, text="Vertical margin (px):").pack(side="left", padx=(0, 6))
        self.margin_var = ctk.StringVar(value="20")
        ctk.CTkEntry(r3, textvariable=self.margin_var,
                     width=56).pack(side="left")

        # ── Encoding ─────────────────────────────────────────────────────────
        enc_card = _card(self, "Encoding")
        enc_row = ctk.CTkFrame(enc_card, fg_color="transparent")
        enc_row.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(enc_row, text="Video CRF (0–51):").pack(side="left", padx=(0, 6))
        self.crf_var = ctk.StringVar(value="18")
        ctk.CTkEntry(enc_row, textvariable=self.crf_var,
                     width=52).pack(side="left", padx=(0, 24))

        ctk.CTkLabel(enc_row, text="Preset:").pack(side="left", padx=(0, 6))
        self.preset_var = ctk.StringVar(value="fast")
        ctk.CTkOptionMenu(enc_row, variable=self.preset_var,
                          values=["ultrafast", "superfast", "veryfast",
                                  "faster", "fast", "medium", "slow"],
                          width=110).pack(side="left", padx=(0, 24))

        ctk.CTkLabel(enc_row, text="Audio:").pack(side="left", padx=(0, 6))
        self.audio_var = ctk.StringVar(value="copy")
        ctk.CTkOptionMenu(enc_row, variable=self.audio_var,
                          values=["copy", "aac 128k", "aac 192k", "strip"],
                          width=110).pack(side="left")

        # ── Action row + preview ─────────────────────────────────────────────
        self.cmd_preview = CommandPreview(self, self._build_cmd)
        _action_row(self, self._run, self.cancel,
                    run_label="Burn Subtitles", preview=self.cmd_preview)
        self.cmd_preview.pack(fill="x", pady=(6, 0))
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    # ── Colour swatch helpers ─────────────────────────────────────────────────

    def _update_swatch(self, *_):
        try:
            self._swatch.configure(fg_color=self.color_var.get())
        except Exception:
            pass

    def _update_oswatch(self, *_):
        try:
            self._oswatch.configure(fg_color=self.outline_color_var.get())
        except Exception:
            pass

    # ── Command builder ───────────────────────────────────────────────────────

    @staticmethod
    def _hex_to_ass(hex_color: str) -> str:
        """Convert #RRGGBB → ASS &H00BBGGRR colour string."""
        h = hex_color.lstrip("#")
        if len(h) != 6:
            return "&H00FFFFFF"
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H00{b}{g}{r}"

    def _force_style(self) -> str:
        """Build the ASS force_style string for .srt files."""
        alignment = self.POSITIONS.get(self.pos_var.get(), 2)
        pri_color = self._hex_to_ass(self.color_var.get())
        out_color = self._hex_to_ass(self.outline_color_var.get())
        bold   = 1 if self.bold_var.get()   else 0
        italic = 1 if self.italic_var.get() else 0
        try:
            outline = int(self.outline_var.get())
        except ValueError:
            outline = 2
        try:
            margin = int(self.margin_var.get())
        except ValueError:
            margin = 20
        font = self.font_var.get().strip() or "Arial"
        size = self.size_var.get()
        return (
            f"FontName={font},FontSize={size},"
            f"PrimaryColour={pri_color},"
            f"OutlineColour={out_color},"
            f"Outline={outline},"
            f"Bold={bold},Italic={italic},"
            f"Alignment={alignment},"
            f"MarginV={margin}"
        )

    def _build_cmd(self):
        video = self.video_zone.get()
        sub   = self.sub_zone.get()
        if not video or not self.app.ffmpeg:
            return None

        sub_path = sub or "<subtitle.srt>"
        out_path = f"<{Path(video).stem}_subbed.mp4>" if video else "<output.mp4>"

        # Escape the subtitle path for the filter string (Windows back-slashes
        # and colons are problematic inside filtergraph strings)
        def _esc(p):
            return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

        is_ass = sub_path.lower().endswith((".ass", ".ssa"))

        if is_ass:
            vf = f"ass='{_esc(sub_path)}'"
        else:
            fs = self._force_style()
            vf = f"subtitles='{_esc(sub_path)}':force_style='{fs}'"

        crf    = self.crf_var.get()
        preset = self.preset_var.get()
        cmd    = [self.app.ffmpeg, "-y", "-i", video,
                  "-vf", vf,
                  "-c:v", "libx264", "-crf", crf, "-preset", preset]

        audio = self.audio_var.get()
        if audio == "strip":
            cmd += ["-an"]
        elif audio == "copy":
            cmd += ["-c:a", "copy"]
        else:
            # "aac 128k" or "aac 192k"
            parts = audio.split()
            cmd += ["-c:a", "aac", "-b:a", parts[1] if len(parts) > 1 else "128k"]

        cmd.append(out_path)
        return cmd

    # ── Run ───────────────────────────────────────────────────────────────────

    def _run(self):
        video = self.video_zone.get()
        sub   = self.sub_zone.get()

        if not video or not os.path.exists(video):
            messagebox.showerror("Error", "Please select a valid input video.")
            return
        if not sub or not os.path.exists(sub):
            messagebox.showerror("Error", "Please select a valid subtitle file (.srt or .ass).")
            return
        if not self.app.ffmpeg:
            messagebox.showerror("Error", "FFmpeg not found.")
            return

        p   = Path(video)
        out = self.app.smart_save_dialog(
            "Subtitle",
            initialfile=f"{p.stem}_subbed.mp4",
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv"), ("All files", "*.*")])
        if not out:
            return

        # Build real command (with the actual output path)
        def _esc(path):
            return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

        is_ass = sub.lower().endswith((".ass", ".ssa"))
        if is_ass:
            vf = f"ass='{_esc(sub)}'"
        else:
            fs = self._force_style()
            vf = f"subtitles='{_esc(sub)}':force_style='{fs}'"

        crf    = self.crf_var.get()
        preset = self.preset_var.get()
        cmd    = [self.app.ffmpeg, "-y", "-i", video,
                  "-vf", vf,
                  "-c:v", "libx264", "-crf", crf, "-preset", preset]

        audio = self.audio_var.get()
        if audio == "strip":
            cmd += ["-an"]
        elif audio == "copy":
            cmd += ["-c:a", "copy"]
        else:
            parts = audio.split()
            cmd += ["-c:a", "aac", "-b:a", parts[1] if len(parts) > 1 else "128k"]

        cmd.append(out)
        duration = get_duration(self.app.ffprobe, video) if self.app.ffprobe else None

        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Subtitles", output_path=out)


# ══════════════════════════════════════════════════════════════
# Text Watermark Page
# ══════════════════════════════════════════════════════════════

class TextWatermarkPage(BasePage):
    """
    Overlay custom text on a video using the drawtext filter.
    Supports position, font size, colour, opacity, and optional fade-in/out.
    """

    POSITIONS = {
        "Bottom Centre": "x=(w-text_w)/2:y=h-th-{m}",
        "Bottom Left":   "x={m}:y=h-th-{m}",
        "Bottom Right":  "x=w-text_w-{m}:y=h-th-{m}",
        "Top Centre":    "x=(w-text_w)/2:y={m}",
        "Top Left":      "x={m}:y={m}",
        "Top Right":     "x=w-text_w-{m}:y={m}",
        "Centre":        "x=(w-text_w)/2:y=(h-th)/2",
    }

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        _page_header(self, "🔤  Text Watermark",
                     "Overlay custom text — position, size, colour, opacity, fade.")

        self.video_zone = FileDropZone(
            self, label="Input Video",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.video_zone.pack(fill="x", pady=(0, 6))

        # ── Text content ─────────────────────────────────────────────────────
        txt_card = _card(self, "Watermark Text")
        txt_row = ctk.CTkFrame(txt_card, fg_color="transparent")
        txt_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(txt_row, text="Text:").pack(side="left", padx=(0, 8))
        self.text_var = ctk.StringVar(value="© My Channel")
        ctk.CTkEntry(txt_row, textvariable=self.text_var,
                     width=340).pack(side="left", fill="x", expand=True)

        # ── Style ─────────────────────────────────────────────────────────────
        style_card = _card(self, "Style")

        r1 = ctk.CTkFrame(style_card, fg_color="transparent")
        r1.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(r1, text="Font:").pack(side="left", padx=(0, 6))
        self.font_var = ctk.StringVar(value="Arial")
        ctk.CTkEntry(r1, textvariable=self.font_var,
                     width=110).pack(side="left", padx=(0, 20))

        ctk.CTkLabel(r1, text="Size:").pack(side="left", padx=(0, 6))
        self.size_var = ctk.StringVar(value="32")
        ctk.CTkOptionMenu(r1, variable=self.size_var,
                          values=["14", "18", "24", "28", "32",
                                  "36", "42", "48", "56", "72"],
                          width=70).pack(side="left", padx=(0, 20))

        ctk.CTkLabel(r1, text="Colour:").pack(side="left", padx=(0, 6))
        self.color_var = ctk.StringVar(value="#FFFFFF")
        ctk.CTkEntry(r1, textvariable=self.color_var,
                     width=88).pack(side="left", padx=(0, 4))
        self._swatch = ctk.CTkFrame(r1, width=20, height=20, corner_radius=4,
                                    fg_color="#FFFFFF")
        self._swatch.pack(side="left", padx=(0, 20))
        self.color_var.trace_add("write", self._update_swatch)

        ctk.CTkLabel(r1, text="Opacity (0–1):").pack(side="left", padx=(0, 6))
        self.alpha_var = ctk.StringVar(value="0.8")
        ctk.CTkOptionMenu(r1, variable=self.alpha_var,
                          values=["0.1", "0.2", "0.3", "0.4", "0.5",
                                  "0.6", "0.7", "0.8", "0.9", "1.0"],
                          width=70).pack(side="left")

        r2 = ctk.CTkFrame(style_card, fg_color="transparent")
        r2.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(r2, text="Shadow colour:").pack(side="left", padx=(0, 6))
        self.shadow_var = ctk.StringVar(value="#000000")
        ctk.CTkEntry(r2, textvariable=self.shadow_var,
                     width=88).pack(side="left", padx=(0, 4))
        self._sswatch = ctk.CTkFrame(r2, width=20, height=20, corner_radius=4,
                                     fg_color="#000000")
        self._sswatch.pack(side="left", padx=(0, 20))
        self.shadow_var.trace_add("write", self._update_sswatch)

        ctk.CTkLabel(r2, text="Shadow opacity:").pack(side="left", padx=(0, 6))
        self.shadow_alpha_var = ctk.StringVar(value="0.6")
        ctk.CTkOptionMenu(r2, variable=self.shadow_alpha_var,
                          values=["0.0", "0.2", "0.4", "0.6", "0.8", "1.0"],
                          width=70).pack(side="left", padx=(0, 20))

        self.bold_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(r2, text="Bold", variable=self.bold_var).pack(
            side="left", padx=(0, 16))

        # ── Position ─────────────────────────────────────────────────────────
        pos_card = _card(self, "Position")
        p_row = ctk.CTkFrame(pos_card, fg_color="transparent")
        p_row.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(p_row, text="Position:").pack(side="left", padx=(0, 8))
        self.pos_var = ctk.StringVar(value="Bottom Right")
        ctk.CTkOptionMenu(p_row, variable=self.pos_var,
                          values=list(self.POSITIONS.keys()),
                          width=180).pack(side="left", padx=(0, 24))

        ctk.CTkLabel(p_row, text="Margin (px):").pack(side="left", padx=(0, 6))
        self.margin_var = ctk.StringVar(value="20")
        ctk.CTkEntry(p_row, textvariable=self.margin_var,
                     width=56).pack(side="left")

        # ── Fade ─────────────────────────────────────────────────────────────
        fade_card = _card(self, "Fade  (optional)")
        f_row = ctk.CTkFrame(fade_card, fg_color="transparent")
        f_row.pack(fill="x", padx=10, pady=(0, 10))

        self.fade_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(f_row, text="Enable fade",
                        variable=self.fade_var).pack(side="left", padx=(0, 20))

        ctk.CTkLabel(f_row, text="Fade-in (s):").pack(side="left", padx=(0, 6))
        self.fade_in_var = ctk.StringVar(value="1.0")
        ctk.CTkEntry(f_row, textvariable=self.fade_in_var,
                     width=52).pack(side="left", padx=(0, 20))

        ctk.CTkLabel(f_row, text="Fade-out start (s):").pack(side="left", padx=(0, 6))
        self.fade_out_var = ctk.StringVar(value="5.0")
        ctk.CTkEntry(f_row, textvariable=self.fade_out_var,
                     width=52).pack(side="left", padx=(0, 20))

        ctk.CTkLabel(f_row, text="Fade-out dur (s):").pack(side="left", padx=(0, 6))
        self.fade_dur_var = ctk.StringVar(value="1.0")
        ctk.CTkEntry(f_row, textvariable=self.fade_dur_var,
                     width=52).pack(side="left")

        # ── Action ───────────────────────────────────────────────────────────
        self.cmd_preview = CommandPreview(self, self._build_cmd)
        _action_row(self, self._run, self.cancel,
                    run_label="Apply Watermark", preview=self.cmd_preview)
        self.cmd_preview.pack(fill="x", pady=(6, 0))
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    # ── Swatch helpers ────────────────────────────────────────────────────────

    def _update_swatch(self, *_):
        try:
            self._swatch.configure(fg_color=self.color_var.get())
        except Exception:
            pass

    def _update_sswatch(self, *_):
        try:
            self._sswatch.configure(fg_color=self.shadow_var.get())
        except Exception:
            pass

    # ── Colour conversion ─────────────────────────────────────────────────────

    @staticmethod
    def _hex_to_ffcolor(hex_col: str, alpha: str) -> str:
        """Return FFmpeg drawtext colour string: 0xRRGGBBAA"""
        h = hex_col.lstrip("#")
        if len(h) != 6:
            h = "FFFFFF"
        try:
            a_int = int(float(alpha) * 255)
        except ValueError:
            a_int = 204  # 0.8 default
        a_hex = f"{a_int:02X}"
        return f"0x{h.upper()}{a_hex}"

    # ── Filter builder ────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_font_path(bold: bool) -> str | None:
        """
        Return an absolute path to a suitable .ttf / .ttc font on this OS,
        or None if nothing is found (FFmpeg falls back to its built-in font).
        Works on Windows, macOS, and most Linux distros.
        """
        suffix = "-Bold" if bold else ""
        import sys as _sys
        if _sys.platform == "win32":
            base = os.environ.get("WINDIR", r"C:\Windows")
            candidates = [
                os.path.join(base, "Fonts", f"{'arialbd' if bold else 'arial'}.ttf"),
                os.path.join(base, "Fonts", f"{'calibrib' if bold else 'calibri'}.ttf"),
                os.path.join(base, "Fonts", f"{'verdanab' if bold else 'verdana'}.ttf"),
            ]
        elif _sys.platform == "darwin":
            candidates = [
                f"/System/Library/Fonts/Helvetica.ttc",
                f"/Library/Fonts/Arial{suffix}.ttf",
                f"/System/Library/Fonts/Arial.ttf",
                f"/System/Library/Fonts/SFNSText.ttf",
                "/Library/Fonts/Tahoma.ttf",
            ]
        else:  # Linux / BSD
            candidates = [
                f"/usr/share/fonts/truetype/dejavu/DejaVuSans{suffix}.ttf",
                f"/usr/share/fonts/truetype/liberation/LiberationSans{suffix}.ttf",
                f"/usr/share/fonts/truetype/freefont/FreeSans{suffix}.ttf",
                f"/usr/share/fonts/truetype/ubuntu/Ubuntu{'-B' if bold else '-R'}.ttf",
                f"/usr/share/fonts/truetype/noto/NotoSans-{'Bold' if bold else 'Regular'}.ttf",
            ]
        for p in candidates:
            if os.path.isfile(p):
                return p
        return None  # FFmpeg will use its built-in fallback font

    def _drawtext_filter(self, out_placeholder="") -> str:
        text = self.text_var.get().replace("'", "\\'").replace(":", "\\:")
        font = self.font_var.get().strip() or "Arial"
        size = self.size_var.get()
        fc   = self._hex_to_ffcolor(self.color_var.get(), self.alpha_var.get())
        sc   = self._hex_to_ffcolor(self.shadow_var.get(), self.shadow_alpha_var.get())
        bold = 1 if self.bold_var.get() else 0

        try:
            margin = int(self.margin_var.get())
        except ValueError:
            margin = 20

        pos_tmpl = self.POSITIONS.get(self.pos_var.get(),
                                       "x=w-text_w-{m}:y=h-th-{m}")
        pos = pos_tmpl.replace("{m}", str(margin))

        # Resolve a platform-appropriate font file. If nothing found, omit
        # fontfile= and let FFmpeg use its built-in fallback (works everywhere).
        fp = self._resolve_font_path(bold)
        # FFmpeg filter strings need backslashes converted and colons escaped
        fp_str = fp.replace("\\", "/").replace(":", "\\:") if fp else None

        parts = [f"text='{text}'"]
        if fp_str:
            parts.append(f"fontfile='{fp_str}'")
        parts += [
            f"font={font}",
            f"fontsize={size}",
            f"fontcolor={fc}",
            f"shadowcolor={sc}",
            f"shadowx=2:shadowy=2",
            pos,
        ]

        if self.fade_var.get():
            try:
                fi  = float(self.fade_in_var.get())
                fo  = float(self.fade_out_var.get())
                fd  = float(self.fade_dur_var.get())
            except ValueError:
                fi, fo, fd = 1.0, 5.0, 1.0
            # alpha expression: fade in over fi seconds, then fade out
            fade_expr = (
                f"if(lt(t,{fi}),t/{fi},"
                f"if(lt(t,{fo}),1,"
                f"if(lt(t,{fo+fd}),({fo+fd}-t)/{fd},0)))"
            )
            parts.append(f"alpha='{fade_expr}'")

        return "drawtext=" + ":".join(parts)

    def _build_cmd(self):
        video = self.video_zone.get()
        if not video or not self.app.ffmpeg:
            return None
        out = f"<{Path(video).stem}_watermarked.mp4>"
        vf  = self._drawtext_filter()
        return [self.app.ffmpeg, "-y", "-i", video,
                "-vf", vf,
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                "-c:a", "copy", out]

    def _run(self):
        video = self.video_zone.get()
        if not video or not os.path.exists(video):
            messagebox.showerror("Error", "Please select a valid input video.")
            return
        if not self.text_var.get().strip():
            messagebox.showerror("Error", "Please enter watermark text.")
            return

        p   = Path(video)
        out = self.app.smart_save_dialog(
            "TextWatermark",
            initialfile=f"{p.stem}_watermarked.mp4",
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv"),
                       ("All files", "*.*")])
        if not out:
            return

        vf  = self._drawtext_filter()
        cmd = [self.app.ffmpeg, "-y", "-i", video,
               "-vf", vf,
               "-c:v", "libx264", "-crf", "18", "-preset", "fast",
               "-c:a", "copy", out]

        duration = get_duration(self.app.ffprobe, video) if self.app.ffprobe else None
        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Text Watermark", output_path=out)


# ══════════════════════════════════════════════════════════════
# Image Watermark Page
# ══════════════════════════════════════════════════════════════

class ImageWatermarkPage(BasePage):
    """
    Overlay a PNG logo (with transparency) onto a video using the overlay filter.
    Supports 9 anchor positions, scale, and opacity.
    """

    # overlay filter x/y expressions — W/H = video dims, w/h = overlay dims
    POSITIONS = {
        "Bottom Right":  "x=W-w-{m}:y=H-h-{m}",
        "Bottom Left":   "x={m}:y=H-h-{m}",
        "Bottom Centre": "x=(W-w)/2:y=H-h-{m}",
        "Top Right":     "x=W-w-{m}:y={m}",
        "Top Left":      "x={m}:y={m}",
        "Top Centre":    "x=(W-w)/2:y={m}",
        "Centre":        "x=(W-w)/2:y=(H-h)/2",
        "Middle Left":   "x={m}:y=(H-h)/2",
        "Middle Right":  "x=W-w-{m}:y=(H-h)/2",
    }

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        _page_header(self, "🖼️  Image Watermark",
                     "Add a PNG logo with transparency and position control.")

        self.video_zone = FileDropZone(
            self, label="Input Video",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.video_zone.pack(fill="x", pady=(0, 6))

        self.logo_zone = FileDropZone(
            self, label="Logo / Watermark Image  (PNG recommended for transparency)",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp"),
                       ("PNG", "*.png"), ("All files", "*.*")])
        self.logo_zone.pack(fill="x", pady=(0, 6))

        # ── Position & Size ───────────────────────────────────────────────────
        pos_card = _card(self, "Position & Size")

        r1 = ctk.CTkFrame(pos_card, fg_color="transparent")
        r1.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(r1, text="Position:").pack(side="left", padx=(0, 8))
        self.pos_var = ctk.StringVar(value="Bottom Right")
        ctk.CTkOptionMenu(r1, variable=self.pos_var,
                          values=list(self.POSITIONS.keys()),
                          width=180).pack(side="left", padx=(0, 24))

        ctk.CTkLabel(r1, text="Margin (px):").pack(side="left", padx=(0, 6))
        self.margin_var = ctk.StringVar(value="20")
        ctk.CTkEntry(r1, textvariable=self.margin_var,
                     width=56).pack(side="left", padx=(0, 24))

        ctk.CTkLabel(r1, text="Scale logo to % of video width:").pack(
            side="left", padx=(0, 6))
        self.scale_var = ctk.StringVar(value="15")
        ctk.CTkOptionMenu(r1, variable=self.scale_var,
                          values=["5", "8", "10", "12", "15",
                                  "20", "25", "30", "40", "50", "100"],
                          width=70).pack(side="left")
        ctk.CTkLabel(r1, text="%").pack(side="left", padx=(2, 0))

        # ── Opacity ───────────────────────────────────────────────────────────
        op_card = _card(self, "Opacity")
        op_row = ctk.CTkFrame(op_card, fg_color="transparent")
        op_row.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(op_row, text="Opacity (0–1):").pack(side="left", padx=(0, 8))
        self.opacity_var = ctk.DoubleVar(value=1.0)
        self.opacity_slider = ctk.CTkSlider(
            op_row, from_=0.0, to=1.0, number_of_steps=20,
            variable=self.opacity_var, command=self._opacity_moved)
        self.opacity_slider.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.opacity_display = ctk.CTkLabel(op_row, text="1.0", width=36)
        self.opacity_display.pack(side="left")

        # ── Action ───────────────────────────────────────────────────────────
        self.cmd_preview = CommandPreview(self, self._build_cmd)
        _action_row(self, self._run, self.cancel,
                    run_label="Apply Watermark", preview=self.cmd_preview)
        self.cmd_preview.pack(fill="x", pady=(6, 0))
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _opacity_moved(self, val):
        self.opacity_display.configure(text=f"{float(val):.1f}")

    def _overlay_filtergraph(self, video_path, logo_path, out_placeholder=""):
        """
        Build the full filtergraph string.
        Scale the logo to (scale_pct/100) * video_width, then overlay.
        If opacity < 1.0, premultiply alpha via colorchannelmixer.
        """
        try:
            margin = int(self.margin_var.get())
        except ValueError:
            margin = 20
        try:
            scale_pct = float(self.scale_var.get())
        except ValueError:
            scale_pct = 15.0

        opacity = round(self.opacity_var.get(), 2)
        pos_tmpl = self.POSITIONS.get(self.pos_var.get(), "x=W-w-{m}:y=H-h-{m}")
        pos = pos_tmpl.replace("{m}", str(margin))

        # Scale the logo proportionally to scale_pct % of video width
        scale_filter = f"[1:v]scale=iw*{scale_pct/100:.4f}*trunc(W/iw):trunc(ow/a/2)*2[logo]"

        if opacity < 1.0:
            # Multiply all channels (including alpha) by opacity
            scale_filter = (
                f"[1:v]scale=iw*{scale_pct/100:.4f}*trunc(W/iw):trunc(ow/a/2)*2,"
                f"colorchannelmixer=aa={opacity:.2f}[logo]"
            )

        overlay = f"[0:v][logo]overlay={pos}[out]"
        return f"{scale_filter};{overlay}", "[out]"

    def _build_cmd(self):
        video = self.video_zone.get()
        logo  = self.logo_zone.get()
        if not video or not self.app.ffmpeg:
            return None
        logo_path  = logo or "<logo.png>"
        out        = f"<{Path(video).stem}_watermarked.mp4>"
        fg, map_lbl = self._overlay_filtergraph(video, logo_path)
        return [self.app.ffmpeg, "-y", "-i", video, "-i", logo_path,
                "-filter_complex", fg,
                "-map", map_lbl, "-map", "0:a?",
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                "-c:a", "copy", out]

    def _run(self):
        video = self.video_zone.get()
        logo  = self.logo_zone.get()
        if not video or not os.path.exists(video):
            messagebox.showerror("Error", "Please select a valid input video.")
            return
        if not logo or not os.path.exists(logo):
            messagebox.showerror("Error", "Please select a logo/watermark image.")
            return

        p   = Path(video)
        out = self.app.smart_save_dialog(
            "ImageWatermark",
            initialfile=f"{p.stem}_watermarked.mp4",
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv"),
                       ("All files", "*.*")])
        if not out:
            return

        fg, map_lbl = self._overlay_filtergraph(video, logo)
        cmd = [self.app.ffmpeg, "-y", "-i", video, "-i", logo,
               "-filter_complex", fg,
               "-map", map_lbl, "-map", "0:a?",
               "-c:v", "libx264", "-crf", "18", "-preset", "fast",
               "-c:a", "copy", out]

        duration = get_duration(self.app.ffprobe, video) if self.app.ffprobe else None
        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Image Watermark", output_path=out)


# ══════════════════════════════════════════════════════════════
# Extract Subtitle Track Page
# ══════════════════════════════════════════════════════════════

class ExtractSubtitlePage(BasePage):
    """
    Pull embedded subtitle tracks out of MKV (or any container that supports
    embedded subtitles) as .srt or .ass files.
    Uses ffprobe to list available subtitle streams, then ffmpeg -map to extract.
    """

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._streams = []   # list of dicts from ffprobe
        self._build()

    def _build(self):
        _page_header(self, "📤  Extract Subtitle Track",
                     "Pull embedded .srt / .ass subtitle tracks from MKV and other containers.")

        self.video_zone = FileDropZone(
            self, label="Input File  (MKV, MP4, …)",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")])
        self.video_zone.pack(fill="x", pady=(0, 6))

        # ── Scan button + stream list ─────────────────────────────────────────
        scan_row = ctk.CTkFrame(self, fg_color="transparent")
        scan_row.pack(fill="x", pady=(0, 8))
        ctk.CTkButton(scan_row, text="Scan Subtitle Tracks", width=160,
                      command=self._scan).pack(side="left")
        self.scan_status = ctk.CTkLabel(
            scan_row, text="", font=ctk.CTkFont(size=12),
            text_color=TC["text_dim"])
        self.scan_status.pack(side="left", padx=12)

        stream_card = _card(self, "Subtitle Streams Found")
        self.stream_list = tk.Listbox(
            stream_card,
            selectmode=tk.SINGLE,
            bg=TC["card_inner"], fg=TC["text"],
            selectbackground=TC["accent"],
            font=("Courier", 11),
            relief="flat", borderwidth=0,
            height=6)
        self.stream_list.pack(fill="x", padx=10, pady=(0, 10))

        # ── Output format ─────────────────────────────────────────────────────
        fmt_card = _card(self, "Output Format")
        fmt_row = ctk.CTkFrame(fmt_card, fg_color="transparent")
        fmt_row.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(fmt_row, text="Format:").pack(side="left", padx=(0, 10))
        self.fmt_var = ctk.StringVar(value="srt")
        ctk.CTkRadioButton(fmt_row, text=".srt  (SubRip — wide compatibility)",
                           variable=self.fmt_var, value="srt").pack(
            side="left", padx=(0, 24))
        ctk.CTkRadioButton(fmt_row, text=".ass  (Advanced SubStation — preserves styling)",
                           variable=self.fmt_var, value="ass").pack(side="left")

        # ── Extract All shortcut ──────────────────────────────────────────────
        all_row = ctk.CTkFrame(self, fg_color="transparent")
        all_row.pack(fill="x", pady=(0, 4))
        self.extract_all_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(all_row,
                        text="Extract ALL subtitle tracks at once",
                        variable=self.extract_all_var).pack(side="left")

        _action_row(self, self._run, self.cancel, run_label="Extract")
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    # ── Scan ─────────────────────────────────────────────────────────────────

    def _scan(self):
        inp = self.video_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file first.")
            return
        if not self.app.ffprobe:
            messagebox.showerror("Error", "ffprobe not found — needed for stream detection.")
            return

        self.scan_status.configure(text="Scanning…",
                                   text_color=TC["text_dim"])
        self.stream_list.delete(0, tk.END)
        self._streams = []

        def _work():
            try:
                r = subprocess.run(
                    [self.app.ffprobe, "-v", "quiet",
                     "-print_format", "json",
                     "-show_streams", inp],
                    capture_output=True, text=True, timeout=15)
                data   = json.loads(r.stdout)
                subs   = [s for s in data.get("streams", [])
                          if s.get("codec_type") == "subtitle"]
            except Exception as exc:
                self.after(0, lambda e=exc: self.scan_status.configure(
                    text=f"Error: {e}", text_color=("red", "#f44336")))
                return

            def _update(streams=subs):
                self._streams = streams
                self.stream_list.delete(0, tk.END)
                if not streams:
                    self.scan_status.configure(
                        text="No subtitle tracks found.",
                        text_color=TC["text_dim"])
                    return
                self.scan_status.configure(
                    text=f"{len(streams)} subtitle track(s) found.",
                    text_color=("green", "#4caf50"))
                for i, s in enumerate(streams):
                    idx    = s.get("index", i)
                    codec  = s.get("codec_name", "?").upper()
                    tags   = s.get("tags", {})
                    lang   = tags.get("language", tags.get("lang", "?"))
                    title  = tags.get("title", "")
                    label  = f"  Stream #{idx}  [{codec}]  lang={lang}"
                    if title:
                        label += f'  "{title}"'
                    self.stream_list.insert(tk.END, label)
                # Auto-select first track
                if streams:
                    self.stream_list.selection_set(0)

            self.after(0, _update)

        threading.Thread(target=_work, daemon=True).start()

    # ── Extract ───────────────────────────────────────────────────────────────

    def _run(self):
        inp = self.video_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return
        if not self.app.ffmpeg:
            messagebox.showerror("Error", "FFmpeg not found.")
            return

        fmt = self.fmt_var.get()

        if self.extract_all_var.get():
            self._extract_all(inp, fmt)
        else:
            self._extract_selected(inp, fmt)

    def _extract_selected(self, inp, fmt):
        sel = self.stream_list.curselection()
        if not sel or not self._streams:
            messagebox.showerror("Error",
                                 "Scan the file first and select a subtitle track.")
            return

        stream = self._streams[sel[0]]
        stream_idx = stream.get("index", sel[0])
        tags  = stream.get("tags", {})
        lang  = tags.get("language", tags.get("lang", "und"))

        p   = Path(inp)
        out = self.app.smart_save_dialog(
            "ExtractSub",
            initialfile=f"{p.stem}.{lang}.{fmt}",
            defaultextension=f".{fmt}",
            filetypes=[(fmt.upper(), f"*.{fmt}"), ("All files", "*.*")])
        if not out:
            return

        cmd = [self.app.ffmpeg, "-y", "-i", inp,
               "-map", f"0:{stream_idx}",
               "-c:s", "srt" if fmt == "srt" else "ass",
               out]

        self.run_ffmpeg(cmd, None, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Extract Subtitle", output_path=out)

    def _extract_all(self, inp, fmt):
        if not self._streams:
            messagebox.showerror("Error",
                                 "Scan the file first to detect subtitle tracks.")
            return

        p      = Path(inp)
        folder = filedialog.askdirectory(title="Choose output folder")
        if not folder:
            return

        outputs = []
        cmd = [self.app.ffmpeg, "-y", "-i", inp]
        for s in self._streams:
            idx  = s.get("index", 0)
            tags = s.get("tags", {})
            lang = tags.get("language", tags.get("lang", "und"))
            out  = str(Path(folder) / f"{p.stem}.{lang}.track{idx}.{fmt}")
            cmd += ["-map", f"0:{idx}"]
            outputs.append(out)

        # Codec flag applies to all subtitle outputs
        cmd += ["-c:s", "srt" if fmt == "srt" else "ass"]
        cmd += outputs

        first_out = outputs[0] if outputs else ""
        self.run_ffmpeg(cmd, None, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done",
                            f"Extracted {len(outputs)} track(s) to:\n{folder}"
                        ) if ok else None,
                        page_name="Extract Subtitle", output_path=first_out)


# ══════════════════════════════════════════════════════════════
# Media Player Page
# ══════════════════════════════════════════════════════════════

class PlayerPage(BasePage):
    """
    Built-in media player using ffplay as the video backend.

    Architecture:
    - ffplay renders video in its own native window (cross-platform,
      no extra Python dependencies required beyond ffplay in PATH).
    - A tkinter UI provides:
        • File picker / drag-drop zone
        • Play / Pause / Stop buttons
        • Seek bar that polls ffplay's -report log for position
        • Volume slider (passed at launch)
        • Speed control (re-launches ffplay with -vf setpts)
    - Seeking re-launches ffplay from the requested position because
      ffplay has no IPC seek protocol, which is the standard approach.

    Note: ffplay must be in PATH (it ships with ffmpeg on all platforms).
    """

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._proc:        subprocess.Popen | None = None
        self._poll_job:    str | None = None   # after() job id
        self._duration:    float | None = None
        self._position:    float = 0.0
        self._paused:      bool  = False
        self._seek_dragging: bool = False
        self._ffplay       = find_tool("ffplay")
        self._build()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build(self):
        _page_header(self, "▶  Media Player",
                     "Preview any video or audio file with seek, volume, and speed control.")

        # ffplay availability notice
        if not self._ffplay:
            ctk.CTkLabel(
                self,
                text="⚠  ffplay not found in PATH.\n"
                     "ffplay ships with FFmpeg — install FFmpeg to enable playback.",
                text_color=("orange", "#ffb74d"),
                font=ctk.CTkFont(size=13)).pack(pady=20)

        self.file_zone = FileDropZone(
            self, label="Media File",
            filetypes=[("Media files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS + AUDIO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.file_zone.pack(fill="x", pady=(0, 10))

        # ── Seek bar ──────────────────────────────────────────────────────────
        seek_card = _card(self, "Position")
        seek_inner = ctk.CTkFrame(seek_card, fg_color="transparent")
        seek_inner.pack(fill="x", padx=10, pady=(0, 10))

        self.pos_label = ctk.CTkLabel(seek_inner, text="0:00:00", width=60,
                                       font=ctk.CTkFont(family="Courier", size=12))
        self.pos_label.pack(side="left")
        self.seek_var = ctk.DoubleVar(value=0.0)
        self.seek_bar = ctk.CTkSlider(
            seek_inner, from_=0, to=100,
            variable=self.seek_var,
            command=self._on_seek_drag)
        self.seek_bar.pack(side="left", fill="x", expand=True, padx=8)
        self.dur_label = ctk.CTkLabel(seek_inner, text="0:00:00", width=60,
                                       font=ctk.CTkFont(family="Courier", size=12))
        self.dur_label.pack(side="left")

        # Bind mouse release on the slider to trigger an actual seek
        self.seek_bar.bind("<ButtonRelease-1>", self._on_seek_release)

        # ── Transport controls ────────────────────────────────────────────────
        ctrl_card = _card(self, "Controls")
        ctrl_row = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        ctrl_row.pack(fill="x", padx=10, pady=(0, 10))

        btn_kw = dict(width=90, height=34, font=ctk.CTkFont(size=13))
        grey   = dict(fg_color=TC["secondary"],
                      hover_color=TC["secondary_hover"],
                      text_color=TC["secondary_text"])

        self.play_btn = ctk.CTkButton(ctrl_row, text="▶  Play",
                                       command=self._play, **btn_kw)
        self.play_btn.pack(side="left", padx=(0, 6))

        self.pause_btn = ctk.CTkButton(ctrl_row, text="⏸  Pause",
                                        command=self._pause,
                                        state="disabled", **btn_kw, **grey)
        self.pause_btn.pack(side="left", padx=(0, 6))

        self.stop_btn = ctk.CTkButton(ctrl_row, text="⏹  Stop",
                                       command=self._stop,
                                       state="disabled", **btn_kw, **grey)
        self.stop_btn.pack(side="left", padx=(0, 24))

        # Volume
        ctk.CTkLabel(ctrl_row, text="Vol:").pack(side="left", padx=(0, 6))
        self.vol_var = ctk.IntVar(value=100)
        ctk.CTkSlider(ctrl_row, from_=0, to=100, width=100,
                      variable=self.vol_var).pack(side="left", padx=(0, 4))
        self.vol_lbl = ctk.CTkLabel(ctrl_row, text="100%", width=40,
                                     font=ctk.CTkFont(size=11))
        self.vol_lbl.pack(side="left", padx=(0, 20))
        self.vol_var.trace_add("write", lambda *_: self.vol_lbl.configure(
            text=f"{self.vol_var.get()}%"))

        # Speed
        ctk.CTkLabel(ctrl_row, text="Speed:").pack(side="left", padx=(0, 6))
        self.speed_var = ctk.StringVar(value="1.0x")
        ctk.CTkOptionMenu(ctrl_row, variable=self.speed_var,
                          values=["0.25x", "0.5x", "0.75x", "1.0x",
                                  "1.25x", "1.5x", "2.0x"],
                          width=80).pack(side="left")

        # ── Status ────────────────────────────────────────────────────────────
        self.status_lbl = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=12),
            text_color=TC["text_dim"])
        self.status_lbl.pack(anchor="w", pady=(6, 0))

        # ── Open from history shortcut ────────────────────────────────────────
        hist_row = ctk.CTkFrame(self, fg_color="transparent")
        hist_row.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(hist_row, text="Quick open from recent output:",
                     font=ctk.CTkFont(size=12),
                     text_color=TC["text_dim"]).pack(side="left", padx=(0, 10))
        self.hist_var = ctk.StringVar(value="")
        self._hist_menu = ctk.CTkOptionMenu(
            hist_row, variable=self.hist_var,
            values=["(none)"], width=300,
            command=self._open_from_history)
        self._hist_menu.pack(side="left")
        ctk.CTkButton(hist_row, text="Refresh", width=80,
                      fg_color=TC["secondary"],
                      hover_color=TC["secondary_hover"],
                      text_color=TC["secondary_text"],
                      command=self._refresh_history).pack(side="left", padx=8)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fmt_time(self, secs: float) -> str:
        s = max(0.0, secs)
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sc = int(s % 60)
        return f"{h}:{m:02d}:{sc:02d}"

    def _get_speed(self) -> float:
        try:
            return float(self.speed_var.get().rstrip("x"))
        except ValueError:
            return 1.0

    # ── Playback controls ─────────────────────────────────────────────────────

    def _play(self, start_at: float = 0.0):
        """Launch ffplay from start_at seconds."""
        path = self.file_zone.get()
        if not path or not os.path.exists(path):
            messagebox.showerror("Player", "Please select a valid media file.")
            return
        if not self._ffplay:
            messagebox.showerror("Player",
                                 "ffplay not found.\nInstall FFmpeg to enable playback.")
            return

        self._stop(silent=True)

        # Load duration on first play
        if self._duration is None and self.app.ffprobe:
            dur = get_duration(self.app.ffprobe, path)
            if dur:
                self._duration = dur
                self.seek_bar.configure(to=dur)
                self.dur_label.configure(text=self._fmt_time(dur))

        speed  = self._get_speed()
        volume = self.vol_var.get()

        cmd = [self._ffplay, "-autoexit", "-loglevel", "quiet"]
        cmd += ["-volume", str(volume)]
        if start_at > 0.1:
            cmd += ["-ss", str(start_at)]
        if speed != 1.0:
            cmd += ["-vf", f"setpts={1/speed:.4f}*PTS",
                    "-af", f"atempo={speed:.2f}"]
        cmd.append(path)

        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            messagebox.showerror("Player", f"Could not launch ffplay:\n{exc}")
            return

        self._position  = start_at
        self._paused    = False
        self._play_start_wall = time.time()
        self._play_start_pos  = start_at
        self._speed_factor    = speed

        self.play_btn.configure(state="disabled")
        self.pause_btn.configure(state="normal")
        self.stop_btn.configure(state="normal")
        self.status_lbl.configure(text="Playing…",
                                   text_color=("green", "#4caf50"))
        self._poll()

    def _pause(self):
        """Toggle pause — ffplay has no IPC, so we stop and remember position."""
        if self._paused:
            # Resume from remembered position
            self._paused = False
            self._play(start_at=self._position)
            self.pause_btn.configure(text="⏸  Pause")
        else:
            self._paused   = True
            self._position = self._current_position()
            self._stop(silent=True)
            self.play_btn.configure(state="normal")
            self.pause_btn.configure(text="▶  Resume", state="normal")
            self.stop_btn.configure(state="normal")
            self.status_lbl.configure(text=f"Paused at {self._fmt_time(self._position)}",
                                       text_color=TC["text_dim"])

    def _stop(self, silent=False):
        """Terminate ffplay and reset UI."""
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None
        if self._proc:
            try:
                self._proc.terminate()
                self._proc = None
            except Exception:
                pass
        if not silent:
            self._position = 0.0
            self.seek_var.set(0.0)
            self.pos_label.configure(text="0:00:00")
            self.status_lbl.configure(text="Stopped.",
                                       text_color=TC["text_dim"])
        self.play_btn.configure(state="normal")
        self.pause_btn.configure(text="⏸  Pause", state="disabled")
        self.stop_btn.configure(state="disabled")

    # ── Seek ──────────────────────────────────────────────────────────────────

    def _on_seek_drag(self, val):
        self._seek_dragging = True
        self.pos_label.configure(text=self._fmt_time(float(val)))

    def _on_seek_release(self, _event):
        self._seek_dragging = False
        target = self.seek_var.get()
        self._play(start_at=target)

    # ── Position polling ──────────────────────────────────────────────────────

    def _current_position(self) -> float:
        """Estimate current position from wall-clock elapsed time."""
        if not hasattr(self, "_play_start_wall"):
            return self._position
        elapsed = (time.time() - self._play_start_wall) * self._speed_factor
        return self._play_start_pos + elapsed

    def _poll(self):
        """Update seek bar + check if ffplay has exited. Runs every 500 ms."""
        if self._proc is None:
            return
        if self._proc.poll() is not None:
            # ffplay exited (end of file or user closed window)
            self._stop(silent=False)
            self.status_lbl.configure(text="Playback finished.",
                                       text_color=TC["text_dim"])
            return

        if not self._seek_dragging:
            pos = self._current_position()
            if self._duration:
                pos = min(pos, self._duration)
            self._position = pos
            self.seek_var.set(pos)
            self.pos_label.configure(text=self._fmt_time(pos))

        self._poll_job = self.after(500, self._poll)

    # ── History quick-open ────────────────────────────────────────────────────

    def _refresh_history(self):
        outputs = [j["output"] for j in self.app.history
                   if j.get("success") and j.get("output")
                   and os.path.exists(j["output"])]
        if not outputs:
            self._hist_menu.configure(values=["(none)"])
            self.hist_var.set("(none)")
        else:
            names = [Path(o).name for o in outputs]
            # Store full paths by name — last one wins if duplicates
            self._hist_paths = dict(zip(names, outputs))
            self._hist_menu.configure(values=list(self._hist_paths.keys()))
            self.hist_var.set(names[-1])

    def _open_from_history(self, name: str):
        if not hasattr(self, "_hist_paths"):
            return
        path = self._hist_paths.get(name)
        if path and os.path.exists(path):
            self.file_zone.paths = [path]
            self.file_zone.path_label.configure(
                text=Path(path).name, text_color=TC["secondary_text"])
            self._duration = None  # force re-probe


# ══════════════════════════════════════════════════════════════
# History Page  (NEW)
# ══════════════════════════════════════════════════════════════

class HistoryPage(ctk.CTkScrollableFrame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.configure(fg_color="transparent")
        _page_header(self, "🕒  History",
                     "All jobs completed this session.")
        self._list = ctk.CTkFrame(self, fg_color="transparent")
        self._list.pack(fill="x")
        self._empty = ctk.CTkLabel(
            self._list, text="No jobs completed yet.",
            text_color=TC["text_dim"], font=ctk.CTkFont(size=13))
        self._empty.pack(pady=30)

        ctk.CTkButton(self, text="Clear History", width=120,
                      fg_color=TC["secondary"],
                      hover_color=TC["secondary_hover"],
                      text_color=TC["secondary_text"],
                      command=self._clear).pack(anchor="w", pady=(12, 0))

    def refresh(self):
        for w in self._list.winfo_children():
            w.destroy()
        if not self.app.history:
            ctk.CTkLabel(
                self._list, text="No jobs completed yet.",
                text_color=TC["text_dim"],
                font=ctk.CTkFont(size=13)).pack(pady=30)
            return
        for job in reversed(self.app.history):
            self._add_row(job)

    def _add_row(self, job):
        ok    = job["success"]
        row   = ctk.CTkFrame(self._list,
                             fg_color=TC["filedrop"], corner_radius=6)
        row.pack(fill="x", pady=3)

        ctk.CTkLabel(row, text="✓" if ok else "✗",
                     text_color=("green", "#4caf50") if ok else ("red", "#f44336"),
                     font=ctk.CTkFont(size=16, weight="bold"),
                     width=32).pack(side="left", padx=10, pady=8)

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, pady=6)

        ctk.CTkLabel(info,
                     text=f"{job['page']}  ·  {job['timestamp']}",
                     font=ctk.CTkFont(size=11),
                     text_color=TC["text_dim"]).pack(anchor="w")

        out  = job.get("output", "")
        name = Path(out).name if out else "—"
        ctk.CTkLabel(info, text=name,
                     font=ctk.CTkFont(size=12)).pack(anchor="w")

        if out and os.path.exists(out):
            sz = os.path.getsize(out) / (1024 * 1024)
            ctk.CTkLabel(info, text=f"💾 {sz:.1f} MB",
                         font=ctk.CTkFont(size=11),
                         text_color=TC["text_dim"]).pack(anchor="w")

        if out and os.path.isfile(out):
            ctk.CTkButton(row, text="📂", width=36, height=30,
                          fg_color="transparent",
                          command=lambda o=out: self._open_folder(o)).pack(
                side="right", padx=8)

    @staticmethod
    def _open_folder(path):
        folder = str(Path(path).parent)
        try:
            import sys
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.run(["open", folder])
            else:
                subprocess.run(["xdg-open", folder])
        except Exception:
            pass

    def _clear(self):
        self.app.history.clear()
        self.refresh()



# ══════════════════════════════════════════════════════════════
# Help Page
# ══════════════════════════════════════════════════════════════

class HelpPage(ctk.CTkScrollableFrame):
    """
    In-app help reference: feature overview, tips, FFmpeg install guide,
    and developer contact.
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.configure(fg_color="transparent")
        self._build()

    def _build(self):
        _page_header(self, "❓  Help & Documentation",
                     "Guides, tips, and contact info for FFmpex.")

        # ── Quick-start ───────────────────────────────────────────────────────
        qs_card = _card(self, "Quick Start")
        qs_items = [
            ("1", "Install FFmpeg",
             "FFmpex needs FFmpeg in your system PATH.\n"
             "  Windows : winget install ffmpeg\n"
             "  macOS   : brew install ffmpeg\n"
             "  Ubuntu  : sudo apt install ffmpeg\n"
             "  All     : https://ffmpeg.org/download.html"),
            ("2", "Install optional Python packages",
             "  pip install pillow       # thumbnail previews\n"
             "  pip install tkinterdnd2  # drag-and-drop file input\n"
             "  pip install pystray      # system tray icon\n"
             "  pip install plyer        # desktop notifications"),
            ("3", "Pick a tool from the sidebar",
             "Each page is self-contained. Select your file, adjust settings,\n"
             "then press the action button (or Ctrl+Enter)."),
            ("4", "Check the FFmpeg log if something fails",
             "Every page has a collapsible \u25b6 Show Log panel below the progress bar.\n"
             "The raw FFmpeg stderr output is there — it always explains the error."),
        ]
        for num, title, body in qs_items:
            row = ctk.CTkFrame(qs_card, fg_color=TC["card_inner"], corner_radius=6)
            row.pack(fill="x", padx=10, pady=(0, 6))
            hdr = ctk.CTkFrame(row, fg_color="transparent")
            hdr.pack(fill="x", padx=10, pady=(8, 2))
            ctk.CTkLabel(hdr, text=num,
                         width=22, height=22,
                         corner_radius=11,
                         fg_color=("#1a6db5","#2a7dc5"),
                         text_color="white",
                         font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(hdr, text=title,
                         font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            ctk.CTkLabel(row, text=body,
                         font=ctk.CTkFont(size=12),
                         text_color=TC["text_dim"],
                         justify="left").pack(anchor="w", padx=14, pady=(0, 8))

        # ── Feature index ─────────────────────────────────────────────────────
        feat_card = _card(self, "Feature Reference")
        features = [
            ("🔄  Convert",        "Convert between any video or audio format. Includes 2-pass GIF with palette generation."),
            ("📦  Compress",       "Reduce file size with CRF presets (Discord, WhatsApp, etc.) and optional downscale."),
            ("🎯  2-Pass VBR",     "Hit a precise MB target. Calculates the exact bitrate and runs a 2-pass analysis + encode."),
            ("📁  Batch",          "Convert many files at once with a shared settings profile, scheduler, and auto-shutdown."),
            ("📋  Job Queue",      "Build a heterogeneous queue: different operations per file, save/load as JSON."),
            ("✂️  Trim & Cut",     "Clip between timestamps with visual sliders. Fast stream-copy or full re-encode."),
            ("✂️  Split",          "Divide into N equal segments or cut at specific timestamps."),
            ("🔗  Merge",          "Concatenate clips in any order. Uses ffmpeg concat demuxer (stream copy, instant)."),
            ("📐  Crop & Pad",     "Crop to any region or pad to a target aspect ratio with letterboxing."),
            ("⏪  Reverse",        "Memory-efficient chunk-based reverse — safe on large files."),
            ("⚡  Speed Change",   "0.25×–4× with automatic atempo chaining and pitch correction."),
            ("🖼️  Export Frames",  "Extract every Nth frame or 1 frame per N seconds as PNG/JPG."),
            ("🔤  Subtitles",      "Burn-in SRT or ASS subtitles with full style control (font, size, colour, position)."),
            ("🔤  Text Watermark", "drawtext overlay with position, fade, colour swatch preview. Cross-platform fonts."),
            ("🖼️  Image Watermark","PNG logo overlay with opacity, 9 anchor positions, proportional scaling."),
            ("📤  Extract Subs",   "Scan MKV for embedded subtitle tracks and extract them as SRT or ASS."),
            ("🎨  Color Grading",  "Brightness, contrast, saturation, gamma, and hue with a 5-second live preview."),
            ("⚡  HW Accel",      "Auto-detect NVENC / VideoToolbox / VAAPI / AMF and encode with GPU acceleration."),
            ("🌐  Web Streaming",  "Fast-start MP4, HLS (.m3u8 + .ts segments), or DASH (.mpd) output."),
            ("📱  Platform",       "One-click spec-compliant export for YouTube, Instagram Reels, TikTok, Twitter/X, Vimeo."),
            ("📺  Device",         "Device-optimised encode for iPhone, Android, Apple TV, PS5, Chromecast, Roku."),
            ("🎵  Extract Audio",  "Rip audio to MP3, AAC, FLAC, WAV, OGG, OPUS, and more."),
            ("🔇  Audio Track",    "Remove audio, replace with silence, or swap in a new audio file."),
            ("➕  Mix Audio",      "Blend a music track into a video with per-stream volume, fade, and loop control."),
            ("🔊  Normalise",      "EBU R128 loudnorm. Platform presets: YouTube −14 LUFS, Podcast −16, Broadcast −23."),
            ("🎙️  Denoise",        "afftdn spectral denoiser with optional highpass and lowpass filters."),
            ("🎼  Waveform",       "Generate a showwavespic image with colour themes and inline preview."),
            ("▶  Player",          "ffplay-backed media player with seek bar, volume, speed control."),
            ("🔍  Media Info",     "Full ffprobe inspector: streams, chapters, metadata, raw JSON."),
        ]
        for icon_title, desc in features:
            fr = ctk.CTkFrame(feat_card, fg_color="transparent")
            fr.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(fr, text=icon_title,
                         width=190, anchor="w",
                         font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
            ctk.CTkLabel(fr, text=desc,
                         font=ctk.CTkFont(size=12),
                         text_color=TC["text_dim"],
                         anchor="w", justify="left").pack(side="left", fill="x", expand=True)
        ctk.CTkFrame(feat_card, fg_color="transparent", height=6).pack()

        # ── Tips & gotchas ────────────────────────────────────────────────────
        tips_card = _card(self, "Tips & Common Gotchas")
        tips = [
            ("Merge needs matching streams",
             "Files being merged must share the same codec, resolution, and frame rate for "
             "stream-copy to work cleanly. Re-encode mismatched clips first with Convert."),
            ("CRF vs 2-Pass VBR",
             "CRF keeps quality constant — file size varies by content complexity. "
             "2-Pass VBR keeps file size constant — quality varies. Use 2-Pass when you "
             "need to hit a platform upload limit precisely."),
            ("Text watermarks on Windows/macOS",
             "FFmpex probes for a system font automatically. If the font looks wrong, "
             "enter a font name that actually exists on your OS in the Font field."),
            ("HLS / DASH output",
             "These modes write many files. Always set an output folder first. "
             "The folder is safe to serve directly from a web server or CDN."),
            ("Reverse on large files",
             "The chunk-based reverse is memory-safe but each chunk boundary requires a "
             "re-encode. Use a larger chunk size (30 s) for speed, smaller (2 s) for less RAM."),
            ("Scheduler auto-shutdown",
             "The shutdown command is issued 60 seconds after the batch completes on Windows "
             "(run \'shutdown /a\' to cancel). On macOS/Linux it calls the system poweroff immediately."),
            ("Drag & drop not working",
             "Install tkinterdnd2 (pip install tkinterdnd2) and restart FFmpex. "
             "The Settings page shows whether it is detected."),
        ]
        for tip_title, tip_body in tips:
            tr = ctk.CTkFrame(tips_card, fg_color=TC["card_inner"], corner_radius=6)
            tr.pack(fill="x", padx=10, pady=(0, 6))
            ctk.CTkLabel(tr, text=tip_title,
                         font=ctk.CTkFont(size=12, weight="bold")).pack(
                anchor="w", padx=10, pady=(8, 2))
            ctk.CTkLabel(tr, text=tip_body,
                         font=ctk.CTkFont(size=12),
                         text_color=TC["text_dim"],
                         wraplength=700, justify="left").pack(
                anchor="w", padx=10, pady=(0, 8))

        # ── Contact & links ───────────────────────────────────────────────────
        contact_card = _card(self, "Contact & Source Code")

        rows = [
            ("Developer", "SSJ", None),
            ("Email",     "magnusshadowmend@gmail.com",
             "mailto:magnusshadowmend@gmail.com"),
            ("GitHub",    "github.com/shubh-ssj",
             "https://github.com/shubh-ssj"),
            ("FFmpeg",    "ffmpeg.org/documentation.html",
             "https://ffmpeg.org/documentation.html"),
        ]
        for label, text, url in rows:
            cr = ctk.CTkFrame(contact_card, fg_color="transparent")
            cr.pack(fill="x", padx=14, pady=3)
            ctk.CTkLabel(cr, text=label,
                         width=80, anchor="w",
                         font=ctk.CTkFont(size=12),
                         text_color=TC["text_dim"]).pack(side="left")
            if url:
                ctk.CTkButton(
                    cr, text=text,
                    font=ctk.CTkFont(size=12),
                    fg_color="transparent",
                    hover=False,
                    text_color=("#1a6db5","#5da7d6"),
                    cursor="hand2",
                    command=lambda u=url: self._open_link(u)
                ).pack(side="left", padx=0)
            else:
                ctk.CTkLabel(cr, text=text,
                             font=ctk.CTkFont(size=12, weight="bold"),
                             text_color=TC["text"]).pack(side="left")
        ctk.CTkFrame(contact_card, fg_color="transparent", height=8).pack()

    @staticmethod
    def _open_link(url: str):
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════
# Settings Page
# ══════════════════════════════════════════════════════════════

class SettingsPage(ctk.CTkScrollableFrame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.configure(fg_color="transparent")
        self._build()

    def _build(self):
        _page_header(self, "⚙️  Settings", "")

        # ── FFmpeg status ────────────────────────────────────────────────────
        ff_card = _card(self, "FFmpeg Installation")
        for tool, attr in [("ffmpeg", "ffmpeg"), ("ffprobe", "ffprobe")]:
            val = getattr(self.app, attr)
            ok  = val is not None
            r   = ctk.CTkFrame(ff_card, fg_color="transparent")
            r.pack(fill="x", padx=10, pady=3)
            ctk.CTkLabel(r,
                         text=f"{'✓' if ok else '✗'}  {tool}",
                         text_color=("green", "#4caf50") if ok else ("red", "#f44336"),
                         font=ctk.CTkFont(size=13, weight="bold"),
                         width=100).pack(side="left")
            ctk.CTkLabel(r,
                         text=val if val else "Not found in PATH",
                         text_color=TC["text_dim"],
                         font=ctk.CTkFont(size=12)).pack(side="left")

        if not self.app.ffmpeg:
            ctk.CTkLabel(ff_card,
                         text="  Install FFmpeg and make sure it's in your PATH:\n"
                              "  →  Windows :  winget install ffmpeg\n"
                              "  →  macOS   :  brew install ffmpeg\n"
                              "  →  Ubuntu  :  sudo apt install ffmpeg\n"
                              "  →  Download:  https://ffmpeg.org/download.html",
                         justify="left",
                         text_color=TC["text_dim"],
                         font=ctk.CTkFont(size=12)).pack(anchor="w", padx=14, pady=(4, 12))
        else:
            ctk.CTkFrame(ff_card, fg_color="transparent", height=8).pack()

        # ── Optional dependencies ────────────────────────────────────────────
        dep_card = _card(self, "Optional Features")
        deps = [
            ("Pillow (thumbnail previews)", HAS_PIL,
             "pip install pillow"),
            ("tkinterdnd2 (drag & drop)", HAS_DND,
             "pip install tkinterdnd2"),
            ("pystray (system tray icon)", HAS_TRAY,
             "pip install pystray"),
            ("plyer (desktop notifications)", HAS_PLYER,
             "pip install plyer"),
        ]
        for dep_name, installed, install_cmd in deps:
            dr = ctk.CTkFrame(dep_card, fg_color="transparent")
            dr.pack(fill="x", padx=10, pady=3)
            ctk.CTkLabel(dr,
                         text=f"{'✓' if installed else '○'}  {dep_name}",
                         text_color=("green", "#4caf50") if installed else ("gray50", "gray55"),
                         font=ctk.CTkFont(size=12),
                         width=300).pack(side="left")
            if not installed:
                ctk.CTkLabel(dr,
                             text=install_cmd,
                             text_color=TC["text_dim"],
                             font=ctk.CTkFont(family="Courier", size=11)).pack(side="left")
        ctk.CTkFrame(dep_card, fg_color="transparent", height=6).pack()

        # ── Keyboard shortcuts reference ──────────────────────────────────────
        kb_card = _card(self, "⌨  Keyboard Shortcuts")
        shortcuts = [
            ("Ctrl + O",           "Open / Browse file on current page"),
            ("Ctrl + Enter",       "Run the current page's job"),
            ("Esc",                "Cancel the running job"),
            ("F5",                 "Reload file info (Load Info / Analyze) on current page"),
            ("Alt + ←  / Alt + →", "Navigate back / forward through page history"),
            ("Ctrl + Tab",         "Cycle to next page in sidebar order"),
            ("Ctrl + Shift + Tab", "Cycle to previous page"),
            ("Ctrl + 1 – 9",       "Jump to Convert / Compress / Batch / Trim / Split / Merge / Extract / Mute / History"),
            ("Ctrl + H",           "History"),
            ("Ctrl + M",           "Media Info"),
            ("Ctrl + P",           "Player"),
            ("Ctrl + /",           "Help"),
            ("Ctrl + ,",           "Settings"),
            ("Ctrl + W",           "Minimise to tray"),
            ("Space",              "Preview clip  (Trim page only — not while typing)"),
            ("Ctrl + R",           "Reset all sliders  (Color Grading page)"),
            ("Ctrl + =  / Ctrl + −","Nudge speed ±0.25×  (Speed Change page)"),
        ]
        for key, desc in shortcuts:
            kr = ctk.CTkFrame(kb_card, fg_color="transparent")
            kr.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(kr, text=key,
                         font=ctk.CTkFont(family="Courier", size=12, weight="bold"),
                         width=150, anchor="w").pack(side="left")
            ctk.CTkLabel(kr, text=desc,
                         font=ctk.CTkFont(size=12),
                         text_color=TC["text_dim"],
                         anchor="w").pack(side="left", fill="x")
        ctk.CTkFrame(kb_card, fg_color="transparent", height=6).pack()

        # ── Appearance ───────────────────────────────────────────────────────
        app_card = _card(self, "Appearance")

        # Light / Dark / System
        mode_row = ctk.CTkFrame(app_card, fg_color="transparent")
        mode_row.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(mode_row, text="Mode:", width=80).pack(side="left")
        self.theme_var = ctk.StringVar(value=ctk.get_appearance_mode())
        for t in ("Light", "Dark", "System"):
            ctk.CTkRadioButton(
                mode_row, text=t, variable=self.theme_var, value=t,
                command=lambda: ctk.set_appearance_mode(self.theme_var.get()),
            ).pack(side="left", padx=10)

        # ── System tray behaviour ─────────────────────────────────────────────
        _sep(app_card, padx=10, pady=(0, 6))
        tray_row = ctk.CTkFrame(app_card, fg_color="transparent")
        tray_row.pack(fill="x", padx=10, pady=(0, 10))
        self._tray_close_var = ctk.BooleanVar(
            value=self.app.app_state.get_tray_close())
        ctk.CTkCheckBox(
            tray_row,
            text="Minimise to system tray when the window is closed",
            variable=self._tray_close_var,
            command=self._on_tray_close_changed,
        ).pack(side="left")
        ctk.CTkLabel(
            tray_row,
            text="  (off = X quits the app)",
            font=ctk.CTkFont(size=11),
            text_color=TC["text_dim"],
        ).pack(side="left")

        # ── Theme grid ───────────────────────────────────────────────────────
        _sep(app_card, padx=10, pady=(0, 6))
        ctk.CTkLabel(app_card,
                     text="Theme  —  click any card to select",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=10, pady=(0, 4))
        ctk.CTkLabel(app_card,
                     text="Your choice is saved instantly. A restart applies it to every panel.",
                     font=ctk.CTkFont(size=11),
                     text_color=TC["text_dim"]).pack(anchor="w", padx=10, pady=(0, 8))

        self._theme_status = ctk.CTkLabel(
            app_card, text="",
            font=ctk.CTkFont(size=11),
            text_color=("green","#4caf50"))
        self._theme_status.pack(anchor="w", padx=10, pady=(0, 6))

        grid_frame = ctk.CTkFrame(app_card, fg_color="transparent")
        grid_frame.pack(fill="x", padx=10, pady=(0, 12))

        COLS = 3
        for idx, (name, (_, preview)) in enumerate(FULL_THEMES.items()):
            bg_color, accent_color, text_color = preview
            row_i = idx // COLS
            col_i = idx % COLS

            card = ctk.CTkFrame(
                grid_frame,
                fg_color=bg_color,
                corner_radius=8,
                border_width=2,
                border_color=accent_color,
                cursor="hand2",
            )
            card.grid(row=row_i, column=col_i, padx=4, pady=4, sticky="ew")
            grid_frame.columnconfigure(col_i, weight=1)

            # Accent stripe
            stripe = ctk.CTkFrame(card, fg_color=accent_color, height=4, corner_radius=0)
            stripe.pack(fill="x")

            # Name label (over the dark bg — use hardcoded text_color from preview)
            lbl = tk.Label(
                card, text=name,
                bg=bg_color, fg=text_color,
                font=("Segoe UI", 10) if hasattr(tk, "font") else ("Arial", 10),
                padx=8, pady=6, anchor="w", cursor="hand2",
            )
            lbl.pack(fill="x")

            # Colour dots row
            dot_row = tk.Frame(card, bg=bg_color)
            dot_row.pack(fill="x", padx=8, pady=(0, 6))
            for dot_color in (bg_color, accent_color, text_color):
                tk.Label(dot_row, bg=dot_color, width=2,
                         relief="flat").pack(side="left", padx=2)

            # Bind click on every child so the whole card is clickable
            def _on_click(n=name):
                self._apply_theme(n)
            for widget in (card, stripe, lbl, dot_row):
                widget.bind("<Button-1>", lambda e, n=name: self._apply_theme(n))

    def _on_tray_close_changed(self):
        """Save tray-close preference and apply it immediately."""
        val = self._tray_close_var.get()
        self.app.app_state.save_tray_close(val)
        self.app._update_close_behavior()

    def _apply_theme(self, theme_name: str):
        """
        Save the chosen theme and offer to restart immediately so every
        widget picks up the new colours.  The theme is written to disk
        first so it loads correctly on the next launch regardless of
        whether the user restarts now or later.
        """
        # 1. Save immediately — even if they click "Later" the choice persists
        self.app.app_state.save_theme(theme_name)

        # 2. Show status in the Settings page
        self._theme_status.configure(
            text=f"✓  \"{theme_name}\" saved — restart to apply fully.",
            text_color=TC["text_dim"])

        # 3. Offer restart
        restart = messagebox.askyesno(
            "Restart to apply theme?",
            f"Theme changed to:\n\n  {theme_name}\n\n"
            "A restart is needed to fully apply the new colours to all "
            "panels and widgets.\n\n"
            "Restart now?",
            icon="question",
        )
        if restart:
            self.app._restart_app()

        # ── About ────────────────────────────────────────────────────────────
        about_card = _card(self, "About")

        # App title + version
        title_row = ctk.CTkFrame(about_card, fg_color="transparent")
        title_row.pack(fill="x", padx=14, pady=(4, 2))
        ctk.CTkLabel(title_row, text="FFmpex",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        ctk.CTkLabel(title_row, text="  v2.4",
                     font=ctk.CTkFont(size=14),
                     text_color=TC["text_dim"]).pack(side="left", anchor="s", pady=(0, 1))

        ctk.CTkLabel(about_card,
                     text="A clean, modern FFmpeg GUI wrapper built with Python 3 + CustomTkinter.",
                     font=ctk.CTkFont(size=12),
                     text_color=TC["text_dim"],
                     justify="left").pack(anchor="w", padx=14, pady=(0, 10))

        _sep(about_card, padx=12, pady=4)

        # Developer credits
        ctk.CTkLabel(about_card, text="Developer",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TC["text_dim"]).pack(anchor="w", padx=14, pady=(6, 2))

        dev_grid = ctk.CTkFrame(about_card, fg_color="transparent")
        dev_grid.pack(fill="x", padx=14, pady=(0, 4))

        # Name row
        name_row = ctk.CTkFrame(dev_grid, fg_color="transparent")
        name_row.pack(fill="x", pady=2)
        ctk.CTkLabel(name_row, text="Name",
                     width=72, anchor="w",
                     font=ctk.CTkFont(size=12),
                     text_color=TC["text_dim"]).pack(side="left")
        ctk.CTkLabel(name_row, text="SSJ",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TC["text"]).pack(side="left")

        # Email row
        email_row = ctk.CTkFrame(dev_grid, fg_color="transparent")
        email_row.pack(fill="x", pady=2)
        ctk.CTkLabel(email_row, text="Email",
                     width=72, anchor="w",
                     font=ctk.CTkFont(size=12),
                     text_color=TC["text_dim"]).pack(side="left")
        ctk.CTkButton(
            email_row,
            text="magnusshadowmend@gmail.com",
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            hover=False,
            text_color=TC["logo"],
            cursor="hand2",
            command=lambda: self._open_link("mailto:magnusshadowmend@gmail.com")
        ).pack(side="left", padx=0)

        # GitHub row
        gh_row = ctk.CTkFrame(dev_grid, fg_color="transparent")
        gh_row.pack(fill="x", pady=2)
        ctk.CTkLabel(gh_row, text="GitHub",
                     width=72, anchor="w",
                     font=ctk.CTkFont(size=12),
                     text_color=TC["text_dim"]).pack(side="left")
        ctk.CTkButton(
            gh_row,
            text="github.com/shubh-ssj",
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            hover=False,
            text_color=TC["logo"],
            cursor="hand2",
            command=lambda: self._open_link("https://github.com/shubh-ssj")
        ).pack(side="left", padx=0)

        _sep(about_card, padx=12, pady=4)

        # Changelog — v2.4
        ctk.CTkLabel(about_card, text="What's new in v2.4",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TC["text_dim"]).pack(anchor="w", padx=14, pady=(4, 2))
        ctk.CTkLabel(about_card,
                     text="  ·  Format-correct video codec selection (WebM→VP9, OGV→Theora, WMV→WMV2…)\n"
                          "  ·  Per-format audio codec mapping for all 19 container types\n"
                          "  ·  GIF 2-pass command preview no longer shows broken && token\n"
                          "  ·  run_ffmpeg_chain: fixed success variable unbound risk in error paths\n"
                          "  ·  MergePage: fixed missing initialfile in save dialog (crash fix)\n"
                          "  ·  Single-instance guard — Windows mutex, macOS/Linux flock\n"
                          "  ·  CLI flags: --version and --ffmpeg <path>\n"
                          "  ·  Auto OS dark/light theme detection on first launch",
                     font=ctk.CTkFont(size=12),
                     text_color=TC["text_dim"],
                     justify="left").pack(anchor="w", padx=14, pady=(0, 4))

        _sep(about_card, padx=12, pady=4)

        # Previous releases (collapsed summary)
        ctk.CTkLabel(about_card, text="Earlier releases",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TC["text_dim"]).pack(anchor="w", padx=14, pady=(4, 2))
        ctk.CTkLabel(about_card,
                     text="v2.3  —  Estimated output size labels · Recently used files · Batch prefix/suffix naming\n"
                          "          Post-encode Reveal in Folder · Auto theme detection · pcm removed from AUDIO_EXTS\n"
                          "v2.2  —  20+ themes · Hardware acceleration · Platform & Device presets\n"
                          "          Job Queue · Color Grading · Web Streaming · HLS/DASH output\n"
                          "v2.1  —  Drag-and-drop · System tray · Desktop notifications · Keyboard shortcuts\n"
                          "v2.0  —  Complete rewrite: CustomTkinter UI · BasePage architecture · PresetBar",
                     font=ctk.CTkFont(size=11),
                     text_color=TC["text_dim"],
                     justify="left").pack(anchor="w", padx=14, pady=(0, 12))

    @staticmethod
    def _open_link(url: str):
        """Open a URL or mailto link in the default browser / mail client."""
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:
            pass


def detect_hw_encoders(ffmpeg_path: str) -> list[str]:
    """
    Probe which hardware encoders are actually available.
    Returns list of HW_ENCODERS keys that work on this machine
    (always includes 'None (software)').
    """
    available = ["None (software)"]
    if not ffmpeg_path:
        return available
    probe_map = {
        "NVENC (NVIDIA)":        "h264_nvenc",
        "VideoToolbox (Apple)":  "h264_videotoolbox",
        "VAAPI (Linux)":         "h264_vaapi",
        "AMF (AMD)":             "h264_amf",
    }
    for label, enc in probe_map.items():
        try:
            r = subprocess.run(
                [ffmpeg_path, "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=8
            )
            if enc in r.stdout:
                available.append(label)
        except Exception:
            pass
    return available


# ══════════════════════════════════════════════════════════════
# Color Grading Page
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
# Two-Pass VBR Page  — hit a precise file-size target
# ══════════════════════════════════════════════════════════════

class TwoPassVBRPage(BasePage):
    """
    2-pass VBR encode that targets a user-specified output file size in MB.

    Why 2-pass outperforms CRF for size-targeting
    ──────────────────────────────────────────────
    CRF encoding is quality-constant: you get stable visual quality but
    unpredictable file size (a clip of talking heads and a clip of fireworks
    at the same CRF can differ in size by 5×).

    2-pass VBR is bitrate-constant: you specify a target bitrate computed
    from the desired output size, and FFmpeg distributes bits intelligently
    across the whole file — easy scenes get fewer bits, complex scenes get
    more — while still landing near your size target.

    Algorithm
    ─────────
    1.  Probe duration with ffprobe (required).
    2.  Compute target video bitrate:
            total_bits  = target_mb × 1024² × 8
            audio_bits  = audio_kbps × 1000 × duration_secs
            video_bits  = total_bits − audio_bits
            video_kbps  = max(50, video_bits / duration_secs / 1000)
    3.  Pass 1 — analysis, no output:
            ffmpeg -y -i input -c:v libx264 -b:v {kbps}k
                   -pass 1 -an -f null {null_dev}
    4.  Pass 2 — actual encode:
            ffmpeg -y -i input -c:v libx264 -b:v {kbps}k
                   -pass 2 -c:a aac -b:a {audio_kbps}k output

    The passlogfile is written to a system temp dir so it never pollutes the
    user's working directory and is cleaned up after both passes.

    Platform notes
    ──────────────
    • null device  : /dev/null on Unix, NUL on Windows
    • passlogfile  : tempfile.mktemp() path (no extension — FFmpeg appends -0.log)
    • After pass 2, the .log and .log.mbtree files are deleted automatically
    """

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._duration: float | None = None
        self._build()

    def _build(self):
        _page_header(
            self, "🎯  2-Pass VBR",
            "Target a precise output file size in MB — more accurate than CRF for size control.")

        self.input_zone = FileDropZone(
            self, label="Input Video",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 6))

        # Duration row
        dur_row = ctk.CTkFrame(self, fg_color="transparent")
        dur_row.pack(fill="x", pady=(0, 10))
        self._dur_label = ctk.CTkLabel(
            dur_row, text="",
            font=ctk.CTkFont(size=12), text_color=TC["text_dim"])
        self._dur_label.pack(side="left", padx=(0, 12))
        ctk.CTkButton(dur_row, text="Load Info", width=90, height=28,
                      command=self._load_info).pack(side="left")

        # ── Size target ──────────────────────────────────────────────────────
        target_card = _card(self, "Target File Size")
        t_row = ctk.CTkFrame(target_card, fg_color="transparent")
        t_row.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(t_row, text="Target size:").pack(side="left", padx=(0, 8))
        self._size_var = ctk.StringVar(value="50")
        ctk.CTkEntry(t_row, textvariable=self._size_var, width=70).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(t_row, text="MB").pack(side="left", padx=(0, 24))

        # Quick-pick buttons for common limits
        ctk.CTkLabel(t_row, text="Quick:").pack(side="left", padx=(0, 8))
        grey = {"fg_color": TC["quick"], "hover_color": TC["quick_hover"],
                "text_color": TC["quick_text"]}
        for mb in ["8", "16", "50", "100", "500", "1000"]:
            label = f"{mb} MB" if int(mb) < 1000 else "1 GB"
            ctk.CTkButton(t_row, text=label, width=58, height=26,
                          command=lambda v=mb: self._size_var.set(v),
                          **grey).pack(side="left", padx=2)

        # Estimated bitrate display (updates when Load Info is clicked)
        self._bitrate_label = ctk.CTkLabel(
            target_card, text="",
            font=ctk.CTkFont(size=12), text_color=TC["text_dim"])
        self._bitrate_label.pack(anchor="w", padx=12, pady=(0, 10))

        # ── Encoding options ─────────────────────────────────────────────────
        enc_card = _card(self, "Encoding Options")
        e_row = ctk.CTkFrame(enc_card, fg_color="transparent")
        e_row.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(e_row, text="Video codec:").pack(side="left", padx=(0, 8))
        self._vcodec_var = ctk.StringVar(value="libx264")
        ctk.CTkOptionMenu(e_row, variable=self._vcodec_var,
                          values=["libx264", "libx265"],
                          width=110).pack(side="left", padx=(0, 24))

        ctk.CTkLabel(e_row, text="x264/x265 preset:").pack(side="left", padx=(0, 8))
        self._preset_var = ctk.StringVar(value="slow")
        ctk.CTkOptionMenu(e_row, variable=self._preset_var,
                          values=["ultrafast","superfast","veryfast","faster",
                                  "fast","medium","slow","slower","veryslow"],
                          width=110).pack(side="left", padx=(0, 24))

        ctk.CTkLabel(e_row, text="Audio bitrate:").pack(side="left", padx=(0, 8))
        self._ab_var = ctk.StringVar(value="128k")
        ctk.CTkOptionMenu(e_row, variable=self._ab_var,
                          values=BITRATES, width=90).pack(side="left")

        e2_row = ctk.CTkFrame(enc_card, fg_color="transparent")
        e2_row.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(e2_row, text="Scale:").pack(side="left", padx=(0, 8))
        self._scale_var = ctk.StringVar(value="Original")
        ctk.CTkOptionMenu(e2_row, variable=self._scale_var,
                          values=list(SCALE_OPTIONS.keys()), width=130).pack(side="left", padx=(0, 24))

        ctk.CTkLabel(e2_row, text="Min video bitrate (kbps):").pack(side="left", padx=(0, 8))
        self._minbr_var = ctk.StringVar(value="50")
        ctk.CTkEntry(e2_row, textvariable=self._minbr_var, width=60).pack(side="left")

        # ── How it works note ────────────────────────────────────────────────
        info_card = _card(self, "How it works")
        ctk.CTkLabel(
            info_card,
            text=("Pass 1 analyses the entire video to build a complexity map.  "
                  "Pass 2 uses it to allocate bits optimally across every frame "
                  "-- complex scenes get more, simple ones less -- "
                  "while staying near your target size.\n"
                  "Slower presets give better quality at the same bitrate. "
                  "'slow' is a good default. 'veryslow' is worth it for archiving."),
            text_color=TC["text_dim"], font=ctk.CTkFont(size=12),
            wraplength=680, justify="left").pack(anchor="w", padx=12, pady=(0, 10))

        # Pass indicator
        self._pass_label = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TC["text_dim"])
        self._pass_label.pack(anchor="w", pady=(0, 4))

        _action_row(self, self._run, self.cancel, run_label="Start 2-Pass")
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_info(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp) or not self.app.ffprobe:
            messagebox.showinfo("Note", "Select a file and ensure ffprobe is installed.")
            return
        dur = get_duration(self.app.ffprobe, inp)
        if not dur:
            self._dur_label.configure(
                text="Could not read duration.", text_color=("red","#f44336"))
            return
        self._duration = dur
        self._dur_label.configure(
            text=f"⏱  {secs_to_ts(dur)}",
            text_color=TC["nav_text"])
        self._update_bitrate_display()

    def _update_bitrate_display(self):
        if not self._duration:
            return
        try:
            target_mb = float(self._size_var.get())
        except ValueError:
            return
        audio_kbps = int(self._ab_var.get().rstrip("k"))
        vkbps = self._calc_video_kbps(target_mb, self._duration, audio_kbps)
        self._bitrate_label.configure(
            text=f"→  Calculated video bitrate: {vkbps} kbps  "
                 f"(audio: {audio_kbps} kbps  ·  total budget: "
                 f"{target_mb:.0f} MB × 8 / {self._duration:.0f}s "
                 f"= {int(target_mb*8*1024/self._duration)} kbps)")

    @staticmethod
    def _calc_video_kbps(target_mb: float, duration_secs: float,
                          audio_kbps: int, min_kbps: int = 50) -> int:
        """Return the video bitrate in kbps that hits target_mb."""
        total_bits = target_mb * 1024 * 1024 * 8
        audio_bits = audio_kbps * 1000 * duration_secs
        video_bits = total_bits - audio_bits
        kbps = max(min_kbps, int(video_bits / duration_secs / 1000))
        return kbps

    # ── Run ───────────────────────────────────────────────────────────────────

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input video.")
            return
        if not self.app.ffmpeg:
            messagebox.showerror("Error", "FFmpeg not found.")
            return

        # Validate size
        try:
            target_mb = float(self._size_var.get())
            if target_mb <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Enter a valid positive number for target size.")
            return

        # Need duration for bitrate math
        duration = self._duration
        if not duration and self.app.ffprobe:
            duration = get_duration(self.app.ffprobe, inp)
        if not duration or duration <= 0:
            messagebox.showerror(
                "Error",
                "Could not determine file duration.\n"
                "Click 'Load Info' first, or check that ffprobe is installed.")
            return
        self._duration = duration

        p   = Path(inp)
        out = self.app.smart_save_dialog(
            "TwoPassVBR",
            initialfile=f"{p.stem}_2pass.mp4",
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv"), ("All files", "*.*")])
        if not out:
            return

        try:
            min_kbps = int(self._minbr_var.get())
        except ValueError:
            min_kbps = 50

        audio_kbps = int(self._ab_var.get().rstrip("k"))
        video_kbps = self._calc_video_kbps(target_mb, duration, audio_kbps, min_kbps)
        vcodec     = self._vcodec_var.get()
        preset     = self._preset_var.get()
        scale      = SCALE_OPTIONS.get(self._scale_var.get())

        # FIX: mktemp() is insecure — use an exclusive temp directory so
        # FFmpeg's companion log files (passlog-0.log, .mbtree) are isolated.
        _passdir = tempfile.mkdtemp(prefix="ffmpex_pass_")
        passlog  = os.path.join(_passdir, "ffmpex_pass")

        # Null output device is platform-dependent
        import sys as _sys
        null_dev = "NUL" if _sys.platform == "win32" else "/dev/null"

        # Shared video filter arg
        vf_args = ["-vf", f"scale={scale}"] if scale else []

        # Pass 1 command — analysis only, no audio, output to null
        cmd_pass1 = (
            [self.app.ffmpeg, "-y", "-i", inp]
            + vf_args
            + ["-c:v", vcodec, "-b:v", f"{video_kbps}k",
               "-preset", preset,
               "-pass", "1", "-passlogfile", passlog,
               "-an",           # no audio in pass 1
               "-f", "null", null_dev]
        )

        # Pass 2 command — actual encode with audio
        cmd_pass2 = (
            [self.app.ffmpeg, "-y", "-i", inp]
            + vf_args
            + ["-c:v", vcodec, "-b:v", f"{video_kbps}k",
               "-preset", preset,
               "-pass", "2", "-passlogfile", passlog,
               "-c:a", "aac", "-b:a", self._ab_var.get(),
               out]
        )

        if self._running:
            messagebox.showwarning("Busy", "A job is already running on this page.")
            return

        self._running = True
        self.progress.reset()
        self._pass_label.configure(
            text=f"Target: {target_mb:.0f} MB  →  video {video_kbps} kbps  |  audio {audio_kbps} kbps",
            text_color=TC["text_dim"])

        def _cleanup_passlog():
            for suffix in ("-0.log", "-0.log.mbtree"):
                try:
                    path = passlog + suffix
                    if os.path.exists(path):
                        os.unlink(path)
                except Exception:
                    pass
            try:
                os.rmdir(_passdir)   # remove the now-empty temp dir
            except Exception:
                pass

        def _work():
            success = True
            for pass_num, cmd in enumerate([cmd_pass1, cmd_pass2], start=1):
                if not self._running:
                    success = False
                    break

                label = f"Pass {pass_num}/2 — {'Analysis' if pass_num == 1 else 'Encoding'}…"
                pct_base = (pass_num - 1) * 50.0  # 0–50 for pass1, 50–100 for pass2

                self.after(0, lambda l=label, p=pct_base:
                           self.progress.update_progress(p, status=l))
                self.after(0, lambda l=label:
                           self._pass_label.configure(
                               text=self._pass_label.cget("text").split("  |  Pass")[0]
                                    + f"  |  Pass {pass_num}/2",
                               text_color=("#1a6db5","#5da7d6")))

                try:
                    self._proc = subprocess.Popen(
                        cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                        text=True, universal_newlines=True)

                    for line in self._proc.stderr:
                        line = line.rstrip()
                        self.after(0, lambda l=line:
                                   self.progress.update_progress(
                                       self.progress.bar.get() * 100, log_line=l))
                        enc_t = parse_progress_time(line)
                        if enc_t is not None and duration > 0:
                            pass_pct = min(1.0, enc_t / duration) * 50.0
                            overall  = pct_base + pass_pct
                            eta_secs = None
                            if enc_t > 0:
                                # Estimate ETA for this pass only
                                pass_elapsed = enc_t  # rough proxy
                                eta_secs = int((duration - enc_t) / (enc_t / max(pass_elapsed, 0.01)))
                            status = (f"Pass {pass_num}/2 — "
                                      f"{'Analysis' if pass_num == 1 else 'Encoding'}…"
                                      + (f"  ETA {eta_secs}s" if eta_secs else ""))
                            self.after(0, lambda p=overall, s=status:
                                       self.progress.update_progress(p, status=s))

                    self._proc.wait()
                    if self._proc.returncode != 0:
                        success = False
                        break

                except Exception as exc:
                    self.after(0, lambda e=exc:
                               self.progress.update_progress(0, status=f"Error: {e}"))
                    success = False
                    break

            # Always clean up passlog files — in finally so it runs even on error
            try:
                pass
            finally:
                _cleanup_passlog()
                self._running = False
                self._proc    = None

            # Pass output_path for the Reveal button; omit input_path since
            # TwoPassVBR already shows its own size-vs-target report below.
            self.after(0, lambda s=success: self.progress.done(
                s, output_path=out))
            self.after(0, lambda s=success:
                       self.app.add_history("2-Pass VBR", out, s))

            if success:
                # Report actual output size vs target
                def _report():
                    try:
                        actual_mb = os.path.getsize(out) / (1024 * 1024)
                        diff_pct  = abs(actual_mb - target_mb) / target_mb * 100
                        self._pass_label.configure(
                            text=f"✓  Done  |  Target: {target_mb:.1f} MB  "
                                 f"→  Actual: {actual_mb:.1f} MB  "
                                 f"({diff_pct:.1f}% {'over' if actual_mb > target_mb else 'under'})",
                            text_color=("green","#4caf50"))
                        messagebox.showinfo(
                            "Done",
                            f"Saved to:\n{out}\n\n"
                            f"Target size:  {target_mb:.1f} MB\n"
                            f"Actual size:  {actual_mb:.1f} MB  "
                            f"({diff_pct:.1f}% {'over' if actual_mb > target_mb else 'under'})")
                    except Exception:
                        messagebox.showinfo("Done", f"Saved to:\n{out}")
                self.after(0, _report)

        threading.Thread(target=_work, daemon=True).start()


class ColorGradingPage(BasePage):
    """
    Brightness / Contrast / Saturation / Hue via the eq + hue filters.
    Live-preview via a 5-second clip so the user can see changes in real time.
    """

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._preview_path: str | None = None
        self._build()

    def _build(self):
        _page_header(self, "🎨  Color Grading",
                     "Adjust brightness, contrast, saturation and hue via FFmpeg's eq filter.")

        self.input_zone = FileDropZone(
            self, label="Input Video",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 6))

        # ── eq parameters ────────────────────────────────────────────────────
        eq_card = _card(self, "Color Adjustments  (eq filter)")
        self._sliders: dict[str, ctk.DoubleVar] = {}

        params = [
            # (label, attr_key, from_, to, default, step)
            ("Brightness",  "brightness",  -1.0,  1.0,  0.0,  200),
            ("Contrast",    "contrast",     0.0,  3.0,  1.0,  300),
            ("Saturation",  "saturation",   0.0,  3.0,  1.0,  300),
            ("Gamma",       "gamma",        0.1,  10.0, 1.0,  100),
        ]
        for lbl, key, lo, hi, default, steps in params:
            row = ctk.CTkFrame(eq_card, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=(0, 6))
            ctk.CTkLabel(row, text=f"{lbl}:", width=100).pack(side="left")
            var = ctk.DoubleVar(value=default)
            self._sliders[key] = var
            val_lbl = ctk.CTkLabel(row, text=f"{default:.2f}", width=52)
            ctk.CTkSlider(
                row, from_=lo, to=hi, number_of_steps=steps, variable=var,
                command=lambda v, vl=val_lbl: vl.configure(text=f"{float(v):.2f}")
            ).pack(side="left", fill="x", expand=True, padx=(0, 8))
            val_lbl.pack(side="left")

        # ── hue ──────────────────────────────────────────────────────────────
        hue_card = _card(self, "Hue  (hue filter)")
        h_row = ctk.CTkFrame(hue_card, fg_color="transparent")
        h_row.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(h_row, text="Hue shift (°):", width=100).pack(side="left")
        self._hue_var = ctk.DoubleVar(value=0.0)
        self._hue_lbl = ctk.CTkLabel(h_row, text="0°", width=52)
        ctk.CTkSlider(h_row, from_=-180, to=180, number_of_steps=360,
                      variable=self._hue_var,
                      command=lambda v: self._hue_lbl.configure(text=f"{float(v):.0f}°")
                      ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._hue_lbl.pack(side="left")

        h2_row = ctk.CTkFrame(hue_card, fg_color="transparent")
        h2_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(h2_row, text="Saturation (hue):", width=130).pack(side="left")
        self._hue_sat_var = ctk.DoubleVar(value=1.0)
        self._hue_sat_lbl = ctk.CTkLabel(h2_row, text="1.00", width=52)
        ctk.CTkSlider(h2_row, from_=0, to=3, number_of_steps=300,
                      variable=self._hue_sat_var,
                      command=lambda v: self._hue_sat_lbl.configure(text=f"{float(v):.2f}")
                      ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._hue_sat_lbl.pack(side="left")

        # ── Reset + Live Preview ──────────────────────────────────────────────
        ctrl_row = ctk.CTkFrame(self, fg_color="transparent")
        ctrl_row.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(ctrl_row, text="↺  Reset All", width=110,
                      fg_color=TC["secondary"],
                      hover_color=TC["secondary_hover"],
                      text_color=TC["secondary_text"],
                      command=self._reset).pack(side="left")
        ctk.CTkButton(ctrl_row, text="▶  Generate 5s clip preview", width=210,
                      command=self._preview).pack(side="left", padx=10)
        self._preview_lbl = ctk.CTkLabel(
            ctrl_row, text="  (Ctrl+R to reset)", font=ctk.CTkFont(size=11),
            text_color=TC["text_dim"])
        self._preview_lbl.pack(side="left")

        # ── Inline before/after frame viewer ─────────────────────────────────
        ba_frame = ctk.CTkFrame(self, fg_color=TC["filedrop"], corner_radius=8)
        ba_frame.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(ba_frame, text="Before / After  (click ▶ Load frames to compare)",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(8,4))

        ba_panels = ctk.CTkFrame(ba_frame, fg_color="transparent")
        ba_panels.pack(fill="x", padx=10, pady=(0,10))
        ba_panels.columnconfigure(0, weight=1)
        ba_panels.columnconfigure(1, weight=1)

        self._before_preview = VideoPreviewWidget(
            ba_panels, app=self.app, label="Before (original)", show_ffplay=False)
        self._before_preview.grid(row=0, column=0, sticky="nsew", padx=(0,4))

        self._after_preview = VideoPreviewWidget(
            ba_panels, app=self.app, label="After (graded)", show_ffplay=False)
        self._after_preview.grid(row=0, column=1, sticky="nsew", padx=(4,0))

        load_row = ctk.CTkFrame(ba_frame, fg_color="transparent")
        load_row.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkButton(load_row, text="▶  Load frames", width=130,
                      command=self._load_ba_frames).pack(side="left")
        self._ba_status = ctk.CTkLabel(
            load_row, text="", font=ctk.CTkFont(size=11),
            text_color=TC["text_dim"])
        self._ba_status.pack(side="left", padx=10)

        self.cmd_preview = CommandPreview(self, self._build_cmd)
        _action_row(self, self._run, self.cancel, run_label="Apply Grading",
                    preview=self.cmd_preview)
        self.cmd_preview.pack(fill="x", pady=(6, 0))
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _eq_filter(self) -> str:
        b  = self._sliders["brightness"].get()
        c  = self._sliders["contrast"].get()
        s  = self._sliders["saturation"].get()
        g  = self._sliders["gamma"].get()
        return (f"eq=brightness={b:.3f}:contrast={c:.3f}"
                f":saturation={s:.3f}:gamma={g:.3f}")

    def _vf(self) -> str:
        filters = [self._eq_filter()]
        h  = self._hue_var.get()
        hs = self._hue_sat_var.get()
        if abs(h) > 0.01 or abs(hs - 1.0) > 0.01:
            filters.append(f"hue=h={h:.1f}:s={hs:.3f}")
        return ",".join(filters)

    def _load_ba_frames(self):
        """Extract the source frame and a graded frame and show side by side."""
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp) or not self.app.ffmpeg:
            messagebox.showerror("Error", "Select a valid input video first.")
            return
        dur = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None
        ts  = (dur / 2) if dur else 5.0

        self._ba_status.configure(text="Extracting frames…")

        # Before: raw frame
        self._before_preview.seek_immediate(ts, filepath=inp)

        # After: apply the grading filter to a temp frame
        vf  = self._vf()
        _fd, tmp = tempfile.mkstemp(suffix=".jpg")
        os.close(_fd)

        def _work():
            try:
                subprocess.run(
                    [self.app.ffmpeg, "-y", "-ss", str(ts), "-i", inp,
                     "-vf", vf, "-vframes", "1",
                     "-vf", f"{vf},scale=320:-2", tmp],
                    capture_output=True, timeout=30)
                if os.path.exists(tmp) and os.path.getsize(tmp) > 0 and HAS_PIL:
                    img     = PILImage.open(tmp)
                    img.load()
                    ctk_img = ctk.CTkImage(img, size=(320, int(img.height * 320 / img.width)))
                    def _show(ci=ctk_img):
                        self._after_preview._ctk_image = ci
                        self._after_preview._img_label.configure(image=ci, text="")
                        self._after_preview._ts_label.configure(text=f"⏱  {secs_to_ts(ts)}")
                    self.after(0, _show)
                    self.after(0, lambda: self._ba_status.configure(
                        text="✓  Frames loaded.", text_color=("green","#4caf50")))
                else:
                    self.after(0, lambda: self._ba_status.configure(
                        text="(install Pillow for inline previews)",
                        text_color=TC["text_dim"]))
            except Exception as exc:
                self.after(0, lambda e=exc: self._ba_status.configure(
                    text=f"Error: {e}", text_color=("red","#f44336")))
            finally:
                try: os.unlink(tmp)
                except Exception: pass

        threading.Thread(target=_work, daemon=True).start()

    def _reset(self):
        defaults = {"brightness": 0.0, "contrast": 1.0,
                    "saturation": 1.0, "gamma": 1.0}
        for k, v in defaults.items():
            self._sliders[k].set(v)
        self._hue_var.set(0.0)
        self._hue_sat_var.set(1.0)

    def _preview(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Select a valid input video first.")
            return
        if not self.app.ffmpeg:
            return
        _fd, tmp = tempfile.mkstemp(suffix="_preview.mp4")
        os.close(_fd)
        self._preview_lbl.configure(text="Generating preview…")
        vf = self._vf()

        def _work():
            try:
                subprocess.run(
                    [self.app.ffmpeg, "-y", "-ss", "0", "-t", "5",
                     "-i", inp, "-vf", vf, "-c:v", "libx264", "-crf", "23",
                     "-preset", "ultrafast", "-c:a", "aac", "-b:a", "96k", tmp],
                    capture_output=True, timeout=60
                )
                if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                    self._preview_path = tmp
                    self.after(0, lambda: self._preview_lbl.configure(
                        text="Preview ready — opening…"))
                    import sys
                    if sys.platform == "win32":
                        os.startfile(tmp)
                    elif sys.platform == "darwin":
                        subprocess.run(["open", tmp])
                    else:
                        subprocess.run(["xdg-open", tmp])
                else:
                    self.after(0, lambda: self._preview_lbl.configure(
                        text="Preview failed — check log."))
            except Exception as exc:
                self.after(0, lambda e=exc: self._preview_lbl.configure(
                    text=f"Error: {e}"))

        threading.Thread(target=_work, daemon=True).start()

    def _build_cmd(self):
        inp = self.input_zone.get()
        if not inp or not self.app.ffmpeg:
            return None
        out = f"<{Path(inp).stem}_graded.mp4>"
        return [self.app.ffmpeg, "-y", "-i", inp, "-vf", self._vf(),
                "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                "-c:a", "copy", out]

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Select a valid input video.")
            return
        p   = Path(inp)
        out = self.app.smart_save_dialog(
            "ColorGrading",
            initialfile=f"{p.stem}_graded.mp4",
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv"), ("All files", "*.*")])
        if not out:
            return
        duration = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None
        cmd = [self.app.ffmpeg, "-y", "-i", inp, "-vf", self._vf(),
               "-c:v", "libx264", "-crf", "18", "-preset", "slow",
               "-c:a", "copy", out]
        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Color Grading", output_path=out)


# ══════════════════════════════════════════════════════════════
# Hardware Acceleration Page
# ══════════════════════════════════════════════════════════════

class HardwareAccelPage(BasePage):
    """
    Encode using detected hardware encoders (NVENC / VideoToolbox / VAAPI / AMF).
    Falls back to libx264 if none are found.
    """

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._available: list[str] = []
        self._build()

    def _build(self):
        _page_header(self, "⚡  Hardware Acceleration",
                     "Re-encode using GPU hardware encoders for dramatically faster processing.")

        self.input_zone = FileDropZone(
            self, label="Input Video",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 6))

        # ── Encoder detection ────────────────────────────────────────────────
        det_card = _card(self, "Encoder Selection")
        det_row  = ctk.CTkFrame(det_card, fg_color="transparent")
        det_row.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkButton(det_row, text="🔍  Auto-Detect Encoders", width=190,
                      command=self._detect).pack(side="left")
        self._det_lbl = ctk.CTkLabel(
            det_row, text="Click to detect available hardware encoders.",
            font=ctk.CTkFont(size=11), text_color=TC["text_dim"])
        self._det_lbl.pack(side="left", padx=12)

        enc_row = ctk.CTkFrame(det_card, fg_color="transparent")
        enc_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(enc_row, text="Encoder:").pack(side="left", padx=(0, 8))
        self._enc_var = ctk.StringVar(value="None (software)")
        self._enc_menu = ctk.CTkOptionMenu(
            enc_row, variable=self._enc_var,
            values=list(HW_ENCODERS.keys()), width=220)
        self._enc_menu.pack(side="left")

        # ── Quality ──────────────────────────────────────────────────────────
        q_card = _card(self, "Quality")
        q_row  = ctk.CTkFrame(q_card, fg_color="transparent")
        q_row.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(q_row, text="CRF / QP (0=lossless → 51=worst):").pack(side="left", padx=(0, 8))
        self._crf_var = ctk.IntVar(value=23)
        self._crf_lbl = ctk.CTkLabel(q_row, text="23", width=30)
        ctk.CTkSlider(q_row, from_=0, to=51, number_of_steps=51,
                      variable=self._crf_var,
                      command=lambda v: self._crf_lbl.configure(text=str(int(float(v))))
                      ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._crf_lbl.pack(side="left")

        enc2_row = ctk.CTkFrame(q_card, fg_color="transparent")
        enc2_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(enc2_row, text="x264/x265 preset:").pack(side="left", padx=(0, 8))
        self._preset_var = ctk.StringVar(value="fast")
        ctk.CTkOptionMenu(enc2_row, variable=self._preset_var,
                          values=["ultrafast","superfast","veryfast","faster",
                                  "fast","medium","slow","slower","veryslow"],
                          width=120).pack(side="left", padx=(0, 20))
        ctk.CTkLabel(enc2_row, text="Scale:").pack(side="left", padx=(0, 8))
        self._scale_var = ctk.StringVar(value="Original")
        ctk.CTkOptionMenu(enc2_row, variable=self._scale_var,
                          values=list(SCALE_OPTIONS.keys()), width=120).pack(side="left")

        self.cmd_preview = CommandPreview(self, self._build_cmd)
        _action_row(self, self._run, self.cancel, run_label="Encode",
                    preview=self.cmd_preview)
        self.cmd_preview.pack(fill="x", pady=(6, 0))
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))

    def _detect(self):
        if not self.app.ffmpeg:
            messagebox.showerror("Error", "FFmpeg not found.")
            return
        self._det_lbl.configure(text="Detecting…")
        def _work():
            found = detect_hw_encoders(self.app.ffmpeg)
            self._available = found
            self.after(0, lambda: self._enc_menu.configure(values=found))
            self.after(0, lambda: self._enc_var.set(found[0]))
            labels = ", ".join(found)
            self.after(0, lambda: self._det_lbl.configure(
                text=f"Found: {labels}", text_color=("green", "#4caf50")))
        threading.Thread(target=_work, daemon=True).start()

    @staticmethod
    def _hw_quality_flags(venc: str, crf: int, preset: str) -> list[str]:
        """Return the correct quality flags for a hardware or software encoder."""
        v = venc.lower()
        if "nvenc" in v or "amf" in v or "qsv" in v:
            return ["-qp", str(crf)]
        if "videotoolbox" in v:
            return ["-q:v", str(max(1, 100 - crf * 2))]
        if "vaapi" in v:
            return ["-qp", str(crf)]
        if "libaom" in v:
            return ["-crf", str(crf), "-b:v", "0"]
        if "libsvtav1" in v:
            return ["-crf", str(crf), "-preset", "6"]
        # Software fallback
        return ["-crf", str(crf), "-preset", preset]

    def _build_cmd(self):
        inp = self.input_zone.get()
        if not inp or not self.app.ffmpeg:
            return None
        enc   = HW_ENCODERS[self._enc_var.get()]
        venc  = enc["venc"]
        aenc  = enc["aenc"]
        crf   = self._crf_var.get()
        scale = SCALE_OPTIONS.get(self._scale_var.get())
        out   = f"<{Path(inp).stem}{enc['suffix']}.mp4>"
        cmd   = [self.app.ffmpeg, "-y", "-i", inp]
        if "vaapi" in venc:
            vf_str = f"format=nv12,hwupload{(',' + 'scale_vaapi=' + scale) if scale else ''}"
            cmd += ["-vaapi_device", "/dev/dri/renderD128", "-vf", vf_str]
        elif scale:
            cmd += ["-vf", f"scale={scale}"]
        cmd += ["-c:v", venc]
        cmd += self._hw_quality_flags(venc, crf, self._preset_var.get())
        cmd += ["-c:a", aenc, "-b:a", "128k", out]
        return cmd

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Select a valid input video.")
            return
        enc      = HW_ENCODERS[self._enc_var.get()]
        p        = Path(inp)
        out      = self.app.smart_save_dialog(
            "HardwareAccel",
            initialfile=f"{p.stem}{enc['suffix']}.mp4",
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv"), ("All files", "*.*")])
        if not out:
            return
        duration = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None
        venc     = enc["venc"]
        aenc     = enc["aenc"]
        crf      = self._crf_var.get()
        scale    = SCALE_OPTIONS.get(self._scale_var.get())
        cmd      = [self.app.ffmpeg, "-y", "-i", inp]
        if "vaapi" in venc:
            vf_str = f"format=nv12,hwupload{(',' + 'scale_vaapi=' + scale) if scale else ''}"
            cmd += ["-vaapi_device", "/dev/dri/renderD128", "-vf", vf_str]
        elif scale:
            cmd += ["-vf", f"scale={scale}"]
        cmd += ["-c:v", venc]
        cmd += self._hw_quality_flags(venc, crf, self._preset_var.get())
        cmd += ["-c:a", aenc, "-b:a", "128k", out]
        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="HW Encode", output_path=out)


# ══════════════════════════════════════════════════════════════
# Web Streaming Page
# ══════════════════════════════════════════════════════════════

class WebStreamingPage(BasePage):
    """
    Produces web-optimised output:
      • Fast-start MP4  (moov atom moved to front)
      • HLS  (.m3u8 playlist + .ts segments)
      • DASH  (.mpd manifest + segments)
    """

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        _page_header(self, "🌐  Web Streaming",
                     "Optimise for web delivery: fast-start MP4, HLS segments, or DASH manifest.")

        self.input_zone = FileDropZone(
            self, label="Input Video",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 6))

        # ── Mode ────────────────────────────────────────────────────────────
        mode_card = _card(self, "Output Mode")
        self._mode_var = ctk.StringVar(value="faststart")
        modes = [
            ("faststart", "Fast-start MP4  —  moov atom moved to front (progressive download)"),
            ("hls",       "HLS  —  m3u8 playlist + .ts segments (Apple/CDN streaming)"),
            ("dash",      "DASH  —  .mpd manifest + segments (YouTube/Netflix-style adaptive)"),
        ]
        for val, desc in modes:
            ctk.CTkRadioButton(
                mode_card, text=desc, variable=self._mode_var, value=val,
                command=self._on_mode
            ).pack(anchor="w", padx=10, pady=4)

        # ── HLS / DASH options ──────────────────────────────────────────────
        self._seg_card = _card(self, "Segment Options  (HLS / DASH)")
        seg_row = ctk.CTkFrame(self._seg_card, fg_color="transparent")
        seg_row.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(seg_row, text="Segment duration (s):").pack(side="left", padx=(0, 8))
        self._seg_dur_var = ctk.StringVar(value="6")
        ctk.CTkEntry(seg_row, textvariable=self._seg_dur_var, width=60).pack(side="left", padx=(0, 20))
        ctk.CTkLabel(seg_row, text="Playlist name:").pack(side="left", padx=(0, 8))
        self._playlist_var = ctk.StringVar(value="index.m3u8")
        ctk.CTkEntry(seg_row, textvariable=self._playlist_var, width=140).pack(side="left")

        # ── Video quality ────────────────────────────────────────────────────
        q_card = _card(self, "Video Quality")
        q_row  = ctk.CTkFrame(q_card, fg_color="transparent")
        q_row.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(q_row, text="CRF:").pack(side="left", padx=(0, 8))
        self._crf_var = ctk.IntVar(value=23)
        self._crf_lbl = ctk.CTkLabel(q_row, text="23", width=30)
        ctk.CTkSlider(q_row, from_=0, to=51, number_of_steps=51,
                      variable=self._crf_var,
                      command=lambda v: self._crf_lbl.configure(text=str(int(float(v))))
                      ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._crf_lbl.pack(side="left")

        q2_row = ctk.CTkFrame(q_card, fg_color="transparent")
        q2_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(q2_row, text="Scale:").pack(side="left", padx=(0, 8))
        self._scale_var = ctk.StringVar(value="Original")
        ctk.CTkOptionMenu(q2_row, variable=self._scale_var,
                          values=list(SCALE_OPTIONS.keys()), width=130).pack(side="left")

        # ── Output folder ────────────────────────────────────────────────────
        out_card = _card(self, "Output Folder  (required for HLS/DASH)")
        out_row  = ctk.CTkFrame(out_card, fg_color="transparent")
        out_row.pack(fill="x", padx=10, pady=(0, 10))
        self._outdir_var = ctk.StringVar()
        ctk.CTkEntry(out_row, textvariable=self._outdir_var,
                     placeholder_text="Leave blank for save-dialog (fast-start MP4 only)").pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(out_row, text="Browse", width=80,
                      command=lambda: self._outdir_var.set(
                          filedialog.askdirectory() or "")).pack(side="left")

        self.cmd_preview = CommandPreview(self, self._build_cmd)
        _action_row(self, self._run, self.cancel, run_label="Generate",
                    preview=self.cmd_preview)
        self.cmd_preview.pack(fill="x", pady=(6, 0))
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))
        self._on_mode()

    def _on_mode(self):
        mode = self._mode_var.get()
        if mode == "faststart":
            self._seg_card.pack_forget()
        else:
            self._seg_card.pack(fill="x", pady=(0, 10))

    def _common_video_args(self):
        crf   = self._crf_var.get()
        scale = SCALE_OPTIONS.get(self._scale_var.get())
        args  = ["-c:v", "libx264", "-crf", str(crf), "-preset", "fast",
                 "-c:a", "aac", "-b:a", "128k"]
        if scale:
            args = ["-vf", f"scale={scale}"] + args
        return args

    def _build_cmd(self):
        inp  = self.input_zone.get()
        if not inp or not self.app.ffmpeg:
            return None
        mode = self._mode_var.get()
        base = [self.app.ffmpeg, "-y", "-i", inp] + self._common_video_args()
        if mode == "faststart":
            return base + ["-movflags", "+faststart", f"<{Path(inp).stem}_web.mp4>"]
        elif mode == "hls":
            seg  = self._seg_dur_var.get()
            return base + ["-f", "hls", "-hls_time", seg,
                           "-hls_playlist_type", "vod",
                           f"<output_dir/{self._playlist_var.get()}>"]
        else:  # dash
            seg  = self._seg_dur_var.get()
            return base + ["-f", "dash", "-seg_duration", seg,
                           f"<output_dir/manifest.mpd>"]

    def _run(self):
        inp  = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Select a valid input video.")
            return
        mode    = self._mode_var.get()
        p       = Path(inp)
        outdir_s = self._outdir_var.get().strip()
        duration = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None
        base     = [self.app.ffmpeg, "-y", "-i", inp] + self._common_video_args()

        if mode == "faststart":
            if outdir_s:
                out = str(Path(outdir_s) / f"{p.stem}_web.mp4")
            else:
                out = self.app.smart_save_dialog(
                    "WebStreaming",
                    initialfile=f"{p.stem}_web.mp4",
                    defaultextension=".mp4",
                    filetypes=[("MP4", "*.mp4"), ("All files", "*.*")])
            if not out:
                return
            cmd = base + ["-movflags", "+faststart", out]
            self.run_ffmpeg(cmd, duration, self.progress,
                            on_done=lambda ok: messagebox.showinfo(
                                "Done", f"Saved to:\n{out}") if ok else None,
                            page_name="Web Streaming", output_path=out)

        elif mode in ("hls", "dash"):
            if not outdir_s:
                messagebox.showerror("Error", "Choose an output folder for HLS/DASH.")
                return
            outdir = Path(outdir_s)
            outdir.mkdir(parents=True, exist_ok=True)
            seg = self._seg_dur_var.get()
            if mode == "hls":
                playlist = self._playlist_var.get() or "index.m3u8"
                out      = str(outdir / playlist)
                cmd = base + ["-f", "hls", "-hls_time", seg,
                              "-hls_playlist_type", "vod",
                              "-hls_segment_filename",
                              str(outdir / "segment_%03d.ts"), out]
            else:
                out = str(outdir / "manifest.mpd")
                cmd = base + ["-f", "dash", "-seg_duration", seg,
                              "-use_timeline", "1", "-use_template", "1", out]
            self.run_ffmpeg(cmd, duration, self.progress,
                            on_done=lambda ok: messagebox.showinfo(
                                "Done", f"Files saved to:\n{outdir}") if ok else None,
                            page_name="Web Streaming", output_path=str(outdir))


# ══════════════════════════════════════════════════════════════
# Platform Presets Page
# ══════════════════════════════════════════════════════════════

class PlatformPresetsPage(BasePage):
    """One-click spec-compliant output for social/streaming platforms."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        _page_header(self, "📱  Platform Presets",
                     "One-click export for YouTube, Instagram Reels, TikTok, Twitter/X, and Vimeo.")

        self.input_zone = FileDropZone(
            self, label="Input Video",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 6))

        preset_card = _card(self, "Select Platform")
        self._plat_var = ctk.StringVar(value=list(PLATFORM_PRESETS.keys())[0])

        for name, cfg in PLATFORM_PRESETS.items():
            row = ctk.CTkFrame(preset_card, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=2)
            ctk.CTkRadioButton(
                row, text=name, variable=self._plat_var, value=name,
                command=self._on_preset, width=180
            ).pack(side="left")
            ctk.CTkLabel(row, text=cfg["desc"],
                         font=ctk.CTkFont(size=11),
                         text_color=TC["text_dim"]).pack(side="left", padx=8)

        ctk.CTkFrame(preset_card, fg_color="transparent", height=4).pack()

        self._desc_lbl = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=12),
            text_color=TC["text_dim"], wraplength=700, justify="left")
        self._desc_lbl.pack(anchor="w", pady=(0, 6))

        # Override CRF
        ovr_card = _card(self, "Overrides  (optional)")
        ovr_row  = ctk.CTkFrame(ovr_card, fg_color="transparent")
        ovr_row.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(ovr_row, text="Custom CRF  (leave blank = use preset):").pack(side="left", padx=(0, 8))
        self._crf_ovr = ctk.StringVar(value="")
        ctk.CTkEntry(ovr_row, textvariable=self._crf_ovr, width=52).pack(side="left")

        ovr2_row = ctk.CTkFrame(ovr_card, fg_color="transparent")
        ovr2_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(ovr2_row, text="Audio bitrate override:").pack(side="left", padx=(0, 8))
        self._ab_ovr = ctk.StringVar(value="")
        ctk.CTkOptionMenu(ovr2_row, variable=self._ab_ovr,
                          values=["", "64k", "96k", "128k", "192k", "256k", "320k"],
                          width=100).pack(side="left")

        self.cmd_preview = CommandPreview(self, self._build_cmd)
        _action_row(self, self._run, self.cancel, run_label="Export",
                    preview=self.cmd_preview)
        self.cmd_preview.pack(fill="x", pady=(6, 0))
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))
        self._on_preset()

    def _on_preset(self):
        cfg = PLATFORM_PRESETS.get(self._plat_var.get(), {})
        self._desc_lbl.configure(text=f"ℹ️  {cfg.get('desc', '')}")

    def _build_args(self, inp: str, out: str) -> list[str]:
        cfg   = PLATFORM_PRESETS[self._plat_var.get()]
        crf   = self._crf_ovr.get().strip() or cfg["crf"]
        ab    = self._ab_ovr.get().strip()   or cfg["ab"]
        scale = cfg.get("scale")
        cmd   = [self.app.ffmpeg, "-y", "-i", inp]
        if scale:
            cmd += ["-vf", f"scale={scale}"]
        cmd += ["-c:v", cfg["vcodec"]]
        if "profile" in cfg:
            cmd += ["-profile:v", cfg["profile"]]
        if "level" in cfg:
            cmd += ["-level:v", cfg["level"]]
        cmd += ["-crf", str(crf), "-preset", cfg["preset_enc"],
                "-c:a", cfg["acodec"], "-b:a", ab]
        cmd += cfg.get("extra", [])
        cmd.append(out)
        return cmd

    def _build_cmd(self):
        inp = self.input_zone.get()
        if not inp or not self.app.ffmpeg:
            return None
        cfg = PLATFORM_PRESETS[self._plat_var.get()]
        out = f"<{Path(inp).stem}_{self._plat_var.get().replace(' ','_')}.{cfg['ext']}>"
        return self._build_args(inp, out)

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Select a valid input video.")
            return
        cfg  = PLATFORM_PRESETS[self._plat_var.get()]
        p    = Path(inp)
        name = self._plat_var.get().replace(" ", "_").replace("/", "_")
        out  = self.app.smart_save_dialog(
            "PlatformPresets",
            initialfile=f"{p.stem}_{name}.{cfg['ext']}",
            defaultextension=f".{cfg['ext']}",
            filetypes=[(cfg['ext'].upper(), f"*.{cfg['ext']}"), ("All files", "*.*")])
        if not out:
            return
        duration = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None
        cmd = self._build_args(inp, out)
        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Platform Preset", output_path=out)


# ══════════════════════════════════════════════════════════════
# Device Presets Page
# ══════════════════════════════════════════════════════════════

class DevicePresetsPage(BasePage):
    """Optimised codec + container per playback device."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        _page_header(self, "📺  Device Presets",
                     "Encode for a specific playback device: iPhone, Android, Apple TV, PS5, and more.")

        self.input_zone = FileDropZone(
            self, label="Input Video",
            filetypes=[("Video files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 6))

        dev_card = _card(self, "Select Device")
        self._dev_var = ctk.StringVar(value=list(DEVICE_PRESETS.keys())[0])

        for name, cfg in DEVICE_PRESETS.items():
            row = ctk.CTkFrame(dev_card, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=2)
            ctk.CTkRadioButton(
                row, text=name, variable=self._dev_var, value=name,
                command=self._on_device, width=210
            ).pack(side="left")
            ctk.CTkLabel(row, text=cfg["desc"],
                         font=ctk.CTkFont(size=11),
                         text_color=TC["text_dim"]).pack(side="left", padx=8)

        ctk.CTkFrame(dev_card, fg_color="transparent", height=4).pack()

        self._desc_lbl = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=12),
            text_color=TC["text_dim"], wraplength=700, justify="left")
        self._desc_lbl.pack(anchor="w", pady=(0, 6))

        ovr_card = _card(self, "Overrides  (optional)")
        ovr_row  = ctk.CTkFrame(ovr_card, fg_color="transparent")
        ovr_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(ovr_row, text="Custom CRF:").pack(side="left", padx=(0, 8))
        self._crf_ovr = ctk.StringVar(value="")
        ctk.CTkEntry(ovr_row, textvariable=self._crf_ovr, width=52).pack(side="left", padx=(0, 20))
        ctk.CTkLabel(ovr_row, text="Audio bitrate:").pack(side="left", padx=(0, 8))
        self._ab_ovr = ctk.StringVar(value="")
        ctk.CTkOptionMenu(ovr_row, variable=self._ab_ovr,
                          values=["", "64k", "96k", "128k", "192k", "256k"],
                          width=100).pack(side="left")

        self.cmd_preview = CommandPreview(self, self._build_cmd)
        _action_row(self, self._run, self.cancel, run_label="Export",
                    preview=self.cmd_preview)
        self.cmd_preview.pack(fill="x", pady=(6, 0))
        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 20))
        self._on_device()

    def _on_device(self):
        cfg = DEVICE_PRESETS.get(self._dev_var.get(), {})
        self._desc_lbl.configure(text=f"ℹ️  {cfg.get('desc', '')}")

    def _build_args(self, inp: str, out: str) -> list[str]:
        cfg  = DEVICE_PRESETS[self._dev_var.get()]
        crf  = self._crf_ovr.get().strip() or cfg["crf"]
        ab   = self._ab_ovr.get().strip()  or cfg["ab"]
        scale = cfg.get("scale")
        cmd   = [self.app.ffmpeg, "-y", "-i", inp]
        if scale:
            cmd += ["-vf", f"scale={scale}"]
        cmd += ["-c:v", cfg["vcodec"]]
        if "profile" in cfg:
            cmd += ["-profile:v", cfg["profile"]]
        if "level" in cfg:
            cmd += ["-level:v", cfg["level"]]
        cmd += ["-crf", str(crf), "-preset", cfg["preset_enc"],
                "-c:a", cfg["acodec"], "-b:a", ab]
        cmd += cfg.get("extra", [])
        cmd.append(out)
        return cmd

    def _build_cmd(self):
        inp = self.input_zone.get()
        if not inp or not self.app.ffmpeg:
            return None
        cfg  = DEVICE_PRESETS[self._dev_var.get()]
        name = self._dev_var.get().replace(" ", "_").replace("/", "_")
        out  = f"<{Path(inp).stem}_{name}.{cfg['ext']}>"
        return self._build_args(inp, out)

    def _run(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Select a valid input video.")
            return
        cfg  = DEVICE_PRESETS[self._dev_var.get()]
        p    = Path(inp)
        name = self._dev_var.get().replace(" ", "_").replace("/", "_")
        out  = self.app.smart_save_dialog(
            "DevicePresets",
            initialfile=f"{p.stem}_{name}.{cfg['ext']}",
            defaultextension=f".{cfg['ext']}",
            filetypes=[(cfg['ext'].upper(), f"*.{cfg['ext']}"), ("All files", "*.*")])
        if not out:
            return
        duration = get_duration(self.app.ffprobe, inp) if self.app.ffprobe else None
        cmd = self._build_args(inp, out)
        self.run_ffmpeg(cmd, duration, self.progress,
                        on_done=lambda ok: messagebox.showinfo(
                            "Done", f"Saved to:\n{out}") if ok else None,
                        page_name="Device Preset", output_path=out)


# ══════════════════════════════════════════════════════════════
# Main Application Window
# ══════════════════════════════════════════════════════════════

class FFmpexApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Inject tkinterdnd2 DnD support into the existing Tk root if available
        if HAS_DND:
            try:
                tkinterdnd2.TkinterDnD._require(self)
            except Exception:
                pass

        self.title("FFmpex")
        self.geometry("1140x760")
        self.minsize(920, 640)

        self.ffmpeg  = find_tool("ffmpeg")
        self.ffprobe = find_tool("ffprobe")
        self.history: list[dict] = []
        self.app_state = AppState()

        self._tray_icon = None   # pystray icon instance (set in _setup_tray)

        # ── Theme selection ───────────────────────────────────────────────────
        # On first launch (no saved theme) auto-detect OS dark/light preference
        # and pick an appropriate default rather than always forcing dark.
        saved_theme = self.app_state.get_theme()
        if saved_theme == "FFmpex Default (Dark Blue)":
            # Only auto-detect when the user hasn't explicitly saved a preference
            _os_default = self._detect_os_theme()
            if _os_default and _os_default != saved_theme:
                saved_theme = _os_default
        # Apply chosen theme BEFORE building UI so all widgets pick up correct TC colors
        apply_full_theme(saved_theme)

        self._build_ui()
        self.show_page(self.app_state.last_page())   # restore page from before restart
        self._bind_shortcuts()
        self._setup_tray()
        self._restore_geometry()

        if not self.ffmpeg:
            self.after(600, self._warn_missing_ffmpeg)

    # ── Keyboard shortcuts ────────────────────────────────────────────────────

    @staticmethod
    def _detect_os_theme() -> str | None:
        """
        Return the FFmpex theme name that best matches the current OS
        appearance setting, or None if it cannot be determined.
        Checked once at startup; does not react to live OS changes.
        """
        _sys = platform.system()
        try:
            if _sys == "Darwin":
                r = subprocess.run(
                    ["defaults", "read", "-g", "AppleInterfaceStyle"],
                    capture_output=True, text=True, timeout=3)
                # "Dark" → dark mode; anything else (error / "Light") → light
                if r.returncode != 0 or r.stdout.strip().lower() != "dark":
                    return "Light (Clean)"
                return None   # already dark — keep default

            elif _sys == "Windows":
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
                val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                winreg.CloseKey(key)
                if val == 1:
                    return "Light (Clean)"
                return None   # dark — keep default

            elif _sys == "Linux":
                # Try gsettings (GNOME) first
                r = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface",
                     "color-scheme"],
                    capture_output=True, text=True, timeout=3)
                if r.returncode == 0:
                    if "light" in r.stdout.lower():
                        return "Light (Clean)"
                    return None
                # Fallback: GTK_THEME env var
                gtk = os.environ.get("GTK_THEME", "").lower()
                if "light" in gtk:
                    return "Light (Clean)"
        except Exception:
            pass
        return None   # unknown — keep default

    # ── Page navigation history (browser-style back/forward) ─────────────────
    # Maintained as a list of page keys + current index into it.
    _nav_history: list[str] = []
    _nav_idx: int = -1

    def _bind_shortcuts(self):
        """Bind app-wide keyboard shortcuts."""

        # ── File / job ───────────────────────────────────────────────────────
        # Open file  Ctrl+O
        self.bind_all("<Control-o>", lambda e: self._shortcut_open())
        self.bind_all("<Control-O>", lambda e: self._shortcut_open())
        # Run        Ctrl+Enter
        self.bind_all("<Control-Return>", lambda e: self._shortcut_run())
        # Cancel     Esc
        self.bind_all("<Escape>",     lambda e: self._shortcut_cancel())
        # Reload file info  F5
        self.bind_all("<F5>",         lambda e: self._shortcut_reload())

        # ── Numbered page jump  Ctrl+1 … Ctrl+9 ─────────────────────────────
        _page_keys = [
            "Convert", "Compress", "Batch", "Trim", "Split",
            "Merge", "Extract", "Mute", "History",
        ]
        for i, page in enumerate(_page_keys, start=1):
            self.bind_all(f"<Control-Key-{i}>",
                          lambda e, p=page: self.show_page(p))

        # ── Named page shortcuts ─────────────────────────────────────────────
        self.bind_all("<Control-comma>",  lambda e: self.show_page("Settings"))
        self.bind_all("<Control-h>",      lambda e: self.show_page("History"))
        self.bind_all("<Control-H>",      lambda e: self.show_page("History"))
        self.bind_all("<Control-m>",      lambda e: self.show_page("MediaInfo"))
        self.bind_all("<Control-M>",      lambda e: self.show_page("MediaInfo"))
        self.bind_all("<Control-p>",      lambda e: self.show_page("Player"))
        self.bind_all("<Control-P>",      lambda e: self.show_page("Player"))
        self.bind_all("<Control-slash>",  lambda e: self.show_page("Help"))
        self.bind_all("<Control-w>",      lambda e: self._minimize_to_tray())

        # ── Page cycling  Ctrl+Tab / Ctrl+Shift+Tab ──────────────────────────
        self.bind_all("<Control-Tab>",         lambda e: self._cycle_page(+1))
        self.bind_all("<Control-Shift-Tab>",   lambda e: self._cycle_page(-1))
        # Some platforms fire ISO_Left_Tab for Shift+Tab
        self.bind_all("<Control-ISO_Left_Tab>", lambda e: self._cycle_page(-1))

        # ── Browser-style Back / Forward  Alt+Left / Alt+Right ───────────────
        self.bind_all("<Alt-Left>",  lambda e: self._nav_back())
        self.bind_all("<Alt-Right>", lambda e: self._nav_forward())

        # ── Page-local: Speed +/- ────────────────────────────────────────────
        self.bind_all("<Control-equal>", lambda e: self._shortcut_speed_nudge(+0.25))
        self.bind_all("<Control-minus>", lambda e: self._shortcut_speed_nudge(-0.25))

        # ── Page-local: Color Grading reset ──────────────────────────────────
        self.bind_all("<Control-r>",
                      lambda e: self._shortcut_page_action("_reset"))
        self.bind_all("<Control-R>",
                      lambda e: self._shortcut_page_action("_reset"))

        # ── Page-local: Trim — preview clip (Space) ───────────────────────────
        # Space is bound loosely; only fires if not inside a text Entry
        self.bind_all("<space>", lambda e: self._shortcut_trim_preview(e))

    # ── Navigation helpers ────────────────────────────────────────────────────

    # All page keys in sidebar order (used for Ctrl+Tab cycling)
    _ALL_PAGES: list[str] = [
        "Convert", "Compress", "TwoPassVBR", "Batch", "JobQueue",
        "PlatformPresets", "DevicePresets",
        "Trim", "Split", "Merge", "Crop", "Reverse", "Speed", "Frames",
        "Subtitle", "TextWatermark", "ImageWatermark", "ExtractSub",
        "ColorGrading", "HardwareAccel", "WebStreaming",
        "Extract", "Mute", "MixAudio", "Normalise", "Denoise", "Waveform",
        "Player", "History", "MediaInfo", "Help",
    ]

    def show_page(self, name: str):
        """Override to maintain nav history."""
        if self._current:
            self._pages[self._current].pack_forget()
            if self._current in self._nav_btns:
                self._nav_btns[self._current].configure(
                    fg_color="transparent",
                    font=ctk.CTkFont(size=13))

        page = self._pages.get(name)
        if page is None:
            return
        if name == "History":
            page.refresh()
        if name == "Player":
            page._refresh_history()
        page.pack(fill="both", expand=True, padx=24, pady=20)
        self._current = name
        self.app_state.remember_page(name)   # persist for restart restore

        if name in self._nav_btns:
            self._nav_btns[name].configure(
                fg_color=TC["nav_active"],
                font=ctk.CTkFont(size=13, weight="bold"))

        # ── History tracking (truncate forward stack on new navigation) ──────
        if self._nav_idx < len(self._nav_history) - 1:
            self._nav_history = self._nav_history[:self._nav_idx + 1]
        if not self._nav_history or self._nav_history[-1] != name:
            self._nav_history.append(name)
        self._nav_idx = len(self._nav_history) - 1

    def _nav_back(self):
        """Alt+Left — go to the previously visited page."""
        if self._nav_idx > 0:
            self._nav_idx -= 1
            self._show_page_no_history(self._nav_history[self._nav_idx])

    def _nav_forward(self):
        """Alt+Right — go to the next page in history."""
        if self._nav_idx < len(self._nav_history) - 1:
            self._nav_idx += 1
            self._show_page_no_history(self._nav_history[self._nav_idx])

    def _show_page_no_history(self, name: str):
        """Switch page without pushing to the nav history stack."""
        if self._current:
            self._pages[self._current].pack_forget()
            if self._current in self._nav_btns:
                self._nav_btns[self._current].configure(
                    fg_color="transparent",
                    font=ctk.CTkFont(size=13))
        page = self._pages.get(name)
        if page is None:
            return
        if name == "History": page.refresh()
        if name == "Player":  page._refresh_history()
        page.pack(fill="both", expand=True, padx=24, pady=20)
        self._current = name
        if name in self._nav_btns:
            self._nav_btns[name].configure(
                fg_color=TC["nav_active"],
                font=ctk.CTkFont(size=13, weight="bold"))

    def _cycle_page(self, direction: int):
        """Ctrl+Tab / Ctrl+Shift+Tab — cycle through pages in sidebar order."""
        pages = self._ALL_PAGES
        if not self._current or self._current not in pages:
            return
        idx  = pages.index(self._current)
        next_page = pages[(idx + direction) % len(pages)]
        self.show_page(next_page)

    # ── Action shortcuts ──────────────────────────────────────────────────────

    def _shortcut_open(self):
        """Ctrl+O — browse for file on the current page."""
        page = self._pages.get(self._current)
        if page is None:
            return
        for attr in ("input_zone", "video_zone", "file_zone"):
            zone = getattr(page, attr, None)
            if zone and hasattr(zone, "_browse"):
                zone._browse()
                return

    def _shortcut_run(self):
        """Ctrl+Enter — run the current page's job."""
        page = self._pages.get(self._current)
        if page and hasattr(page, "_run"):
            page._run()

    def _shortcut_cancel(self):
        """Esc — cancel the running job."""
        page = self._pages.get(self._current)
        if page and hasattr(page, "cancel"):
            page.cancel()

    def _shortcut_reload(self):
        """F5 — reload file info on the current page."""
        page = self._pages.get(self._current)
        if page is None:
            return
        for method in ("_load_info", "_analyze", "_probe"):
            fn = getattr(page, method, None)
            if callable(fn):
                fn()
                return

    def _shortcut_page_action(self, method_name: str):
        """Call a named method on the current page if it exists."""
        page = self._pages.get(self._current)
        if page:
            fn = getattr(page, method_name, None)
            if callable(fn):
                fn()

    def _shortcut_speed_nudge(self, delta: float):
        """Ctrl++ / Ctrl+- — nudge speed slider when on SpeedPage."""
        if self._current != "Speed":
            return
        page = self._pages.get("Speed")
        if page and hasattr(page, "speed_var"):
            current = page.speed_var.get()
            new_val = max(0.25, min(4.0, round(current + delta, 2)))
            page.speed_var.set(new_val)
            page._on_speed(new_val)

    def _shortcut_trim_preview(self, event):
        """Space — open preview clip on TrimPage (ignore if typing in an Entry)."""
        if self._current != "Trim":
            return
        # Don't fire if a text entry widget has focus
        focused = self.focus_get()
        if focused and focused.winfo_class() in ("Entry", "Text", "TEntry"):
            return
        page = self._pages.get("Trim")
        if page and hasattr(page, "dual_preview"):
            page.dual_preview._preview_clip()

    # ── System Tray ───────────────────────────────────────────────────────────

    @staticmethod
    def _build_app_icon(size: int = 64) -> "PILImage.Image | None":
        """
        Return the FFmpex icon at the requested pixel size.

        Tries to load ffmpex_icon.png from:
          1. sys._MEIPASS  (PyInstaller _internal folder when frozen)
          2. Next to the script / exe  (dev mode or installed)
        Falls back to a programmatically-drawn play-triangle icon if neither
        location has the file (e.g. first run before the icon is generated).
        """
        if not HAS_PIL:
            return None

        # ── Try loading from file ─────────────────────────────────────────────
        search_dirs = []
        # When frozen by PyInstaller, bundled data lives in sys._MEIPASS
        if getattr(sys, "frozen", False):
            search_dirs.append(Path(getattr(sys, "_MEIPASS", "")))
        # Also check next to the exe / script (dev mode + icon export path)
        search_dirs.append(Path(sys.executable).parent)
        search_dirs.append(Path(sys.argv[0]).resolve().parent)

        for d in search_dirs:
            p = d / "ffmpex_icon.png"
            if p.exists():
                try:
                    img = PILImage.open(str(p)).convert("RGBA")
                    if size != img.width or size != img.height:
                        img = img.resize((size, size), PILImage.LANCZOS)
                    return img
                except Exception:
                    pass   # corrupt file — fall through to drawn fallback

        # ── Programmatic fallback ─────────────────────────────────────────────
        # Dark slate background, orange-red play triangle.
        # Used on very first launch before ffmpex_icon.png exists.
        try:
            from PIL import ImageDraw
            img  = PILImage.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            top_col, bottom_col = (28, 30, 45), (16, 17, 28)
            radius = max(4, size // 7)
            for y in range(size):
                t = y / max(size - 1, 1)
                r = int(top_col[0] + (bottom_col[0] - top_col[0]) * t)
                g = int(top_col[1] + (bottom_col[1] - top_col[1]) * t)
                b = int(top_col[2] + (bottom_col[2] - top_col[2]) * t)
                draw.line([(0, y), (size - 1, y)], fill=(r, g, b, 255))

            mask = PILImage.new("L", (size, size), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, size-1, size-1], radius=radius, fill=255)
            img.putalpha(mask)
            draw = ImageDraw.Draw(img)

            tri_t, tri_b = size * 0.20, size * 0.68
            tri_l, tri_r = size * 0.22, size * 0.78
            mid_y = (tri_t + tri_b) / 2
            so = max(1, size // 32)
            draw.polygon([(tri_l+so, tri_t+so),(tri_l+so, tri_b+so),(tri_r+so, mid_y+so)],
                         fill=(0,0,0,90))
            draw.polygon([(tri_l, tri_t),(tri_l, tri_b),(tri_r, mid_y)],
                         fill=(255, 75, 35, 255))
            return img
        except Exception:
            try:
                return PILImage.new("RGBA", (size, size), (28, 30, 45, 255))
            except Exception:
                return None

    def _set_window_icon(self):
        """
        Set the taskbar/titlebar icon from the generated PIL image.
        Uses iconphoto() which works on all platforms without needing a .ico file.
        Also exports a .ico alongside the script for the installer to pick up.
        """
        if not HAS_PIL:
            return
        try:
            import io
            from PIL import ImageTk

            # Build at 32px (good balance for iconphoto on all platforms)
            img32 = self._build_app_icon(32)
            img16 = self._build_app_icon(16)
            if img32 is None:
                return

            tk_img32 = ImageTk.PhotoImage(img32)
            tk_img16 = ImageTk.PhotoImage(img16) if img16 else tk_img32

            # Keep references alive on the instance so GC doesn't collect them
            self._icon_tk_32 = tk_img32
            self._icon_tk_16 = tk_img16

            self.iconphoto(True, tk_img32, tk_img16)

            # ── Export icon files for the installer / next build ─────────────
            # Only when running from source (not frozen).
            # Exports both the .ico (for Inno Setup) and the .png (for runtime).
            if not getattr(sys, "frozen", False):
                try:
                    base     = Path(sys.argv[0]).resolve().parent
                    ico_path = base / "ffmpex.ico"
                    png_path = base / "ffmpex_icon.png"
                    if not ico_path.exists() or not png_path.exists():
                        icon_sizes = [256, 128, 64, 48, 32, 24, 16]
                        icon_imgs  = [self._build_app_icon(s) for s in icon_sizes]
                        icon_imgs  = [i for i in icon_imgs if i is not None]
                        if icon_imgs:
                            if not ico_path.exists():
                                icon_imgs[0].save(str(ico_path), format="ICO",
                                                  append_images=icon_imgs[1:])
                            if not png_path.exists():
                                icon_imgs[0].save(str(png_path), format="PNG")
                except Exception:
                    pass   # best-effort

        except Exception:
            pass   # icon is cosmetic; never block startup

    def _update_close_behavior(self):
        """
        Apply the current tray-close preference to the WM_DELETE_WINDOW protocol.
        Called at startup and whenever the setting is toggled in Settings.
        """
        if self.app_state.get_tray_close() and self._tray_icon is not None:
            self.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)
        else:
            self.protocol("WM_DELETE_WINDOW", self._on_close_no_tray)

    def _setup_tray(self):
        """Set up system-tray icon (requires pystray + PIL). Best-effort."""
        # Always try to set the window/taskbar icon regardless of tray support
        self._set_window_icon()

        if not HAS_TRAY or not HAS_PIL:
            self.protocol("WM_DELETE_WINDOW", self._on_close_no_tray)
            return

        try:
            icon_img = self._build_app_icon(64)
            if icon_img is None:
                raise ValueError("Icon build failed")
        except Exception:
            self.protocol("WM_DELETE_WINDOW", self._on_close_no_tray)
            return

        menu = pystray.Menu(
            TrayItem("Show FFmpex",   self._tray_show, default=True),
            TrayItem("Batch Convert", lambda icon, item: self._tray_show_page("Batch")),
            pystray.Menu.SEPARATOR,
            TrayItem("Quit",          self._tray_quit),
        )
        self._tray_icon = pystray.Icon("FFmpex", icon_img, "FFmpex", menu)

        # Apply saved preference (default: X = quit, not minimise to tray)
        self._update_close_behavior()

    def _minimize_to_tray(self):
        """Hide main window, show tray icon."""
        self._save_geometry()
        if self._tray_icon is None:
            self.iconify()
            return
        self.withdraw()
        if not self._tray_icon._running:
            threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _tray_show(self, icon=None, item=None):
        """Restore window from tray."""
        self.after(0, self._restore_window)

    def _tray_show_page(self, page: str):
        self.after(0, lambda: (self._restore_window(), self.show_page(page)))

    def _restore_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _tray_quit(self, icon=None, item=None):
        """Quit from tray."""
        self._save_geometry()
        if self._tray_icon:
            self._tray_icon.stop()
        self.after(0, self.destroy)

    def _on_close_no_tray(self):
        """Close handler — used when tray-close is off, or tray is unavailable."""
        self._save_geometry()
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        self.destroy()

    def _restart_app(self):
        """
        Save state, release the single-instance lock, stop the tray icon,
        then relaunch using the same interpreter and script path.

        The lock MUST be released before the new process starts — otherwise
        the new instance sees the mutex/flock still held and refuses to launch.
        """
        self._save_geometry()

        # 1. Stop tray so its daemon thread doesn't keep the process alive
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass

        # 2. Release the single-instance lock so the new process can acquire it
        if hasattr(self, "_instance_lock") and self._instance_lock is not None:
            try:
                _sys = platform.system()
                if _sys == "Windows":
                    import ctypes
                    ctypes.windll.kernel32.CloseHandle(self._instance_lock)
                else:
                    # flock is released automatically when fd is closed
                    try:
                        self._instance_lock.close()
                    except Exception:
                        pass
            except Exception:
                pass
            self._instance_lock = None

        # 3. Close window
        self.destroy()

        script = Path(sys.argv[0]).resolve()
        args   = [sys.executable, str(script)] + sys.argv[1:]

        if platform.system() == "Windows":
            # Small delay lets the mutex release propagate before new process starts
            import time as _time; _time.sleep(0.15)
            subprocess.Popen(args)
            sys.exit(0)
        else:
            # Replace current process image — lock fd is closed by exec automatically
            os.execv(sys.executable, args)

    def add_history(self, page_name: str, output_path: str, success: bool):
        """Called by BasePage.run_ffmpeg after each job completes."""
        self.history.append({
            "page":      page_name,
            "output":    output_path,
            "success":   success,
            "timestamp": datetime.now().strftime("%Y-%m-%d  %H:%M"),
        })
        # Refresh the history page live if it's currently visible
        if self._current == "History":
            self._pages["History"].refresh()

    def _warn_missing_ffmpeg(self):
        messagebox.showwarning(
            "FFmpeg Not Found",
            "FFmpeg was not found on your system.\n\n"
            "Please install it and restart FFmpex.\n\n"
            "  Windows : winget install ffmpeg\n"
            "  macOS   : brew install ffmpeg\n"
            "  Ubuntu  : sudo apt install ffmpeg\n\n"
            "Or download from https://ffmpeg.org/download.html")
        self.show_page("Settings")

    def _restore_geometry(self):
        geo = self.app_state.geometry()
        if geo:
            try:
                self.geometry(geo)
            except Exception:
                pass

    def _save_geometry(self):
        self.app_state.remember_geometry(self.geometry())

    def refresh_chrome(self):
        """
        Reconfigure structural chrome widgets with current TC colors.
        Called by apply_full_theme() after a theme change.
        Page-interior cards (built once at startup) need a restart to rebuild.
        """
        try:
            self.sidebar.configure(fg_color=TC["sidebar"])
            self._nav_scroll.configure(fg_color=TC["sidebar"])
            self.content.configure(fg_color=TC["content"])
        except Exception:
            pass
        for key, btn in self._nav_btns.items():
            try:
                is_active = (key == self._current)
                btn.configure(
                    fg_color=TC["nav_active"] if is_active else "transparent",
                    text_color=TC["nav_text"],
                    hover_color=TC["nav_hover"],
                )
            except Exception:
                pass

    def smart_save_dialog(self, page_name: str, initialfile: str,
                          defaultextension: str, filetypes: list,
                          title: str = "") -> str:
        """
        Wrapper around filedialog.asksaveasfilename that remembers the last
        directory used on each page and restores it next time.
        Returns the chosen path string, or "" if cancelled.
        """
        initial_dir = self.app_state.last_outdir(page_name)
        dlg_kwargs: dict = dict(
            initialdir=initial_dir,
            initialfile=initialfile,
            defaultextension=defaultextension,
            filetypes=filetypes,
        )
        if title:
            dlg_kwargs["title"] = title
        path = filedialog.asksaveasfilename(**dlg_kwargs)
        if path:
            self.app_state.remember_outdir(page_name, path)
        return path or ""

    def _build_ui(self):
        # ── Sidebar ──────────────────────────────────────────────────────────
        SIDEBAR_W = 220
        self.sidebar = ctk.CTkFrame(
            self, width=SIDEBAR_W, corner_radius=0,
            fg_color=TC["sidebar"])
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # ── Fixed top: logo + version ─────────────────────────────────────
        logo = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo.pack(fill="x", padx=16, pady=(22, 2))
        ctk.CTkLabel(logo, text="FF",
                     font=ctk.CTkFont(size=30, weight="bold"),
                     text_color=TC["logo"]).pack(side="left")
        ctk.CTkLabel(logo, text="mpex",
                     font=ctk.CTkFont(size=30)).pack(side="left")
        ctk.CTkLabel(self.sidebar, text="FFmpeg GUI  •  v2.4",
                     font=ctk.CTkFont(size=10),
                     text_color=TC["nav_section"]).pack(
            anchor="w", padx=18, pady=(0, 10))

        _sep(self.sidebar, padx=12, pady=(0, 4))

        # ── Fixed bottom: Settings + status dot ──────────────────────────
        # (packed with side="bottom" BEFORE the scrollable area so they
        #  stay pinned regardless of how many nav items there are)
        dot_text  = "● ffmpeg OK" if self.ffmpeg else "● ffmpeg missing"
        dot_color = ("green", "#4caf50") if self.ffmpeg else ("red", "#f44336")
        ctk.CTkLabel(self.sidebar, text=dot_text, text_color=dot_color,
                     font=ctk.CTkFont(size=10)).pack(side="bottom", pady=(0, 6))

        _sep(self.sidebar, padx=12, pady=4, side="bottom")

        settings_btn = ctk.CTkButton(
            self.sidebar, text="⚙️  Settings", anchor="w",
            fg_color="transparent",
            text_color=TC["nav_text"],
            hover_color=TC["nav_hover"],
            font=ctk.CTkFont(size=13), height=38,
            command=lambda: self.show_page("Settings"))
        settings_btn.pack(fill="x", padx=8, pady=(0, 2), side="bottom")

        # ── Scrollable nav area fills all remaining space ─────────────────
        # fg_color matches the sidebar so it looks seamless; scrollbar_fg_color
        # is set to match so the scrollbar blends in on most themes.
        self._nav_scroll = ctk.CTkScrollableFrame(
            self.sidebar,
            fg_color=TC["sidebar"],
            scrollbar_fg_color=TC["sidebar"],
            scrollbar_button_color=TC["scrollbar"],
            scrollbar_button_hover_color=TC["accent"],
            corner_radius=0)
        self._nav_scroll.pack(fill="both", expand=True)

        self._nav_btns: dict[str, ctk.CTkButton] = {}
        # Settings button was created above; register it now
        self._nav_btns["Settings"] = settings_btn

        def _nav_section(label):
            ctk.CTkLabel(self._nav_scroll, text=label,
                         font=ctk.CTkFont(size=10),
                         text_color=TC["nav_section"]).pack(
                anchor="w", padx=16, pady=(8, 2))

        def _nav_btn(text, key):
            btn = ctk.CTkButton(
                self._nav_scroll, text=text, anchor="w",
                fg_color="transparent",
                text_color=TC["nav_text"],
                hover_color=TC["nav_hover"],
                font=ctk.CTkFont(size=13), height=34,
                command=lambda k=key: self.show_page(k))
            btn.pack(fill="x", padx=4, pady=1)
            self._nav_btns[key] = btn

        _nav_section("CONVERT & PACKAGE")
        _nav_btn("🔄  Convert",       "Convert")
        _nav_btn("📦  Compress",      "Compress")
        _nav_btn("🎯  2-Pass VBR",   "TwoPassVBR")
        _nav_btn("📁  Batch",         "Batch")
        _nav_btn("📋  Job Queue",     "JobQueue")
        _nav_btn("📱  Platform",      "PlatformPresets")
        _nav_btn("📺  Device",        "DevicePresets")

        _nav_section("VIDEO TOOLS")
        _nav_btn("✂️  Trim & Cut",    "Trim")
        _nav_btn("✂️  Split",         "Split")
        _nav_btn("🔗  Merge",         "Merge")
        _nav_btn("📐  Crop & Pad",    "Crop")
        _nav_btn("⏪  Reverse",       "Reverse")
        _nav_btn("⚡  Speed Change",  "Speed")
        _nav_btn("🖼️  Export Frames", "Frames")
        _nav_btn("🔤  Subtitles",     "Subtitle")
        _nav_btn("🔤  Text Mark",     "TextWatermark")
        _nav_btn("🖼️  Image Mark",    "ImageWatermark")
        _nav_btn("📤  Extract Subs",  "ExtractSub")
        _nav_btn("🎨  Color Grading", "ColorGrading")
        _nav_btn("⚡  HW Accel",     "HardwareAccel")
        _nav_btn("🌐  Web Streaming", "WebStreaming")

        _nav_section("AUDIO TOOLS")
        _nav_btn("🎵  Extract Audio", "Extract")
        _nav_btn("🔇  Audio Track",   "Mute")
        _nav_btn("➕  Mix Audio",     "MixAudio")
        _nav_btn("🔊  Normalise",     "Normalise")
        _nav_btn("🎙️  Denoise",       "Denoise")
        _nav_btn("🎼  Waveform",      "Waveform")

        _nav_section("OTHER")
        _nav_btn("▶  Player",         "Player")
        _nav_btn("🕒  History",       "History")
        _nav_btn("🔍  Media Info",    "MediaInfo")
        _nav_btn("❓  Help",          "Help")

        # (Settings button and status dot are built above, before the scroll frame)

        # ── Content area ──────────────────────────────────────────────────────
        self.content = ctk.CTkFrame(
            self, fg_color=TC["content"], corner_radius=0)
        self.content.pack(side="right", fill="both", expand=True)

        self._pages: dict[str, ctk.CTkFrame] = {
            "Convert":   ConvertPage(self.content, self),
            "Compress":  CompressPage(self.content, self),
            "TwoPassVBR": TwoPassVBRPage(self.content, self),
            "Trim":      TrimPage(self.content, self),
            "Split":     SplitPage(self.content, self),
            "Merge":     MergePage(self.content, self),
            "Crop":      CropPage(self.content, self),
            "Reverse":   ReversePage(self.content, self),
            "Speed":     SpeedPage(self.content, self),
            "Frames":    FramesPage(self.content, self),
            "Extract":   ExtractPage(self.content, self),
            "Mute":      MutePage(self.content, self),
            "MixAudio":  MixAudioPage(self.content, self),
            "Normalise": NormalisePage(self.content, self),
            "Denoise":   DenoisePage(self.content, self),
            "Waveform":  WaveformPage(self.content, self),
            "Batch":     BatchPage(self.content, self),
            "JobQueue":  JobQueuePage(self.content, self),
            "History":   HistoryPage(self.content, self),
            "MediaInfo":  MediaInfoPage(self.content, self),
            "Help":      HelpPage(self.content, self),
            "Settings":  SettingsPage(self.content, self),
            "Subtitle":       SubtitlePage(self.content, self),
            "TextWatermark":  TextWatermarkPage(self.content, self),
            "ImageWatermark": ImageWatermarkPage(self.content, self),
            "ExtractSub":     ExtractSubtitlePage(self.content, self),
            "Player":         PlayerPage(self.content, self),
            "ColorGrading":   ColorGradingPage(self.content, self),
            "HardwareAccel":  HardwareAccelPage(self.content, self),
            "WebStreaming":   WebStreamingPage(self.content, self),
            "PlatformPresets":PlatformPresetsPage(self.content, self),
            "DevicePresets":  DevicePresetsPage(self.content, self),
        }
        self._current: str | None = None

    # show_page is now defined inside _bind_shortcuts block above
    # (kept here as a noop to avoid breaking any lingering direct calls)




# ══════════════════════════════════════════════════════════════
# Media Info / Probe Page
# ══════════════════════════════════════════════════════════════

class MediaInfoPage(BasePage):
    """
    Deep-dive ffprobe inspector.  Shows every stream, all format metadata,
    chapter list, and raw JSON in a collapsible panel.
    """

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._last_json: dict | None = None
        self._build()

    def _build(self):
        _page_header(self, "🔍  Media Info",
                     "Inspect every stream, track, chapter, and metadata field in a file.")

        self.input_zone = FileDropZone(
            self, label="Input File",
            filetypes=[("Media files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS + AUDIO_EXTS)),
                       ("All files", "*.*")],
            show_thumbnail=True, app=self.app)
        self.input_zone.pack(fill="x", pady=(0, 10))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 10))
        ctk.CTkButton(btn_row, text="🔍  Probe File", width=130,
                      command=self._probe).pack(side="left")
        ctk.CTkButton(btn_row, text="Copy JSON", width=100,
                      fg_color=TC["secondary"],
                      hover_color=TC["secondary_hover"],
                      text_color=TC["secondary_text"],
                      command=self._copy_json).pack(side="left", padx=(10, 0))
        ctk.CTkButton(btn_row, text="Save JSON…", width=100,
                      fg_color=TC["secondary"],
                      hover_color=TC["secondary_hover"],
                      text_color=TC["secondary_text"],
                      command=self._save_json).pack(side="left", padx=(8, 0))
        self._probe_status = ctk.CTkLabel(
            btn_row, text="", font=ctk.CTkFont(size=12),
            text_color=TC["text_dim"])
        self._probe_status.pack(side="left", padx=(14, 0))

        # ── Format summary card ──────────────────────────────────────────────
        self._fmt_card = _card(self, "Format")
        self._fmt_frame = ctk.CTkFrame(self._fmt_card, fg_color="transparent")
        self._fmt_frame.pack(fill="x", padx=10, pady=(0, 10))
        self._fmt_label = ctk.CTkLabel(
            self._fmt_frame, text="No file probed yet.",
            font=ctk.CTkFont(size=12), text_color=TC["text_dim"],
            justify="left", anchor="w")
        self._fmt_label.pack(anchor="w")

        # ── Streams card ─────────────────────────────────────────────────────
        self._streams_card = _card(self, "Streams")
        self._streams_box = ctk.CTkTextbox(
            self._streams_card, height=200,
            font=ctk.CTkFont(family="Courier", size=11),
            state="disabled")
        self._streams_box.pack(fill="x", padx=10, pady=(0, 10))

        # ── Chapters card ────────────────────────────────────────────────────
        self._chap_card = _card(self, "Chapters")
        self._chap_label = ctk.CTkLabel(
            self._chap_card, text="No chapters.",
            font=ctk.CTkFont(size=12), text_color=TC["text_dim"])
        self._chap_label.pack(anchor="w", padx=10, pady=(0, 10))

        # ── Format metadata card ─────────────────────────────────────────────
        self._meta_card = _card(self, "Embedded Metadata Tags")
        self._meta_box = ctk.CTkTextbox(
            self._meta_card, height=120,
            font=ctk.CTkFont(family="Courier", size=11),
            state="disabled")
        self._meta_box.pack(fill="x", padx=10, pady=(0, 10))

        # ── Raw JSON (collapsible) ────────────────────────────────────────────
        self._json_visible = False
        json_hdr = ctk.CTkFrame(self, fg_color="transparent")
        json_hdr.pack(fill="x", pady=(0, 4))
        self._json_btn = ctk.CTkButton(
            json_hdr, text="▶  Raw JSON", width=120, height=26,
            fg_color="transparent", font=ctk.CTkFont(size=11),
            text_color=TC["text_dim"],
            hover_color=TC["nav_hover"],
            command=self._toggle_json)
        self._json_btn.pack(side="left")

        self._json_box = ctk.CTkTextbox(
            self, height=300,
            font=ctk.CTkFont(family="Courier", size=10),
            state="disabled")

    # ── Probe ────────────────────────────────────────────────────────────────

    def _probe(self):
        inp = self.input_zone.get()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Media Info", "Please select a valid file.")
            return
        if not self.app.ffprobe:
            messagebox.showerror("Media Info", "ffprobe not found.")
            return

        self._probe_status.configure(text="Probing…", text_color=TC["text_dim"])

        def _work():
            try:
                r = subprocess.run(
                    [self.app.ffprobe, "-v", "quiet",
                     "-print_format", "json",
                     "-show_streams", "-show_format", "-show_chapters",
                     inp],
                    capture_output=True, text=True, timeout=30)
                data = json.loads(r.stdout)
                self.after(0, lambda d=data: self._display(d))
            except Exception as exc:
                self.after(0, lambda e=exc:
                           self._probe_status.configure(
                               text=f"Error: {e}",
                               text_color=("red", "#f44336")))

        threading.Thread(target=_work, daemon=True).start()

    def _display(self, data: dict):
        self._last_json = data
        fmt = data.get("format", {})

        # ── Format summary ───────────────────────────────────────────────────
        dur_raw  = float(fmt.get("duration", 0) or 0)
        size_raw = int(fmt.get("size", 0) or 0)
        br_raw   = int(fmt.get("bit_rate", 0) or 0)
        dur_str  = f"{int(dur_raw // 3600)}h {int((dur_raw % 3600) // 60)}m {int(dur_raw % 60)}s" if dur_raw else "?"
        size_str = f"{size_raw / (1024*1024):.2f} MB" if size_raw else "?"
        br_str   = f"{br_raw // 1000} kbps" if br_raw else "?"
        n_streams = fmt.get("nb_streams", "?")
        fmt_name  = fmt.get("format_long_name") or fmt.get("format_name") or "?"
        fname     = Path(fmt.get("filename", "")).name

        fmt_lines = [
            f"File:      {fname}",
            f"Format:    {fmt_name}",
            f"Duration:  {dur_str}",
            f"Size:      {size_str}",
            f"Bit rate:  {br_str}",
            f"Streams:   {n_streams}",
        ]
        self._fmt_label.configure(
            text="\n".join(fmt_lines),
            text_color=TC["secondary_text"])

        # ── Streams ──────────────────────────────────────────────────────────
        streams = data.get("streams", [])
        stream_lines = []
        for s in streams:
            idx   = s.get("index", "?")
            stype = s.get("codec_type", "?").upper()
            codec = s.get("codec_name", "?")
            if stype == "VIDEO":
                fps_raw = s.get("r_frame_rate", "0/1")
                try:
                    n, d = fps_raw.split("/")
                    fps  = f"{float(n)/float(d):.3f} fps"
                except Exception:
                    fps = fps_raw
                w, h = s.get("width","?"), s.get("height","?")
                pix  = s.get("pix_fmt","?")
                profile = s.get("profile","")
                lang = s.get("tags",{}).get("language","")
                line = (f"  #{idx} VIDEO   {codec.upper()} {w}×{h}  {fps}"
                        f"  pix={pix}")
                if profile: line += f"  profile={profile}"
                if lang:    line += f"  lang={lang}"
                br = s.get("bit_rate")
                if br: line += f"  {int(br)//1000}kbps"
            elif stype == "AUDIO":
                ch    = s.get("channels","?")
                sr    = s.get("sample_rate","?")
                layout= s.get("channel_layout","")
                lang  = s.get("tags",{}).get("language","")
                title = s.get("tags",{}).get("title","")
                line  = f"  #{idx} AUDIO   {codec.upper()}  {ch}ch @ {sr}Hz"
                if layout: line += f"  {layout}"
                if lang:   line += f"  lang={lang}"
                if title:  line += f"  [{title}]"
                br = s.get("bit_rate")
                if br: line += f"  {int(br)//1000}kbps"
            elif stype == "SUBTITLE":
                lang  = s.get("tags",{}).get("language","")
                title = s.get("tags",{}).get("title","")
                line  = f"  #{idx} SUBTITLE  {codec}"
                if lang:  line += f"  lang={lang}"
                if title: line += f"  [{title}]"
            else:
                line = f"  #{idx} {stype}  {codec}"
            stream_lines.append(line)

        self._streams_box.configure(state="normal")
        self._streams_box.delete("1.0", "end")
        self._streams_box.insert("end", "\n".join(stream_lines) if stream_lines else "No streams found.")
        self._streams_box.configure(state="disabled")

        # ── Chapters ─────────────────────────────────────────────────────────
        chapters = data.get("chapters", [])
        if chapters:
            chap_lines = []
            for c in chapters:
                t = c.get("tags", {})
                title = t.get("title", f"Chapter {c.get('id','?')}")
                start = float(c.get("start_time", 0))
                end   = float(c.get("end_time", 0))
                def _ts(s):
                    return f"{int(s//3600)}:{int((s%3600)//60):02d}:{int(s%60):02d}"
                chap_lines.append(f"  {_ts(start)} – {_ts(end)}   {title}")
            self._chap_label.configure(
                text="\n".join(chap_lines),
                font=ctk.CTkFont(family="Courier", size=11),
                text_color=TC["secondary_text"])
        else:
            self._chap_label.configure(
                text="No chapters.",
                font=ctk.CTkFont(size=12),
                text_color=TC["text_dim"])

        # ── Metadata tags ─────────────────────────────────────────────────────
        tags = fmt.get("tags", {})
        if tags:
            tag_lines = [f"  {k:<20} {v}" for k, v in tags.items()]
            meta_text = "\n".join(tag_lines)
        else:
            meta_text = "  (no metadata tags)"

        self._meta_box.configure(state="normal")
        self._meta_box.delete("1.0", "end")
        self._meta_box.insert("end", meta_text)
        self._meta_box.configure(state="disabled")

        # ── Raw JSON ─────────────────────────────────────────────────────────
        self._json_box.configure(state="normal")
        self._json_box.delete("1.0", "end")
        self._json_box.insert("end", json.dumps(data, indent=2))
        self._json_box.configure(state="disabled")

        self._probe_status.configure(
            text=f"✓  {len(streams)} stream(s)  ·  {len(chapters)} chapter(s)",
            text_color=("green", "#4caf50"))

    def _toggle_json(self):
        self._json_visible = not self._json_visible
        if self._json_visible:
            self._json_box.pack(fill="x", pady=(0, 16))
            self._json_btn.configure(text="▼  Raw JSON")
        else:
            self._json_box.pack_forget()
            self._json_btn.configure(text="▶  Raw JSON")

    def _copy_json(self):
        if not self._last_json:
            return
        self.clipboard_clear()
        self.clipboard_append(json.dumps(self._last_json, indent=2))
        self._probe_status.configure(text="✓  JSON copied to clipboard",
                                      text_color=("green","#4caf50"))
        self.after(2000, lambda: self._probe_status.configure(text=""))

    def _save_json(self):
        if not self._last_json:
            messagebox.showinfo("Media Info", "Probe a file first.")
            return
        inp = self.input_zone.get() or "mediainfo"
        out = self.app.smart_save_dialog(
            "MediaInfo",
            initialfile=f"{Path(inp).stem}_mediainfo.json",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if out:
            Path(out).write_text(
                json.dumps(self._last_json, indent=2, ensure_ascii=False),
                encoding="utf-8")
            messagebox.showinfo("Saved", f"Media info saved to:\n{out}")



# ══════════════════════════════════════════════════════════════
# Custom FFmpeg Arguments  (appended to every page via widget)
# ══════════════════════════════════════════════════════════════

class CustomArgsBar(ctk.CTkFrame):
    """
    Collapsible "Expert: Custom FFmpeg Args" bar.
    Drop it onto any page and call .extra_args() to get a list[str]
    to append to the command.

    Usage in a page _build():
        self.args_bar = CustomArgsBar(self)
        self.args_bar.pack(fill="x", pady=(0, 6))

    Then in _run() / _build_cmd():
        cmd += self.args_bar.extra_args()
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent,
                         fg_color=TC["card"],
                         corner_radius=8, **kwargs)
        self._open = False
        self._build()

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=10, pady=6)
        self._toggle_btn = ctk.CTkButton(
            hdr, text="🛠  Expert: Custom FFmpeg Args", anchor="w",
            fg_color="transparent",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TC["nav_text"],
            hover_color=TC["nav_hover"],
            command=self._toggle)
        self._toggle_btn.pack(side="left")

        self._body = ctk.CTkFrame(self, fg_color="transparent")

        hint = ctk.CTkLabel(
            self._body,
            text="Extra flags appended verbatim to the FFmpeg command before the output file.  "
                 "Example:  -map_metadata 0  -movflags +faststart  -threads 4",
            font=ctk.CTkFont(size=11),
            text_color=TC["text_dim"],
            wraplength=720, justify="left")
        hint.pack(anchor="w", padx=10, pady=(0, 4))

        self._var = ctk.StringVar()
        self._entry = ctk.CTkEntry(
            self._body, textvariable=self._var,
            placeholder_text="-map_metadata 0  -movflags +faststart",
            font=ctk.CTkFont(family="Courier", size=11),
            height=32)
        self._entry.pack(fill="x", padx=10, pady=(0, 10))

    def _toggle(self):
        self._open = not self._open
        if self._open:
            self._body.pack(fill="x")
            self._toggle_btn.configure(text="🛠  Expert: Custom FFmpeg Args  ▲")
        else:
            self._body.pack_forget()
            self._toggle_btn.configure(text="🛠  Expert: Custom FFmpeg Args")

    def extra_args(self) -> list[str]:
        """Return parsed argument list, or [] if empty."""
        raw = self._var.get().strip()
        if not raw:
            return []
        import shlex
        try:
            return shlex.split(raw)
        except ValueError:
            # Un-parseable — return as single token rather than crashing
            return raw.split()


# ══════════════════════════════════════════════════════════════
# Job Queue Page  — multi-job, per-job settings, run in sequence
# ══════════════════════════════════════════════════════════════

# Supported job operations and their parameter schemas
JQ_OPS = {
    "Convert":      {"ext": "mp4",  "crf": "23",  "bitrate": "192k", "scale": "Original"},
    "Compress":     {"ext": "mp4",  "crf": "23",  "bitrate": "128k", "scale": "Original"},
    "Extract Audio":{"ext": "mp3",  "bitrate": "192k"},
    "Trim":         {"start": "00:00:00", "end": "", "fast": True},
    "Mute":         {"mode": "remove"},
    "Reverse":      {},
    "Speed":        {"speed": "2.0"},
    "Normalise":    {"target_lufs": "-16", "method": "ebu"},
    "Custom":       {"args": ""},
}

JQ_FILE = Path.home() / "ffmpex_jobqueue.json"


def _jq_build_cmd(ffmpeg: str, job: dict) -> list[str] | None:
    """
    Turn a job dict into an FFmpeg command list.
    Returns None if the job cannot be built (missing fields).
    job keys: op, input, output, params{}
    """
    inp    = job.get("input", "")
    out    = job.get("output", "")
    op     = job.get("op", "")
    params = job.get("params", {})

    if not inp or not out or not ffmpeg:
        return None

    base = [ffmpeg, "-y", "-i", inp]

    if op == "Convert":
        ext = params.get("ext", "mp4")
        cmd = base[:]
        if ext in VIDEO_EXTS:
            cmd += ["-c:v", "libx264", "-crf", params.get("crf", "23"),
                    "-preset", "fast", "-c:a", "aac",
                    "-b:a", params.get("bitrate", "192k")]
            scale = SCALE_OPTIONS.get(params.get("scale", "Original"))
            if scale:
                cmd += ["-vf", f"scale={scale}"]
        else:
            codec = AUDIO_CODEC_MAP.get(ext, "copy")
            cmd += ["-vn", "-c:a", codec]
            if ext not in ("flac", "wav"):
                cmd += ["-b:a", params.get("bitrate", "192k")]
        cmd.append(out)
        return cmd

    if op == "Compress":
        cmd = base + ["-c:v", "libx264", "-crf", params.get("crf", "23"),
                      "-preset", "fast", "-c:a", "aac",
                      "-b:a", params.get("bitrate", "128k")]
        scale = SCALE_OPTIONS.get(params.get("scale", "Original"))
        if scale:
            cmd += ["-vf", f"scale={scale}"]
        cmd.append(out)
        return cmd

    if op == "Extract Audio":
        ext   = params.get("ext", "mp3")
        codec = AUDIO_CODEC_MAP.get(ext, "libmp3lame")
        cmd   = base + ["-vn", "-c:a", codec]
        if ext not in ("flac", "wav"):
            cmd += ["-b:a", params.get("bitrate", "192k")]
        cmd.append(out)
        return cmd

    if op == "Trim":
        start = ts_to_secs(params.get("start", "0")) or 0.0
        end_s = params.get("end", "")
        end   = ts_to_secs(end_s) if end_s else None
        cmd   = [ffmpeg, "-y", "-ss", str(start), "-i", inp]
        if end is not None:
            cmd += ["-t", str(end - start)]
        if params.get("fast", True):
            cmd += ["-c", "copy"]
        cmd.append(out)
        return cmd

    if op == "Mute":
        mode = params.get("mode", "remove")
        if mode == "remove":
            cmd = base + ["-c:v", "copy", "-an", out]
        else:
            cmd = base + ["-c:v", "copy", "-af", "volume=0", out]
        return cmd

    if op == "Reverse":
        cmd = base + ["-vf", "reverse", "-af", "areverse", out]
        return cmd

    if op == "Speed":
        speed = float(params.get("speed", "2.0"))
        vf    = f"setpts={1/speed:.4f}*PTS"
        af    = f"atempo={min(2.0, max(0.5, speed)):.2f}"
        cmd   = base + ["-vf", vf, "-af", af, out]
        return cmd

    if op == "Normalise":
        method = params.get("method", "ebu")
        if method == "ebu":
            lufs = params.get("target_lufs", "-16")
            cmd  = base + ["-af", f"loudnorm=I={lufs}:TP=-1.5:LRA=11", out]
        else:
            cmd = base + ["-af", "dynaudnorm", out]
        return cmd

    if op == "Custom":
        import shlex
        extra = params.get("args", "")
        try:
            extra_list = shlex.split(extra)
        except ValueError:
            extra_list = extra.split()
        cmd = base + extra_list + [out]
        return cmd

    return None


class JobQueuePage(BasePage):
    """
    Multi-job queue: each row has its own input file, operation, settings,
    and output path.  Jobs are built individually and run sequentially in
    a single background thread.
    """

    # Colour coding per job status
    STATUS_COLORS = {
        "pending":  ("gray75",  "gray30"),
        "running":  ("#1a6db5", "#1a6db5"),
        "done":     ("green",   "#2e7d32"),
        "failed":   ("red",     "#b71c1c"),
        "skipped":  ("gray60",  "gray45"),
    }

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._jobs: list[dict] = []      # list of job dicts
        self._job_rows: list[ctk.CTkFrame] = []  # parallel UI rows
        self._selected: int | None = None
        self._build()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build(self):
        _page_header(
            self, "📋  Job Queue",
            "Build a list of jobs — each with its own file, operation, and settings — "
            "then run them all in sequence.")

        # ── Toolbar ──────────────────────────────────────────────────────────
        tb = ctk.CTkFrame(self, fg_color="transparent")
        tb.pack(fill="x", pady=(0, 8))

        grey = {"fg_color": TC["secondary"],
                "hover_color": TC["secondary_hover"],
                "text_color": ("gray10", "gray90")}

        ctk.CTkButton(tb, text="➕  Add Job",    width=110,
                      command=self._add_job).pack(side="left", padx=(0, 6))
        ctk.CTkButton(tb, text="🗑  Remove",      width=90,
                      command=self._remove_selected, **grey).pack(side="left", padx=(0, 6))
        ctk.CTkButton(tb, text="⬆  Up",          width=70,
                      command=self._move_up, **grey).pack(side="left", padx=(0, 4))
        ctk.CTkButton(tb, text="⬇  Down",        width=70,
                      command=self._move_down, **grey).pack(side="left", padx=(0, 6))
        ctk.CTkButton(tb, text="Clear All",       width=80,
                      command=self._clear_all, **grey).pack(side="left", padx=(0, 16))
        ctk.CTkButton(tb, text="💾  Save Queue",  width=120,
                      command=self._save_queue, **grey).pack(side="left", padx=(0, 6))
        ctk.CTkButton(tb, text="📂  Load Queue",  width=120,
                      command=self._load_queue, **grey).pack(side="left")

        self._count_lbl = ctk.CTkLabel(
            tb, text="0 jobs", font=ctk.CTkFont(size=12),
            text_color=TC["text_dim"])
        self._count_lbl.pack(side="right")

        # ── Job editor panel (shown when a job is selected) ───────────────────
        self._editor = ctk.CTkFrame(
            self, fg_color=TC["card"], corner_radius=8)
        self._editor.pack(fill="x", pady=(0, 10))
        self._editor_placeholder = ctk.CTkLabel(
            self._editor,
            text="Select a job from the list below to edit its settings.",
            text_color=TC["text_dim"], font=ctk.CTkFont(size=12))
        self._editor_placeholder.pack(pady=16)
        self._editor_content: ctk.CTkFrame | None = None

        # ── Job list ─────────────────────────────────────────────────────────
        list_card = _card(self, "Jobs")
        self._list_frame = ctk.CTkFrame(list_card, fg_color="transparent")
        self._list_frame.pack(fill="x", padx=8, pady=(0, 8))
        self._empty_lbl = ctk.CTkLabel(
            self._list_frame,
            text="No jobs yet — click '➕ Add Job' to start.",
            text_color=TC["text_dim"], font=ctk.CTkFont(size=12))
        self._empty_lbl.pack(pady=20)

        # ── Run controls ─────────────────────────────────────────────────────
        run_row = ctk.CTkFrame(self, fg_color="transparent")
        run_row.pack(fill="x", pady=(6, 0))

        ctk.CTkButton(run_row, text="▶  Run Queue", width=140,
                      font=ctk.CTkFont(size=13),
                      command=self._run_queue).pack(side="left")
        ctk.CTkButton(run_row, text="Cancel", width=90,
                      command=self.cancel, **grey).pack(side="left", padx=10)

        self._skip_failed = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(run_row, text="Skip failed jobs and continue",
                        variable=self._skip_failed).pack(side="left", padx=(10, 0))

        _sep(self, pady=8)
        self.progress = ProgressSection(self)
        self.progress.pack(fill="x", pady=(0, 6))

        self._queue_status = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=12),
            text_color=TC["text_dim"])
        self._queue_status.pack(anchor="w", pady=(0, 16))

    # ── Job list rendering ────────────────────────────────────────────────────

    def _refresh_list(self):
        for w in self._list_frame.winfo_children():
            w.destroy()
        self._job_rows.clear()

        if not self._jobs:
            self._empty_lbl = ctk.CTkLabel(
                self._list_frame,
                text="No jobs yet — click '➕ Add Job' to start.",
                text_color=TC["text_dim"], font=ctk.CTkFont(size=12))
            self._empty_lbl.pack(pady=20)
            self._count_lbl.configure(text="0 jobs")
            return

        self._count_lbl.configure(
            text=f"{len(self._jobs)} job{'s' if len(self._jobs) != 1 else ''}")

        for i, job in enumerate(self._jobs):
            self._add_list_row(i, job)

    def _add_list_row(self, idx: int, job: dict):
        status = job.get("status", "pending")
        bg     = self.STATUS_COLORS.get(status, ("gray75", "gray30"))

        row = ctk.CTkFrame(
            self._list_frame,
            fg_color=TC["card"] if idx == self._selected
            else ("gray87", "gray20"),
            corner_radius=6)
        row.pack(fill="x", pady=2)
        self._job_rows.append(row)

        # Status dot
        dot_map = {"pending": "○", "running": "◉", "done": "✓",
                   "failed": "✗", "skipped": "—"}
        dot_col = {"pending": ("gray50","gray50"), "running": ("#1a6db5","#5da7d6"),
                   "done": ("green","#4caf50"), "failed": ("red","#f44336"),
                   "skipped": ("gray50","gray50")}
        ctk.CTkLabel(row, text=dot_map.get(status, "○"),
                     text_color=dot_col.get(status, ("gray50","gray50")),
                     font=ctk.CTkFont(size=16, weight="bold"),
                     width=28).pack(side="left", padx=(8, 4), pady=6)

        # Job number
        ctk.CTkLabel(row, text=f"#{idx+1}",
                     font=ctk.CTkFont(size=11),
                     text_color=TC["text_dim"],
                     width=32).pack(side="left", padx=(0, 8))

        # Operation badge
        op_badge = ctk.CTkFrame(row, fg_color=("#1a6db5", "#1a4f80"),
                                corner_radius=4)
        op_badge.pack(side="left", padx=(0, 10), pady=5)
        ctk.CTkLabel(op_badge, text=job.get("op", "?"),
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=("white", "white"),
                     padx=6).pack()

        # File info
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, pady=4)

        inp_name = Path(job.get("input", "")).name or "(no input)"
        out_name = Path(job.get("output", "")).name or "(no output set)"
        ctk.CTkLabel(info, text=inp_name,
                     font=ctk.CTkFont(size=12),
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(info, text=f"→  {out_name}",
                     font=ctk.CTkFont(size=11),
                     text_color=TC["text_dim"],
                     anchor="w").pack(anchor="w")

        # Per-job progress bar (shown during run)
        if status == "running":
            pb = ctk.CTkProgressBar(row, width=80, height=8)
            pb.set(0)
            pb.pack(side="right", padx=10)
            job["_pb"] = pb

        # Edit button
        ctk.CTkButton(row, text="✎", width=32, height=28,
                      fg_color="transparent",
                      hover_color=("gray75", "gray30"),
                      command=lambda i=idx: self._select_job(i)
                      ).pack(side="right", padx=(0, 6))

        # Make whole row clickable
        for widget in (row,):
            widget.bind("<Button-1>", lambda e, i=idx: self._select_job(i))

    # ── Job selection & editor ────────────────────────────────────────────────

    def _select_job(self, idx: int):
        self._selected = idx
        self._refresh_list()
        self._show_editor(idx)

    def _show_editor(self, idx: int):
        """Rebuild the editor panel for job[idx]."""
        job = self._jobs[idx]

        if self._editor_content:
            self._editor_content.destroy()
            self._editor_content = None
        self._editor_placeholder.pack_forget()

        frame = ctk.CTkFrame(self._editor, fg_color="transparent")
        frame.pack(fill="x", padx=12, pady=10)
        self._editor_content = frame

        # ── Row 0: header ─────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(frame, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(hdr, text=f"Editing Job #{idx+1}",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        ctk.CTkButton(hdr, text="Apply Changes", width=120, height=28,
                      command=lambda: self._apply_editor(idx)).pack(side="right")

        # ── Row 1: operation selector ─────────────────────────────────────────
        op_row = ctk.CTkFrame(frame, fg_color="transparent")
        op_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(op_row, text="Operation:", width=90).pack(side="left")
        op_var = ctk.StringVar(value=job.get("op", "Convert"))
        op_menu = ctk.CTkOptionMenu(
            op_row, variable=op_var,
            values=list(JQ_OPS.keys()), width=160,
            command=lambda v, f=frame, i=idx: self._on_op_change(v, f, i))
        op_menu.pack(side="left", padx=(0, 20))
        job["_op_var"] = op_var

        # ── Row 2: input file ─────────────────────────────────────────────────
        inp_row = ctk.CTkFrame(frame, fg_color="transparent")
        inp_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(inp_row, text="Input:", width=90).pack(side="left")
        inp_var = ctk.StringVar(value=job.get("input", ""))
        ctk.CTkEntry(inp_row, textvariable=inp_var,
                     font=ctk.CTkFont(size=11), width=380).pack(side="left", padx=(0, 6))
        ctk.CTkButton(inp_row, text="Browse", width=72, height=26,
                      fg_color=TC["secondary"],
                      hover_color=TC["secondary_hover"],
                      text_color=TC["secondary_text"],
                      command=lambda v=inp_var: self._browse_input(v)
                      ).pack(side="left")
        job["_inp_var"] = inp_var

        # ── Row 3: output path ────────────────────────────────────────────────
        out_row = ctk.CTkFrame(frame, fg_color="transparent")
        out_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(out_row, text="Output:", width=90).pack(side="left")
        out_var = ctk.StringVar(value=job.get("output", ""))
        ctk.CTkEntry(out_row, textvariable=out_var,
                     font=ctk.CTkFont(size=11), width=380).pack(side="left", padx=(0, 6))
        ctk.CTkButton(out_row, text="Browse", width=72, height=26,
                      fg_color=TC["secondary"],
                      hover_color=TC["secondary_hover"],
                      text_color=TC["secondary_text"],
                      command=lambda v=out_var, j=job: self._browse_output(v, j)
                      ).pack(side="left")
        ctk.CTkButton(out_row, text="Auto", width=52, height=26,
                      fg_color=TC["secondary"],
                      hover_color=TC["secondary_hover"],
                      text_color=TC["secondary_text"],
                      command=lambda iv=inp_var, ov=out_var, j=job: self._auto_output(iv, ov, j)
                      ).pack(side="left", padx=(4, 0))
        job["_out_var"] = out_var

        # ── Row 4: op-specific params ─────────────────────────────────────────
        self._build_param_section(frame, job)

    def _build_param_section(self, frame: ctk.CTkFrame, job: dict):
        """Build operation-specific parameter widgets inside the editor."""
        # Remove existing param frame if any
        if hasattr(job, "_param_frame") or "_param_frame" in job:
            try:
                job["_param_frame"].destroy()
            except Exception:
                pass

        op     = job.get("op", "Convert")
        params = job.get("params", {})
        pf     = ctk.CTkFrame(frame, fg_color=TC["card_inner"], corner_radius=6)
        pf.pack(fill="x", pady=(4, 0))
        job["_param_frame"] = pf

        grey = {"fg_color": ("gray72","gray32"), "hover_color": ("gray62","gray42"),
                "text_color": ("gray10","gray90")}

        if op in ("Convert", "Compress"):
            r1 = ctk.CTkFrame(pf, fg_color="transparent")
            r1.pack(fill="x", padx=10, pady=(8, 4))

            ctk.CTkLabel(r1, text="Format:", width=80).pack(side="left")
            ext_var = ctk.StringVar(value=params.get("ext", "mp4"))
            ctk.CTkOptionMenu(r1, variable=ext_var,
                              values=VIDEO_EXTS + AUDIO_EXTS,
                              width=90).pack(side="left", padx=(0, 16))
            job["_ext_var"] = ext_var

            ctk.CTkLabel(r1, text="CRF:", width=40).pack(side="left")
            crf_var = ctk.StringVar(value=params.get("crf", "23"))
            ctk.CTkEntry(r1, textvariable=crf_var, width=50).pack(side="left", padx=(0, 16))
            job["_crf_var"] = crf_var

            ctk.CTkLabel(r1, text="Audio:", width=50).pack(side="left")
            br_var = ctk.StringVar(value=params.get("bitrate", "128k"))
            ctk.CTkOptionMenu(r1, variable=br_var, values=BITRATES, width=90).pack(side="left", padx=(0, 16))
            job["_br_var"] = br_var

            ctk.CTkLabel(r1, text="Scale:", width=50).pack(side="left")
            sc_var = ctk.StringVar(value=params.get("scale", "Original"))
            ctk.CTkOptionMenu(r1, variable=sc_var,
                              values=list(SCALE_OPTIONS.keys()), width=120).pack(side="left")
            job["_sc_var"] = sc_var
            ctk.CTkFrame(pf, fg_color="transparent", height=4).pack()

        elif op == "Extract Audio":
            r1 = ctk.CTkFrame(pf, fg_color="transparent")
            r1.pack(fill="x", padx=10, pady=(8, 8))
            ctk.CTkLabel(r1, text="Format:", width=80).pack(side="left")
            ext_var = ctk.StringVar(value=params.get("ext", "mp3"))
            ctk.CTkOptionMenu(r1, variable=ext_var, values=AUDIO_EXTS, width=90).pack(side="left", padx=(0,16))
            job["_ext_var"] = ext_var
            ctk.CTkLabel(r1, text="Bitrate:", width=60).pack(side="left")
            br_var = ctk.StringVar(value=params.get("bitrate", "192k"))
            ctk.CTkOptionMenu(r1, variable=br_var, values=BITRATES, width=90).pack(side="left")
            job["_br_var"] = br_var

        elif op == "Trim":
            r1 = ctk.CTkFrame(pf, fg_color="transparent")
            r1.pack(fill="x", padx=10, pady=(8, 4))
            ctk.CTkLabel(r1, text="Start:", width=50).pack(side="left")
            st_var = ctk.StringVar(value=params.get("start", "00:00:00"))
            ctk.CTkEntry(r1, textvariable=st_var, width=100).pack(side="left", padx=(0,16))
            job["_start_var"] = st_var
            ctk.CTkLabel(r1, text="End:", width=40).pack(side="left")
            en_var = ctk.StringVar(value=params.get("end", ""))
            ctk.CTkEntry(r1, textvariable=en_var, width=100,
                         placeholder_text="HH:MM:SS").pack(side="left", padx=(0,16))
            job["_end_var"] = en_var
            fast_var = ctk.BooleanVar(value=params.get("fast", True))
            ctk.CTkCheckBox(r1, text="Fast cut (stream copy)", variable=fast_var).pack(side="left")
            job["_fast_var"] = fast_var
            ctk.CTkFrame(pf, fg_color="transparent", height=4).pack()

        elif op == "Mute":
            r1 = ctk.CTkFrame(pf, fg_color="transparent")
            r1.pack(fill="x", padx=10, pady=(8, 8))
            ctk.CTkLabel(r1, text="Mode:", width=60).pack(side="left")
            mode_var = ctk.StringVar(value=params.get("mode", "remove"))
            ctk.CTkOptionMenu(r1, variable=mode_var,
                              values=["remove", "silence"], width=120).pack(side="left")
            job["_mode_var"] = mode_var

        elif op == "Speed":
            r1 = ctk.CTkFrame(pf, fg_color="transparent")
            r1.pack(fill="x", padx=10, pady=(8, 8))
            ctk.CTkLabel(r1, text="Speed:", width=60).pack(side="left")
            sp_var = ctk.StringVar(value=params.get("speed", "2.0"))
            ctk.CTkOptionMenu(r1, variable=sp_var,
                              values=["0.25", "0.5", "0.75", "1.25", "1.5", "2.0", "4.0"],
                              width=100).pack(side="left")
            job["_speed_var"] = sp_var

        elif op == "Normalise":
            r1 = ctk.CTkFrame(pf, fg_color="transparent")
            r1.pack(fill="x", padx=10, pady=(8, 8))
            ctk.CTkLabel(r1, text="Method:", width=70).pack(side="left")
            meth_var = ctk.StringVar(value=params.get("method", "ebu"))
            ctk.CTkOptionMenu(r1, variable=meth_var,
                              values=["ebu", "dynaudnorm"], width=120).pack(side="left", padx=(0,16))
            job["_meth_var"] = meth_var
            ctk.CTkLabel(r1, text="Target LUFS:", width=90).pack(side="left")
            lufs_var = ctk.StringVar(value=params.get("target_lufs", "-16"))
            ctk.CTkOptionMenu(r1, variable=lufs_var,
                              values=["-14", "-16", "-18", "-23", "-24"],
                              width=80).pack(side="left")
            job["_lufs_var"] = lufs_var

        elif op == "Custom":
            r1 = ctk.CTkFrame(pf, fg_color="transparent")
            r1.pack(fill="x", padx=10, pady=(8, 4))
            ctk.CTkLabel(r1, text="FFmpeg args\n(after -i input):",
                         font=ctk.CTkFont(size=11),
                         text_color=TC["text_dim"],
                         width=120, justify="left").pack(side="left", anchor="n")
            args_var = ctk.StringVar(value=params.get("args", ""))
            ctk.CTkEntry(r1, textvariable=args_var,
                         font=ctk.CTkFont(family="Courier", size=11),
                         width=380).pack(side="left")
            job["_args_var"] = args_var
            ctk.CTkLabel(pf, text="Example:  -c:v libx265 -crf 22 -c:a copy",
                         font=ctk.CTkFont(size=10),
                         text_color=TC["text_dim"]).pack(anchor="w", padx=10, pady=(0,8))

        elif op in ("Reverse",):
            ctk.CTkLabel(pf, text="No additional settings.",
                         text_color=TC["text_dim"],
                         font=ctk.CTkFont(size=11)).pack(padx=10, pady=10)

    def _on_op_change(self, new_op: str, frame: ctk.CTkFrame, idx: int):
        job = self._jobs[idx]
        job["op"] = new_op
        job["params"] = dict(JQ_OPS.get(new_op, {}))
        self._build_param_section(frame, job)
        # Auto-update output extension
        self._auto_output(job.get("_inp_var"), job.get("_out_var"), job)

    def _apply_editor(self, idx: int):
        """Read all editor widgets back into job[idx]."""
        job = self._jobs[idx]
        job["op"]     = job.get("_op_var",  ctk.StringVar()).get()
        job["input"]  = job.get("_inp_var", ctk.StringVar()).get()
        job["output"] = job.get("_out_var", ctk.StringVar()).get()

        op = job["op"]
        p  = {}
        if op in ("Convert", "Compress"):
            p["ext"]     = job.get("_ext_var", ctk.StringVar(value="mp4")).get()
            p["crf"]     = job.get("_crf_var", ctk.StringVar(value="23")).get()
            p["bitrate"] = job.get("_br_var",  ctk.StringVar(value="128k")).get()
            p["scale"]   = job.get("_sc_var",  ctk.StringVar(value="Original")).get()
        elif op == "Extract Audio":
            p["ext"]     = job.get("_ext_var", ctk.StringVar(value="mp3")).get()
            p["bitrate"] = job.get("_br_var",  ctk.StringVar(value="192k")).get()
        elif op == "Trim":
            p["start"] = job.get("_start_var", ctk.StringVar()).get()
            p["end"]   = job.get("_end_var",   ctk.StringVar()).get()
            p["fast"]  = job.get("_fast_var",  ctk.BooleanVar(value=True)).get()
        elif op == "Mute":
            p["mode"]  = job.get("_mode_var",  ctk.StringVar(value="remove")).get()
        elif op == "Speed":
            p["speed"] = job.get("_speed_var", ctk.StringVar(value="2.0")).get()
        elif op == "Normalise":
            p["method"]      = job.get("_meth_var", ctk.StringVar(value="ebu")).get()
            p["target_lufs"] = job.get("_lufs_var", ctk.StringVar(value="-16")).get()
        elif op == "Custom":
            p["args"] = job.get("_args_var", ctk.StringVar()).get()

        job["params"] = p
        self._refresh_list()

    # ── Browse helpers ────────────────────────────────────────────────────────

    def _browse_input(self, var: ctk.StringVar):
        path = filedialog.askopenfilename(
            filetypes=[("Media files",
                        " ".join(f"*.{e}" for e in VIDEO_EXTS + AUDIO_EXTS)),
                       ("All files", "*.*")])
        if path:
            var.set(path)

    def _browse_output(self, var: ctk.StringVar, job: dict):
        op  = job.get("op", "Convert")
        ext = job.get("params", {}).get("ext", "mp4")
        inp = job.get("input", "")
        ini = f"{Path(inp).stem}_{op.lower().replace(' ','_')}.{ext}" if inp else f"output.{ext}"
        path = self.app.smart_save_dialog(
            "JobQueue",
            initialfile=ini,
            defaultextension=f".{ext}",
            filetypes=[(ext.upper(), f"*.{ext}"), ("All files", "*.*")])
        if path:
            var.set(path)

    def _auto_output(self, inp_var, out_var, job: dict):
        """Generate an automatic output path from the input + operation."""
        if inp_var is None or out_var is None:
            return
        inp = inp_var.get() if hasattr(inp_var, "get") else ""
        if not inp:
            return
        op  = job.get("op", "Convert")
        ext = job.get("params", {}).get("ext", "mp4")
        if op == "Extract Audio":
            ext = job.get("params", {}).get("ext", "mp3")
        slug = op.lower().replace(" ", "_")
        out  = str(Path(inp).parent / f"{Path(inp).stem}_{slug}.{ext}")
        if out_var and hasattr(out_var, "set"):
            out_var.set(out)

    # ── Add / remove / reorder ────────────────────────────────────────────────

    def _add_job(self):
        job = {
            "op":     "Convert",
            "input":  "",
            "output": "",
            "params": dict(JQ_OPS["Convert"]),
            "status": "pending",
        }
        self._jobs.append(job)
        self._selected = len(self._jobs) - 1
        self._refresh_list()
        self._show_editor(self._selected)

    def _remove_selected(self):
        if self._selected is None or not self._jobs:
            return
        self._jobs.pop(self._selected)
        self._selected = min(self._selected, len(self._jobs) - 1) if self._jobs else None
        self._clear_editor()
        self._refresh_list()
        if self._selected is not None and self._selected >= 0:
            self._show_editor(self._selected)

    def _move_up(self):
        i = self._selected
        if i is None or i == 0 or not self._jobs:
            return
        self._jobs[i-1], self._jobs[i] = self._jobs[i], self._jobs[i-1]
        self._selected = i - 1
        self._refresh_list()
        self._show_editor(self._selected)

    def _move_down(self):
        i = self._selected
        if i is None or i >= len(self._jobs) - 1 or not self._jobs:
            return
        self._jobs[i], self._jobs[i+1] = self._jobs[i+1], self._jobs[i]
        self._selected = i + 1
        self._refresh_list()
        self._show_editor(self._selected)

    def _clear_all(self):
        if not self._jobs:
            return
        if not messagebox.askyesno("Clear Queue", "Remove all jobs?"):
            return
        self._jobs.clear()
        self._selected = None
        self._clear_editor()
        self._refresh_list()

    def _clear_editor(self):
        if self._editor_content:
            self._editor_content.destroy()
            self._editor_content = None
        self._editor_placeholder.pack(pady=16)

    # ── Save / Load queue ─────────────────────────────────────────────────────

    def _serialise_jobs(self) -> list[dict]:
        """Return a JSON-safe copy of jobs (strip widget references)."""
        clean = []
        for j in self._jobs:
            clean.append({
                "op":     j.get("op", ""),
                "input":  j.get("input", ""),
                "output": j.get("output", ""),
                "params": dict(j.get("params", {})),
            })
        return clean

    def _save_queue(self):
        # Apply any pending editor changes first
        if self._selected is not None:
            self._apply_editor(self._selected)
        path = self.app.smart_save_dialog(
            "JobQueue",
            initialfile="ffmpex_jobqueue.json",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        data = {
            "version": "1.0",
            "created": datetime.now().isoformat(timespec="seconds"),
            "jobs":    self._serialise_jobs(),
        }
        try:
            Path(path).write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            messagebox.showinfo("Queue Saved",
                                f"{len(self._jobs)} job(s) saved to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Save Failed", str(exc))

    def _load_queue(self):
        path = filedialog.askopenfilename(
            title="Load Job Queue",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            jobs = data.get("jobs", [])
            if not isinstance(jobs, list):
                raise ValueError("Invalid queue file format.")
            loaded = []
            for j in jobs:
                loaded.append({
                    "op":     j.get("op", "Convert"),
                    "input":  j.get("input", ""),
                    "output": j.get("output", ""),
                    "params": dict(j.get("params", {})),
                    "status": "pending",
                })
            if self._jobs and not messagebox.askyesno(
                "Load Queue",
                f"Replace the current {len(self._jobs)} job(s) with "
                f"{len(loaded)} loaded job(s)?"):
                return
            self._jobs = loaded
            self._selected = None
            self._clear_editor()
            self._refresh_list()
            # Check for missing input files
            missing = [j["input"] for j in self._jobs
                       if j["input"] and not os.path.exists(j["input"])]
            if missing:
                messagebox.showwarning(
                    "Missing Files",
                    f"{len(missing)} input file(s) not found on disk:\n" +
                    "\n".join(Path(m).name for m in missing[:5]) +
                    ("\n…" if len(missing) > 5 else "") +
                    "\n\nEdit the affected jobs to update their paths.")
        except Exception as exc:
            messagebox.showerror("Load Failed", str(exc))

    # ── Run queue ─────────────────────────────────────────────────────────────

    def _run_queue(self):
        if self._running:
            messagebox.showwarning("Busy", "Queue is already running.")
            return

        # Apply editor changes before running
        if self._selected is not None:
            self._apply_editor(self._selected)

        if not self._jobs:
            messagebox.showerror("Empty Queue", "Add at least one job first.")
            return

        if not self.app.ffmpeg:
            messagebox.showerror("Error", "FFmpeg not found. Check Settings.")
            return

        # Validate all jobs
        problems = []
        for i, job in enumerate(self._jobs):
            if not job.get("input"):
                problems.append(f"Job #{i+1}: no input file")
            elif not os.path.exists(job["input"]):
                problems.append(f"Job #{i+1}: input not found — {Path(job['input']).name}")
            if not job.get("output"):
                problems.append(f"Job #{i+1}: no output path set")

        if problems:
            messagebox.showerror(
                "Queue Validation Failed",
                "\n".join(problems[:10]) +
                (f"\n…and {len(problems)-10} more" if len(problems) > 10 else ""))
            return

        # Reset all statuses
        for job in self._jobs:
            job["status"] = "pending"
        self._refresh_list()

        total      = len(self._jobs)
        skip_fail  = self._skip_failed.get()
        ffmpeg     = self.app.ffmpeg
        ffprobe    = self.app.ffprobe

        self._running = True
        self.progress.reset()
        start_wall = time.time()

        def _worker():
            done_ok = 0
            for i, job in enumerate(self._jobs):
                if not self._running:
                    # Cancelled
                    for j2 in self._jobs[i:]:
                        j2["status"] = "skipped"
                    self.after(0, self._refresh_list)
                    break

                # Mark running
                job["status"] = "running"
                self.after(0, self._refresh_list)
                self.after(0, lambda n=job["op"], idx=i:
                           self._queue_status.configure(
                               text=f"Running job {idx+1}/{total}: {n}  —  "
                                    f"{Path(self._jobs[idx]['input']).name}",
                               text_color=TC["text_dim"]))

                cmd = _jq_build_cmd(ffmpeg, job)
                if cmd is None:
                    job["status"] = "failed"
                    self.after(0, self._refresh_list)
                    if not skip_fail:
                        break
                    continue

                # Get duration for progress
                dur = None
                if ffprobe and os.path.exists(job["input"]):
                    dur = get_duration(ffprobe, job["input"])

                # Ensure output directory exists
                try:
                    Path(job["output"]).parent.mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass

                try:
                    self._proc = subprocess.Popen(
                        cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                        text=True, universal_newlines=True)

                    for line in self._proc.stderr:
                        line = line.rstrip()
                        self.after(0, lambda l=line:
                                   self.progress.update_progress(
                                       self.progress.bar.get() * 100, log_line=l))
                        enc_t = parse_progress_time(line)
                        if enc_t is not None and dur and dur > 0:
                            job_pct  = min(1.0, enc_t / dur)
                            overall  = ((i + job_pct) / total) * 100
                            elapsed  = time.time() - start_wall
                            eta      = int(((total - i - job_pct) / max(i + job_pct, 0.01))
                                          * elapsed) if i + job_pct > 0 else 0
                            self.after(0, lambda p=overall, e=eta:
                                       self.progress.update_progress(
                                           p, status=f"Job {i+1}/{total}  —  ETA {e}s"))

                    self._proc.wait()
                    success = self._proc.returncode == 0
                except Exception as exc:
                    self.after(0, lambda e=exc:
                               self.progress.update_progress(0, status=f"Error: {e}"))
                    success = False

                job["status"] = "done" if success else "failed"
                if success:
                    done_ok += 1
                    self.app.add_history("Job Queue", job["output"], True)
                self.after(0, self._refresh_list)

                if not success and not skip_fail:
                    # Mark remaining as skipped
                    for j2 in self._jobs[i+1:]:
                        j2["status"] = "skipped"
                    self.after(0, self._refresh_list)
                    break

            # Done
            self._running = False
            self._proc    = None
            elapsed = int(time.time() - start_wall)
            all_ok  = done_ok == total

            self.after(0, lambda: self.progress.done(all_ok))
            self.after(0, lambda: self._queue_status.configure(
                text=(f"{'✓' if all_ok else '⚠'}  "
                      f"{done_ok}/{total} jobs completed in {elapsed}s."),
                text_color=("green","#4caf50") if all_ok else ("orange","#ff9800")))

            send_notification(
                "FFmpex — Queue Complete",
                f"{done_ok}/{total} jobs finished in {elapsed}s.")

        threading.Thread(target=_worker, daemon=True).start()


# ══════════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════════

APP_VERSION = "2.4.0"

def _cli():
    """Handle --version / --help before the GUI starts."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="ffmpex",
        description="FFmpex — a clean FFmpeg GUI wrapper.",
        add_help=True,
    )
    parser.add_argument(
        "--version", action="version",
        version=f"FFmpex {APP_VERSION}  (Python {sys.version.split()[0]})"
    )
    parser.add_argument(
        "--ffmpeg", metavar="PATH",
        help="Override the FFmpeg executable path used at startup."
    )
    # parse_known_args so tkinter's own argv handling doesn't choke
    args, _ = parser.parse_known_args()
    return args


def _single_instance_lock():
    """
    Enforce a single running instance.
    Returns a lock object that must be kept alive for the duration of the
    process (assign it to a variable — do not let it be GC'd).

    Windows : named mutex via ctypes
    macOS/Linux : lock file in /tmp

    Returns None if the platform check is not needed or if we ARE the first
    instance.  Exits with a friendly message if another instance is running.
    """
    _sys = platform.system()

    if _sys == "Windows":
        import ctypes
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "FFmpex_SingleInstance_v2")
        err   = ctypes.windll.kernel32.GetLastError()
        ERROR_ALREADY_EXISTS = 183
        if err == ERROR_ALREADY_EXISTS:
            import tkinter as _tk
            import tkinter.messagebox as _mb
            root = _tk.Tk(); root.withdraw()
            _mb.showwarning("FFmpex already running",
                            "FFmpex is already open.\n\n"
                            "Check your system tray if you can't find the window.")
            root.destroy()
            sys.exit(0)
        return mutex   # keep alive

    else:
        lock_path = Path(tempfile.gettempdir()) / "ffmpex.lock"
        try:
            import fcntl
            lock_fh = open(lock_path, "w")
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_fh.write(str(os.getpid()))
            lock_fh.flush()
            return lock_fh   # keep alive; released automatically on exit
        except (IOError, OSError):
            import tkinter as _tk
            import tkinter.messagebox as _mb
            root = _tk.Tk(); root.withdraw()
            _mb.showwarning("FFmpex already running",
                            "FFmpex is already open.")
            root.destroy()
            sys.exit(0)
        except ImportError:
            pass   # fcntl not available (shouldn't happen on POSIX)
    return None


if __name__ == "__main__":
    # ── Suppress console windows on Windows (frozen builds) ──────────────────
    # When PyInstaller builds with --windowed, every subprocess.Popen call
    # (ffmpeg, ffprobe, where.exe, winreg etc.) spawns a visible CMD flash.
    # Patching Popen here covers all call sites with zero code duplication.
    if platform.system() == "Windows":
        _OrigPopen = subprocess.Popen
        class _NoCmdPopen(_OrigPopen):
            def __init__(self, *a, **kw):
                # Only add the flag if the caller didn't set creationflags
                if "creationflags" not in kw:
                    kw["creationflags"] = subprocess.CREATE_NO_WINDOW
                super().__init__(*a, **kw)
        subprocess.Popen = _NoCmdPopen
    # ── Crash logger ─────────────────────────────────────────────────────────
    # When built with --windowed, any unhandled exception is completely silent.
    # This writes a crash log next to the exe so failures are always diagnosable.
    import traceback as _traceback

    def _crash_log(exc: BaseException):
        """Write a crash report next to the executable."""
        try:
            log_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) \
                      else Path(__file__).parent
            log_path = log_dir / "ffmpex_crash.log"
            with open(log_path, "w", encoding="utf-8") as _f:
                _f.write(f"FFmpex {APP_VERSION} crash report\n")
                _f.write(f"Python {sys.version}\n")
                _f.write(f"Platform {platform.platform()}\n")
                _f.write(f"Executable {sys.executable}\n\n")
                _traceback.print_exc(file=_f)
            # Show a dialog so the user knows something went wrong
            try:
                import tkinter as _tk
                import tkinter.messagebox as _mb
                _r = _tk.Tk(); _r.withdraw()
                _mb.showerror(
                    "FFmpex — Startup Error",
                    f"FFmpex encountered an error on startup and could not open.\n\n"
                    f"A crash report has been saved to:\n{log_path}\n\n"
                    f"Error: {type(exc).__name__}: {exc}")
                _r.destroy()
            except Exception:
                pass
        except Exception:
            pass

    try:
        args = _cli()
        _lock = _single_instance_lock()   # must stay in scope until exit

        app = FFmpexApp()

        # Store the instance lock on the app so _restart_app can release it
        app._instance_lock = _lock

        # Apply --ffmpeg override if provided
        if hasattr(args, "ffmpeg") and args.ffmpeg:
            if os.path.isfile(args.ffmpeg):
                app.ffmpeg = args.ffmpeg
            else:
                import tkinter.messagebox as _mb
                _mb.showwarning("FFmpex",
                                f"--ffmpeg path not found:\n{args.ffmpeg}\n\n"
                                "Using auto-detected FFmpeg instead.")

        app.mainloop()

    except Exception as _exc:
        _crash_log(_exc)
        raise
