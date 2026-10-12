"""Video and audio ingestion engine for MARAT.

Extracts speech from lecture videos, symposium talks, and research podcasts.
Supports fast caption extraction for YouTube and local Whisper ASR for
offline video/audio recordings.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def _ensure_ffmpeg() -> bool:
    """Make sure ffmpeg is discoverable in PATH, pulling bundled binary if needed."""
    if shutil.which("ffmpeg"):
        return True
    try:
        import imageio_ffmpeg

        exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
        bin_dir = exe.parent
        target = bin_dir / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if not target.exists():
            shutil.copyfile(exe, target)
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
        return bool(shutil.which("ffmpeg"))
    except Exception:
        return False


def _format_timestamp(seconds: float) -> str:
    """Convert float seconds to MM:SS or HH:MM:SS string."""
    s = int(seconds)
    hours = s // 3600
    minutes = (s % 3600) // 60
    secs = s % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def extract_youtube_id(url: str) -> str | None:
    """Extract 11-char YouTube ID from typical URL formats."""
    patterns = [
        r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url.strip())
        if match:
            return match.group(1)
    return None


class TranscriptSegment(BaseModel):
    start: float
    end: float
    timestamp: str
    text: str


class VideoLecture(BaseModel):
    title: str
    url: str
    duration_seconds: float = 0.0
    segments: list[TranscriptSegment] = Field(default_factory=list)
    full_text: str = ""
    source_type: str = "youtube"


def fetch_youtube_captions(video_id: str) -> list[TranscriptSegment] | None:
    """Attempt fast caption extraction via youtube-transcript-api."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        ytt = YouTubeTranscriptApi()
        if hasattr(ytt, "fetch"):
            fetched = ytt.fetch(video_id, languages=["en", "en-US", "en-GB"])
            raw = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else list(fetched)
        elif hasattr(YouTubeTranscriptApi, "get_transcript"):
            raw = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US", "en-GB"])
        else:
            raw = []

        segments = []
        for entry in raw:
            start = float(entry.get("start", 0.0))
            dur = float(entry.get("duration", 0.0))
            text = (entry.get("text") or "").strip()
            if text:
                segments.append(
                    TranscriptSegment(
                        start=start,
                        end=start + dur,
                        timestamp=_format_timestamp(start),
                        text=text,
                    )
                )
        return segments if segments else None
    except Exception:
        return None


def download_audio_track(url: str, output_dir: Path) -> tuple[Path | None, dict[str, Any]]:
    """Download audio from video URL using yt-dlp. Returns (audio_path, metadata)."""
    _ensure_ffmpeg()
    try:
        import yt_dlp

        out_template = str(output_dir / "%(id)s.%(ext)s")
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }
            ],
            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                return None, {}
            video_id = info.get("id", "audio")
            mp3_path = output_dir / f"{video_id}.mp3"
            if mp3_path.exists():
                return mp3_path, info
            # Check if any audio file matches pattern
            for f in output_dir.glob(f"{video_id}.*"):
                return f, info
            return None, info
    except Exception as e:
        print(f"[VideoIngest] yt-dlp error: {e}")
        return None, {}


def transcribe_local_audio(
    audio_path: Path, model_size: str = "base"
) -> list[TranscriptSegment]:
    """Transcribe audio file using OpenAI Whisper locally."""
    _ensure_ffmpeg()
    try:
        import whisper

        model = whisper.load_model(model_size)
        result = model.transcribe(str(audio_path), fp16=False)
        segments = []
        for seg in result.get("segments", []):
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", 0.0))
            text = (seg.get("text") or "").strip()
            if text:
                segments.append(
                    TranscriptSegment(
                        start=start,
                        end=end,
                        timestamp=_format_timestamp(start),
                        text=text,
                    )
                )
        return segments
    except Exception as e:
        print(f"[VideoIngest] Whisper error: {e}")
        return []


def ingest_video(
    source: str, title: str = "", whisper_model: str = "base"
) -> VideoLecture | None:
    """Ingest lecture from YouTube URL or local video/audio file.
    
    1. Checks if source is a YouTube link.
    2. Tries fast caption extraction first (no heavy download).
    3. Falls back to yt-dlp download + Whisper transcription.
    4. If local file path, runs Whisper directly.
    """
    local_path = Path(source)
    if local_path.exists() and local_path.is_file():
        segs = transcribe_local_audio(local_path, model_size=whisper_model)
        full = " ".join(s.text for s in segs)
        duration = segs[-1].end if segs else 0.0
        return VideoLecture(
            title=title or local_path.stem,
            url=str(local_path.resolve()),
            duration_seconds=duration,
            segments=segs,
            full_text=full,
            source_type="local_file",
        )

    yt_id = extract_youtube_id(source)
    if yt_id:
        url = f"https://www.youtube.com/watch?v={yt_id}"
        # Strategy 1: Instant captions API
        captions = fetch_youtube_captions(yt_id)
        if captions:
            full = " ".join(c.text for c in captions)
            duration = captions[-1].end if captions else 0.0
            return VideoLecture(
                title=title or f"YouTube Lecture ({yt_id})",
                url=url,
                duration_seconds=duration,
                segments=captions,
                full_text=full,
                source_type="youtube_captions",
            )

        # Strategy 2: Download audio track + Whisper
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_file, meta = download_audio_track(url, Path(tmpdir))
            if audio_file and audio_file.exists():
                segs = transcribe_local_audio(audio_file, model_size=whisper_model)
                full = " ".join(s.text for s in segs)
                return VideoLecture(
                    title=title or meta.get("title", f"YouTube Lecture ({yt_id})"),
                    url=url,
                    duration_seconds=float(meta.get("duration", segs[-1].end if segs else 0.0)),
                    segments=segs,
                    full_text=full,
                    source_type="youtube_whisper",
                )

    return None


def chunk_transcript_with_timestamps(
    lecture: VideoLecture, window_seconds: float = 60.0
) -> list[tuple[str, str]]:
    """Group segments into ~60-second semantic blocks with timestamp citations.
    
    Returns list of (timestamp_tag, chunk_text).
    Example: ("[02:15]", "[02:15] Neural networks require activation functions...")
    """
    if not lecture.segments:
        return []

    chunks: list[tuple[str, str]] = []
    current_text: list[str] = []
    current_start = lecture.segments[0].start
    current_ts = lecture.segments[0].timestamp

    for seg in lecture.segments:
        current_text.append(seg.text)
        if (seg.end - current_start) >= window_seconds:
            block = f"[{current_ts}] " + " ".join(current_text)
            chunks.append((current_ts, block))
            current_text = []
            current_start = seg.end
            current_ts = seg.timestamp

    if current_text:
        block = f"[{current_ts}] " + " ".join(current_text)
        chunks.append((current_ts, block))

    return chunks


def index_lecture_in_rag(lecture: VideoLecture) -> int:
    """Index timestamped video lecture blocks into ChromaDB vault."""
    from ..rag.store import get_rag

    rag = get_rag()
    blocks = chunk_transcript_with_timestamps(lecture)
    if not blocks:
        return 0

    texts = [b[1] for b in blocks]
    metadatas = [
        {
            "source": lecture.url,
            "title": lecture.title,
            "timestamp": b[0],
            "type": "video_lecture",
        }
        for b in blocks
    ]
    return rag.add_texts(texts=texts, metadatas=metadatas)
